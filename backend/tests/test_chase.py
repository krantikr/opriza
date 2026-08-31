"""The chase board: whose turn it is, and what that is worth.

Three properties carry the design and are pinned here:

* **Exactly one turn per quotation**, resolved by urgency. A quotation counted
  in two tabs makes every number on the screen a lie.
* **A customer who replied and was never answered is visible.** The single
  most urgent thing on a desk. If this regresses the screen is worthless.
* **Ordering is latest activity.** The board reads as a live feed - whatever
  moved most recently is the top row. Money at risk is still computed, and the
  factors behind it are still returned so the UI can show its working; it just
  no longer decides the order.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models import (
    Email,
    EmailCategory,
    EmailSourceType,
    MailDirection,
    ProcessingStatus,
    QuotationLineItem,
    QuotationPricing,
    QuotationRequest,
    QuotationStatus,
)
from app.services.chase import COLD_AFTER_DAYS, ChaseService, ChaseTurn


@pytest.fixture()
def sent_quotation(db, quoted_quotation) -> QuotationRequest:
    """The fixture quotation, actually out the door and priced.

    The board only considers quotations that reached the customer, so a
    quotation still in review is deliberately invisible to it.
    """
    quoted_quotation.status = QuotationStatus.SENT
    quoted_quotation.sent_at = datetime.now(UTC) - timedelta(days=6)

    item = quoted_quotation.line_items[0]
    db.add(
        QuotationPricing(
            quotation_line_item_id=item.id,
            quote_rate=Decimal("61000.00"),
            line_total=Decimal("1220000.00"),
            quantity_mt=Decimal("20"),
        )
    )
    db.commit()
    return quoted_quotation


def reply(db, quotation, *, body="Rate is high sir.", category=EmailCategory.PRICE_NEGOTIATION,
          answered=False, days_ago=2, attachments=False) -> Email:
    """A customer reply on the quotation's thread."""
    email = Email(
        message_id=f"local:reply-{quotation.id}-{days_ago}-{category.value}",
        thread_id=quotation.email.thread_id,
        source=EmailSourceType.LOCAL,
        sender_email=quotation.customer_email,
        sender_name=quotation.customer_name_raw,
        subject=f"Re: {quotation.quotation_number}",
        body_text=body,
        received_at=datetime.now(UTC) - timedelta(days=days_ago),
        processing_status=ProcessingStatus.PROCESSED,
        category=category,
        direction=MailDirection.INBOUND,
        replied_to_quotation_id=quotation.id,
        has_attachments=attachments,
        answered_at=datetime.now(UTC) if answered else None,
    )
    db.add(email)
    db.commit()
    return email


# ---------------------------------------------------------------------------
# Whose turn
# ---------------------------------------------------------------------------


def test_unanswered_reply_is_your_turn(db, sent_quotation):
    """A customer actively waiting is the most urgent row on the board."""
    reply(db, sent_quotation)

    rows = ChaseService(db).board()

    assert len(rows) == 1
    assert rows[0].turn is ChaseTurn.YOURS
    assert "nobody has answered" in rows[0].reason
    assert rows[0].last_actor == "They replied"
    assert rows[0].next_step == "Answer on price"


def test_unclassified_reply_still_counts(db, sent_quotation):
    """A reply the AI has not read yet is still a customer waiting.

    `pipeline_state` gates on `awaiting_us`, which only classified mail
    carries. The board must not inherit that gate: a reply sitting unprocessed
    is exactly the mail most at risk of being missed.
    """
    email = reply(db, sent_quotation, category=EmailCategory.GENERAL)
    email.category = None
    email.awaiting_us = False
    db.commit()

    assert ChaseService(db).board()[0].turn is ChaseTurn.YOURS


def test_answered_reply_is_their_turn(db, sent_quotation):
    """Acting on something removes it from the urgent bucket."""
    reply(db, sent_quotation, answered=True)

    rows = ChaseService(db).board()

    assert rows[0].turn is ChaseTurn.THEIRS


def test_passed_promise_is_your_turn(db, sent_quotation):
    """A date the customer named is a better moment to call than an interval."""
    sent_quotation.promised_date = date.today() - timedelta(days=3)
    db.commit()

    rows = ChaseService(db).board()

    assert rows[0].turn is ChaseTurn.YOURS
    # The exact day count is not asserted: `promised_date` is a local date and
    # the resolver counts in UTC, so the two disagree by one across midnight.
    # What matters is that the row names the date and says it has passed.
    assert "promised to decide" in rows[0].reason
    assert "ago" in rows[0].reason


def test_future_promise_is_not_yet_yours(db, sent_quotation):
    sent_quotation.promised_date = date.today() + timedelta(days=3)
    db.commit()

    assert ChaseService(db).board()[0].turn is ChaseTurn.THEIRS


def test_long_silence_goes_cold(db, sent_quotation):
    sent_quotation.sent_at = datetime.now(UTC) - timedelta(days=COLD_AFTER_DAYS + 4)
    db.commit()

    row = ChaseService(db).board()[0]
    assert row.turn is ChaseTurn.COLD
    assert "no reply" in row.reason


def test_snoozed_leaves_the_working_buckets(db, sent_quotation):
    """A row nobody can act on yet must not sit in the urgent list.

    Snoozing has to win over an unanswered reply, or parking something the
    customer already wrote about would not actually park it.
    """
    reply(db, sent_quotation)
    sent_quotation.snoozed_until = date.today() + timedelta(days=7)
    db.commit()

    assert ChaseService(db).board()[0].turn is ChaseTurn.SNOOZED


def test_expired_snooze_comes_back(db, sent_quotation):
    reply(db, sent_quotation)
    sent_quotation.snoozed_until = date.today() - timedelta(days=1)
    db.commit()

    assert ChaseService(db).board()[0].turn is ChaseTurn.YOURS


def test_order_outranks_a_haggle(db, sent_quotation):
    """Resolution is ordered by urgency: an unopened order is not a nudge."""
    reply(db, sent_quotation, category=EmailCategory.ORDER, attachments=True,
          body="Please find attached our PO.")

    row = ChaseService(db).board()[0]
    assert row.turn is ChaseTurn.YOURS
    assert "purchase order" in row.reason
    assert row.has_attachment


def test_every_row_has_exactly_one_turn(db, sent_quotation):
    """One quotation, one bucket - so the tab counts cannot double-count."""
    reply(db, sent_quotation)
    sent_quotation.promised_date = date.today() - timedelta(days=2)
    db.commit()

    service = ChaseService(db)
    rows = service.board()
    counts = service.counts(rows)

    assert len(rows) == 1
    assert sum(counts.values()) == len(rows)


# ---------------------------------------------------------------------------
# What is on the board at all
# ---------------------------------------------------------------------------


def test_unsent_quotations_are_not_chased(db, quoted_quotation):
    """Nothing reached the customer, so there is nothing to follow up."""
    assert ChaseService(db).board() == []


def test_a_despatched_quotation_stays_on_the_board_awaiting_payment(db, sent_quotation):
    """Despatch is not the end of the follow-up: the money is still out.

    The board used to drop these, which handed the trader back the job of
    remembering which delivered orders had not been paid for.
    """
    sent_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    sent_quotation.despatched_at = datetime.now(UTC)
    db.commit()

    rows = ChaseService(db).board()

    assert [r.stage for r in rows] == ["payment_pending"]


def test_a_paid_quotation_leaves_the_board(db, sent_quotation):
    """Paid is finished - nothing is owed in either direction."""
    sent_quotation.status = QuotationStatus.PAID
    db.commit()

    assert ChaseService(db).board() == []


def test_a_flagged_buyer_marks_the_row_priority(db, sent_quotation):
    """The same highlight the quotations list gives, on the same deal.

    A row that is starred on one screen and plain on the other teaches a
    trader that the star means something screen-specific, which it does not.
    """
    assert ChaseService(db).board()[0].is_priority is False

    sent_quotation.customer.is_priority = True
    db.commit()

    assert ChaseService(db).board()[0].is_priority is True


def test_a_negotiating_quotation_is_still_followed_up(db, sent_quotation):
    sent_quotation.status = QuotationStatus.NEGOTIATION
    db.commit()

    rows = ChaseService(db).board()

    assert [r.stage for r in rows] == ["negotiation"]


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_ordered_by_latest_activity_not_by_money(db, sent_quotation, plate, customer):
    """The most recently touched thread is the top row.

    The board reads as a live feed: a small quotation that moved yesterday
    sits above a larger one nobody has touched in three weeks. Money at risk
    is still computed and still shown - it just no longer decides the order.
    """
    recent = _second_quotation(db, customer, value=Decimal("50000.00"), days_ago=1)

    rows = ChaseService(db).board()

    assert rows[0].quotation_id == recent.id
    assert rows[0].value < rows[1].value  # ...despite being the smaller quote
    assert rows[1].quotation_id == sent_quotation.id


def test_a_fresh_reply_goes_straight_to_the_top(db, sent_quotation, customer):
    """A reply that just landed is the row a trader wants first."""
    _second_quotation(db, customer, value=Decimal("2000000.00"), days_ago=2)
    reply(db, sent_quotation, days_ago=0)

    rows = ChaseService(db).board()

    assert rows[0].quotation_id == sent_quotation.id


def test_factors_explain_the_ranking(db, sent_quotation):
    """A ranking a trader cannot interrogate is one they stop trusting."""
    reply(db, sent_quotation)

    row = ChaseService(db).board()[0]

    assert row.factors
    assert any("Your turn" in f.label for f in row.factors)
    product = 1.0
    for factor in row.factors:
        product *= factor.factor
    assert row.value_at_risk == pytest.approx(row.value * product)


def _second_quotation(db, customer, *, value: Decimal, days_ago: int) -> QuotationRequest:
    email = Email(
        message_id=f"local:second-{value}",
        thread_id=f"local-thread:second-{value}",
        source=EmailSourceType.LOCAL,
        sender_email=customer.email,
        sender_name=customer.name,
        subject="Enquiry - angle",
        body_text="Please quote 8 MT of angle.",
        received_at=datetime.now(UTC) - timedelta(days=days_ago + 1),
        processing_status=ProcessingStatus.PROCESSED,
        category=EmailCategory.QUOTATION_REQUEST,
    )
    db.add(email)
    db.flush()

    quotation = QuotationRequest(
        quotation_number=f"Q-{int(value)}",
        email_id=email.id,
        customer_id=customer.id,
        customer_email=customer.email,
        customer_name_raw=customer.name,
        status=QuotationStatus.SENT,
        sent_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(quotation)
    db.flush()

    item = QuotationLineItem(
        quotation_request_id=quotation.id,
        line_no=1,
        product_type="Angle",
        grade="E250",
        thickness_mm=8.0,
        quantity_mt=Decimal("8"),
    )
    db.add(item)
    db.flush()
    db.add(
        QuotationPricing(
            quotation_line_item_id=item.id,
            quote_rate=value / Decimal("8"),
            line_total=value,
            quantity_mt=Decimal("8"),
        )
    )
    db.commit()
    return quotation


# ---------------------------------------------------------------------------
# What the columns carry
#
# A body snippet was tried here first and cut: two clamped lines of an email
# are almost always the salutation ("Dear Kranti Kumar,") and never the ask,
# so the widest column on the screen carried no information. These pin the
# facts that replaced it.
# ---------------------------------------------------------------------------


def test_next_step_names_the_action(db, sent_quotation):
    """The column tells the trader what to do, not what was written."""
    reply(db, sent_quotation, category=EmailCategory.ORDER)
    assert ChaseService(db).board()[0].next_step == "Confirm the order"


def test_next_step_warns_before_stock_is_short(db, sent_quotation):
    """Chasing an order the yard cannot fill is worse than not chasing it."""
    item = sent_quotation.line_items[0]
    item.stock_availability.sufficient = False
    item.stock_availability.available_qty_mt = Decimal("5")
    db.commit()

    row = ChaseService(db).board()[0]
    assert row.stock_short
    assert "15 MT short" in (row.stock_note or "")
    assert row.next_step == "Check stock before replying"


def test_last_activity_is_dated_not_paraphrased(db, sent_quotation):
    """Who moved last and when - answerable exactly, unlike a summary."""
    email = reply(db, sent_quotation, days_ago=2)

    row = ChaseService(db).board()[0]
    assert row.last_at == email.received_at
    assert row.last_direction == "INBOUND"
    assert row.last_actor == "They replied"
    assert row.message_count >= 2


def test_unanswered_quotation_reports_our_own_last_move(db, sent_quotation):
    """With no reply the thread's last movement is the quotation itself.

    Otherwise the row reads as though the conversation had never started.
    """
    row = ChaseService(db).board()[0]
    assert row.last_actor == "You quoted"
    assert row.last_at == sent_quotation.sent_at
    assert row.last_direction == "OUTBOUND"


def test_quote_age_is_separate_from_time_waiting(db, sent_quotation):
    """A six-day-old quotation replied to yesterday is not six days stale."""
    reply(db, sent_quotation, days_ago=1)

    row = ChaseService(db).board()[0]
    assert row.quote_age_days == 6
    assert row.days_waiting == 1


def test_terms_travel_with_the_row(db, sent_quotation):
    """Delivery and payment decide the call as much as the rate does."""
    row = ChaseService(db).board()[0]
    assert row.delivery_location == "Patna"
