"""Draft generation (pipeline stage 7).

The model receives verified facts and writes prose around them. It never sees
the pricing rules, the price master or the invoice history, because it has no
business deciding any of it - by the time this runs, the numbers are settled.

`ai.guards.verify_draft_facts` then checks the generated body actually contains
the figures it was given. That check is deliberately outside the prompt: an
instruction is a request, and a quotation that silently rounds a rate is a
commercial document that misstates a price.
"""

from __future__ import annotations

from ai.llm.base import LLMClient, system, user
from ai.llm.factory import get_client
from ai.prompts import load
from ai.schemas import AIOutcome, DraftEmail

TASK = "draft"

_REGENERATE_NOTE = (
    "Your previous draft did not reproduce the supplied facts exactly:\n\n"
    "$violations\n\n"
    "Write the email again. Every price, quantity, specification and term must "
    "appear exactly as given in the facts. Do not round, reformat or recalculate."
)


def generate_draft(
    *,
    facts: str,
    original_subject: str | None = None,
    original_body: str | None = None,
    violations: list[str] | None = None,
    previous_draft: str | None = None,
    client: LLMClient | None = None,
    model: str | None = None,
) -> AIOutcome[DraftEmail]:
    """Write a quotation reply from verified facts.

    `violations` and `previous_draft` are supplied on a regeneration attempt so
    the model is told precisely which figure it altered.
    """
    llm = client or get_client()

    context = ["<verified_facts>", facts.strip(), "</verified_facts>"]

    if original_subject or original_body:
        context += [
            "",
            "<customer_enquiry>",
            f"Subject: {original_subject or '(no subject)'}",
            "",
            (original_body or "").strip()[:4_000],
            "</customer_enquiry>",
        ]

    messages = [system(load("draft")), user("\n".join(context))]

    if previous_draft and violations:
        messages.append({"role": "assistant", "content": previous_draft})
        messages.append(
            user(
                _REGENERATE_NOTE.replace(
                    "$violations", "\n".join(f"- {v}" for v in violations)
                )
            )
        )

    return llm.structured(
        task=TASK, messages=messages, schema=DraftEmail, model=model, max_tokens=2_000
    )
