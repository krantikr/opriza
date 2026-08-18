"""Shared text preparation for prompts."""

from __future__ import annotations

TRUNCATION_MARKER = "\n\n[... message truncated ...]"


def truncate(text: str | None, max_chars: int) -> str:
    """Trim to a character budget, marking the cut so the model knows.

    An unmarked truncation invites the model to treat a cut-off list as
    complete, which for a multi-item RFQ means silently dropping line items.
    """
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + TRUNCATION_MARKER


def build_email_block(
    *,
    subject: str | None,
    body: str | None,
    sender_name: str | None = None,
    sender_email: str | None = None,
    received_at: str | None = None,
    max_chars: int = 12_000,
) -> str:
    """Render an email as a labelled block for the model to read."""
    lines = ["<email>"]
    if sender_name or sender_email:
        who = " ".join(part for part in (sender_name, f"<{sender_email}>" if sender_email else "") if part)
        lines.append(f"From: {who}")
    if received_at:
        lines.append(f"Date: {received_at}")
    lines.append(f"Subject: {subject or '(no subject)'}")
    lines.append("")
    lines.append(truncate(body, max_chars))
    lines.append("</email>")
    return "\n".join(lines)
