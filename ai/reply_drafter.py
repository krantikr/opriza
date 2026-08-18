"""Courtesy reply generation for a declined quotation.

Deliberately not `drafter.py` with a flag: that module writes an offer with
figures that must be reproduced exactly, and runs its output through
`ai.guards.verify_draft_facts`. This writes the opposite kind of email - one
that must *not* repeat any figure - so it gets its own prompt and no fact
guard, rather than a conditional bolted onto the quotation drafter.
"""

from __future__ import annotations

from ai.llm.base import LLMClient, system, user
from ai.llm.factory import get_client
from ai.prompts import load
from ai.schemas import AIOutcome, DraftEmail

TASK = "decline_reply"


def draft_decline_reply(
    *,
    customer_name: str | None,
    quotation_number: str,
    quotation_summary: str,
    customer_reply_text: str,
    original_subject: str | None,
    client: LLMClient | None = None,
    model: str | None = None,
) -> AIOutcome[DraftEmail]:
    """Write a short courtesy acknowledgement for a customer who declined."""
    llm = client or get_client()

    context = [
        f"Customer: {customer_name or '(name not given)'}",
        f"Quotation reference: {quotation_number}",
        "",
        "<quoted_previously>",
        quotation_summary.strip(),
        "</quoted_previously>",
        "",
        "<customer_reply_declining>",
        customer_reply_text.strip()[:4_000],
        "</customer_reply_declining>",
        "",
        f"Original subject: {original_subject or '(no subject)'}",
    ]

    messages = [system(load("decline_reply")), user("\n".join(context))]

    return llm.structured(task=TASK, messages=messages, schema=DraftEmail, model=model, max_tokens=800)
