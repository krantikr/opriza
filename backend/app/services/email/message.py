"""Source-agnostic representation of a fetched email.

Gmail and the local `.eml` reader both produce this shape, so nothing
downstream - ingestion, classification, extraction - knows or cares where a
message came from. That is what lets the whole pipeline be developed and
demonstrated before any Gmail credentials exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.models.enums import EmailSourceType

_HTML_BLOCK_END = re.compile(r"(?i)</(p|div|tr|li|h[1-6]|blockquote)>")
_HTML_BREAK = re.compile(r"(?i)<br\s*/?>")
_HTML_DROP = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_HTML_TAG = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    """Flatten an HTML body to readable plain text.

    Deliberately dependency-free and conservative: block ends become newlines,
    tags are stripped, entities are unescaped. Enquiry emails are prose and
    simple tables, not layouts, so this is sufficient and predictable.
    """
    from html import unescape

    text = _HTML_DROP.sub(" ", html)
    text = _HTML_BREAK.sub("\n", text)
    text = _HTML_BLOCK_END.sub("\n", text)
    text = _HTML_TAG.sub(" ", text)
    text = unescape(text)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


@dataclass(frozen=True, slots=True)
class RawAttachment:
    filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    content: bytes | None = None


@dataclass(frozen=True, slots=True)
class RawEmail:
    """One message as fetched, before any interpretation."""

    # Stable, source-assigned identity. This is the deduplication key and is
    # enforced UNIQUE in the database.
    message_id: str
    source: EmailSourceType
    thread_id: str | None = None
    # The RFC 5322 Message-ID header, kept separately because the reply must
    # carry it in In-Reply-To/References to thread correctly on send.
    rfc822_message_id: str | None = None

    sender_email: str | None = None
    sender_name: str | None = None
    recipient_email: str | None = None
    subject: str | None = None
    body_text: str | None = None
    snippet: str | None = None
    received_at: datetime | None = None
    #: True when this is our own sent mail rather than something that
    #: arrived. Taken from the source rather than guessed from the sender,
    #: which would break for a desk with several addresses or an alias.
    outbound: bool = False
    attachments: list[RawAttachment] = field(default_factory=list)

    @property
    def has_attachments(self) -> bool:
        return bool(self.attachments)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RawEmail {self.message_id} {self.subject!r}>"
