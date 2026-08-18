"""OpenRouter client.

OpenRouter speaks the OpenAI wire protocol, so the official `openai` SDK is
pointed at it rather than hand-rolling HTTP. One gateway key gives access to
every model, and switching model is a config change.

The interesting part is `structured()`. Structured-output support on OpenRouter
varies by model, and the whole point of the gateway is that the model can be
changed freely - so the extractor cannot assume strict schema mode exists. It
degrades in three stages:

    1. strict `json_schema`  - the API itself guarantees the shape
    2. `json_object`         - the API guarantees valid JSON, schema in prompt
    3. prompt only           - JSON recovered from free text

and within each stage it will make one repair attempt, handing the validation
error back to the model. Only when all of that fails does it raise, and the
caller then routes the enquiry to a human. At no point does a partially-parsed
or guessed value reach the pricing engine.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ai.config import LLMConfig
from ai.llm.base import LLMClient, LLMError, Messages, StructuredOutputError, assistant, user
from ai.llm.schema import describe_schema, extract_json, schema_name, to_strict_schema
from ai.schemas import AIOutcome, LLMUsage

T = TypeVar("T", bound=BaseModel)


class OutputMode(StrEnum):
    STRICT_SCHEMA = "strict_schema"
    JSON_OBJECT = "json_object"
    PROMPT_ONLY = "prompt_only"


_SCHEMA_INSTRUCTION = (
    "Respond with a single JSON object and nothing else - no prose, no markdown "
    "fences, no explanation. It must conform exactly to this JSON Schema, "
    "including every property:\n\n{schema}"
)

_REPAIR_INSTRUCTION = (
    "Your previous response did not satisfy the required schema.\n\n"
    "Error:\n{error}\n\n"
    "Return the corrected JSON object only. Do not add commentary. "
    "Do not invent values to fill fields - use null where the source text does "
    "not state something."
)


class OpenRouterClient(LLMClient):
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self._client: Any = None

    # --- Transport --------------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            self.config.require()
            from openai import OpenAI

            self._client = OpenAI(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                timeout=self.config.timeout_seconds,
                max_retries=self.config.max_retries,
                default_headers={
                    # OpenRouter attribution headers; harmless elsewhere.
                    "HTTP-Referer": self.config.app_url,
                    "X-Title": self.config.app_title,
                },
            )
        return self._client

    def _call(
        self,
        *,
        model: str,
        messages: Messages,
        response_format: dict[str, Any] | None,
        max_tokens: int | None,
    ) -> tuple[str, dict[str, Any]]:
        """One chat completion. Returns (text, metadata)."""
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if "openrouter.ai" in self.config.base_url:
            # Ask OpenRouter to return the actual cost of the generation.
            # Other OpenAI-compatible gateways (e.g. NVIDIA NIM) reject this
            # as an unsupported parameter.
            kwargs["extra_body"] = {"usage": {"include": True}}
        if response_format:
            kwargs["response_format"] = response_format
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = self.client.chat.completions.create(**kwargs)

        if not response.choices:
            raise LLMError("model returned no choices")

        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        extra = getattr(usage, "model_extra", None) or {}

        meta = {
            "generation_id": getattr(response, "id", None),
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            "cost_usd": extra.get("cost"),
            "finish_reason": response.choices[0].finish_reason,
        }
        return text, meta

    @staticmethod
    def _is_unsupported_format(exc: Exception) -> bool:
        """True when the failure looks like 'this model cannot do that format'.

        Deliberately broad: falling back to a weaker output mode costs one extra
        call, whereas failing hard would drop an enquiry the business cares
        about.
        """
        try:
            from openai import BadRequestError, NotFoundError, UnprocessableEntityError
        except ImportError:  # pragma: no cover - dependency is declared
            return False

        if isinstance(exc, BadRequestError | UnprocessableEntityError | NotFoundError):
            return True

        text = str(exc).lower()
        return any(
            token in text
            for token in ("response_format", "json_schema", "structured output", "not supported")
        )

    # --- Public API -------------------------------------------------------

    def complete(
        self,
        *,
        task: str,
        messages: Messages,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> AIOutcome[str]:
        chosen = model or self.config.model_for(task)
        usage = LLMUsage(model=chosen, task=task)
        started = time.perf_counter()

        try:
            text, meta = self._call(
                model=chosen, messages=messages, response_format=None, max_tokens=max_tokens
            )
        except Exception as exc:
            usage.latency_ms = int((time.perf_counter() - started) * 1000)
            usage.succeeded = False
            usage.error = str(exc)
            raise LLMError(f"{task} completion failed: {exc}") from exc

        self._apply(usage, meta)
        usage.latency_ms = int((time.perf_counter() - started) * 1000)
        return AIOutcome(value=text, usage=usage)

    def structured(
        self,
        *,
        task: str,
        messages: Messages,
        schema: type[T],
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> AIOutcome[T]:
        chosen = model or self.config.model_for(task)
        usage = LLMUsage(model=chosen, task=task, attempts=0)
        started = time.perf_counter()
        failures: list[str] = []

        for mode in OutputMode:
            try:
                value = self._attempt_mode(
                    mode=mode,
                    task=task,
                    model=chosen,
                    messages=messages,
                    schema=schema,
                    max_tokens=max_tokens,
                    usage=usage,
                    failures=failures,
                )
            except LLMError as exc:
                # Transport-level failure that is not about output format.
                usage.latency_ms = int((time.perf_counter() - started) * 1000)
                usage.succeeded = False
                usage.error = str(exc)
                raise

            if value is not None:
                usage.strict_schema_used = mode is OutputMode.STRICT_SCHEMA
                usage.latency_ms = int((time.perf_counter() - started) * 1000)
                usage.succeeded = True
                return AIOutcome(value=value, usage=usage)

        usage.latency_ms = int((time.perf_counter() - started) * 1000)
        usage.succeeded = False
        usage.error = " | ".join(failures[-3:])
        raise StructuredOutputError(
            f"{task}: model could not produce valid {schema.__name__} after "
            f"{usage.attempts} attempt(s). Last errors: {usage.error}"
        )

    # --- Internals --------------------------------------------------------

    def _attempt_mode(
        self,
        *,
        mode: OutputMode,
        task: str,
        model: str,
        messages: Messages,
        schema: type[T],
        max_tokens: int | None,
        usage: LLMUsage,
        failures: list[str],
    ) -> T | None:
        """Try one output mode, with a single repair round. None = move on."""
        request_messages = list(messages)
        response_format: dict[str, Any] | None = None

        if mode is OutputMode.STRICT_SCHEMA:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name(schema),
                    "strict": True,
                    "schema": to_strict_schema(schema),
                },
            }
        else:
            # Without API-side enforcement the schema has to be in the prompt.
            request_messages.append(
                user(_SCHEMA_INSTRUCTION.format(schema=describe_schema(schema)))
            )
            if mode is OutputMode.JSON_OBJECT:
                response_format = {"type": "json_object"}

        for repair in (False, True):
            usage.attempts += 1
            try:
                text, meta = self._call(
                    model=model,
                    messages=request_messages,
                    response_format=response_format,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                if self._is_unsupported_format(exc) and mode is not OutputMode.PROMPT_ONLY:
                    failures.append(f"{mode.value}: {exc}")
                    return None  # try a weaker mode
                raise LLMError(f"{task} call failed in {mode.value} mode: {exc}") from exc

            self._apply(usage, meta)

            try:
                return schema.model_validate(extract_json(text))
            except (ValueError, ValidationError) as exc:
                failures.append(f"{mode.value}: {exc}")
                if repair:
                    return None  # repair already used; fall to the next mode
                request_messages = [
                    *request_messages,
                    assistant(text),
                    user(_REPAIR_INSTRUCTION.format(error=str(exc)[:1500])),
                ]

        return None

    @staticmethod
    def _apply(usage: LLMUsage, meta: dict[str, Any]) -> None:
        """Accumulate token counts across every attempt in one logical call."""
        usage.prompt_tokens += meta.get("prompt_tokens", 0)
        usage.completion_tokens += meta.get("completion_tokens", 0)
        usage.total_tokens += meta.get("total_tokens", 0)
        if (cost := meta.get("cost_usd")) is not None:
            usage.cost_usd = (usage.cost_usd or 0.0) + float(cost)
        if generation_id := meta.get("generation_id"):
            usage.generation_id = generation_id
