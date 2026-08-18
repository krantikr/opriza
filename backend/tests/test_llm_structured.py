"""The structured-output ladder.

These tests exist because the fallback path is the part of the AI layer most
likely to be exercised in anger and least likely to be noticed when it breaks:
the whole point of an LLM gateway is that the model can be swapped, and the new
model may not support strict schemas.

The transport is scripted; the logic under test is the real one.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ai.config import LLMConfig
from ai.llm.base import LLMError, StructuredOutputError
from ai.llm.openrouter import OpenRouterClient
from ai.llm.schema import extract_json, to_strict_schema
from ai.schemas import ClassificationResult, EmailCategory, ExtractedEnquiry

VALID = json.dumps(
    {"category": "QUOTATION_REQUEST", "confidence": 0.95, "reason": "Asks for a rate."}
)


class ScriptedClient(OpenRouterClient):
    """OpenRouterClient with the HTTP call replaced by a scripted sequence."""

    def __init__(self, script: list[object]) -> None:
        super().__init__(LLMConfig(api_key="test-key"))
        self.script = list(script)
        self.calls: list[dict] = []

    def _call(self, *, model, messages, response_format, max_tokens):  # type: ignore[override]
        self.calls.append({"response_format": response_format, "messages": messages})
        if not self.script:
            raise AssertionError("scripted client ran out of responses")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "generation_id": "gen-abc",
            "cost_usd": 0.0002,
        }


def bad_request(message: str) -> Exception:
    """A genuine openai.BadRequestError, as the SDK would raise it."""
    from openai import BadRequestError

    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return BadRequestError(message, response=httpx.Response(400, request=request), body=None)


def messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": "Please quote 20 MT of 10mm plate."}]


def test_strict_schema_succeeds_on_first_attempt():
    client = ScriptedClient([VALID])

    outcome = client.structured(
        task="classify", messages=messages(), schema=ClassificationResult
    )

    assert outcome.value.category is EmailCategory.QUOTATION_REQUEST
    assert outcome.usage.attempts == 1
    assert outcome.usage.strict_schema_used is True
    assert outcome.usage.total_tokens == 120
    assert outcome.usage.cost_usd == pytest.approx(0.0002)
    assert client.calls[0]["response_format"]["type"] == "json_schema"


def test_falls_back_to_json_object_when_model_rejects_strict_schema():
    client = ScriptedClient([bad_request("response_format json_schema is not supported"), VALID])

    outcome = client.structured(
        task="classify", messages=messages(), schema=ClassificationResult
    )

    assert outcome.value.confidence == pytest.approx(0.95)
    assert outcome.usage.strict_schema_used is False
    assert client.calls[0]["response_format"]["type"] == "json_schema"
    assert client.calls[1]["response_format"] == {"type": "json_object"}
    # The schema must reach the model in the prompt once the API stops enforcing it.
    assert "JSON Schema" in client.calls[1]["messages"][-1]["content"]


def test_falls_back_to_prompt_only_when_json_object_also_rejected():
    client = ScriptedClient(
        [
            bad_request("json_schema not supported"),
            bad_request("json_object not supported"),
            f"Here you go:\n```json\n{VALID}\n```",
        ]
    )

    outcome = client.structured(
        task="classify", messages=messages(), schema=ClassificationResult
    )

    assert outcome.value.category is EmailCategory.QUOTATION_REQUEST
    assert client.calls[2]["response_format"] is None


def test_repairs_a_schema_violation_within_the_same_mode():
    invalid = json.dumps({"category": "NOT_A_CATEGORY", "confidence": 0.9, "reason": "x"})
    client = ScriptedClient([invalid, VALID])

    outcome = client.structured(
        task="classify", messages=messages(), schema=ClassificationResult
    )

    assert outcome.value.category is EmailCategory.QUOTATION_REQUEST
    assert outcome.usage.attempts == 2
    # The repair turn must show the model its own output and the error.
    repair = client.calls[1]["messages"]
    assert repair[-2]["role"] == "assistant"
    assert "did not satisfy the required schema" in repair[-1]["content"]
    # Tokens accumulate across attempts rather than reporting only the last.
    assert outcome.usage.total_tokens == 240


def test_gives_up_after_exhausting_every_mode():
    garbage = "I am not going to answer in JSON."
    client = ScriptedClient([garbage] * 6)

    with pytest.raises(StructuredOutputError) as exc:
        client.structured(task="extract", messages=messages(), schema=ExtractedEnquiry)

    # Three modes, one repair each.
    assert len(client.calls) == 6
    assert "ExtractedEnquiry" in str(exc.value)


def test_transport_failure_is_not_mistaken_for_a_format_problem():
    """A network error must surface, not silently downgrade the output mode."""
    client = ScriptedClient([ConnectionResetError("connection reset by peer")])

    with pytest.raises(LLMError):
        client.structured(task="classify", messages=messages(), schema=ClassificationResult)

    assert len(client.calls) == 1


def test_missing_api_key_is_reported_before_any_request():
    from ai.config import LLMNotConfigured

    client = OpenRouterClient(LLMConfig(api_key=""))

    with pytest.raises(LLMNotConfigured):
        _ = client.client


# --- Schema shaping --------------------------------------------------------


def test_strict_schema_marks_every_property_required():
    schema = to_strict_schema(ExtractedEnquiry)

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])

    line_item = schema["$defs"]["SteelLineItem"]
    assert set(line_item["required"]) == set(line_item["properties"])
    # Optionality is expressed as nullability, so a value the email omits comes
    # back as an explicit null rather than a missing key.
    assert {"type": "number"} in line_item["properties"]["thickness_mm"]["anyOf"]
    assert {"type": "null"} in line_item["properties"]["thickness_mm"]["anyOf"]


def test_strict_schema_drops_keywords_the_api_rejects():
    schema = json.dumps(to_strict_schema(ClassificationResult))

    for keyword in ("minimum", "maximum", "default", "pattern", "format"):
        assert f'"{keyword}"' not in schema


def test_ref_nodes_carry_no_sibling_keys():
    category = to_strict_schema(ClassificationResult)["properties"]["category"]
    assert category == {"$ref": "#/$defs/EmailCategory"}


# --- JSON recovery ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        'Sure, here is the result: {"a": 1} - let me know if you need more.',
    ],
)
def test_extract_json_recovers_from_common_wrappings(raw):
    assert extract_json(raw) == {"a": 1}


@pytest.mark.parametrize("raw", ["", "   ", "no json here at all"])
def test_extract_json_rejects_unrecoverable_text(raw):
    with pytest.raises(ValueError):
        extract_json(raw)
