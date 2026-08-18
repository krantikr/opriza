"""Email classification (pipeline stage 2).

Runs on every inbound message, so it uses the cheap model by default. Its
output decides whether an email enters the quotation workflow at all; anything
it is unsure about should land on a human's screen rather than in a customer's
inbox.
"""

from __future__ import annotations

from ai.llm.base import LLMClient, system, user
from ai.llm.factory import get_client
from ai.prompts import load
from ai.schemas import AIOutcome, ClassificationResult
from ai.text import build_email_block

# Classification needs the gist, not the whole thread. A shorter budget here is
# a direct saving at a thousand emails a day.
MAX_BODY_CHARS = 6_000

TASK = "classify"


def classify_email(
    *,
    subject: str | None,
    body: str | None,
    sender_name: str | None = None,
    sender_email: str | None = None,
    client: LLMClient | None = None,
    model: str | None = None,
) -> AIOutcome[ClassificationResult]:
    """Categorise one email. Raises `StructuredOutputError` if it cannot."""
    llm = client or get_client()

    messages = [
        system(load("classify")),
        user(
            build_email_block(
                subject=subject,
                body=body,
                sender_name=sender_name,
                sender_email=sender_email,
                max_chars=MAX_BODY_CHARS,
            )
        ),
    ]

    return llm.structured(
        task=TASK, messages=messages, schema=ClassificationResult, model=model, max_tokens=500
    )
