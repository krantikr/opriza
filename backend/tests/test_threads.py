"""The conversation view over a quotation.

Two properties matter and both are pinned here:

* **Chronological, and complete.** A trader reading a thread must see every
  message, including a reply the customer sent straight from their mail
  client without touching this system.
* **The state spans the conversation.** A reply lives on its own row, so
  reading only the original enquiry would report a conversation that is
  actively waiting on us as finished.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.db import utcnow
from app.models import (
    DraftStatus,
    Email,
    EmailSourceType,
    FollowUp,
    ProcessingStatus,
    QuotationDraft,
    QuotationStatus,
    ReplyIntent,
)
from app.services.threads import MessageDirection, MessageKind, build_thread, thread_state


@pytest.fixture()
def conversation(db, default_org, quoted_quotation):
    """An enquiry, our quotation, their reply, and our nudge."""
    quotation = quoted_quotation
    base = quotation.email.received_at

    quotation.status = QuotationStatus.SENT
    quotation.sent_at = base + timedelta(hours=2)
    db.add(
        QuotationDraft(
            quotation_request_id=quotation.id,
            version=1,
            is_current=True,
            subject="Our quotation",
            body="Rs 62,500 per MT ex-works.",
            status=DraftStatus.SENT,
        )
    )
    db.add(
        Email(
            organisation_id=default_org,
            message_id="local:thread-reply",
            thread_id=quotation.email.thread_id,
            source=EmailSourceType.LOCAL,
            sender_email=quotation.email.sender_email,
            subject="Re: enquiry",
            body_text="Can you do better on the rate?",
            received_at=base + timedelta(days=1),
            processing_status=ProcessingStatus.PROCESSED,
            replied_to_quotation_id=quotation.id,
            reply_intent=ReplyIntent.NEEDS_REVIEW,
            awaiting_us=True,
        )
    )
    db.add(
        FollowUp(
            organisation_id=default_org,
            quotation_request_id=quotation.id,
            subject="Following up",
            body="Any thoughts on our offer?",
            sent=True,
            # Dated explicitly: `created_at` defaults to now, which would sort
            # a historic conversation's nudge before the quotation it chases.
            created_at=base + timedelta(days=3),
        )
    )
    db.commit()
    return quotation


def test_the_thread_reads_in_the_order_it_happened(db, conversation):
    """They asked, we quoted, they replied, we chased."""
    messages = build_thread(db, conversation)

    assert [m.kind for m in messages] == [
        MessageKind.ENQUIRY,
        MessageKind.QUOTATION,
        MessageKind.REPLY,
        MessageKind.FOLLOW_UP,
    ]
    assert [m.at for m in messages] == sorted(m.at for m in messages)


def test_each_message_says_who_wrote_it(db, conversation):
    """Direction carries the shape of a conversation at a glance."""
    messages = build_thread(db, conversation)
    assert [m.direction for m in messages] == [
        MessageDirection.INBOUND,
        MessageDirection.OUTBOUND,
        MessageDirection.INBOUND,
        MessageDirection.OUTBOUND,
    ]


def test_a_customer_reply_sent_straight_from_their_mail_client_appears(db, conversation):
    """The case that motivated this: they never touch our interface."""
    bodies = [m.body for m in build_thread(db, conversation)]
    assert "Can you do better on the rate?" in bodies


def test_a_reply_carries_what_it_was_understood_to_mean(db, conversation):
    reply = next(
        m for m in build_thread(db, conversation) if m.kind is MessageKind.REPLY
    )
    assert reply.outcome == "Needs a person to read it"


def test_nothing_is_invented_when_there_is_no_reading(db, conversation):
    """An absent outcome is more honest than a guess."""
    enquiry = next(
        m for m in build_thread(db, conversation) if m.kind is MessageKind.ENQUIRY
    )
    assert enquiry.outcome is None


def test_an_unsent_quotation_is_not_shown_as_correspondence(db, quoted_quotation):
    """A draft nobody approved was never received, so it is not in the thread."""
    db.add(
        QuotationDraft(
            quotation_request_id=quoted_quotation.id,
            version=1,
            is_current=True,
            subject="Draft",
            body="Not sent yet.",
        )
    )
    db.commit()

    kinds = [m.kind for m in build_thread(db, quoted_quotation)]
    assert MessageKind.QUOTATION not in kinds


# --- The state of the whole conversation -----------------------------------


def test_the_state_follows_the_reply_not_the_original_enquiry(db, conversation):
    """The bug this guards: the enquiry is DONE once quoted, while the reply
    that needs answering sits on a different row. Reading only the first
    message showed a conversation waiting on us as finished."""
    from app.services.pipeline_state import PipelineState, resolve_state

    assert resolve_state(conversation.email) is PipelineState.DONE
    assert thread_state(db, conversation) == "NEEDS_REPLY"


def test_answering_the_reply_settles_the_conversation(db, conversation):
    """Acting on it clears it - the property the mailbox rests on."""
    from sqlalchemy import select

    reply = db.scalars(
        select(Email).where(Email.replied_to_quotation_id == conversation.id)
    ).one()
    reply.answered_at = utcnow()
    db.commit()

    assert thread_state(db, conversation) == "DONE"


def test_the_most_urgent_stage_wins(db, conversation):
    """A complaint outranks a question, exactly as it does per message."""
    from sqlalchemy import select

    from app.models import EmailCategory

    reply = db.scalars(
        select(Email).where(Email.replied_to_quotation_id == conversation.id)
    ).one()
    reply.category = EmailCategory.COMPLAINT
    db.commit()

    assert thread_state(db, conversation) == "COMPLAINT"


# --- The mailbox's way in ---------------------------------------------------


def test_the_mailbox_shows_a_conversation_not_one_message(db, conversation):
    """A reply detached from what it answers is what this replaces.

    The Inbox works in emails, so it needs its own entry point; opening any
    message in a conversation shows the whole conversation.
    """
    from app.services.threads import thread_for_email

    messages = thread_for_email(db, conversation.email)
    assert len(messages) > 1
    assert messages[0].kind is MessageKind.ENQUIRY


def test_opening_a_reply_shows_the_same_conversation(db, conversation):
    """Whichever end a trader opens it from, it is one thread."""
    from sqlalchemy import select

    from app.services.threads import thread_for_email

    reply = db.scalars(
        select(Email).where(Email.replied_to_quotation_id == conversation.id)
    ).one()

    from_enquiry = [m.id for m in thread_for_email(db, conversation.email)]
    from_reply = [m.id for m in thread_for_email(db, reply)]
    assert from_enquiry == from_reply


def test_mail_with_no_quotation_still_reads_as_a_conversation(db, default_org):
    """A delivery query or complaint has no quotation, and must not be shown
    as a single message stripped of its context."""
    from app.models import EmailCategory, EmailSourceType, MailDirection
    from app.services.threads import thread_for_email

    enquiry = Email(
        organisation_id=default_org,
        message_id="local:dq-1",
        thread_id="thread-dq",
        source=EmailSourceType.LOCAL,
        subject="Where is my material?",
        body_text="Any update on the despatch?",
        received_at=utcnow(),
        processing_status=ProcessingStatus.SKIPPED,
        category=EmailCategory.DELIVERY_QUERY,
    )
    answer = Email(
        organisation_id=default_org,
        message_id="local:dq-2",
        thread_id="thread-dq",
        source=EmailSourceType.LOCAL,
        subject="Re: Where is my material?",
        body_text="It leaves tomorrow.",
        received_at=utcnow(),
        direction=MailDirection.OUTBOUND,
        processing_status=ProcessingStatus.SKIPPED,
    )
    db.add_all([enquiry, answer])
    db.commit()

    messages = thread_for_email(db, enquiry)
    assert len(messages) == 2
    assert messages[1].direction is MessageDirection.OUTBOUND


def test_a_message_that_stands_alone_is_still_returned(db, default_org):
    """One message is a one-message conversation, not an error."""
    from app.models import EmailSourceType
    from app.services.threads import thread_for_email

    lone = Email(
        organisation_id=default_org,
        message_id="local:lone",
        source=EmailSourceType.LOCAL,
        subject="Hello",
        body_text="Just saying hello.",
        received_at=utcnow(),
        processing_status=ProcessingStatus.SKIPPED,
    )
    db.add(lone)
    db.commit()

    assert len(thread_for_email(db, lone)) == 1
