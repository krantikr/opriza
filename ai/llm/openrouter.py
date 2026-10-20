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

import logging
import re
import time
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ai.config import LLMConfig
from ai.llm.base import (
    LLMClient,
    LLMError,
    Messages,
    ModelUnavailableError,
    RateLimitedError,
    StructuredOutputError,
    assistant,
    user,
)
from ai.llm.schema import describe_schema, extract_json, schema_name, to_strict_schema
from ai.schemas import AIOutcome, LLMUsage

logger = logging.getLogger(__name__)

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


#: OpenAI's reasoning families: GPT-5.x, GPT-6.x and the o-series.
_REASONING = re.compile(r"^openai/(gpt-[5-9]|o\d)")


def is_reasoning_model(model: str) -> bool:
    """True for models that reason before answering (no temperature, effort applies)."""
    return bool(_REASONING.match(model or ""))


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
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        reasoning = is_reasoning_model(model)
        if not reasoning:
            # OpenAI's reasoning models accept only their default temperature
            # and reject anything else outright, so they get none.
            kwargs["temperature"] = self.config.temperature
        if "openrouter.ai" in self.config.base_url:
            # Ask OpenRouter to return the actual cost of the generation.
            # Other OpenAI-compatible gateways (e.g. NVIDIA NIM) reject this
            # as an unsupported parameter.
            extra: dict[str, Any] = {"usage": {"include": True}}
            if reasoning and self.config.reasoning_effort:
                # Reasoning tokens are billed as output; short tasks need little.
                extra["reasoning"] = {"effort": self.config.reasoning_effort, "exclude": True}
            kwargs["extra_body"] = extra
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
    def _is_rate_limited(exc: Exception) -> bool:
        """True when the gateway is refusing us for load, not for shape.

        Checked *before* `_is_unsupported_format`, because a 429 body often
        echoes the rejected request - `response_format` and all - and would
        otherwise trip that function's text match. Reading a rate limit as
        "this model cannot do strict schema" is the worst possible response
        to it: the ladder walks down through every weaker mode, each with its
        own repair round, and fires a burst of doomed calls at a gateway that
        just asked us to slow down.
        """
        try:
            from openai import APIStatusError, RateLimitError
        except ImportError:  # pragma: no cover - dependency is declared
            return False

        if isinstance(exc, RateLimitError):
            return True
        # Some gateways surface overload as 5xx rather than 429; those are
        # equally not about output format.
        if isinstance(exc, APIStatusError):
            return exc.status_code == 429 or exc.status_code >= 500
        return False

    @staticmethod
    def _is_model_unavailable(exc: Exception) -> bool:
        """True when the *model itself* cannot be reached, whatever we ask it.

        A retired model, a name the gateway does not know, or one this account
        has lost access to. Checked before `_is_unsupported_format`, and this
        ordering is the whole point: OpenRouter returns 404 for a retired
        model, `NotFoundError` was already being read as "this model cannot do
        strict schema", and so a dead model walked the entire output ladder -
        strict, json_object, prompt_only, each with a repair round - firing six
        doomed calls before surfacing an error that blamed the output format.
        The message a trader saw was "classify call failed in prompt_only
        mode", which describes neither the cause nor the fix.

        No weaker output mode helps here. The only useful move is a different
        model.
        """
        try:
            from openai import APIStatusError, NotFoundError, PermissionDeniedError
        except ImportError:  # pragma: no cover - dependency is declared
            return False

        if isinstance(exc, NotFoundError | PermissionDeniedError):
            return True
        if isinstance(exc, APIStatusError) and exc.status_code in (401, 402, 403, 404):
            return True

        # Gateways vary in status code but converge on wording. Matched on the
        # model-specific phrases only, so an unsupported *parameter* is not
        # mistaken for an unsupported *model*.
        text = str(exc).lower()
        return any(
            token in text
            for token in (
                "no longer available",
                "no endpoints found",
                "is not a valid model",
                "unknown model",
                "model not found",
                "has been deprecated",
                "transitioned to a paid model",
                "insufficient credits",
            )
        )

    @staticmethod
    def _is_unsupported_format(exc: Exception) -> bool:
        """True when the failure looks like 'this model cannot do that format'.

        Deliberately broad: falling back to a weaker output mode costs one extra
        call, whereas failing hard would drop an enquiry the business cares
        about. Callers must rule out `_is_rate_limited` first - breadth here is
        only safe once load errors have been taken off the table.
        """
        try:
            from openai import BadRequestError, UnprocessableEntityError
        except ImportError:  # pragma: no cover - dependency is declared
            return False

        # `NotFoundError` is deliberately absent: it means the model does not
        # exist, which `_is_model_unavailable` handles by switching model.
        # Treating it as a format problem is what sent retired models down the
        # whole output ladder.
        if isinstance(exc, BadRequestError | UnprocessableEntityError):
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
            substitute = self._is_model_unavailable(exc) and model is None
            fallback = self.config.fallback_for(task) if substitute else None

            if fallback is None:
                usage.latency_ms = int((time.perf_counter() - started) * 1000)
                usage.succeeded = False
                usage.error = str(exc)
                if self._is_rate_limited(exc):
                    raise RateLimitedError(f"{task} rate-limited by the gateway: {exc}") from exc
                raise LLMError(f"{task} completion failed: {exc}") from exc

            logger.warning(
                "%s: model %s is unavailable (%s); falling back to %s.",
                task,
                chosen,
                str(exc)[:200],
                fallback,
            )
            usage.model = fallback
            usage.fell_back_from = chosen
            try:
                text, meta = self._call(
                    model=fallback,
                    messages=messages,
                    response_format=None,
                    max_tokens=max_tokens,
                )
            except Exception as second:
                usage.latency_ms = int((time.perf_counter() - started) * 1000)
                usage.succeeded = False
                usage.error = f"{chosen}: {exc} | fallback {fallback}: {second}"
                if self._is_rate_limited(second):
                    raise RateLimitedError(f"{task} rate-limited by the gateway: {second}") from second
                raise LLMError(
                    f"{task} completion failed on {chosen} and fallback {fallback}: {second}"
                ) from second

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

        try:
            return self._structured_on(
                model=chosen,
                task=task,
                messages=messages,
                schema=schema,
                max_tokens=max_tokens,
                usage=usage,
                started=started,
            )
        except ModelUnavailableError as exc:
            fallback = self.config.fallback_for(task) if model is None else None
            if fallback is None:
                usage.succeeded = False
                usage.error = str(exc)
                raise LLMError(f"{task}: {exc}") from exc

            # A fresh ladder on the substitute model: output-mode support is a
            # property of the model, so nothing learned about the dead one
            # carries over.
            logger.warning(
                "%s: model %s is unavailable (%s); falling back to %s.",
                task,
                chosen,
                str(exc)[:200],
                fallback,
            )
            usage.model = fallback
            usage.fell_back_from = chosen
            try:
                return self._structured_on(
                    model=fallback,
                    task=task,
                    messages=messages,
                    schema=schema,
                    max_tokens=max_tokens,
                    usage=usage,
                    started=started,
                )
            except ModelUnavailableError as second:
                # Name both. "good/model is unavailable" alone reads as a
                # config error about the fallback, hiding that the task's own
                # model is the one that needs changing.
                usage.succeeded = False
                usage.error = f"{chosen}: {exc} | fallback {fallback}: {second}"
                raise LLMError(
                    f"{task}: neither {chosen} nor fallback {fallback} is available. {second}"
                ) from second

    def _structured_on(
        self,
        *,
        model: str,
        task: str,
        messages: Messages,
        schema: type[T],
        max_tokens: int | None,
        usage: LLMUsage,
        started: float,
    ) -> AIOutcome[T]:
        """Walk the output-mode ladder against one model."""
        chosen = model
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
            request_messages.append(user(_SCHEMA_INSTRUCTION.format(schema=describe_schema(schema))))
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
                if self._is_rate_limited(exc):
                    # Abandon the whole ladder, not just this mode. The gateway
                    # is not going to like a weaker output mode any better, and
                    # retrying is what caused the overload.
                    raise RateLimitedError(
                        f"{task} rate-limited by the gateway in {mode.value} mode: {exc}"
                    ) from exc
                if self._is_model_unavailable(exc):
                    # Unwind the whole ladder. A retired model does not become
                    # reachable in a weaker output mode, and walking down to
                    # prompt_only is what turned one dead model into six failed
                    # calls and an error message about output format.
                    raise ModelUnavailableError(f"model {model} is unavailable: {exc}") from exc
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
