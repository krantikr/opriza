"""Falling back to a second model when the configured one is unreachable.

The case that prompted these: `inclusionai/ling-2.6-flash` was retired by
OpenRouter mid-deployment. Every inbound email then failed classification, the
inbox filled with "could not be read", and the error a trader was shown -
"classify call failed in prompt_only mode" - pointed at the output format
rather than at the dead model, because a 404 was being read as "this model
cannot do strict schema" and sent down the whole output ladder.

The transport is scripted; the logic under test is the real one.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ai.config import DEFAULT_FALLBACK_MODEL, LLMConfig
from ai.llm.base import LLMError, RateLimitedError
from ai.llm.openrouter import OpenRouterClient
from ai.schemas import ClassificationResult

VALID = json.dumps(
    {"category": "QUOTATION_REQUEST", "confidence": 0.95, "reason": "Asks for a rate."}
)


class ModelTrackingClient(OpenRouterClient):
    """Scripted transport that records which model each call was sent to."""

    def __init__(self, script: list[object], config: LLMConfig | None = None) -> None:
        super().__init__(config or LLMConfig(api_key="test-key"))
        self.script = list(script)
        self.models: list[str] = []

    def _call(self, *, model, messages, response_format, max_tokens):  # type: ignore[override]
        self.models.append(model)
        if not self.script:
            raise AssertionError("scripted client ran out of responses")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "generation_id": "gen-1",
            "cost_usd": 0.0001,
        }


def _err(kind, status: int, message: str) -> Exception:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return kind(message, response=httpx.Response(status, request=request), body=None)


def retired_model() -> Exception:
    """The exact error OpenRouter returned for the retired model."""
    from openai import NotFoundError

    return _err(
        NotFoundError,
        404,
        "Ling-2.6-flash is no longer available as a free model. "
        "It has transitioned to a paid model.",
    )


def messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": "Please quote 20 MT of 10mm plate."}]


def config(primary: str = "dead/model", fallback: str = "good/model") -> LLMConfig:
    return LLMConfig(
        api_key="test-key",
        models={"classify": primary, "extract": primary, "draft": primary},
        fallback_model=fallback,
    )


# --- The reported failure ---------------------------------------------------


def test_a_retired_model_falls_back_instead_of_failing(caplog):
    client = ModelTrackingClient([retired_model(), VALID], config())

    outcome = client.structured(
        task="classify", messages=messages(), schema=ClassificationResult
    )

    assert outcome.value.category.value == "QUOTATION_REQUEST"
    assert client.models == ["dead/model", "good/model"]
    assert outcome.usage.model == "good/model"
    assert outcome.usage.fell_back_from == "dead/model"


def test_a_dead_model_does_not_walk_the_output_ladder():
    """One call to the dead model, not six.

    This is the actual regression: `NotFoundError` was classified as an
    unsupported *format*, so the client tried strict, then json_object, then
    prompt_only, each with a repair round, before giving up.
    """
    client = ModelTrackingClient([retired_model(), VALID], config())

    client.structured(task="classify", messages=messages(), schema=ClassificationResult)

    assert client.models.count("dead/model") == 1


def test_the_error_names_the_model_when_the_fallback_also_fails():
    client = ModelTrackingClient([retired_model(), retired_model()], config())

    with pytest.raises(LLMError) as excinfo:
        client.structured(task="classify", messages=messages(), schema=ClassificationResult)

    text = str(excinfo.value)
    assert "dead/model" in text
    # The message must point at the model, not at the output format.
    assert "prompt_only" not in text


# --- What must NOT trigger a fallback ---------------------------------------


def test_an_unsupported_format_still_walks_the_ladder_on_the_same_model():
    """A 400 about response_format is a format problem, not a model problem."""
    from openai import BadRequestError

    client = ModelTrackingClient(
        [_err(BadRequestError, 400, "response_format is not supported"), VALID], config()
    )

    outcome = client.structured(
        task="classify", messages=messages(), schema=ClassificationResult
    )

    assert client.models == ["dead/model", "dead/model"], "must not change model"
    assert outcome.usage.fell_back_from is None


def test_rate_limiting_does_not_burn_the_fallback():
    """A 429 means slow down, not switch model - the fallback shares the key."""
    from openai import RateLimitError

    client = ModelTrackingClient([_err(RateLimitError, 429, "slow down")], config())

    with pytest.raises(RateLimitedError):
        client.structured(task="classify", messages=messages(), schema=ClassificationResult)

    assert client.models == ["dead/model"]


def test_an_explicit_model_argument_is_never_substituted():
    """A caller naming a model meant that model; silently using another lies."""
    client = ModelTrackingClient([retired_model()], config())

    with pytest.raises(LLMError):
        client.structured(
            task="classify",
            messages=messages(),
            schema=ClassificationResult,
            model="caller/choice",
        )

    assert client.models == ["caller/choice"]


def test_no_fallback_when_the_task_already_runs_on_it():
    """Retrying the same name against the same gateway earns the same error."""
    client = ModelTrackingClient([retired_model()], config(primary="same/model", fallback="same/model"))

    with pytest.raises(LLMError):
        client.structured(task="classify", messages=messages(), schema=ClassificationResult)

    assert client.models == ["same/model"]


def test_falling_back_can_be_switched_off():
    client = ModelTrackingClient([retired_model()], config(fallback=""))

    with pytest.raises(LLMError):
        client.structured(task="classify", messages=messages(), schema=ClassificationResult)

    assert client.models == ["dead/model"]


# --- Free-text completions take the same path -------------------------------


def test_complete_falls_back_too():
    client = ModelTrackingClient([retired_model(), "Dear Sir, ..."], config())

    outcome = client.complete(task="draft", messages=messages())

    assert outcome.value.startswith("Dear Sir")
    assert client.models == ["dead/model", "good/model"]
    assert outcome.usage.fell_back_from == "dead/model"


def test_the_default_fallback_is_a_widely_available_model():
    """Whatever it is, it must not be one of the models that just died."""
    assert DEFAULT_FALLBACK_MODEL
    assert "ling-2.6" not in DEFAULT_FALLBACK_MODEL
