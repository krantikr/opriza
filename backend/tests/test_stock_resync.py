"""Keeping the open book in step with the floor.

A quotation is priced from stock as it stood when it was raised. When the floor
moves - a cost is corrected, or the sheet is re-imported - every quotation still
on the desk is quoting a number the business no longer pays. These pin that the
open book follows, and that a sent quotation never does.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete, update

from app.models import (
    PricingComponentKind,
    PricingRule,
    PricingRuleSet,
    QuotationLineItem,
    QuotationStatus,
    StockItem,
)
from app.services.pricing.service import PricingService
from app.services.stock.resync import StockResyncService


@pytest.fixture()
def rules(db) -> PricingRuleSet:
    rs = PricingRuleSet(version=1, label="Test", is_active=True)
    rs.rules = [
        PricingRule(code="base_price", label="Base",
                    kind=PricingComponentKind.BASE_PRICE, priority=10, config={}),
        PricingRule(code="target_margin", label="Margin",
                    kind=PricingComponentKind.TARGET_MARGIN, priority=100,
                    config={"pct": 10.0}),
    ]
    db.add(rs)
    db.commit()
    return rs


def _price_once(db, quotation, rules) -> Decimal:
    item = quotation.line_items[0]
    PricingService(db, rules).price_line(item, quotation=quotation)
    db.commit()
    db.refresh(item)
    return item.pricing.quote_rate


# ---------------------------------------------------------------------------
# A cost correction on a lot
# ---------------------------------------------------------------------------


def test_a_corrected_landed_cost_reaches_the_open_quotation(db, quoted_quotation, rules):
    item = quoted_quotation.line_items[0]
    item.matched_stock_item.landed_cost_per_kg = 50.0
    db.commit()
    first = _price_once(db, quoted_quotation, rules)

    item.matched_stock_item.landed_cost_per_kg = 60.0
    db.commit()

    result = StockResyncService(db).resync_open_quotations(rematch=False)
    db.refresh(item)

    assert result.quotations_repriced == 1
    assert item.pricing.quote_rate != first
    assert item.pricing.quote_rate == Decimal("66000.00")


def test_the_draft_is_flagged_so_the_reviewer_rewrites_it(db, quoted_quotation, rules):
    """A price that moved under a written draft must not go out unannounced."""
    item = quoted_quotation.line_items[0]
    item.matched_stock_item.landed_cost_per_kg = 50.0
    db.commit()
    _price_once(db, quoted_quotation, rules)

    item.matched_stock_item.landed_cost_per_kg = 75.0
    db.commit()
    StockResyncService(db).resync_open_quotations(rematch=False)
    db.refresh(item)

    assert item.pricing.draft_stale is True


def test_an_unchanged_cost_leaves_the_quotation_alone(db, quoted_quotation, rules):
    """A resync that touches nothing must not flag every draft on the desk."""
    item = quoted_quotation.line_items[0]
    item.matched_stock_item.landed_cost_per_kg = 50.0
    db.commit()
    _price_once(db, quoted_quotation, rules)

    result = StockResyncService(db).resync_open_quotations(rematch=False)
    db.refresh(item)

    assert result.quotations_repriced == 0
    assert item.pricing.draft_stale is False


# ---------------------------------------------------------------------------
# A wholesale re-import
# ---------------------------------------------------------------------------


def test_a_reimport_leaves_lines_unmatched_until_the_resync_repairs_them(
    db, quoted_quotation, rules
):
    """The importer detaches every line to satisfy the foreign key.

    Regression: nothing re-matched them afterwards, so a routine monthly import
    left open quotations pointing at nothing and pricing to "no base price".
    """
    item = quoted_quotation.line_items[0]
    original = item.matched_stock_item
    original.landed_cost_per_kg = 50.0
    db.commit()
    _price_once(db, quoted_quotation, rules)

    # What the importer does: detach, wipe, then load the new sheet.
    replacement = StockItem(
        product_type=original.product_type,
        grade=original.grade,
        thickness_mm=original.thickness_mm,
        width_mm=original.width_mm,
        length_mm=original.length_mm,
        location=original.location,
        balance_qty_kg=original.balance_qty_kg,
        landed_cost_per_kg=64.0,
    )
    db.execute(
        update(QuotationLineItem)
        .where(QuotationLineItem.matched_stock_item_id.is_not(None))
        .values(matched_stock_item_id=None)
    )
    db.execute(delete(StockItem))
    db.add(replacement)
    db.commit()
    db.refresh(item)
    assert item.matched_stock_item_id is None, "the import detached the line"

    result = StockResyncService(db).resync_open_quotations()
    db.refresh(item)

    assert result.lines_rematched >= 1
    assert item.matched_stock_item_id == replacement.id
    assert item.pricing.quote_rate == Decimal("70400.00")


# ---------------------------------------------------------------------------
# The commitment
# ---------------------------------------------------------------------------


def test_a_sent_quotation_is_never_repriced(db, quoted_quotation, rules):
    """The figures on a sent quotation are the record of what was offered."""
    item = quoted_quotation.line_items[0]
    item.matched_stock_item.landed_cost_per_kg = 50.0
    db.commit()
    sent_rate = _price_once(db, quoted_quotation, rules)

    quoted_quotation.status = QuotationStatus.SENT
    item.matched_stock_item.landed_cost_per_kg = 90.0
    db.commit()

    result = StockResyncService(db).resync_open_quotations(rematch=False)
    db.refresh(item)

    assert result.quotations_examined == 0
    assert item.pricing.quote_rate == sent_rate


@pytest.mark.parametrize(
    "status",
    [
        QuotationStatus.SENT,
        QuotationStatus.APPROVED,
        QuotationStatus.CUSTOMER_ACCEPTED,
        QuotationStatus.CUSTOMER_DECLINED,
    ],
)
def test_every_committed_status_is_left_alone(db, quoted_quotation, rules, status):
    """A declined quotation's price was still sent, so it is frozen too."""
    item = quoted_quotation.line_items[0]
    item.matched_stock_item.landed_cost_per_kg = 50.0
    db.commit()
    original = _price_once(db, quoted_quotation, rules)

    quoted_quotation.status = status
    item.matched_stock_item.landed_cost_per_kg = 90.0
    db.commit()

    StockResyncService(db).resync_open_quotations(rematch=False)
    db.refresh(item)

    assert item.pricing.quote_rate == original


# ---------------------------------------------------------------------------
# Through the import route
# ---------------------------------------------------------------------------


def test_the_import_route_reports_what_it_repriced(client, db, quoted_quotation):
    """A silently repriced book is worse than none: a draft may now understate.

    The route is exercised rather than the service so the wiring is covered -
    a resync that runs but never reaches the response tells the trader nothing.
    """
    import io

    from openpyxl import Workbook

    lot = quoted_quotation.line_items[0].matched_stock_item
    wb = Workbook()
    ws = wb.active
    ws.append(["Product type", "Grade", "Thickness", "Width", "Length",
               "Location", "Balance qty", "Landed cost"])
    ws.append([lot.product_type, lot.grade, lot.thickness_mm, lot.width_mm,
               lot.length_mm, lot.location, 20000, 64.0])
    buffer = io.BytesIO()
    wb.save(buffer)

    response = client.post(
        "/api/v1/stock/import",
        files={"file": ("stock.xlsx", buffer.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # The counts must be present whatever the figures, or the caller cannot
    # tell a quiet import from one that moved the whole book.
    assert "quotations_repriced" in body
    assert "drafts_to_rewrite" in body
