"""What a customer has bought and been quoted before.

The tab exists to answer one question before a rate goes out: is this what
this buyer normally pays? Two properties carry that and are pinned here:

* **`same_material` is strict.** It is what marks a row as a usable anchor, so
  a partial spec match must not qualify - a trader would not accept 16 mm as
  evidence for a 12 mm rate, and neither should the average.
* **The average is over matching material only.** A mean across mixed
  specifications is a number with no meaning, and putting it beside today's
  rate would actively mislead.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models import (
    Customer,
    Email,
    EmailCategory,
    EmailSourceType,
    ProcessingStatus,
    QuantityUnit,
    QuotationLineItem,
    QuotationPricing,
    QuotationRequest,
    QuotationStatus,
    SalesInvoice,
)
from app.services.quotations.past_orders import PastOrdersService


def invoice(db, customer, *, rate, qty="10", days_ago=30,
            product="Plate", grade="E250", thickness=10.0, no="INV-1"):
    row = SalesInvoice(
        invoice_no=no,
        invoice_date=date.today() - timedelta(days=days_ago),
        customer_id=customer.id,
        product_type=product,
        grade=grade,
        thickness_mm=thickness,
        quantity_mt=Decimal(qty),
        rate_per_mt=Decimal(rate),
        delivery_location="Patna",
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def priced(db, quoted_quotation) -> QuotationRequest:
    """The fixture quotation with a settled rate to compare history against."""
    db.add(
        QuotationPricing(
            quotation_line_item_id=quoted_quotation.line_items[0].id,
            quote_rate=Decimal("61000.00"),
            line_total=Decimal("1220000.00"),
            quantity_mt=Decimal("20"),
        )
    )
    db.commit()
    return quoted_quotation


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


def test_lists_what_this_customer_has_bought(db, priced, customer):
    invoice(db, customer, rate="58000", no="INV-100")
    invoice(db, customer, rate="59000", no="INV-101", days_ago=10)

    result = PastOrdersService(db).for_quotation(priced)

    assert result.orders_count == 2
    # Newest first: a trader reads the most recent rate before an older one.
    assert result.invoices[0].invoice_no == "INV-101"
    assert result.last_order_at == date.today() - timedelta(days=10)


def test_another_customer_is_never_borrowed(db, priced, customer):
    """A wrong anchor is worse than no anchor."""
    other = Customer(name="Someone Else", email="other@example.com")
    db.add(other)
    db.flush()
    invoice(db, other, rate="41000", no="INV-OTHER")
    db.commit()

    result = PastOrdersService(db).for_quotation(priced)

    assert result.orders_count == 0
    assert result.avg_rate_same_material is None


def test_line_total_is_derived_from_rate_and_tonnage(db, priced, customer):
    invoice(db, customer, rate="58000", qty="10")

    row = PastOrdersService(db).for_quotation(priced).invoices[0]

    assert row.line_total == Decimal("580000")


# ---------------------------------------------------------------------------
# same_material - the part that decides whether a row is evidence
# ---------------------------------------------------------------------------


def test_matching_specification_is_marked(db, priced, customer):
    # `quoted_quotation` is Plate / E250 / 10 mm.
    invoice(db, customer, rate="58000", product="Plate", grade="E250", thickness=10.0)

    assert PastOrdersService(db).for_quotation(priced).invoices[0].same_material


@pytest.mark.parametrize(
    ("product", "grade", "thickness"),
    [
        ("Plate", "E250", 16.0),  # different thickness
        ("Plate", "E350", 10.0),  # different grade
        ("Coil", "E250", 10.0),  # different product
    ],
)
def test_a_different_specification_is_not_evidence(
    db, priced, customer, product, grade, thickness
):
    """A trader would not accept 16 mm as evidence for a 12 mm rate."""
    invoice(db, customer, rate="58000", product=product, grade=grade, thickness=thickness)

    result = PastOrdersService(db).for_quotation(priced)

    assert result.invoices[0].same_material is False
    assert result.avg_rate_same_material is None


def test_matching_ignores_case_and_padding(db, priced, customer):
    invoice(db, customer, rate="58000", product=" plate ", grade="e250", thickness=10.0)

    assert PastOrdersService(db).for_quotation(priced).invoices[0].same_material


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------


def test_average_covers_matching_material_only(db, priced, customer):
    """A mean across mixed specifications is a number with no meaning."""
    invoice(db, customer, rate="58000", no="A", thickness=10.0)
    invoice(db, customer, rate="60000", no="B", thickness=10.0)
    invoice(db, customer, rate="90000", no="C", thickness=25.0)  # different spec

    result = PastOrdersService(db).for_quotation(priced)

    assert result.avg_rate_same_material == Decimal("59000.00")
    assert result.current_rate == Decimal("61000.00")
    assert result.rate_delta == Decimal("2000.00")


def test_no_history_means_no_comparison(db, priced):
    """Silent rather than inventing a baseline out of nothing."""
    result = PastOrdersService(db).for_quotation(priced)

    assert result.avg_rate_same_material is None
    assert result.rate_delta is None
    assert result.current_rate == Decimal("61000.00")


# ---------------------------------------------------------------------------
# Earlier quotations
# ---------------------------------------------------------------------------


def test_earlier_quotations_carry_their_outcome(db, priced, customer):
    """Whether this buyer converts is as useful as what they paid."""
    for n, status in enumerate(
        [QuotationStatus.CUSTOMER_ACCEPTED, QuotationStatus.CUSTOMER_DECLINED], start=1
    ):
        email = Email(
            message_id=f"local:past-{n}",
            thread_id=f"local-thread:past-{n}",
            source=EmailSourceType.LOCAL,
            sender_email=customer.email,
            subject="Earlier enquiry",
            body_text="Please quote.",
            received_at=datetime.now(UTC) - timedelta(days=60),
            processing_status=ProcessingStatus.PROCESSED,
            category=EmailCategory.QUOTATION_REQUEST,
        )
        db.add(email)
        db.flush()
        past = QuotationRequest(
            quotation_number=f"Q-PAST-{n}",
            email_id=email.id,
            customer_id=customer.id,
            customer_email=customer.email,
            status=status,
        )
        db.add(past)
        db.flush()
        db.add(
            QuotationLineItem(
                quotation_request_id=past.id,
                line_no=1,
                product_type="Plate",
                grade="E250",
                thickness_mm=10.0,
                quantity_mt=Decimal("5"),
                quantity_unit=QuantityUnit.MT,
            )
        )
    db.commit()

    result = PastOrdersService(db).for_quotation(priced)

    assert result.quotes_count == 2
    assert result.quotes_won == 1
    assert all(q.same_material for q in result.quotations)


def test_the_open_quotation_is_not_its_own_history(db, priced, customer):
    result = PastOrdersService(db).for_quotation(priced)

    assert all(q.id != priced.id for q in result.quotations)
