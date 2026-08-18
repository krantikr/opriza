"""Fetch inbound mail and persist it exactly once.

The duplicate guard is the UNIQUE constraint on `emails.message_id`, not the
existence check that precedes it. The check is an optimisation; the constraint
is the guarantee. Two poller runs overlapping in time would both pass a check
and both insert - only the database can actually prevent that, and an
IntegrityError here is treated as a normal duplicate rather than an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Email, EmailAttachment, ProcessingStatus
from app.services import audit
from app.services.email.attachments import extract_text
from app.services.email.message import RawEmail
from app.services.email.source import EmailSource

logger = get_logger(__name__)


@dataclass(slots=True)
class IngestionReport:
    source: str
    fetched: int = 0
    created: int = 0
    duplicates: int = 0
    failed: int = 0
    created_email_ids: list[int] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"ingest[{self.source}] fetched={self.fetched} new={self.created} "
            f"duplicate={self.duplicates} failed={self.failed}"
        )


class EmailIngestionService:
    def __init__(self, db: Session, source: EmailSource) -> None:
        self.db = db
        self.source = source

    def ingest(self, limit: int = 25) -> IngestionReport:
        report = IngestionReport(source=self.source.describe())

        if not self.source.is_available():
            logger.error("Email source unavailable: %s", self.source.describe())
            report.errors.append({"error": f"source unavailable: {self.source.describe()}"})
            return report

        messages = self.source.fetch(limit=limit)
        report.fetched = len(messages)

        for raw in messages:
            try:
                email = self._persist(raw)
            except IntegrityError:
                # Lost the race against a concurrent poll - the other run has it.
                self.db.rollback()
                report.duplicates += 1
                continue
            except Exception as exc:  # noqa: BLE001 - one bad message must not stop the batch
                self.db.rollback()
                report.failed += 1
                report.errors.append({"message_id": raw.message_id, "error": str(exc)})
                logger.error("Failed to ingest %s: %s", raw.message_id, exc)
                continue

            if email is None:
                report.duplicates += 1
            else:
                report.created += 1
                report.created_email_ids.append(email.id)

        logger.info(report.summary())
        return report

    # --- Persistence ------------------------------------------------------

    def _persist(self, raw: RawEmail) -> Email | None:
        """Insert one message, or return None if it is already stored."""
        existing = self.db.scalar(select(Email.id).where(Email.message_id == raw.message_id))
        if existing is not None:
            return None

        email = Email(
            message_id=raw.message_id,
            thread_id=raw.thread_id,
            rfc822_message_id=raw.rfc822_message_id,
            source=raw.source,
            sender_email=raw.sender_email,
            sender_name=raw.sender_name,
            recipient_email=raw.recipient_email,
            subject=raw.subject,
            body_text=raw.body_text,
            snippet=raw.snippet,
            received_at=raw.received_at,
            has_attachments=raw.has_attachments,
            processing_status=ProcessingStatus.PENDING,
        )
        self.db.add(email)
        self.db.flush()  # assigns email.id and trips the UNIQUE constraint early

        for raw_attachment in raw.attachments:
            outcome = extract_text(
                raw_attachment.filename, raw_attachment.mime_type, raw_attachment.content
            )
            if outcome.error:
                logger.info(
                    "Attachment %s on %s: %s",
                    raw_attachment.filename,
                    raw.message_id,
                    outcome.error,
                )
            self.db.add(
                EmailAttachment(
                    email_id=email.id,
                    filename=raw_attachment.filename,
                    mime_type=raw_attachment.mime_type,
                    size_bytes=raw_attachment.size_bytes,
                    extracted_text=outcome.text,
                    extraction_error=outcome.error,
                )
            )

        audit.record(
            self.db,
            entity_type="email",
            entity_id=email.id,
            action="INGESTED",
            details={
                "message_id": raw.message_id,
                "source": raw.source.value,
                "subject": raw.subject,
                "attachments": len(raw.attachments),
            },
        )

        self.db.commit()
        return email
