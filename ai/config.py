"""Configuration for the AI layer.

Reads its own environment variables rather than importing the backend's
settings, so the `ai` package stays independently usable and testable. The
backend passes an explicit `LLMConfig` when it wants to override anything.

Model choice is per task on purpose. Classification runs on every inbound
email - a thousand a day in this business - while extraction and drafting run
only on the quotation subset. Routing them to the same model would multiply the
bill by the volume of the cheapest step.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import find_dotenv, load_dotenv

# `ai/` reads its own environment rather than importing the backend's pydantic
# settings (see module docstring), so it is responsible for loading `.env`
# itself. `find_dotenv` walks up from the current file rather than relying on
# the process's working directory, so this behaves the same whether it's
# imported from a script, the API server, or a test run.
load_dotenv(find_dotenv(usecwd=True))

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

#: Used when a task's own model cannot be reached at all - retired by the
#: gateway, unknown, or the account has lost access to it. Deliberately a
#: widely-available, cheap, general model: its job is to keep the desk running
#: through an outage, not to match the primary model's quality.
DEFAULT_FALLBACK_MODEL = "openai/gpt-5.6-luna"

DEFAULT_MODELS = {
    "classify": "openai/gpt-4o-mini",
    "extract": "anthropic/claude-sonnet-4.5",
    "normalize": "openai/gpt-4o-mini",
    "draft": "anthropic/claude-sonnet-4.5",
    "classify_reply": "openai/gpt-4o-mini",
    "decline_reply": "anthropic/claude-sonnet-4.5",
}


class LLMNotConfigured(RuntimeError):
    """Raised when an AI call is attempted without an API key."""


@dataclass(frozen=True, slots=True)
class LLMConfig:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    app_url: str = "http://localhost:8000"
    app_title: str = "AI Sales Quotation Copilot"
    timeout_seconds: int = 60
    max_retries: int = 2
    temperature: float = 0.0
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    #: One model standing behind every task. Empty disables falling back.
    fallback_model: str = DEFAULT_FALLBACK_MODEL
    #: How hard OpenAI's reasoning models (GPT-5.x, GPT-6.x, o-series) think
    #: before answering: none, minimal, low, medium, high. Reasoning tokens are
    #: billed as output, and our tasks are short, so "low" keeps them cheap.
    reasoning_effort: str = "low"

    @classmethod
    def from_env(cls) -> LLMConfig:
        models = dict(DEFAULT_MODELS)
        for task in models:
            if override := os.getenv(f"LLM_MODEL_{task.upper()}"):
                models[task] = override
        # `normalize` has no dedicated env var by default; follow classify,
        # which is the cheap model, unless explicitly set. Same reasoning for
        # the reply tasks: they run less often than a fresh env var justifies,
        # so they follow whichever of classify/draft they resemble in cost.
        if not os.getenv("LLM_MODEL_NORMALIZE"):
            models["normalize"] = models["classify"]
        if not os.getenv("LLM_MODEL_CLASSIFY_REPLY"):
            models["classify_reply"] = models["classify"]
        if not os.getenv("LLM_MODEL_DECLINE_REPLY"):
            models["decline_reply"] = models["draft"]

        return cls(
            api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
            base_url=os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL),
            app_url=os.getenv("OPENROUTER_APP_URL", "http://localhost:8000"),
            app_title=os.getenv("OPENROUTER_APP_TITLE", "AI Sales Quotation Copilot"),
            timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.0")),
            models=models,
            # Set LLM_MODEL_FALLBACK="" to switch falling back off entirely.
            fallback_model=os.getenv("LLM_MODEL_FALLBACK", DEFAULT_FALLBACK_MODEL).strip(),
            reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "low").strip().lower(),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def model_for(self, task: str) -> str:
        return self.models.get(task) or DEFAULT_MODELS.get(task, DEFAULT_MODELS["extract"])

    def fallback_for(self, task: str) -> str | None:
        """The model to try when `model_for(task)` cannot be reached.

        None when falling back is disabled, or when the task already runs on
        the fallback model - retrying the same name against the same gateway
        would just spend a second call to earn the same error.
        """
        candidate = (self.fallback_model or "").strip()
        if not candidate or candidate == self.model_for(task):
            return None
        return candidate

    def require(self) -> None:
        if not self.configured:
            raise LLMNotConfigured("OPENROUTER_API_KEY is not set. Add it to .env to enable the AI steps.")
