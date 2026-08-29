"""What we have, what we owe, and what we still have to buy.

The figures a trader actually decides from. A balance on its own says nothing:
28 MT against 5 MT of accepted orders is idle capital, and against 40 MT it is
a purchase that needs making this week.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models import (
    QuantityUnit,
    QuotationLineItem,
    QuotationRequest,
    QuotationStatus,
    StockItem,
)
from app.services.stock.position import spec_positions, totals


def _lot(db, **kw) -> StockItem:
    defaults = dict(
        product_type="Plate", grade="E250", thickness_mm=10.0,
        width_mm=1500.0, length_mm=6000.0, location="NAGPUR",
        qty_kg=Decimal("10000"), balance_qty_kg=Decimal("10000"),
        landed_cost_per_kg=56.5, stock_date=date.today(), ageing_days=0,
    )
    lot = StockItem(**{**defaults, **kw})
    db.add(lot)
    db.commit()
    return lot


def _demand(db, status: QuotationStatus, qty: str, *, despatched=None, **spec) -> QuotationRequest:
    """A quotation for `qty` MT in a given state."""
    from datetime import UTC, datetime

    from app.models import Email, EmailCategory, EmailSourceType, ProcessingStatus

    # A quotation hangs off the email that prompted it; the column is not null.
    email = Email(
        message_id=f"local:pos-{status.value}-{qty}",
        thread_id=f"local-thread:pos-{status.value}-{qty}",
        source=EmailSourceType.LOCAL,
        sender_email="buyer@example.com",
        subject="Enquiry",
        body_text="Please quote.",
        received_at=datetime.now(UTC),
        processing_status=ProcessingStatus.PROCESSED,
        category=EmailCategory.QUOTATION_REQUEST,
    )
    db.add(email)
    db.flush()

    q = QuotationRequest(
        quotation_number=f"Q-{status.value[:4]}-{qty}",
        email_id=email.id,
        customer_email="buyer@example.com",
        status=status,
        despatched_at=despatched,
    )
    db.add(q)
    db.flush()

    defaults = dict(
        product_type="Plate", grade="E250", thickness_mm=10.0,
        width_mm=1500.0, length_mm=6000.0,
    )
    db.add(
        QuotationLineItem(
            quotation_request_id=q.id, line_no=1, raw_text="E250 plate",
            quantity=Decimal(qty), quantity_unit=QuantityUnit.MT,
            quantity_mt=Decimal(qty), **{**defaults, **spec},
        )
    )
    db.commit()
    return q


def _only(db):
    rows = spec_positions(db)
    assert len(rows) == 1, [r.key for r in rows]
    return rows[0]


# --- The three figures ------------------------------------------------------


def test_stock_with_no_orders_is_all_free(db):
    _lot(db)  # 10 MT
    p = _only(db)

    assert p.in_stock_mt == Decimal("10.000")
    assert p.committed_mt == Decimal("0.000")
    assert p.free_mt == Decimal("10.000")
    assert p.to_buy_mt == Decimal("0.000")
    assert not p.short


def test_an_accepted_order_reduces_what_is_free(db):
    _lot(db)  # 10 MT
    _demand(db, QuotationStatus.CUSTOMER_ACCEPTED, "4")

    p = _only(db)
    assert p.committed_mt == Decimal("4.000")
    assert p.free_mt == Decimal("6.000")
    assert p.to_buy_mt == Decimal("0.000")


def test_owing_more_than_we_hold_is_what_must_be_bought(db):
    """The number the page exists for."""
    _lot(db)  # 10 MT
    _demand(db, QuotationStatus.CUSTOMER_ACCEPTED, "25")

    p = _only(db)
    assert p.to_buy_mt == Decimal("15.000")
    assert p.free_mt == Decimal("0.000"), "nothing is spare while short"
    assert p.short


def test_free_never_goes_negative(db):
    """A negative 'available' figure is not a quantity anyone can act on."""
    _lot(db)
    _demand(db, QuotationStatus.CUSTOMER_ACCEPTED, "40")
    assert _only(db).free_mt == Decimal("0.000")


# --- What counts as committed ----------------------------------------------


def test_a_quotation_still_with_the_customer_is_prospective_not_committed(db):
    """Treating a quote as an order is how a desk overbuys."""
    _lot(db)
    _demand(db, QuotationStatus.SENT, "30")

    p = _only(db)
    assert p.prospective_mt == Decimal("30.000")
    assert p.committed_mt == Decimal("0.000")
    assert p.to_buy_mt == Decimal("0.000"), "a quote is not a reason to buy"
    assert p.free_mt == Decimal("10.000")


def test_despatched_material_is_no_longer_owed(db):
    from app.core.db import utcnow

    _lot(db)
    _demand(db, QuotationStatus.CUSTOMER_ACCEPTED, "4", despatched=utcnow())

    p = _only(db)
    assert p.committed_mt == Decimal("0.000")
    assert p.free_mt == Decimal("10.000")


def test_a_declined_quotation_counts_for_nothing(db):
    _lot(db)
    _demand(db, QuotationStatus.CUSTOMER_DECLINED, "50")

    p = _only(db)
    assert p.committed_mt == Decimal("0.000")
    assert p.prospective_mt == Decimal("0.000")


# --- Grouping ---------------------------------------------------------------


def test_demand_for_material_we_hold_none_of_still_appears(db):
    """A line the matcher could not place is exactly what must not be missed."""
    _demand(db, QuotationStatus.CUSTOMER_ACCEPTED, "12", grade="S355")

    rows = spec_positions(db)
    assert len(rows) == 1
    assert rows[0].in_stock_mt == Decimal("0.000")
    assert rows[0].to_buy_mt == Decimal("12.000")


def test_the_same_steel_described_differently_is_one_row(db):
    """Stock says "Plate"; the customer wrote "C-45 Plates". One material."""
    _lot(db, product_type="Plate", grade="C-45")
    _demand(db, QuotationStatus.CUSTOMER_ACCEPTED, "3",
            product_type="C-45 Plates", grade="C-45")

    p = _only(db)
    assert p.in_stock_mt == Decimal("10.000")
    assert p.committed_mt == Decimal("3.000")


def test_different_dimensions_stay_separate(db):
    """Merging forms must not merge sizes - they are not interchangeable."""
    _lot(db, thickness_mm=10.0)
    _lot(db, thickness_mm=12.0)

    assert len(spec_positions(db)) == 2


def test_shortfalls_are_listed_first(db):
    """The rows needing a purchase decision must not be below the fold."""
    _lot(db, grade="E250")                      # comfortable
    _demand(db, QuotationStatus.CUSTOMER_ACCEPTED, "30", grade="S355")  # short

    rows = spec_positions(db)
    assert rows[0].grade == "S355"


# --- Totals -----------------------------------------------------------------


def test_a_surplus_of_one_grade_does_not_cover_a_shortfall_of_another(db):
    """Netting them off reports a desk as balanced while it cannot deliver."""
    _lot(db, grade="E250")                                              # 10 MT spare
    _demand(db, QuotationStatus.CUSTOMER_ACCEPTED, "10", grade="S355")  # 10 MT short

    t = totals(spec_positions(db))
    assert t.free_mt == Decimal("10.000")
    assert t.to_buy_mt == Decimal("10.000")
    assert t.specs_short == 1


# --- Cost -------------------------------------------------------------------


def test_cost_is_weighted_by_what_is_actually_on_the_floor(db):
    """Two lots bought at different prices are not equally represented.

    A flat mean of 50 and 60 is 55; but if the floor holds 9 MT of the cheap
    lot and 1 MT of the dear one, the material is worth 51 per kg, not 55.
    """
    _lot(db, balance_qty_kg=Decimal("9000"), landed_cost_per_kg=50.0)
    _lot(db, balance_qty_kg=Decimal("1000"), landed_cost_per_kg=60.0)

    p = _only(db)
    assert p.cost_per_mt == Decimal("51000.00")


def test_purchase_rate_stands_in_when_landed_cost_is_missing(db):
    """The same fallback the pricing engine uses, so the figures agree."""
    _lot(db, landed_cost_per_kg=None, purchase_rate_per_kg=48.0)
    assert _only(db).cost_per_mt == Decimal("48000.00")


def test_a_spec_with_no_cost_on_file_reports_none(db):
    """Blank, not zero - a zero is a price, and this material has none."""
    _lot(db, landed_cost_per_kg=None, purchase_rate_per_kg=None)
    assert _only(db).cost_per_mt is None


def test_an_emptied_lot_does_not_drag_the_average(db):
    """A lot with nothing left is not part of what is on the floor."""
    _lot(db, balance_qty_kg=Decimal("10000"), landed_cost_per_kg=50.0)
    _lot(db, balance_qty_kg=Decimal("0"), landed_cost_per_kg=90.0)

    assert _only(db).cost_per_mt == Decimal("50000.00")
