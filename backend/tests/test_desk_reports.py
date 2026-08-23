"""The trading view of a period: money earned, money lost, and why.

These tests pin the figures a trader would query first - gross profit in
rupees, the reason column behind the losses, and the fact that a period is
calendar-aligned so it can be reconciled against the books.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.db import utcnow
from app.models import LostReason, QuotationPricing, QuotationStatus
from app.services import periods
from app.services.desk import DeskService
from app.services.workbook import WorkbookBuilder


def _price(db, quotation, *, cost: str, quote: str, qty: str = "20") -> None:
    """Give the fixture's single line a stored cost and quote rate."""
    item = quotation.line_items[0]
    db.add(
        QuotationPricing(
            quotation_line_item_id=item.id,
            quantity_mt=Decimal(qty),
            total_cost=Decimal(cost),
            quote_rate=Decimal(quote),
            line_total=Decimal(quote) * Decimal(qty),
            rules_version=1,
        )
    )
    db.commit()
    db.refresh(quotation)


# ---------------------------------------------------------------------------
# Named periods
# ---------------------------------------------------------------------------


def test_a_month_runs_from_the_first_to_today_not_thirty_days_back():
    """A trader closing August wants August, not "since 24 July"."""
    period = periods.resolve("this-month", date(2026, 8, 23))

    assert period.current.start == date(2026, 8, 1)
    assert period.current.end == date(2026, 8, 23)


def test_last_month_is_compared_with_the_month_before_it():
    period = periods.resolve("last-month", date(2026, 8, 23))

    assert period.current.start == date(2026, 7, 1)
    assert period.current.end == date(2026, 7, 31)
    assert period.previous.start == date(2026, 6, 1)
    assert period.previous.end == date(2026, 6, 30)


def test_the_financial_year_starts_in_april():
    """Indian FY. A year ending in December would not reconcile with anything."""
    period = periods.resolve("this-fy", date(2026, 8, 23))

    assert period.current.start == date(2026, 4, 1)
    assert period.label == "FY 26-27"


def test_a_date_in_march_belongs_to_the_financial_year_that_began_last_april():
    period = periods.resolve("this-fy", date(2026, 3, 15))

    assert period.current.start == date(2025, 4, 1)
    assert period.label == "FY 25-26"


def test_quarters_follow_the_financial_year_not_the_calendar():
    """Q1 is April to June, so a July date sits at the start of Q2."""
    period = periods.resolve("this-quarter", date(2026, 7, 5))

    assert period.current.start == date(2026, 7, 1)
    assert period.previous.start == date(2026, 4, 1)


def test_a_long_window_is_bucketed_wider_than_a_short_one():
    """Three hundred daily columns is a smear; the grain widens with the span."""
    assert periods.resolve("this-week", date(2026, 8, 23)).grain == "day"
    assert periods.resolve("last-fy", date(2026, 8, 23)).grain == "month"


def test_a_custom_range_is_compared_with_the_same_number_of_days_before_it():
    period = periods.custom(date(2026, 8, 1), date(2026, 8, 10))

    assert (period.previous.end - period.previous.start).days == 9
    assert period.previous.end == date(2026, 7, 31)


# ---------------------------------------------------------------------------
# Gross profit
# ---------------------------------------------------------------------------


def test_won_business_reports_profit_in_rupees_not_only_a_percentage(
    db, quoted_quotation, default_user
):
    """Twelve percent on four lakh is a worse month than six on four crore."""
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    quoted_quotation.sent_at = utcnow()
    _price(db, quoted_quotation, cost="50000", quote="55000")

    report = DeskService(db).build(periods.resolve("this-month"))

    assert report.won["revenue"] == pytest.approx(1_100_000)
    assert report.won["cost"] == pytest.approx(1_000_000)
    assert report.won["profit"] == pytest.approx(100_000)
    assert report.won["margin_pct"] == pytest.approx(10.0)
    assert report.won["tonnes"] == pytest.approx(20)


def test_profit_per_tonne_is_reported_because_that_is_the_traders_spread(
    db, quoted_quotation, default_user
):
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    _price(db, quoted_quotation, cost="50000", quote="55000")

    report = DeskService(db).build(periods.resolve("this-month"))

    assert report.won["profit_per_mt"] == pytest.approx(5000)


def test_a_line_with_no_recorded_cost_is_not_counted_as_pure_profit(
    db, quoted_quotation, default_user
):
    """An unpriced line is unknown, not free."""
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    db.commit()

    report = DeskService(db).build(periods.resolve("this-month"))

    assert report.won["revenue"] == 0
    assert report.won["profit"] == 0


def test_quotes_still_awaiting_a_reply_are_reported_as_money_at_stake(
    db, quoted_quotation, default_user
):
    """The open book is the pipeline, and it is not revenue until it lands."""
    quoted_quotation.status = QuotationStatus.SENT
    _price(db, quoted_quotation, cost="50000", quote="55000")

    report = DeskService(db).build(periods.resolve("this-month"))

    assert report.open_book["revenue"] == pytest.approx(1_100_000)
    assert report.won["revenue"] == 0


# ---------------------------------------------------------------------------
# Why we lost
# ---------------------------------------------------------------------------


def test_losses_are_grouped_by_the_reason_a_human_recorded(
    db, quoted_quotation, default_user
):
    """Losing on price and losing on stock are opposite fixes."""
    quoted_quotation.status = QuotationStatus.CUSTOMER_DECLINED
    quoted_quotation.lost_reason = LostReason.PRICE
    _price(db, quoted_quotation, cost="50000", quote="55000")

    report = DeskService(db).build(periods.resolve("this-month"))

    assert len(report.lost_reasons) == 1
    row = report.lost_reasons[0]
    assert row["reason"] == "PRICE"
    assert row["count"] == 1
    assert row["value"] == pytest.approx(1_100_000)
    assert row["action"]


def test_a_loss_with_no_reason_recorded_still_appears_rather_than_vanishing(
    db, quoted_quotation, default_user
):
    quoted_quotation.status = QuotationStatus.CUSTOMER_DECLINED
    _price(db, quoted_quotation, cost="50000", quote="55000")

    report = DeskService(db).build(periods.resolve("this-month"))

    assert [r["reason"] for r in report.lost_reasons] == ["OTHER"]


def test_the_profit_we_missed_is_counted_alongside_the_value(
    db, quoted_quotation, default_user
):
    quoted_quotation.status = QuotationStatus.CUSTOMER_DECLINED
    quoted_quotation.lost_reason = LostReason.NO_STOCK
    _price(db, quoted_quotation, cost="50000", quote="55000")

    report = DeskService(db).build(periods.resolve("this-month"))

    assert report.lost_reasons[0]["profit_missed"] == pytest.approx(100_000)


# ---------------------------------------------------------------------------
# Concentration, stock and delivery
# ---------------------------------------------------------------------------


def test_customer_concentration_is_reported_because_it_is_the_real_risk(
    db, quoted_quotation, default_user
):
    """One name carrying the whole book is a different business."""
    _price(db, quoted_quotation, cost="50000", quote="55000")

    report = DeskService(db).build(periods.resolve("this-month"))

    assert report.concentration["top_1_pct"] == pytest.approx(100.0)
    assert report.concentration["customers"] == 1


def test_deadstock_is_separated_from_stock_that_is_still_moving(
    db, plate, default_user
):
    plate.ageing_days = 150
    db.commit()

    report = DeskService(db).build(periods.resolve("this-month"))

    assert report.stock["deadstock_lots"] == 1
    assert report.stock["deadstock_value"] > 0
    assert report.stock["deadstock_pct"] == pytest.approx(100.0)


def test_a_despatch_after_the_promised_date_counts_as_late(
    db, quoted_quotation, default_user
):
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    quoted_quotation.promised_date = date.today() - timedelta(days=5)
    quoted_quotation.despatched_at = datetime.combine(
        date.today() - timedelta(days=2), datetime.min.time()
    )
    db.commit()

    report = DeskService(db).build(periods.resolve("this-month"))

    assert report.delivery["late"] == 1
    assert report.delivery["on_time"] == 0
    assert report.delivery["avg_days_late"] == pytest.approx(3.0)


def test_a_promise_with_no_despatch_recorded_is_not_scored_as_a_failure(
    db, quoted_quotation, default_user
):
    """Missing data is missing data, not a late delivery."""
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    quoted_quotation.promised_date = date.today() - timedelta(days=5)
    db.commit()

    report = DeskService(db).build(periods.resolve("this-month"))

    assert report.delivery["on_time_pct"] is None
    assert report.delivery["overdue_now"] == 1


# ---------------------------------------------------------------------------
# The download
# ---------------------------------------------------------------------------


def test_the_pack_is_a_real_workbook_with_a_sheet_behind_every_headline(
    db, quoted_quotation, default_user
):
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    _price(db, quoted_quotation, cost="50000", quote="55000")
    report = DeskService(db).build(periods.resolve("this-month"))

    builder = WorkbookBuilder("Trading report")
    builder.write_summary(report)
    builder.add_rows("Won & lost by customer", report.customers)
    data = builder.to_bytes()

    assert data[:2] == b"PK"  # xlsx is a zip
    assert "Summary" in builder.wb.sheetnames
    assert "Won & lost by customer" in builder.wb.sheetnames


def test_money_is_written_as_a_number_so_the_column_can_be_summed(db, default_user):
    builder = WorkbookBuilder("Trading report")
    builder.add_rows("Customers", [{"customer": "Acme", "revenue": 1_100_000.0}])
    sheet = builder.wb["Customers"]

    assert sheet["B2"].value == 1_100_000.0
    assert isinstance(sheet["B2"].value, float)


def test_an_empty_sheet_says_so_rather_than_breaking_the_pack(db, default_user):
    builder = WorkbookBuilder("Trading report")
    builder.add_rows("Why we lost", [])

    assert builder.wb["Why we lost"]["A1"].value == "Nothing in this period."
    assert builder.to_bytes()[:2] == b"PK"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_the_desk_endpoint_serves_the_period_it_was_asked_for(client):
    response = client.get("/api/v1/reports/desk?period=last-month")

    assert response.status_code == 200
    assert response.json()["period_key"] == "last-month"


def test_the_pack_downloads_as_a_spreadsheet(client):
    response = client.get("/api/v1/reports/pack?period=this-month")

    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    assert response.content[:2] == b"PK"


def test_the_picker_offers_calendar_periods_with_their_dates(client):
    response = client.get("/api/v1/reports/periods")

    choices = response.json()["choices"]
    assert {c["key"] for c in choices} >= {"this-month", "last-month", "this-fy"}
    assert all(c["range"] for c in choices)


# ---------------------------------------------------------------------------
# Statement 1: enquiry and quotation
# ---------------------------------------------------------------------------


def test_the_enquiry_statement_subtracts_rather_than_merely_listing(
    db, quoted_quotation, default_user
):
    """Each line is a subset of the one above, and the gap is the point."""
    report = DeskService(db).build(periods.resolve("this-month"))
    e = report.enquiries

    assert e["received"] >= e["identified"]
    assert e["not_enquiries"] == e["received"] - e["identified"]
    assert e["raised"] == 1
    assert e["not_raised"] == max(e["identified"] - e["raised"], 0)


def test_the_enquiry_statement_reports_the_rate_that_matters(
    db, quoted_quotation, default_user
):
    quoted_quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
    db.commit()

    e = DeskService(db).build(periods.resolve("this-month")).enquiries

    assert e["won"] == 1
    assert e["lost"] == 0
    assert e["win_rate"] == 100.0


# ---------------------------------------------------------------------------
# Statement 4: stock reconciliation
# ---------------------------------------------------------------------------


def test_the_stock_statement_balances(db, plate, default_user):
    """Opening + receipts - issues must equal closing, or it is not a statement."""
    m = DeskService(db).build(periods.resolve("this-month")).stock_movement

    assert m["opening_mt"] + m["receipts_mt"] - m["issues_mt"] == pytest.approx(
        m["closing_mt"], abs=1e-6
    )


def test_receipts_and_issues_inside_the_window_move_the_opening_figure(
    db, plate, default_user
):
    """Opening is derived backwards from closing, so a receipt lowers it."""
    from app.models import StockMovement, StockMovementKind

    db.add(
        StockMovement(
            stock_item_id=plate.id,
            kind=StockMovementKind.RECEIPT,
            quantity_kg=Decimal("5000"),
            rate_per_kg=Decimal("56.5"),
            movement_date=date.today(),
        )
    )
    db.commit()

    m = DeskService(db).build(periods.resolve("this-month")).stock_movement

    assert m["receipts_mt"] == pytest.approx(5.0)
    assert m["opening_mt"] == pytest.approx(m["closing_mt"] - 5.0)
    assert m["opening_mt"] + m["receipts_mt"] - m["issues_mt"] == pytest.approx(
        m["closing_mt"], abs=1e-6
    )


def test_a_reservation_is_a_hold_and_never_enters_the_statement(
    db, plate, default_user
):
    """A block withholds material; it does not move ownership."""
    from app.models import StockMovement, StockMovementKind

    db.add(
        StockMovement(
            stock_item_id=plate.id,
            kind=StockMovementKind.RESERVATION,
            quantity_kg=Decimal("-2000"),
            movement_date=date.today(),
        )
    )
    db.commit()

    m = DeskService(db).build(periods.resolve("this-month")).stock_movement

    assert m["issues_mt"] == 0
    assert m["movements"] == 0


# ---------------------------------------------------------------------------
# The HTML report
# ---------------------------------------------------------------------------


def test_the_html_report_is_one_self_contained_file(db, quoted_quotation, default_user):
    """No external stylesheet, font or image: it must survive being emailed."""
    from app.services import html_report

    report = DeskService(db).build(periods.resolve("this-month"))
    html = html_report.build(report, organisation="KK Traders")

    assert html.startswith("<!doctype html>")
    assert "<style>" in html
    assert "http://" not in html and "https://" not in html
    assert "<link" not in html and "<script" not in html


def test_the_html_report_carries_all_four_statements(db, quoted_quotation, default_user):
    from app.services import html_report

    report = DeskService(db).build(periods.resolve("this-month"))
    html = html_report.build(report, organisation="KK Traders")

    for title in (
        "Enquiry and quotation",
        "Sales and realisation",
        "Trading and profit",
        "Stock",
    ):
        assert title in html


def test_the_html_report_names_the_business_and_the_period(
    db, quoted_quotation, default_user
):
    from app.services import html_report

    report = DeskService(db).build(periods.resolve("this-month"))
    html = html_report.build(report, organisation="KK Traders")

    assert "KK Traders" in html
    assert report.period_label in html


def test_a_business_name_cannot_inject_markup(db, default_user):
    """The name is data, not markup - it reaches the file escaped."""
    from app.services import html_report

    report = DeskService(db).build(periods.resolve("this-month"))
    html = html_report.build(report, organisation="<script>alert(1)</script>")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_rupees_groups_in_the_indian_convention():
    """A report read in India is read in lakhs, not thousands."""
    from app.services.html_report import rupees, short

    assert rupees(14200000) == "₹1,42,00,000.00"
    assert rupees(-5000) == "(₹5,000.00)"
    assert short(14200000) == "₹1.42Cr"
    assert short(1280000) == "₹12.80L"


def test_the_document_endpoint_serves_html(client):
    response = client.get("/api/v1/reports/document?period=this-month")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.startswith("<!doctype html>")


def test_the_document_can_be_viewed_rather_than_downloaded(client):
    response = client.get("/api/v1/reports/document?period=this-month&download=false")

    assert "inline" in response.headers["content-disposition"]
