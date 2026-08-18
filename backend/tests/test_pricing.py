"""The pricing engine.

The arithmetic is asserted against figures worked out by hand from
`business_rules.yaml`, not against whatever the code happens to produce. If a
rule changes, these tests are supposed to fail.

The golden path, for the reference plate at a 56,500/MT base with five recent
sales averaging 58,000, sold to a tier A customer, 20 MT delivered to Patna:

    base                                            56,500.00
    + 3.5% target margin                            58,477.50
    blend 40% toward the 58,000 recent average      58,286.50
    quantity 20 MT falls in the 5-25 MT slab (0%)   58,286.50
    tier A, -0.5%                                   57,995.07
    + 1,200 freight to Patna                        59,195.07
    floor is 56,500 x 1.02 + 1,200 = 58,830 - clear
    round to nearest 50                             59,200.00
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import (
    ConfidenceLevel,
    Customer,
    CustomerTier,
    MatchStatus,
    PriceMaster,
    Product,
    QuantityUnit,
    SalesTransaction,
)
from app.services.pricing.engine import PricingService


def price_for(db, **kwargs):
    defaults = {
        "quantity_mt": Decimal("20"),
        "match_status": MatchStatus.MATCH_FOUND,
        "has_missing_information": False,
    }
    return PricingService(db).recommend(**{**defaults, **kwargs})


# --- The golden path -------------------------------------------------------


def test_full_chain_produces_the_hand_calculated_price(db, plate, customer, comparable_sales):
    outcome = price_for(db, product=plate, customer=customer, delivery_location="Patna")

    assert outcome.recommended_price == Decimal("59200.00")
    assert outcome.base_price == Decimal("56500.00")
    assert outcome.freight_per_mt == Decimal("1200")
    assert outcome.minimum_allowed_price == Decimal("58830.00")
    assert outcome.line_total == Decimal("1184000.00")
    assert outcome.margin_pct == pytest.approx(2.6549, abs=0.001)
    assert outcome.priced is True


def test_golden_path_is_high_confidence_and_needs_no_review(db, plate, customer, comparable_sales):
    outcome = price_for(db, product=plate, customer=customer, delivery_location="Patna")

    assert outcome.confidence is ConfidenceLevel.HIGH
    assert outcome.requires_manual_review is False
    assert outcome.review_reasons == []


def test_every_step_is_recorded_in_order(db, plate, customer, comparable_sales):
    outcome = price_for(db, product=plate, customer=customer, delivery_location="Patna")

    assert [s.id for s in outcome.steps] == [
        "base_price",
        "target_margin",
        "historical_anchor",
        "quantity_slab",
        "customer_tier",
        "freight",
        "margin_floor",
        "rounding",
    ]


def test_the_explanation_is_built_from_the_calculation(db, plate, customer, comparable_sales):
    """Section 22: 'why did the system recommend this price?' must be answerable."""
    explanation = price_for(
        db, product=plate, customer=customer, delivery_location="Patna"
    ).explanation

    assert "Base price for PLT-E250-10X1500X6000" in explanation
    assert "5 comparable sale(s)" in explanation
    assert "tier A" in explanation
    assert "Freight to Patna" in explanation
    assert "59,200.00" in explanation


def test_each_step_carries_its_before_and_after_price(db, plate, customer, comparable_sales):
    steps = {s.id: s for s in price_for(
        db, product=plate, customer=customer, delivery_location="Patna"
    ).steps}

    assert steps["target_margin"].price_before == pytest.approx(56500.0)
    assert steps["target_margin"].price_after == pytest.approx(58477.5)
    assert steps["freight"].adjustment == pytest.approx(1200.0)


# --- Individual rules ------------------------------------------------------


def test_large_quantity_earns_the_volume_discount(db, plate, customer, comparable_sales):
    small = price_for(db, product=plate, customer=customer, quantity_mt=Decimal("3"))
    large = price_for(db, product=plate, customer=customer, quantity_mt=Decimal("150"))

    assert large.recommended_price < small.recommended_price
    assert "1.5% discount" in next(s for s in large.steps if s.id == "quantity_slab").reason
    assert "1.5% premium" in next(s for s in small.steps if s.id == "quantity_slab").reason


def test_customer_tier_changes_the_price(db, plate, comparable_sales):
    def quote(tier: CustomerTier) -> Decimal:
        record = Customer(name=f"Tier {tier.value}", email=f"{tier.value}@x.test", tier=tier)
        db.add(record)
        db.commit()
        return price_for(db, product=plate, customer=record).recommended_price

    assert quote(CustomerTier.A) < quote(CustomerTier.B) < quote(CustomerTier.C)


def test_freight_is_added_after_the_percentage_steps(db, plate, customer, comparable_sales):
    """A tier discount should reduce the material rate, not the lorry."""
    ex_works = price_for(db, product=plate, customer=customer)
    delivered = price_for(db, product=plate, customer=customer, delivery_location="Patna")

    assert delivered.recommended_price - ex_works.recommended_price == Decimal("1200.00")


def test_freight_tolerates_a_free_text_location(db, plate, customer, comparable_sales):
    outcome = price_for(db, product=plate, customer=customer, delivery_location="Patna, Bihar")
    assert outcome.freight_per_mt == Decimal("1200")


def test_unknown_location_is_quoted_ex_works(db, plate, customer, comparable_sales):
    outcome = price_for(db, product=plate, customer=customer, delivery_location="Reykjavik")

    assert outcome.freight_per_mt == Decimal("0")
    assert "Ex-Works" in next(s for s in outcome.steps if s.id == "freight").reason


def test_price_is_rounded_to_a_quotable_figure(db, plate, customer, comparable_sales):
    price = price_for(db, product=plate, customer=customer, delivery_location="Patna").recommended_price
    assert price % Decimal("50") == 0


# --- Historical anchoring --------------------------------------------------


def test_anchor_is_skipped_when_evidence_is_thin(db, plate, customer):
    """One sale is not a market. The base price stands, and confidence drops."""
    db.add(
        SalesTransaction(
            invoice_number="INV-ONE",
            customer_id=customer.id,
            product_id=plate.id,
            quantity=Decimal("10"),
            unit=QuantityUnit.MT,
            selling_price=Decimal("62000"),
            sale_date=date.today() - timedelta(days=3),
        )
    )
    db.commit()

    outcome = price_for(db, product=plate, customer=customer)
    anchor = next(s for s in outcome.steps if s.id == "historical_anchor")

    assert anchor.applied is False
    assert "3 required" in anchor.reason
    assert outcome.confidence is not ConfidenceLevel.HIGH


def test_window_widens_before_giving_up(db, plate, customer):
    """Nothing in 30 days but plenty in 90 - use the wider window, and say so."""
    for index in range(4):
        db.add(
            SalesTransaction(
                invoice_number=f"INV-OLD-{index}",
                customer_id=customer.id,
                product_id=plate.id,
                quantity=Decimal("20"),
                unit=QuantityUnit.MT,
                selling_price=Decimal("58000"),
                sale_date=date.today() - timedelta(days=45 + index),
            )
        )
    db.commit()

    outcome = price_for(db, product=plate, customer=customer)

    assert outcome.comparables.window_days == 90
    assert outcome.comparables.count == 4
    assert "90 days" in next(s for s in outcome.steps if s.id == "historical_anchor").reason


def test_a_miskeyed_invoice_cannot_drag_the_price(db, plate, customer, comparable_sales):
    """A rate entered per kilogram instead of per tonne must be excluded."""
    db.add(
        SalesTransaction(
            invoice_number="INV-TYPO",
            customer_id=customer.id,
            product_id=plate.id,
            quantity=Decimal("20"),
            unit=QuantityUnit.MT,
            selling_price=Decimal("58"),  # 58 rupees per MT - obviously wrong
            sale_date=date.today() - timedelta(days=1),
        )
    )
    db.commit()

    outcome = price_for(db, product=plate, customer=customer, delivery_location="Patna")

    assert outcome.comparables.outliers_removed == 1
    assert outcome.comparables.count == 5
    assert outcome.recommended_price == Decimal("59200.00")


# --- Refusals and floors ---------------------------------------------------


def test_no_product_means_no_price(db):
    outcome = price_for(db, product=None)

    assert outcome.recommended_price is None
    assert outcome.priced is False
    assert outcome.requires_manual_review is True
    assert "No product was matched" in outcome.review_reasons[0]


def test_product_without_a_current_price_is_not_priced(db):
    product = Product(product_code="NEW-001", product_type="Plate", grade="E250", thickness_mm=8)
    db.add(product)
    db.commit()

    outcome = price_for(db, product=product)

    assert outcome.priced is False
    assert outcome.recommended_price is None
    assert any("No current price" in r for r in outcome.review_reasons)


def test_expired_price_is_not_used(db, plate):
    """Effective dating is real: a lapsed price is not a price."""
    row = db.query(PriceMaster).filter_by(product_id=plate.id).one()
    row.effective_to = date.today() - timedelta(days=1)
    db.commit()

    assert price_for(db, product=plate).priced is False


def test_margin_floor_raises_the_price_and_flags_it(db, plate, customer):
    """A weak market must not push a quotation below the minimum margin."""
    for index in range(5):
        db.add(
            SalesTransaction(
                invoice_number=f"INV-LOW-{index}",
                customer_id=customer.id,
                product_id=plate.id,
                quantity=Decimal("20"),
                unit=QuantityUnit.MT,
                selling_price=Decimal("52000"),
                sale_date=date.today() - timedelta(days=index + 1),
            )
        )
    db.commit()

    outcome = price_for(db, product=plate, customer=customer)
    floor_step = next(s for s in outcome.steps if s.id == "margin_floor")

    assert "below the minimum" in floor_step.reason
    assert "flagged for review" in floor_step.reason
    assert outcome.requires_manual_review is True
    assert any("minimum allowed margin" in r for r in outcome.review_reasons)
    # Corrected, but never quietly: the price still respects the floor.
    assert outcome.recommended_price >= outcome.minimum_allowed_price


def test_rounding_never_drops_below_the_minimum(db, plate, customer):
    """Rounding runs last, so it is the last thing that could undo the floor."""
    for index in range(5):
        db.add(
            SalesTransaction(
                invoice_number=f"INV-LOW-{index}",
                customer_id=customer.id,
                product_id=plate.id,
                quantity=Decimal("20"),
                unit=QuantityUnit.MT,
                selling_price=Decimal("50000"),
                sale_date=date.today() - timedelta(days=index + 1),
            )
        )
    db.commit()

    outcome = price_for(db, product=plate, customer=customer, delivery_location="Patna")
    assert outcome.recommended_price >= outcome.minimum_allowed_price


def test_unknown_quantity_skips_the_slab_without_inventing_one(db, plate, customer, comparable_sales):
    outcome = price_for(db, product=plate, customer=customer, quantity_mt=None)
    slab = next(s for s in outcome.steps if s.id == "quantity_slab")

    assert slab.applied is False
    assert "Quantity is unknown" in slab.reason
    assert outcome.line_total is None
    assert outcome.requires_manual_review is True


def test_ambiguous_match_forces_review(db, plate, customer, comparable_sales):
    outcome = price_for(
        db, product=plate, customer=customer, match_status=MatchStatus.MULTIPLE_MATCHES
    )

    assert outcome.requires_manual_review is True
    assert any("More than one product" in r for r in outcome.review_reasons)


def test_missing_information_forces_review(db, plate, customer, comparable_sales):
    outcome = price_for(db, product=plate, customer=customer, has_missing_information=True)

    assert outcome.requires_manual_review is True
    assert outcome.confidence is not ConfidenceLevel.HIGH


def test_unknown_customer_cannot_reach_high_confidence(db, plate, comparable_sales):
    outcome = price_for(db, product=plate, customer=None)

    assert outcome.confidence is not ConfidenceLevel.HIGH
    tier = next(s for s in outcome.steps if s.id == "customer_tier")
    assert tier.applied is False


# --- Persistence shape -----------------------------------------------------


def test_breakdown_is_json_serialisable(db, plate, customer, comparable_sales):
    """The breakdown is stored as JSON on the recommendation row."""
    import json

    outcome = price_for(db, product=plate, customer=customer, delivery_location="Patna")
    encoded = json.dumps(outcome.breakdown())

    assert "target_margin" in encoded
    assert json.loads(encoded)[0]["id"] == "base_price"


def test_comparables_summary_is_json_serialisable(db, plate, customer, comparable_sales):
    import json

    summary = price_for(db, product=plate, customer=customer).comparables.summary()
    json.dumps(summary)

    assert summary["count"] == 5
    assert summary["average"] == pytest.approx(58000.0)
    assert summary["minimum"] == pytest.approx(57500.0)
    assert summary["maximum"] == pytest.approx(58500.0)


def test_rule_version_is_stamped_for_later_explanation(db, plate, customer, comparable_sales):
    assert price_for(db, product=plate, customer=customer).rule_version == "1.0"
