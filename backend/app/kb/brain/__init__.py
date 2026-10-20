"""Which brain the agents think with: AGENT_BRAIN = rules | llm | auto (default auto)."""

from __future__ import annotations

import os

from app.kb.brain.base import Brain, CatalogEntry, ParsedEnquiry, ParsedLine, ToolCall, ToolSpec
from app.kb.brain.rules import RulesBrain


def brain_mode() -> str:
    import ai.config  # noqa: F401 - loads .env, so AGENT_BRAIN and the key can live there

    mode = (os.getenv("AGENT_BRAIN") or "auto").strip().lower()
    if mode == "auto":
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        # .env.example ships "sk-or-..." as a placeholder; that is not a key.
        return "llm" if key and "..." not in key else "rules"
    return mode if mode in ("llm", "rules") else "rules"


def get_brain() -> Brain:
    if brain_mode() == "llm":
        try:
            from app.kb.brain.llm import LLMBrain

            return LLMBrain()
        except Exception:  # noqa: BLE001 - a misconfigured client must not stop the agents
            return RulesBrain()
    return RulesBrain()


__all__ = [
    "Brain",
    "CatalogEntry",
    "ParsedEnquiry",
    "ParsedLine",
    "RulesBrain",
    "ToolCall",
    "ToolSpec",
    "brain_mode",
    "get_brain",
]
