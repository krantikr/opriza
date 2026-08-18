"""Reply classification: what does a customer's reply to a sent quotation want?

A sibling to `classifier.py`, not a variant of it. The taxonomy is different in
kind - the general classifier sorts first-contact mail into a business
category; this reads a reply already known (deterministically, by Gmail thread)
to belong to a specific quotation, and asks only whether the customer is
saying yes, no, or something else. Kept as a separate module and schema so
neither taxonomy has to accommodate the other's cases.
"""

from __future__ import annotations

from ai.llm.base import LLMClient, system, user
from ai.llm.factory import get_client
from ai.prompts import load
from ai.schemas import AIOutcome, ReplyClassification
from ai.text import build_email_block

TASK = "classify_reply"


def classify_reply(
    *,
    subject: str | None,
    body: str | None,
    quotation_summary: str,
    sender_name: str | None = None,
    sender_email: str | None = None,
    client: LLMClient | None = None,
    model: str | None = None,
) -> AIOutcome[ReplyClassification]:
    """Classify a reply on a thread where a quotation has already been sent."""
    llm = client or get_client()

    context = (
        "<quoted_previously>\n"
        f"{quotation_summary.strip()}\n"
        "</quoted_previously>\n\n"
        + build_email_block(
            subject=subject,
            body=body,
            sender_name=sender_name,
            sender_email=sender_email,
            max_chars=6_000,
        )
    )

    messages = [system(load("classify_reply")), user(context)]

    return llm.structured(
        task=TASK, messages=messages, schema=ReplyClassification, model=model, max_tokens=500
    )
