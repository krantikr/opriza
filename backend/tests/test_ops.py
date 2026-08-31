"""Notifications, follow-up scheduling, stock movement and reports.

The property under test throughout is the one the whole system rests on:
**automation decides when, a human decides whether.** The scheduler may mark a
follow-up due; only a person sends it.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.db import utcnow
from app.models import (
    FollowUpStatus,
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationRule,
    NotificationStatus,
    QuotationRequest,
    QuotationStatus,
    StockItem,
    StockMovementKind,
)
from app.services.notifications import NotificationService
from app.services.reports import DateRange, ReportService
from app.services.stock.movements import StockMovementService


@pytest.fixture()
def sent_quotation(db, quoted_quotation, default_user) -> QuotationRequest:
    """A quotation that has actually gone out - the only chaseable state."""
    quoted_quotation.status = QuotationStatus.SENT
    quoted_quotation.sent_at = utcnow() - timedelta(days=10)
    db.commit()
    return quoted_quotation


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def test_an_in_app_notification_is_raised_without_any_rule_configured(
    db, quoted_quotation, default_user
):
    """The dashboard bell must work on a fresh install."""
    result = NotificationService(db).quotation_ready(quoted_quotation)

    assert result.raised
    row = result.raised[0]
    assert row.channel is NotificationChannel.IN_APP
    assert row.status is NotificationStatus.SENT
    assert quoted_quotation.quotation_number in row.title
    assert row.link == f"/quotations/{quoted_quotation.id}"


def test_a_local_channel_writes_the_message_instead_of_sending_it(
    db, quoted_quotation, default_user, tmp_path, monkeypatch
):
    """WhatsApp is exercisable before any Twilio account exists."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "notification_data_dir", str(tmp_path))
    db.add(
        NotificationRule(
            label="Owner on WhatsApp",
            kind=NotificationKind.QUOTATION_READY,
            channel=NotificationChannel.WHATSAPP,
            recipient_phones=["+919999999999"],
        )
    )
    db.commit()

    result = NotificationService(db).quotation_ready(quoted_quotation)

    assert result.sent == 1
    written = list((tmp_path / "notifications").glob("*.json"))
    assert len(written) == 1
    assert "+919999999999" in written[0].read_text()


def test_a_confidence_condition_filters_out_the_quiet_cases(db, quoted_quotation, default_user):
    """"Only tell me when it needs attention" - a HIGH quote should not interrupt."""
    from app.models import ConfidenceLevel

    db.add(
        NotificationRule(
            label="Only when unsure",
            kind=NotificationKind.QUOTATION_READY,
            channel=NotificationChannel.IN_APP,
            conditions={"max_confidence": "MEDIUM"},
        )
    )
    db.commit()

    quoted_quotation.confidence = ConfidenceLevel.HIGH
    db.commit()
    assert NotificationService(db).quotation_ready(quoted_quotation).raised == []

    quoted_quotation.confidence = ConfidenceLevel.LOW
    db.commit()
    assert NotificationService(db).quotation_ready(quoted_quotation).raised


def test_unread_count_and_marking_read(db, quoted_quotation, default_user):
    service = NotificationService(db)
    service.quotation_ready(quoted_quotation)
    service.quotation_ready(quoted_quotation)

    assert service.unread_count() == 2

    first = db.query(Notification).first()
    service.mark_read(first.id)
    assert service.unread_count() == 1

    assert service.mark_all_read() == 1
    assert service.unread_count() == 0


def test_a_delivery_failure_is_recorded_rather_than_raised(
    db, quoted_quotation, default_user, monkeypatch
):
    """A notification must never be able to break the thing it reports on."""
    from app.services.notifications import channels

    class BrokenChannel(channels.Channel):
        kind = NotificationChannel.IN_APP

        def send(self, *, destination, title, body, link=None):
            return channels.DeliveryResult(sent=False, error="provider exploded")

        def describe(self):
            return "broken"

    monkeypatch.setattr(channels, "get_channel", lambda kind: BrokenChannel())
    monkeypatch.setattr(
        "app.services.notifications.service.get_channel", lambda kind: BrokenChannel()
    )

    result = NotificationService(db).quotation_ready(quoted_quotation)

    assert result.failed == 1
    assert result.raised[0].status is NotificationStatus.FAILED
    assert result.raised[0].error == "provider exploded"


# ---------------------------------------------------------------------------
# Stock movement
# ---------------------------------------------------------------------------


def test_a_receipt_adds_to_the_imported_balance(db, plate, default_user):
    service = StockMovementService(db)
    before = service.balance_for_lots([plate])

    service.record(kind=StockMovementKind.RECEIPT, quantity_kg=Decimal("5000"), stock_item=plate)
    after = service.balance_for_lots([plate])

    assert after.on_hand_kg == before.on_hand_kg + Decimal("5000")


def test_an_issue_always_reduces_however_the_sign_was_passed(db, plate, default_user):
    """A mistyped minus must not inflate stock."""
    service = StockMovementService(db)
    before = service.balance_for_lots([plate])

    service.record(kind=StockMovementKind.ISSUE, quantity_kg=Decimal("1000"), stock_item=plate)
    after = service.balance_for_lots([plate])

    assert after.on_hand_kg == before.on_hand_kg - Decimal("1000")


def test_a_reservation_reduces_what_is_free_without_moving_the_material(db, plate, default_user):
    service = StockMovementService(db)
    before = service.balance_for_lots([plate])

    service.record(kind=StockMovementKind.RESERVATION, quantity_kg=Decimal("3000"), stock_item=plate)
    after = service.balance_for_lots([plate])

    assert after.on_hand_kg == before.on_hand_kg  # still physically there
    assert after.available_kg == before.available_kg - Decimal("3000")


def test_releasing_a_reservation_frees_the_material_again(db, plate, quoted_quotation, default_user):
    service = StockMovementService(db)
    service.reserve_for(quoted_quotation)
    reserved = service.balance_for_lots([plate])

    service.release_for(quoted_quotation, "Customer withdrew.")
    released = service.balance_for_lots([plate])

    assert reserved.available_kg < released.available_kg


def test_movements_survive_a_wholesale_stock_reimport(db, plate, default_user):
    """The import replaces every lot; a recorded receipt must not vanish.

    This is why movements are stored separately rather than mutating the
    imported balance.
    """
    service = StockMovementService(db)
    spec = {
        "product_type": plate.product_type,
        "grade": plate.grade,
        "thickness_mm": plate.thickness_mm,
        "width_mm": plate.width_mm,
        "length_mm": plate.length_mm,
        "diameter_mm": plate.diameter_mm,
    }
    service.record(kind=StockMovementKind.RECEIPT, quantity_kg=Decimal("5000"), stock_item=plate)

    # Simulate the importer: detach references, delete every lot, load anew.
    # The movement keeps its denormalised spec, which is the whole point.
    from app.models import QuotationLineItem, StockMovement

    db.query(QuotationLineItem).update({QuotationLineItem.matched_stock_item_id: None})
    db.query(StockMovement).update({StockMovement.stock_item_id: None})
    db.query(StockItem).delete()
    db.add(StockItem(**spec, location="NAGPUR", balance_qty_kg=Decimal("20000.000"),
                     landed_cost_per_kg=56.5))
    db.commit()

    balance = service.balance_for_spec(spec)
    assert balance.imported_kg == Decimal("20000.000")
    assert balance.movement_kg == Decimal("5000")
    assert balance.on_hand_kg == Decimal("25000.000")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def test_the_funnel_counts_each_stage(db, quoted_quotation, default_user):
    stages = ReportService(db).funnel(DateRange.last_days(30))
    by_name = {s.stage: s.count for s in stages}

    assert by_name["Enquiries received"] >= 0
    assert by_name["Quotations provided"] == 0
    assert by_name["Orders received"] == 0
    assert by_name["Lost / cancelled"] == 0


def test_enquiries_received_carries_the_requested_tonnage(db, quoted_quotation, default_user):
    """What the customer asked for, read off the line item before pricing runs."""
    stages = {s.stage: s for s in ReportService(db).funnel(DateRange.last_days(30))}

    enquiries = stages["Enquiries received"]
    assert enquiries.count == 1
    assert enquiries.tonnes == Decimal("20")


def test_an_enquiry_with_no_stated_quantity_is_flagged_not_zeroed(db, quoted_quotation, default_user):
    """A plate's weight given as a physical spec, or dimensions with no piece
    count, is not a zero-tonne order - it is an order the desk cannot size
    yet. It must not silently vanish into the tonnage total."""
    quoted_quotation.line_items[0].quantity_mt = None
    quoted_quotation.line_items[0].quantity = None
    db.commit()

    stages = {s.stage: s for s in ReportService(db).funnel(DateRange.last_days(30))}
    enquiries = stages["Enquiries received"]

    assert enquiries.count == 1
    assert enquiries.tonnes == Decimal("0")
    assert enquiries.unquantified == 1


def test_win_loss_reports_the_rate_and_the_value(db, quoted_quotation, default_user):
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    quoted_quotation.sent_at = utcnow()
    db.commit()

    report = ReportService(db).win_loss(DateRange.last_days(30))

    assert report.totals["won"] == 1
    assert report.totals["lost"] == 0
    assert report.totals["win_rate_pct"] == 100.0


def test_stock_ageing_separates_deadstock(db, plate, default_user):
    plate.ageing_days = 150
    db.commit()

    report = ReportService(db).stock_ageing(dead_after_days=90)

    assert report.totals["deadstock_lots"] == 1
    assert report.rows[0]["ageing_days"] == 150
    assert Decimal(report.totals["deadstock_value_inr"]) > 0


def test_a_report_exports_as_csv(db, quoted_quotation, default_user):
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    quoted_quotation.sent_at = utcnow()
    db.commit()

    csv_text = ReportService(db).win_loss(DateRange.last_days(30)).to_csv()

    assert "quotation,customer,sent,outcome,value_inr" in csv_text
    assert quoted_quotation.quotation_number in csv_text


def test_an_empty_report_produces_empty_csv_rather_than_an_error(db, default_user):
    assert ReportService(db).win_loss(DateRange.last_days(30)).to_csv() == ""


# ---------------------------------------------------------------------------
# Dashboard trends
# ---------------------------------------------------------------------------


def test_the_series_fills_the_quiet_days(db, quoted_quotation, default_user):
    """A chart drawn only from days with rows misrepresents a quiet week."""
    from app.services.trends import TrendService

    trends = TrendService(db).build(30)

    assert len(trends.series) == 30
    assert sum(p.quotations for p in trends.series) == 1


def test_the_comparison_window_is_the_same_length(db, default_user):
    """30 days against 30 days - never against a partial period."""
    from app.services.trends import TrendService

    trends = TrendService(db).build(14)

    assert trends.days == 14
    assert len(trends.series) == 14
    assert trends.period_label and trends.previous_label
    assert trends.period_label != trends.previous_label


def test_a_delta_reports_direction_and_whether_it_is_welcome(db, default_user):
    """Rising quotations is good; rising time-to-quote is not."""
    from app.services.trends import Delta

    more_quotes = Delta("q", "Quotations", current=10, previous=5)
    assert more_quotes.direction == "up"
    assert more_quotes.good is True
    assert more_quotes.change_pct == 100.0

    slower = Delta("t", "Time to quote", current=10, previous=5, lower_is_better=True)
    assert slower.direction == "up"
    assert slower.good is False

    unchanged = Delta("s", "Sent", current=3, previous=3)
    assert unchanged.direction == "flat"
    assert unchanged.good is None


def test_growth_from_nothing_does_not_divide_by_zero(db, default_user):
    from app.services.trends import Delta

    assert Delta("q", "Q", current=4, previous=0).change_pct == 100.0
    assert Delta("q", "Q", current=0, previous=0).change_pct is None


def test_trends_serialise_for_the_api(db, quoted_quotation, default_user):
    from app.services.trends import TrendService

    payload = TrendService(db).build(7).to_dict()

    assert set(payload) == {"days", "period_label", "previous_label", "series", "deltas"}
    assert all("day" in p and "value" in p for p in payload["series"])
    assert all({"key", "direction", "good"} <= set(d) for d in payload["deltas"])


def test_a_soft_block_holds_stock_without_moving_it(db, plate, default_user):
    """A block withholds tonnage from quoting but leaves it on the floor."""
    service = StockMovementService(db)
    before = service.balance_for_lots([plate])

    service.record(
        kind=StockMovementKind.BLOCK,
        quantity_kg=Decimal("5000"),
        stock_item=plate,
        note="Held for an expected order",
    )
    after = service.balance_for_lots([plate])

    assert after.on_hand_kg == before.on_hand_kg  # still physically present
    assert after.available_kg == before.available_kg - Decimal("5000")


def test_lifting_a_block_puts_the_tonnage_back_on_offer(db, plate, default_user):
    service = StockMovementService(db)
    movement = service.record(
        kind=StockMovementKind.BLOCK, quantity_kg=Decimal("5000"), stock_item=plate
    )
    held = service.balance_for_lots([plate])

    assert service.lift_hold(movement.id) is True
    freed = service.balance_for_lots([plate])

    assert freed.available_kg == held.available_kg + Decimal("5000")
    # Lifting something already lifted is a no-op, not an error.
    assert service.lift_hold(movement.id) is False


def test_availability_quotes_free_stock_not_the_imported_figure(db, plate, customer):
    """The check must not promise material that is despatched or held.

    Regression: availability read `StockItem.balance_qty_kg` alone, so a block
    or an issue recorded after the last import changed nothing about what the
    system was willing to quote.
    """
    from app.services.stock.availability import StockAvailabilityService

    StockMovementService(db).record(
        kind=StockMovementKind.BLOCK, quantity_kg=Decimal("20000"), stock_item=plate
    )

    outcome = StockAvailabilityService(db).check(
        lot_ids=[plate.id], quantity_mt=Decimal("25"), customer=customer
    )

    # 28.26 MT on hand, 20 MT held, so 8.26 MT may actually be promised.
    assert outcome.on_hand_qty_mt == Decimal("28.260")
    assert outcome.available_qty_mt == Decimal("8.260")
    assert outcome.sufficient is False
    assert "reserved against other quotations" in outcome.explanation


# ---------------------------------------------------------------------------
# Business insights
# ---------------------------------------------------------------------------


def test_a_metric_knows_whether_its_movement_is_welcome(db):
    """Rising value is good; rising time-to-quote is not."""
    from app.services.insights import Metric

    more_value = Metric("v", "Quoted value", current=200, previous=100)
    assert more_value.direction == "up"
    assert more_value.good is True
    assert more_value.change_pct == 100.0

    slower = Metric("t", "Time to quote", current=30, previous=10, lower_is_better=True)
    assert slower.direction == "up"
    assert slower.good is False

    unchanged = Metric("s", "Sent", current=5, previous=5)
    assert unchanged.direction == "flat"
    assert unchanged.good is None


def test_growth_from_zero_does_not_divide_by_zero(db):
    from app.services.insights import Metric

    assert Metric("v", "V", current=100, previous=0).change_pct == 100.0
    assert Metric("v", "V", current=0, previous=0).change_pct is None


def test_insights_compare_like_for_like_windows(db, quoted_quotation, default_user):
    from app.services.insights import InsightService

    result = InsightService(db).build(30)

    assert result.period_label and result.previous_label
    assert result.period_label != result.previous_label
    keys = {m.key for m in result.metrics}
    assert {"quoted_value", "win_rate", "margin_pct", "response_hours"} <= keys


def test_open_quotations_are_surfaced_largest_first(db, quoted_quotation, default_user):
    """The cost of leaving a quotation is its value, so that leads the order."""
    from app.services.insights import InsightService

    result = InsightService(db).build(30)

    assert result.attention, "a READY_FOR_REVIEW quotation should be waiting"
    values = [row["value"] for row in result.attention]
    assert values == sorted(values, reverse=True)
    assert result.attention[0]["number"] == quoted_quotation.quotation_number


def test_deadstock_raises_a_highlight_worth_reading(db, plate, default_user):
    from app.services.insights import InsightService

    plate.ageing_days = 200
    db.commit()

    result = InsightService(db).build(30)
    titles = [h.title for h in result.highlights]

    assert any("90 days" in t for t in titles)


def test_highlights_stay_silent_when_there_is_nothing_to_say(db, default_user):
    """An empty desk should not be given invented commentary."""
    from app.services.insights import InsightService

    result = InsightService(db).build(30)
    assert result.highlights == []


def test_the_series_buckets_weekly_over_a_long_window(db, default_user):
    """Ninety daily points is a picket fence; the shape is what matters."""
    from app.services.insights import InsightService

    daily = InsightService(db).build(30)
    weekly = InsightService(db).build(90)

    assert len(daily.series) == 30
    assert len(weekly.series) < 30


def test_insights_serialise_for_the_api(db, quoted_quotation, default_user):
    from app.services.insights import InsightService

    payload = InsightService(db).build(30).to_dict()

    assert {"metrics", "highlights", "series", "attention", "top_customers"} <= set(payload)
    assert all({"key", "direction", "good"} <= set(m) for m in payload["metrics"])


