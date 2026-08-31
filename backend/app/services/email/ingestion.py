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
from app.models import (
    Email,
    EmailAttachment,
    EmailCategory,
    MailDirection,
    ProcessingStatus,
)
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

    def _record_manual_reply(self, email: Email) -> None:
        """A reply the trader sent from Gmail rather than through Steel Desk.

        They have still answered the customer, so the quotation is genuinely
        out and the desk is owed a reply - it belongs in Follow up, not in
        Enquiries. Without this the system shows work that is already done and
        chases a customer who is waiting on nothing, which is the fastest way
        to make an automated desk look broken.

        The draft is left alone: what went out was composed in Gmail and this
        system never saw it, so recording a draft it did not write would be
        inventing a record.
        """
        from app.core.db import utcnow
        from app.models import QuotationStatus

        quotation = _quotation_in_thread(self.db, email)
        if quotation is None or quotation.sent_at is not None:
            return

        quotation.status = QuotationStatus.SENT
        quotation.sent_at = email.received_at or utcnow()
        quotation.review_notes = "\n".join(
            filter(
                None,
                [quotation.review_notes, "Answered directly from the mailbox."],
            )
        )
        # The original enquiry is answered, so it leaves the pending queue.
        if quotation.email is not None:
            quotation.email.answered_at = quotation.sent_at
        self.db.flush()

        logger.info(
            "Recorded a reply sent outside Steel Desk for %s", quotation.quotation_number
        )

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
            direction=MailDirection.OUTBOUND if raw.outbound else MailDirection.INBOUND,
            # Our own sent mail is stored for the thread and to prove a reply
            # happened, but there is nothing for the AI to classify or answer
            # in a message we wrote ourselves.
            processing_status=(
                ProcessingStatus.SKIPPED if raw.outbound else ProcessingStatus.PENDING
            ),
            category=EmailCategory.GENERAL if raw.outbound else None,
        )
        self.db.add(email)
        self.db.flush()  # assigns email.id and trips the UNIQUE constraint early

        if raw.outbound:
            self._record_manual_reply(email)

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


def _quotation_in_thread(db, email: Email):
    """The quotation this outbound message belongs to, by mail thread."""
    from sqlalchemy import select

    from app.models import QuotationRequest

    if not email.thread_id:
        return None
    return db.scalars(
        select(QuotationRequest)
        .join(Email, QuotationRequest.email_id == Email.id)
        .where(Email.thread_id == email.thread_id, Email.id != email.id)
        .order_by(QuotationRequest.id.desc())
        .limit(1)
    ).first()
