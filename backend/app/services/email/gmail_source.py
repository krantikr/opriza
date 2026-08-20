"""Gmail implementation of the email source port."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any

from app.core.logging import get_logger
from app.models.enums import EmailSourceType
from app.services.email.gmail_client import GmailAuthError, GmailClient, b64url_decode
from app.services.email.message import RawAttachment, RawEmail, html_to_text
from app.services.email.source import EmailSource

logger = get_logger(__name__)

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    """Header list -> case-insensitive lookup dict."""
    return {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}


class GmailSource(EmailSource):
    source_type = EmailSourceType.GMAIL

    def __init__(self, client: GmailClient, query: str, fetch_attachments: bool = True) -> None:
        self.client = client
        self.query = query
        self.fetch_attachments = fetch_attachments

    def is_available(self) -> bool:
        return self.client.is_authorized()

    def describe(self) -> str:
        return f"Gmail (query: {self.query})"

    def fetch(self, limit: int = 25) -> list[RawEmail]:
        try:
            message_ids = self.client.list_message_ids(self.query, max_results=limit)
        except GmailAuthError as exc:
            logger.error("Gmail unavailable: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001 - API/network failures are expected
            logger.error("Gmail list failed: %s", exc)
            return []

        emails: list[RawEmail] = []
        for message_id in message_ids:
            try:
                emails.append(self._to_raw_email(self.client.get_message(message_id)))
            except Exception as exc:  # noqa: BLE001 - one bad message must not stop the poll
                logger.error("Could not read Gmail message %s: %s", message_id, exc)

        logger.info("Gmail source fetched %d of %d message(s)", len(emails), len(message_ids))
        return emails

    # --- Conversion -------------------------------------------------------

    def _to_raw_email(self, message: dict[str, Any]) -> RawEmail:
        payload = message.get("payload", {})
        headers = _headers(payload)

        sender_name, sender_email = parseaddr(headers.get("from", ""))
        _, recipient_email = parseaddr(headers.get("to", ""))

        received_at = None
        if internal_date := message.get("internalDate"):
            received_at = datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)

        plain_parts: list[str] = []
        html_parts: list[str] = []
        attachments: list[RawAttachment] = []
        self._walk(payload, message["id"], plain_parts, html_parts, attachments)

        # Prefer the plain-text alternative; fall back to flattened HTML.
        body = "\n".join(p for p in plain_parts if p.strip()).strip()
        if not body and html_parts:
            body = html_to_text("\n".join(html_parts))

        # Gmail's own label is authoritative. Comparing the sender against a
        # configured address would misread an alias or a second address the
        # desk also sends from.
        labels = message.get("labelIds") or []

        return RawEmail(
            outbound="SENT" in labels,
            message_id=message["id"],
            source=self.source_type,
            thread_id=message.get("threadId"),
            rfc822_message_id=headers.get("message-id"),
            sender_email=sender_email.lower() if sender_email else None,
            sender_name=sender_name or None,
            recipient_email=recipient_email or None,
            subject=headers.get("subject"),
            body_text=body,
            snippet=message.get("snippet"),
            received_at=received_at,
            attachments=attachments,
        )

    def _walk(
        self,
        part: dict[str, Any],
        message_id: str,
        plain: list[str],
        html: list[str],
        attachments: list[RawAttachment],
    ) -> None:
        """Recursively collect bodies and attachments from a MIME tree."""
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        filename = part.get("filename") or ""

        if filename:
            attachments.append(self._read_attachment(part, message_id, filename, mime_type, body))
        elif mime_type == "text/plain":
            plain.append(b64url_decode(body.get("data")).decode("utf-8", errors="replace"))
        elif mime_type == "text/html":
            html.append(b64url_decode(body.get("data")).decode("utf-8", errors="replace"))

        for child in part.get("parts", []):
            self._walk(child, message_id, plain, html, attachments)

    def _read_attachment(
        self,
        part: dict[str, Any],
        message_id: str,
        filename: str,
        mime_type: str,
        body: dict[str, Any],
    ) -> RawAttachment:
        size = body.get("size")
        content: bytes | None = None

        if not self.fetch_attachments:
            return RawAttachment(filename=filename, mime_type=mime_type, size_bytes=size)

        if size and size > MAX_ATTACHMENT_BYTES:
            logger.warning("Skipping oversized attachment %s (%s bytes)", filename, size)
            return RawAttachment(filename=filename, mime_type=mime_type, size_bytes=size)

        try:
            if attachment_id := body.get("attachmentId"):
                content = self.client.get_attachment(message_id, attachment_id)
            elif data := body.get("data"):
                content = b64url_decode(data)
        except Exception as exc:  # noqa: BLE001 - a failed download is recorded, not fatal
            logger.error("Could not download attachment %s: %s", filename, exc)

        return RawAttachment(
            filename=filename,
            mime_type=mime_type,
            size_bytes=size or (len(content) if content else None),
            content=content,
        )
