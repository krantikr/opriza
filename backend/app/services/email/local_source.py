"""Reads `.eml` files from a folder.

This is the development and demonstration source. It exists so the entire
pipeline - classification, extraction, matching, pricing, drafting, approval -
can be built, tested and shown without Gmail credentials, and so a demo cannot
be derailed by a network problem.

Identity is the filename stem, which is stable across regenerations of the
sample corpus. Re-running ingestion over the same folder therefore produces
duplicates that the ingestion service skips, exactly as a second Gmail poll
would.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from app.core.logging import get_logger
from app.models.enums import EmailSourceType
from app.services.email.message import RawAttachment, RawEmail, html_to_text
from app.services.email.source import EmailSource

logger = get_logger(__name__)

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024


class LocalFileSource(EmailSource):
    source_type = EmailSourceType.LOCAL

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def is_available(self) -> bool:
        return self.directory.exists()

    def describe(self) -> str:
        return f"local files in {self.directory}"

    def fetch(self, limit: int = 25) -> list[RawEmail]:
        if not self.is_available():
            logger.warning("Local email directory does not exist: %s", self.directory)
            return []

        paths = sorted(self.directory.glob("*.eml"))
        emails: list[RawEmail] = []

        for path in paths[:limit]:
            try:
                emails.append(self._parse(path))
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
                logger.error("Could not parse %s: %s", path.name, exc)

        logger.info("Local source read %d of %d file(s) from %s", len(emails), len(paths), self.directory)
        return emails

    def _parse(self, path: Path) -> RawEmail:
        message: EmailMessage = BytesParser(policy=policy.default).parsebytes(path.read_bytes())

        sender_name, sender_email = parseaddr(message.get("From", ""))
        _, recipient_email = parseaddr(message.get("To", ""))

        received_at = None
        if raw_date := message.get("Date"):
            try:
                received_at = parsedate_to_datetime(raw_date)
                if received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                logger.debug("Unparseable Date header in %s: %r", path.name, raw_date)
        if received_at is None:
            received_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

        body = self._extract_body(message)

        return RawEmail(
            message_id=f"local:{path.stem}",
            source=self.source_type,
            thread_id=f"local-thread:{path.stem}",
            rfc822_message_id=message.get("Message-ID"),
            sender_email=(sender_email or None) and sender_email.lower(),
            sender_name=sender_name or None,
            recipient_email=recipient_email or None,
            subject=message.get("Subject"),
            body_text=body,
            snippet=(body or "")[:400],
            received_at=received_at,
            attachments=self._extract_attachments(message),
        )

    @staticmethod
    def _extract_body(message: EmailMessage) -> str:
        part = message.get_body(preferencelist=("plain", "html"))
        if part is None:
            return ""
        content = part.get_content()
        if part.get_content_subtype() == "html":
            return html_to_text(content)
        return str(content).strip()

    @staticmethod
    def _extract_attachments(message: EmailMessage) -> list[RawAttachment]:
        attachments: list[RawAttachment] = []
        for part in message.iter_attachments():
            filename = part.get_filename()
            if not filename:
                continue
            payload = part.get_payload(decode=True) or b""
            if len(payload) > MAX_ATTACHMENT_BYTES:
                logger.warning("Skipping oversized attachment %s (%d bytes)", filename, len(payload))
                payload = b""
            attachments.append(
                RawAttachment(
                    filename=filename,
                    mime_type=part.get_content_type(),
                    size_bytes=len(payload) or None,
                    content=payload or None,
                )
            )
        return attachments
