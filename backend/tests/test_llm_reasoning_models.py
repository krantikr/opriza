"""Requests to OpenAI's reasoning models (GPT-5.x, GPT-6.x): no temperature,
and a reasoning effort so their thinking tokens stay cheap."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.config import LLMConfig
from ai.llm.openrouter import OpenRouterClient, is_reasoning_model
from app.kb.brain.llm import DEFAULT_AGENT_MODEL, LLMBrain


class Recording:
    """Stands in for `client.chat.completions` and keeps every request."""

    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15, model_extra={"cost": 0.0}
        )
        msg = SimpleNamespace(content='{"text": "ok"}')
        return SimpleNamespace(
            id="gen-1", choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=usage
        )


def client(effort="low"):
    c = OpenRouterClient(LLMConfig(api_key="sk-or-test", reasoning_effort=effort))
    rec = Recording()
    c._client = SimpleNamespace(chat=SimpleNamespace(completions=rec))
    return c, rec


@pytest.mark.parametrize(
    ("model", "reasoning"),
    [
        ("openai/gpt-6-luna", True),
        ("openai/gpt-6.1-sol", True),
        ("openai/gpt-5.6-luna", True),
        ("openai/o4-mini", True),
        ("openai/gpt-4o-mini", False),
        ("deepseek/deepseek-v4-flash", False),
        ("anthropic/claude-sonnet-4.5", False),
    ],
)
def test_which_models_reason(model, reasoning):
    assert is_reasoning_model(model) is reasoning


def test_reasoning_model_gets_effort_and_no_temperature():
    c, rec = client()
    c._call(
        model="openai/gpt-6-luna",
        messages=[{"role": "user", "content": "hi"}],
        response_format=None,
        max_tokens=None,
    )
    req = rec.requests[0]
    assert "temperature" not in req
    assert req["extra_body"]["reasoning"] == {"effort": "low", "exclude": True}


def test_other_models_keep_temperature_and_get_no_reasoning():
    c, rec = client()
    c._call(
        model="deepseek/deepseek-v4-flash",
        messages=[{"role": "user", "content": "hi"}],
        response_format=None,
        max_tokens=None,
    )
    req = rec.requests[0]
    assert req["temperature"] == 0.0 and "reasoning" not in req["extra_body"]


def test_agents_default_to_gpt6_luna(monkeypatch):
    monkeypatch.delenv("AGENT_MODEL_FAST", raising=False)
    monkeypatch.delenv("AGENT_MODEL_WRITE", raising=False)
    monkeypatch.setenv("LLM_MODEL_CLASSIFY", "inclusionai/ling-2.6-flash")
    brain = LLMBrain(client=object())
    assert brain.fast == brain.write_model == DEFAULT_AGENT_MODEL == "openai/gpt-6-luna"
    monkeypatch.setenv("AGENT_MODEL_WRITE", "openai/gpt-6-sol")
    assert LLMBrain(client=object()).write_model == "openai/gpt-6-sol"
