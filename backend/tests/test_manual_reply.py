"""A trader who answers a customer from Gmail rather than through Steel Desk.

This is the ordinary case, not an edge one: a desk that has just connected its
mailbox still works the way it always did. A system that only reads the inbox
cannot see those replies, so it shows finished work as outstanding and chases
customers who are waiting on nothing - the fastest way to make an automated
desk look broken and get switched off.
"""

from __future__ import annotations

from app.models import (
    Email,
    MailDirection,
    ProcessingStatus,
    QuotationStatus,
)
from app.services.email.ingestion import EmailIngestionService
from app.services.email.message import RawEmail
from app.services.email.source import EmailSource
from app.services.pipeline_state import PipelineState, resolve_state


class _Fixed(EmailSource):
    """A source returning exactly what a test hands it."""

    source_type = None

    def __init__(self, emails: list[RawEmail]) -> None:
        self._emails = emails

    def is_available(self) -> bool:
        return True

    def describe(self) -> str:
        return "fixed test source"

    def fetch(self, limit: int = 25) -> list[RawEmail]:
        return self._emails[:limit]


def _reply(quotation, *, outbound: bool = True, message_id: str | None = None) -> RawEmail:
    from app.models import EmailSourceType

    return RawEmail(
        message_id=message_id
        or f"test:{'sent' if outbound else 'in'}-{quotation.id}",
        source=EmailSourceType.LOCAL,
        thread_id=quotation.email.thread_id,
        sender_email="desk@example.com" if outbound else "customer@example.com",
        subject=f"Re: {quotation.email.subject}",
        body_text="Our rate is Rs 62,500 per MT ex-works.",
        received_at=quotation.email.received_at,
        outbound=outbound,
    )


def test_our_own_sent_mail_is_stored(db, quoted_quotation):
    """It has to be, or the thread is missing half the conversation."""
    EmailIngestionService(db, _Fixed([_reply(quoted_quotation)])).ingest()
    db.commit()

    from sqlalchemy import select

    sent = db.scalars(
        select(Email).where(Email.direction == MailDirection.OUTBOUND)
    ).one()
    assert sent.subject.startswith("Re:")


def test_our_own_mail_is_not_sent_through_the_ai(db, quoted_quotation):
    """There is nothing to classify or answer in a message we wrote."""
    EmailIngestionService(db, _Fixed([_reply(quoted_quotation)])).ingest()
    db.commit()

    from sqlalchemy import select

    sent = db.scalars(
        select(Email).where(Email.direction == MailDirection.OUTBOUND)
    ).one()
    assert sent.processing_status is ProcessingStatus.SKIPPED


def test_replying_from_gmail_marks_the_quotation_as_sent(db, quoted_quotation):
    """The trader has answered, so the quotation is genuinely out."""
    assert quoted_quotation.sent_at is None

    EmailIngestionService(db, _Fixed([_reply(quoted_quotation)])).ingest()
    db.commit()
    db.refresh(quoted_quotation)

    assert quoted_quotation.status is QuotationStatus.SENT
    assert quoted_quotation.sent_at is not None


def test_the_enquiry_leaves_the_pending_queue(db, quoted_quotation):
    """It has been answered, so it is no longer work.

    The bug this guards: an answered enquiry sitting in Enquiries forever,
    because the reply was invisible to a system that only read the inbox.
    """
    assert resolve_state(quoted_quotation.email) is PipelineState.ENQUIRY

    EmailIngestionService(db, _Fixed([_reply(quoted_quotation)])).ingest()
    db.commit()
    db.refresh(quoted_quotation)

    assert resolve_state(quoted_quotation.email) is not PipelineState.ENQUIRY


def test_following_up_starts_from_when_the_reply_actually_went_out(
    db, quoted_quotation, default_org
):
    """The clock runs from the real send, not from when we noticed it.

    A reply composed in Gmail is what put the quotation in front of the
    customer, so `sent_at` is its timestamp - the Follow-ups board dates and
    orders every row by it.
    """
    reply = _reply(quoted_quotation)

    EmailIngestionService(db, _Fixed([reply])).ingest()
    db.commit()
    db.refresh(quoted_quotation)

    assert quoted_quotation.sent_at is not None
    assert quoted_quotation.sent_at == reply.received_at


def test_no_draft_is_invented_for_a_reply_we_never_composed(db, quoted_quotation):
    """What went out was written in Gmail. Recording a draft this system did
    not write would be inventing a record of what was quoted."""
    from sqlalchemy import func, select

    from app.models import QuotationDraft

    before = db.scalar(select(func.count()).select_from(QuotationDraft))
    EmailIngestionService(db, _Fixed([_reply(quoted_quotation)])).ingest()
    db.commit()

    assert db.scalar(select(func.count()).select_from(QuotationDraft)) == before


def test_an_inbound_message_is_still_processed_normally(db, quoted_quotation):
    """The change must not stop customers' mail reaching the pipeline."""
    EmailIngestionService(db, _Fixed([_reply(quoted_quotation, outbound=False)])).ingest()
    db.commit()

    from sqlalchemy import select

    arrived = db.scalars(
        select(Email).where(Email.direction == MailDirection.INBOUND, Email.id != quoted_quotation.email_id)
    ).one()
    assert arrived.processing_status is ProcessingStatus.PENDING


def test_a_second_reply_does_not_re_date_the_first_send(db, quoted_quotation):
    """Sending twice must not restart the clock on chasing."""
    EmailIngestionService(db, _Fixed([_reply(quoted_quotation)])).ingest()
    db.commit()
    db.refresh(quoted_quotation)
    first = quoted_quotation.sent_at

    # A distinct id, because `RawEmail` is frozen and message_id is the
    # deduplication key.
    second = _reply(quoted_quotation, message_id="test:sent-again")
    EmailIngestionService(db, _Fixed([second])).ingest()
    db.commit()
    db.refresh(quoted_quotation)

    assert quoted_quotation.sent_at == first


