"""Vocabulary normalisation (pipeline stage 4), used as a fallback only.

The deterministic synonym table in `business_rules.yaml` resolves the common
trade shorthand. This runs only for descriptions it could not place, so it sees
the unusual wording by design.

It maps vocabulary. It does not select a product - that decision stays with the
deterministic matcher, which is the reason a language model cannot pick the
wrong item off the price list.
"""

from __future__ import annotations

from ai.llm.base import LLMClient, system, user
from ai.llm.factory import get_client
from ai.prompts import load
from ai.schemas import AIOutcome, NormalizedProduct

TASK = "normalize"


def normalize_product(
    description: str,
    *,
    client: LLMClient | None = None,
    model: str | None = None,
) -> AIOutcome[NormalizedProduct]:
    """Map a free-text material description to canonical vocabulary."""
    llm = client or get_client()

    messages = [
        system(load("normalize")),
        user(f"Material description:\n{description.strip()}"),
    ]

    return llm.structured(
        task=TASK, messages=messages, schema=NormalizedProduct, model=model, max_tokens=400
    )
