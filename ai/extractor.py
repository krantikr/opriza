"""Requirement extraction (pipeline stage 3).

Turns an enquiry into `ExtractedEnquiry`. Uses the stronger model, because this
is where a mistake becomes a wrong price rather than a wrong folder.

Attachment text is included in the body handed to the model: steel RFQs are
frequently a one-line covering note with the actual requirement in a PDF or
spreadsheet, and extracting from the covering note alone would find nothing.
"""

from __future__ import annotations

from ai.llm.base import LLMClient, system, user
from ai.llm.factory import get_client
from ai.prompts import load
from ai.schemas import AIOutcome, ExtractedEnquiry
from ai.text import build_email_block

# Generous, because a BOQ attachment legitimately runs long and dropping its
# tail would silently drop line items.
MAX_BODY_CHARS = 20_000

TASK = "extract"


def extract_requirement(
    *,
    subject: str | None,
    body: str | None,
    sender_name: str | None = None,
    sender_email: str | None = None,
    received_at: str | None = None,
    client: LLMClient | None = None,
    model: str | None = None,
) -> AIOutcome[ExtractedEnquiry]:
    """Extract structured requirements from one enquiry.

    Raises `StructuredOutputError` when no valid structure could be produced.
    The caller routes such an enquiry to manual review - it never proceeds with
    partial data.
    """
    llm = client or get_client()

    messages = [
        system(load("extract")),
        user(
            build_email_block(
                subject=subject,
                body=body,
                sender_name=sender_name,
                sender_email=sender_email,
                received_at=received_at,
                max_chars=MAX_BODY_CHARS,
            )
        ),
    ]

    return llm.structured(
        task=TASK, messages=messages, schema=ExtractedEnquiry, model=model, max_tokens=4_000
    )
