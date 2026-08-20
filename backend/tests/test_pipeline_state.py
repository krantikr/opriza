"""The pipeline state machine behind the mailbox tabs.

Two properties carry the design, and both are pinned here:

* **Exactly one state per message.** The tabs are a queue of work, so a message
  counted twice makes every number a lie.
* **Acting on something removes it.** A tab that never empties is a tab people
  stop reading, so each transition is tested by performing the action.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.db import utcnow
from app.models import (
    Email,
    EmailCategory,
    EmailSourceType,
    FollowUpSchedule,
    FollowUpStatus,
    ProcessingStatus,
    QuotationStatus,
)
from app.services.pipeline_state import (
    PipelineState,
    follow_up_is_due,
    resolve_state,
)


@pytest.fixture()
def inbound(db, customer):
    """A message from a known customer, with the pipeline fields unset."""
    import itertools

    counter = itertools.count(1)

    def _make(**overrides) -> Email:
        fields = {
            "message_id": f"local:state-{next(counter)}",
            "thread_id": "local-thread:state",
            "source": EmailSourceType.LOCAL,
            "sender_email": customer.email,
            "sender_name": customer.name,
            "subject": "Availability of E250 plate",
            "body_text": "Please quote 20 MT.",
            "received_at": datetime.now(UTC),
            "processing_status": ProcessingStatus.PROCESSED,
            "category": EmailCategory.QUOTATION_REQUEST,
        }
        email = Email(**{**fields, **overrides})
        db.add(email)
        db.commit()
        return email

    return _make


# --- Enquiry ---------------------------------------------------------------


def test_an_enquiry_with_no_quotation_yet_is_pending(db, inbound):
    """Nothing has gone out, so it is still ours to answer."""
    assert resolve_state(inbound()) is PipelineState.ENQUIRY


def test_a_quotation_still_being_worked_on_is_an_enquiry(db, quoted_quotation):
    """READY_FOR_REVIEW means drafted but not sent - the customer has nothing."""
    assert quoted_quotation.status is QuotationStatus.READY_FOR_REVIEW
    assert resolve_state(quoted_quotation.email) is PipelineState.ENQUIRY


def test_sending_the_quotation_takes_it_out_of_enquiries(db, quoted_quotation):
    """The transition that matters: acting on it moves it on."""
    assert resolve_state(quoted_quotation.email) is PipelineState.ENQUIRY

    quoted_quotation.status = QuotationStatus.SENT
    quoted_quotation.sent_at = utcnow()
    db.commit()

    assert resolve_state(quoted_quotation.email) is not PipelineState.ENQUIRY


# --- Follow up -------------------------------------------------------------


def test_a_sent_quotation_is_in_follow_up_from_the_moment_it_goes_out(
    db, quoted_quotation
):
    """Waiting on the clock is still waiting.

    Requiring `DUE` left a quotation that had just been sent in no tab at all
    for the whole of its first interval - the trader had sent something, was
    owed a reply, and the mailbox showed it nowhere.
    """
    quoted_quotation.status = QuotationStatus.SENT
    quoted_quotation.sent_at = utcnow()
    db.add(
        FollowUpSchedule(
            quotation_request_id=quoted_quotation.id,
            attempt_no=1,
            due_at=utcnow() + timedelta(hours=24),
            status=FollowUpStatus.SCHEDULED,
        )
    )
    db.commit()
    db.refresh(quoted_quotation)

    assert resolve_state(quoted_quotation.email) is PipelineState.FOLLOW_UP
    # In the tab, but not yet overdue - the interface says which.
    assert follow_up_is_due(quoted_quotation) is False


def test_the_nudge_falling_due_marks_it_as_owed_without_moving_it(
    db, quoted_quotation
):
    """Becoming due changes the emphasis, not the tab."""
    quoted_quotation.status = QuotationStatus.SENT
    quoted_quotation.sent_at = utcnow() - timedelta(days=1)
    schedule = FollowUpSchedule(
        quotation_request_id=quoted_quotation.id,
        attempt_no=1,
        due_at=utcnow(),
        status=FollowUpStatus.DUE,
    )
    db.add(schedule)
    db.commit()
    db.refresh(quoted_quotation)

    assert resolve_state(quoted_quotation.email) is PipelineState.FOLLOW_UP
    assert follow_up_is_due(quoted_quotation) is True


def test_a_sent_quotation_with_no_rule_at_all_is_not_pending(db, quoted_quotation):
    """Nothing scheduled means nobody decided to chase it, so it is not work."""
    quoted_quotation.status = QuotationStatus.SENT
    quoted_quotation.sent_at = utcnow() - timedelta(days=1)
    db.commit()

    assert resolve_state(quoted_quotation.email) is PipelineState.DONE


def test_sending_the_nudge_clears_it_until_the_next_is_scheduled(
    db, quoted_quotation
):
    """Acting on it removes it - the property the whole tab design rests on."""
    quoted_quotation.status = QuotationStatus.SENT
    quoted_quotation.sent_at = utcnow() - timedelta(days=1)
    schedule = FollowUpSchedule(
        quotation_request_id=quoted_quotation.id,
        attempt_no=1,
        due_at=utcnow(),
        status=FollowUpStatus.DUE,
    )
    db.add(schedule)
    db.commit()
    db.refresh(quoted_quotation)
    assert resolve_state(quoted_quotation.email) is PipelineState.FOLLOW_UP

    schedule.status = FollowUpStatus.SENT
    schedule.resolved_at = utcnow()
    db.commit()
    db.refresh(quoted_quotation)

    assert resolve_state(quoted_quotation.email) is PipelineState.DONE


# --- Needs reply -----------------------------------------------------------


def test_a_customer_question_lands_in_needs_reply(db, inbound):
    assert resolve_state(inbound(awaiting_us=True)) is PipelineState.NEEDS_REPLY


def test_answering_it_clears_it(db, inbound):
    email = inbound(awaiting_us=True)
    assert resolve_state(email) is PipelineState.NEEDS_REPLY

    email.answered_at = utcnow()
    db.commit()

    assert resolve_state(email) is PipelineState.DONE


def test_a_question_outranks_a_quotation_gone_quiet(db, quoted_quotation):
    """The customer is actively waiting, which beats mere silence."""
    quoted_quotation.status = QuotationStatus.SENT
    quoted_quotation.sent_at = utcnow() - timedelta(days=5)
    quoted_quotation.email.awaiting_us = True
    db.add(
        FollowUpSchedule(
            quotation_request_id=quoted_quotation.id,
            attempt_no=1,
            due_at=utcnow(),
            status=FollowUpStatus.DUE,
        )
    )
    db.commit()
    db.refresh(quoted_quotation)

    assert resolve_state(quoted_quotation.email) is PipelineState.NEEDS_REPLY


# --- Delivery --------------------------------------------------------------


def test_an_accepted_order_waits_for_despatch(db, quoted_quotation):
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    db.commit()

    assert resolve_state(quoted_quotation.email) is PipelineState.DELIVERY


def test_marking_it_despatched_clears_it(db, quoted_quotation):
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    db.commit()
    assert resolve_state(quoted_quotation.email) is PipelineState.DELIVERY

    quoted_quotation.despatched_at = utcnow()
    db.commit()

    assert resolve_state(quoted_quotation.email) is PipelineState.DONE


# --- Complaint -------------------------------------------------------------


def test_a_complaint_is_pending_until_answered(db, inbound):
    email = inbound(category=EmailCategory.COMPLAINT)
    assert resolve_state(email) is PipelineState.COMPLAINT

    email.answered_at = utcnow()
    db.commit()

    assert resolve_state(email) is PipelineState.DONE


def test_a_complaint_outranks_everything_else(db, inbound):
    """The most serious thing in the mailbox is seen first."""
    email = inbound(category=EmailCategory.COMPLAINT, awaiting_us=True)
    assert resolve_state(email) is PipelineState.COMPLAINT


# --- Done ------------------------------------------------------------------


def test_mail_needing_nothing_is_done(db, inbound):
    """Spam and acknowledgements are reachable only through All mail."""
    assert resolve_state(inbound(category=EmailCategory.SPAM)) is PipelineState.DONE
    assert resolve_state(inbound(category=EmailCategory.GENERAL)) is PipelineState.DONE


def test_a_declined_quotation_is_done(db, quoted_quotation):
    """Nobody owes anybody anything once the customer has said no."""
    quoted_quotation.status = QuotationStatus.CUSTOMER_DECLINED
    db.commit()

    assert resolve_state(quoted_quotation.email) is PipelineState.DONE


def test_a_failed_enquiry_still_reaches_a_person(db, inbound):
    """Processing failing must not make an enquiry disappear."""
    email = inbound(processing_status=ProcessingStatus.FAILED)
    assert resolve_state(email) is PipelineState.ENQUIRY


# --- The property the whole design rests on --------------------------------


def test_every_message_resolves_to_exactly_one_state(db, inbound, quoted_quotation):
    """A message counted twice makes every tab number a lie."""
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    db.commit()

    emails = [
        inbound(),
        inbound(awaiting_us=True),
        inbound(category=EmailCategory.COMPLAINT),
        inbound(category=EmailCategory.SPAM),
        quoted_quotation.email,
    ]

    for email in emails:
        state = resolve_state(email)
        assert isinstance(state, PipelineState)
        # Resolution is deterministic: asking twice gives the same answer.
        assert resolve_state(email) is state


# --- Mail that is not a quotation request ----------------------------------


def test_a_delivery_query_reaches_the_delivery_tab(db, inbound):
    """"Where is my material" belongs with the other despatch work.

    These were classified, recorded, and then invisible: the workflow marked
    anything that was not a quotation request as SKIPPED without setting
    `awaiting_us`, so the mailbox had nothing to route on and the message sat
    in no tab at all.
    """
    email = inbound(category=EmailCategory.DELIVERY_QUERY, awaiting_us=True)
    assert resolve_state(email) is PipelineState.DELIVERY


def test_a_delivery_query_outranks_the_general_reply_queue(db, inbound):
    """A trader chasing lorries wants them in one place, not scattered
    through Needs reply."""
    email = inbound(category=EmailCategory.DELIVERY_QUERY, awaiting_us=True)
    assert resolve_state(email) is not PipelineState.NEEDS_REPLY


def test_answering_a_delivery_query_clears_it(db, inbound):
    email = inbound(category=EmailCategory.DELIVERY_QUERY, awaiting_us=True)
    assert resolve_state(email) is PipelineState.DELIVERY

    email.answered_at = utcnow()
    db.commit()

    assert resolve_state(email) is PipelineState.DONE


def test_a_complaint_still_outranks_a_delivery_query(db, inbound):
    """Urgency ordering is unchanged by the new route."""
    email = inbound(category=EmailCategory.COMPLAINT, awaiting_us=True)
    assert resolve_state(email) is PipelineState.COMPLAINT
