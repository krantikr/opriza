"""The trader-editable pricing engine.

The figures here are hand-worked, as the old pricing tests were, because an
engine that computes a number nobody has independently checked is worth very
little. The reference build-up is the one the client specified:

    base 52,000 + transport 2,000 + handling 300 + financing 1,088
                + risk 200                                  = 55,588 total cost
    + 3% margin 1,668                                        = 57,256 quote

The other half of these tests is the refusals - the cases where a component
declines to produce a figure rather than inventing one.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import (
    Customer,
    CustomerTier,
    LocationDistance,
    PricingBasis,
    PricingComponentKind,
    PricingRule,
    PricingRuleSet,
    SalesInvoice,
    VehicleRate,
)
from app.services.pricing import PricingContext, PricingEngine
from app.services.pricing.components import NO_BASE_PRICE
from app.services.pricing.defaults import seed_pricing_defaults


def rule(code, kind, priority=100, config=None, conditions=None, active=True) -> PricingRule:
    return PricingRule(
        code=code,
        label=code.replace("_", " ").title(),
        kind=kind,
        priority=priority,
        is_active=active,
        config=config or {},
        conditions=conditions,
    )


@pytest.fixture()
def rule_set(db) -> PricingRuleSet:
    """The reference build-up, with freight as a flat figure for exactness."""
    rs = PricingRuleSet(version=1, label="Test rules", is_active=True)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("transportation", PricingComponentKind.TRANSPORTATION, 20, {"amount_per_mt": 2000}),
        rule("handling", PricingComponentKind.HANDLING, 30, {"amount_per_mt": 300}),
        rule("financing", PricingComponentKind.FINANCING, 40, {"annual_rate_pct": 11.0, "days": 60}),
        rule("risk_buffer", PricingComponentKind.RISK_BUFFER, 50, {"amount_per_mt": 200}),
        rule("target_margin", PricingComponentKind.TARGET_MARGIN, 100, {"pct": 3.0}),
    ]
    db.add(rs)
    db.commit()
    return rs


@pytest.fixture()
def ctx(db) -> PricingContext:
    return PricingContext(db=db, quantity_mt=Decimal("100"), stock_cost_per_mt=Decimal("52000"))


# --- The reference calculation ---------------------------------------------


def test_the_reference_build_up_matches_the_hand_calculation(db, rule_set, ctx):
    outcome = PricingEngine(db, rule_set).price(ctx)

    assert outcome.base_rate == Decimal("52000.00")
    # 52,000 + 2,000 + 300 = 54,300; financing 54,300 x 11% x 60/365 = 981.86
    # Note the reference sheet financed 52,300; the rule finances accumulated
    # cost, which is the figure actually tied up.
    assert outcome.total_cost == Decimal("55481.86")
    assert outcome.margin_amount == Decimal("1664.46")
    assert outcome.quote_rate == Decimal("57146.32")
    assert outcome.line_total == Decimal("5714632.00")


def test_every_component_records_its_own_reason(db, rule_set, ctx):
    outcome = PricingEngine(db, rule_set).price(ctx)

    codes = [c.code for c in outcome.components]
    assert codes == [
        "base_price",
        "transportation",
        "handling",
        "financing",
        "risk_buffer",
        "target_margin",
    ]
    assert all(c.note for c in outcome.components)
    assert "landed cost" in outcome.components[0].note
    assert "11% p.a." in outcome.components[3].note
    assert "3% on total cost" in outcome.components[5].note


def test_each_component_carries_its_running_subtotal(db, rule_set, ctx):
    """The calculator renders these directly, so they must be stored."""
    outcome = PricingEngine(db, rule_set).price(ctx)
    subtotals = [c.subtotal for c in outcome.components]

    assert subtotals[0] == Decimal("52000.00")
    assert subtotals[1] == Decimal("54000.00")
    assert subtotals[2] == Decimal("54300.00")
    assert subtotals[-1] == outcome.quote_rate


def test_the_margin_applies_to_total_cost_not_to_the_base(db, rule_set, ctx):
    outcome = PricingEngine(db, rule_set).price(ctx)
    margin = next(c for c in outcome.components if c.kind == "TARGET_MARGIN")

    assert margin.amount == Decimal("1664.46")
    assert margin.amount != Decimal("52000") * Decimal("0.03")


def test_the_build_up_is_json_serialisable(db, rule_set, ctx):
    """It is persisted as JSON, so a Decimal left in place would fail on write."""
    import json

    outcome = PricingEngine(db, rule_set).price(ctx)
    assert json.loads(json.dumps(outcome.components_as_json()))


# --- Base price resolution -------------------------------------------------


def test_stock_is_preferred_over_a_mill_offer(db, rule_set):
    ctx = PricingContext(
        db=db, stock_cost_per_mt=Decimal("52000"), mill_offer_per_mt=Decimal("54000")
    )
    outcome = PricingEngine(db, rule_set).price(ctx)

    assert outcome.basis is PricingBasis.STOCK
    assert outcome.base_rate == Decimal("52000.00")


def test_a_mill_offer_is_used_when_nothing_is_in_stock(db, rule_set):
    """Quoting against procurement is the other half of the trade."""
    ctx = PricingContext(
        db=db, mill_offer_per_mt=Decimal("54000"), mill_offer_supplier="Jindal"
    )
    outcome = PricingEngine(db, rule_set).price(ctx)

    assert outcome.basis is PricingBasis.MILL_OFFER
    assert outcome.base_rate == Decimal("54000.00")
    assert "Jindal" in outcome.components[0].note


def test_no_stock_and_no_offer_yields_no_price_at_all(db, rule_set):
    """The refusal that matters most: never a plausible-looking invented rate."""
    outcome = PricingEngine(db, rule_set).price(PricingContext(db=db))

    assert outcome.priced is False
    assert outcome.quote_rate is None
    assert "No base price available." in outcome.warnings
    assert outcome.components[0].applied is False


# --- Freight ---------------------------------------------------------------


def test_freight_is_derived_from_distance_and_vehicle_economics(db, rule_set):
    db.add(VehicleRate(name="Trailer", capacity_mt=Decimal("25"), rate_per_day=Decimal("50000"),
                       avg_km_per_day=350, min_days=1))
    db.add(LocationDistance(origin="Nagpur", destination="Patna", distance_km=1050, typical_days=3))
    db.commit()

    rs = PricingRuleSet(version=2, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("transportation", PricingComponentKind.TRANSPORTATION, 20, {"round_trip": False}),
    ]
    db.add(rs)
    db.commit()

    ctx = PricingContext(
        db=db,
        stock_cost_per_mt=Decimal("52000"),
        quantity_mt=Decimal("25"),
        delivery_location="Patna",
        origin_location="Nagpur",
    )
    outcome = PricingEngine(db, rs).price(ctx)
    freight = outcome.components[1]

    # 50,000/day x 3 days over 25 MT = 6,000 per MT
    assert freight.amount == Decimal("6000.00")
    assert "1050 km" in freight.note
    assert "Trailer" in freight.note


def test_an_unknown_destination_is_quoted_ex_works_not_guessed(db, rule_set):
    db.add(VehicleRate(name="Trailer", capacity_mt=Decimal("25"), rate_per_day=Decimal("50000")))
    db.commit()

    rs = PricingRuleSet(version=3, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("transportation", PricingComponentKind.TRANSPORTATION, 20, {}),
    ]
    db.add(rs)
    db.commit()

    ctx = PricingContext(
        db=db, stock_cost_per_mt=Decimal("52000"), quantity_mt=Decimal("20"),
        delivery_location="Somewhere Nobody Configured",
    )
    outcome = PricingEngine(db, rs).price(ctx)
    freight = outcome.components[1]

    assert freight.applied is False
    assert freight.amount == Decimal("0")
    assert "ex-works" in freight.note
    assert any("not configured" in w for w in outcome.warnings)


# --- Conditions ------------------------------------------------------------


def test_a_rule_scoped_to_a_location_does_not_fire_elsewhere(db):
    rs = PricingRuleSet(version=4, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("octroi", PricingComponentKind.HANDLING, 20, {"amount_per_mt": 500},
             conditions={"delivery_location": ["Mumbai"]}),
    ]
    db.add(rs)
    db.commit()

    inside = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"), delivery_location="Mumbai")
    )
    outside = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"), delivery_location="Pune")
    )

    assert inside.quote_rate == Decimal("50500.00")
    assert outside.quote_rate == Decimal("50000.00")


def test_an_unstated_fact_never_satisfies_a_condition(db):
    """A rule for Mumbai must not fire when no destination was given at all."""
    rs = PricingRuleSet(version=5, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("octroi", PricingComponentKind.HANDLING, 20, {"amount_per_mt": 500},
             conditions={"delivery_location": ["Mumbai"]}),
    ]
    db.add(rs)
    db.commit()

    outcome = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"))
    )
    assert outcome.quote_rate == Decimal("50000.00")


def test_an_inactive_rule_is_skipped(db):
    rs = PricingRuleSet(version=6, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("extra", PricingComponentKind.HANDLING, 20, {"amount_per_mt": 999}, active=False),
    ]
    db.add(rs)
    db.commit()

    outcome = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"))
    )
    assert outcome.quote_rate == Decimal("50000.00")


# --- Quantity slabs and tiers ----------------------------------------------


def test_volume_bands_adjust_by_tonnage(db):
    rs = PricingRuleSet(version=7, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("quantity_slab", PricingComponentKind.QUANTITY_SLAB, 20, {
            "of": "RUNNING",
            "slabs": [
                {"min_mt": 0, "max_mt": 25, "pct": 0},
                {"min_mt": 25, "max_mt": None, "pct": -1.0},
            ],
        }),
    ]
    db.add(rs)
    db.commit()

    small = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"), quantity_mt=Decimal("10"))
    )
    large = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"), quantity_mt=Decimal("50"))
    )

    assert small.quote_rate == Decimal("50000.00")
    assert large.quote_rate == Decimal("49500.00")


def test_unknown_quantity_skips_the_slab_without_inventing_one(db):
    rs = PricingRuleSet(version=8, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("quantity_slab", PricingComponentKind.QUANTITY_SLAB, 20, {
            "slabs": [{"min_mt": 0, "max_mt": None, "pct": -5.0}]
        }),
    ]
    db.add(rs)
    db.commit()

    outcome = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"))
    )
    slab = outcome.components[1]
    assert slab.applied is False
    assert "not stated" in slab.note


def test_an_unverified_customer_gets_no_tier_discount(db):
    """A tier nobody has confirmed is not grounds for a discount."""
    unverified = Customer(name="New Co", email="new@co.test", tier=CustomerTier.A, is_verified=False)
    db.add(unverified)
    rs = PricingRuleSet(version=9, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("customer_tier", PricingComponentKind.CUSTOMER_TIER, 20,
             {"tiers": {"A": -5.0}}),
    ]
    db.add(rs)
    db.commit()

    outcome = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"), customer=unverified)
    )
    tier = outcome.components[1]
    assert tier.applied is False
    assert outcome.quote_rate == Decimal("50000.00")
    assert any("Unverified customer" in w for w in outcome.warnings)


# --- Invoice history -------------------------------------------------------


def _invoice(days_ago: int, rate: str, **spec) -> SalesInvoice:
    return SalesInvoice(
        invoice_date=date.today() - timedelta(days=days_ago),
        product_type=spec.get("product_type", "Plate"),
        grade=spec.get("grade", "E250"),
        thickness_mm=spec.get("thickness_mm", 10.0),
        quantity_mt=Decimal("20"),
        rate_per_mt=Decimal(rate),
    )


def test_recent_sales_pull_the_price_toward_the_market(db):
    for _ in range(4):
        db.add(_invoice(5, "54000"))
    rs = PricingRuleSet(version=10, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("invoice_anchor", PricingComponentKind.INVOICE_ANCHOR, 20,
             {"window_days": 30, "min_count": 3, "weight_pct": 50}),
    ]
    db.add(rs)
    db.commit()

    outcome = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"),
                       product_type="Plate", grade="E250", thickness_mm=10.0)
    )
    # Half the way from 50,000 to 54,000.
    assert outcome.quote_rate == Decimal("52000.00")


def test_thin_evidence_is_refused_rather_than_averaged(db):
    db.add(_invoice(5, "54000"))
    rs = PricingRuleSet(version=11, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("invoice_anchor", PricingComponentKind.INVOICE_ANCHOR, 20,
             {"window_days": 30, "max_window_days": 30, "min_count": 3, "weight_pct": 50}),
    ]
    db.add(rs)
    db.commit()

    outcome = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"),
                       product_type="Plate", grade="E250", thickness_mm=10.0)
    )
    anchor = outcome.components[1]
    assert anchor.applied is False
    assert "fewer than the 3 required" in anchor.note
    assert outcome.quote_rate == Decimal("50000.00")


def test_one_miskeyed_invoice_cannot_drag_the_price(db):
    """A rate entered per kg among rates per MT must not move the anchor."""
    for _ in range(5):
        db.add(_invoice(5, "54000"))
    db.add(_invoice(5, "54"))  # the fat finger
    rs = PricingRuleSet(version=12, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("invoice_anchor", PricingComponentKind.INVOICE_ANCHOR, 20,
             {"window_days": 30, "min_count": 3, "weight_pct": 100}),
    ]
    db.add(rs)
    db.commit()

    outcome = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"),
                       product_type="Plate", grade="E250", thickness_mm=10.0)
    )
    assert outcome.quote_rate == Decimal("54000.00")
    assert "outlier(s) rejected" in outcome.components[1].note


# --- Floor and rounding ----------------------------------------------------


def test_the_margin_floor_raises_the_price_and_flags_it(db):
    rs = PricingRuleSet(version=13, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("discount", PricingComponentKind.ADJUSTMENT, 20, {"pct": -10.0, "of": "BASE"}),
        rule("margin_floor", PricingComponentKind.MARGIN_FLOOR, 110, {"minimum_margin_pct": 2.0}),
    ]
    db.add(rs)
    db.commit()

    outcome = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"))
    )

    assert outcome.quote_rate == Decimal("51000.00")
    floor = next(c for c in outcome.components if c.kind == "MARGIN_FLOOR")
    assert "below the 2% minimum" in floor.note
    assert any("Margin floor applied" in w for w in outcome.warnings)


def test_rounding_never_drops_back_through_the_floor(db):
    rs = PricingRuleSet(version=14, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("margin_floor", PricingComponentKind.MARGIN_FLOOR, 110, {"minimum_margin_pct": 2.0}),
        rule("rounding", PricingComponentKind.ROUNDING, 120, {"nearest": 100, "mode": "up"}),
    ]
    db.add(rs)
    db.commit()

    outcome = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"))
    )
    # Floor lifts to 51,000, rounding up to the nearest 100 keeps it there.
    assert outcome.quote_rate == Decimal("51000.00")


def test_terminal_rules_run_last_however_they_are_numbered(db):
    """A mis-ordered rule set must not apply margin to a partial cost."""
    rs = PricingRuleSet(version=15, is_active=False)
    rs.rules = [
        rule("target_margin", PricingComponentKind.TARGET_MARGIN, 1, {"pct": 10.0}),
        rule("base_price", PricingComponentKind.BASE_PRICE, 50),
        rule("handling", PricingComponentKind.HANDLING, 60, {"amount_per_mt": 1000}),
    ]
    db.add(rs)
    db.commit()

    outcome = PricingEngine(db, rs).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"))
    )

    assert [c.kind for c in outcome.components][-1] == "TARGET_MARGIN"
    # 10% of 51,000, not of 0 or of 50,000.
    assert outcome.quote_rate == Decimal("56100.00")


# --- Overrides -------------------------------------------------------------


def test_an_override_replaces_the_figure_but_keeps_the_calculated_one(db, rule_set, ctx):
    outcome = PricingEngine(db, rule_set).price(
        ctx, overrides={"transportation": Decimal("3500")}
    )
    freight = next(c for c in outcome.components if c.code == "transportation")

    assert freight.amount == Decimal("3500.00")
    assert freight.computed_amount == Decimal("2000.00")
    assert freight.overridden is True
    assert "Overridden by a reviewer" in freight.note
    assert "calculated: INR 2,000.00" in freight.note


def test_an_override_flows_through_to_the_quote(db, rule_set, ctx):
    plain = PricingEngine(db, rule_set).price(ctx)
    overridden = PricingEngine(db, rule_set).price(
        ctx, overrides={"transportation": Decimal("3000")}
    )
    assert overridden.quote_rate > plain.quote_rate


# --- No rules configured ---------------------------------------------------


def test_no_published_rule_set_yields_no_price(db):
    outcome = PricingEngine(db, None).price(
        PricingContext(db=db, stock_cost_per_mt=Decimal("50000"))
    )
    assert outcome.priced is False
    assert "No pricing rule set is published." in outcome.warnings


# --- Seeded defaults -------------------------------------------------------


def test_the_seeded_defaults_price_the_reference_enquiry(db):
    """A new installation must produce a sensible figure out of the box."""
    rs = seed_pricing_defaults(db)
    ctx = PricingContext(db=db, stock_cost_per_mt=Decimal("52000"), quantity_mt=Decimal("100"))

    outcome = PricingEngine(db, rs).price(ctx)

    assert outcome.priced
    assert outcome.base_rate == Decimal("52000.00")
    assert outcome.quote_rate > outcome.total_cost
    # Rounded to the nearest 50 by the seeded rounding rule.
    assert outcome.quote_rate % Decimal("50") == 0


def test_seeding_is_idempotent(db):
    first = seed_pricing_defaults(db)
    second = seed_pricing_defaults(db)
    assert first.id == second.id


# --- Serialisation ---------------------------------------------------------


def test_a_priced_line_serialises_when_there_are_no_warnings(db, quoted_quotation, rule_set):
    """`warnings` is stored as NULL when empty; the API must still render it.

    Regression: the detail endpoint 500'd because the schema demanded a list
    and the column held NULL.
    """
    from app.schemas.pricing import PricingOut
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    result = PricingService(db, rule_set).price_line(item, quotation=quoted_quotation)
    db.commit()

    assert result.record.warnings is None
    assert PricingOut.model_validate(result.record).warnings == []


def test_pricing_finds_cost_on_a_sibling_lot_of_the_same_spec(
    db, quoted_quotation, plate, rule_set
):
    """Regression: `matched_stock_item_id` names one representative lot,
    chosen by freshest ageing for display - not the lot with cost data.
    Several lots commonly share a spec at different ages, locations or
    costs. A caller that re-prices without threading the matcher's full
    `lot_ids` through (recalculate, update details) must still find a
    sibling's cost rather than reporting the line unavailable just because
    the one lot it happens to point at carries none.
    """
    from app.models import StockItem
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]

    # The representative lot the item is actually matched to: same spec as
    # `plate`, but no cost on file - exactly what an incomplete import row
    # produces.
    costless = StockItem(
        product_type=plate.product_type,
        grade=plate.grade,
        thickness_mm=plate.thickness_mm,
        width_mm=plate.width_mm,
        length_mm=plate.length_mm,
        location="PUNE",
        balance_qty_kg=Decimal("5000.000"),
        ageing_days=1,  # freshest, so the matcher would pick this one
    )
    db.add(costless)
    db.commit()

    item.matched_stock_item_id = costless.id
    db.commit()

    # No `lot_ids` passed, matching the recalculate/update-details call sites.
    result = PricingService(db, rule_set).price_line(item, quotation=quoted_quotation)
    db.commit()

    base = next(c for c in result.record.components if c["code"] == "base_price")
    assert base["meta"]["basis"] != "UNAVAILABLE"
    assert Decimal(base["amount"]) > 0


def test_an_override_survives_a_recalculation(db, quoted_quotation, rule_set):
    """Recomputing because stock moved must not discard a deliberate figure."""
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    service = PricingService(db, rule_set)
    service.price_line(item, quotation=quoted_quotation)

    service.set_override(item, component_code="handling", amount=Decimal("999"))
    again = service.price_line(item, quotation=quoted_quotation)

    handling = next(c for c in again.record.components if c["code"] == "handling")
    assert handling["amount"] == "999.00"
    assert handling["overridden"] is True
    assert again.record.has_overrides is True


def test_clearing_an_override_restores_the_calculated_figure(db, quoted_quotation, rule_set):
    """Regression: a cached relationship left the override applied after delete."""
    from app.models import PricingOverride
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    service = PricingService(db, rule_set)
    service.price_line(item, quotation=quoted_quotation)

    overridden = service.set_override(item, component_code="handling", amount=Decimal("999"))
    assert overridden.record.has_overrides is True

    cleared = service.clear_override(item, "handling")

    assert db.query(PricingOverride).count() == 0
    assert cleared.record.has_overrides is False
    handling = next(c for c in cleared.record.components if c["code"] == "handling")
    assert handling["amount"] == "300.00"
    assert handling["overridden"] is False


def test_changing_a_figure_marks_the_draft_stale(db, quoted_quotation, rule_set):
    """A draft written against a superseded number must never go out as-is."""
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    service = PricingService(db, rule_set)
    first = service.price_line(item, quotation=quoted_quotation)
    assert first.record.draft_stale is False

    changed = service.set_override(item, component_code="handling", amount=Decimal("5000"))
    assert changed.record.draft_stale is True


def test_a_part_load_does_not_pay_for_a_whole_lorry(db):
    """A 0.5 MT order must not carry an entire trailer's hire.

    Regression: spreading the full hire over the ordered tonnage priced a small
    enquiry at several lakh per MT - arithmetically true, commercially absurd.
    """
    db.add(
        VehicleRate(
            name="Trailer",
            capacity_mt=Decimal("25"),
            rate_per_day=Decimal("50000"),
            avg_km_per_day=350,
            min_days=1,
        )
    )
    db.add(LocationDistance(origin="Nagpur", destination="Patna", distance_km=1050, typical_days=3))
    rs = PricingRuleSet(version=40, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("transportation", PricingComponentKind.TRANSPORTATION, 20,
             {"round_trip": False, "min_load_pct": 40}),
    ]
    db.add(rs)
    db.commit()

    def freight_for(qty: str) -> Decimal:
        outcome = PricingEngine(db, rs).price(
            PricingContext(
                db=db,
                stock_cost_per_mt=Decimal("52000"),
                quantity_mt=Decimal(qty),
                delivery_location="Patna",
                origin_location="Nagpur",
            )
        )
        return next(c for c in outcome.components if c.code == "transportation").amount

    # 50,000/day x 3 days = 150,000, spread over the 10 MT minimum, not 0.5 MT.
    assert freight_for("0.5") == Decimal("15000.00")
    # A full load pays over what it actually occupies.
    assert freight_for("25") == Decimal("6000.00")
    # And the small order is told why.
    outcome = PricingEngine(db, rs).price(
        PricingContext(
            db=db,
            stock_cost_per_mt=Decimal("52000"),
            quantity_mt=Decimal("0.5"),
            delivery_location="Patna",
            origin_location="Nagpur",
        )
    )
    assert "Part load" in outcome.components[1].note


def test_stated_payment_terms_beat_the_configured_default(db):
    """Recording "45 days" must change the financing, not be ignored."""
    rs = PricingRuleSet(version=41, is_active=False)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("financing", PricingComponentKind.FINANCING, 20,
             {"annual_rate_pct": 12.0, "days": 60}),
    ]
    db.add(rs)
    db.commit()

    def financing_for(payment_days):
        outcome = PricingEngine(db, rs).price(
            PricingContext(
                db=db, stock_cost_per_mt=Decimal("100000"), payment_days=payment_days
            )
        )
        return next(c for c in outcome.components if c.code == "financing")

    default = financing_for(None)
    stated = financing_for(30)

    # 100,000 x 12% x 60/365 vs x 30/365 - the stated term halves it.
    assert default.amount == Decimal("1972.60")
    assert stated.amount == Decimal("986.30")
    assert "as agreed with this customer" in stated.note
    assert "as agreed" not in default.note


# ---------------------------------------------------------------------------
# Overriding a component the engine could not compute
# ---------------------------------------------------------------------------


def test_overriding_the_base_price_answers_the_warning_it_raised(db, quoted_quotation, rule_set):
    """A reviewer supplying the missing figure has answered the complaint.

    Regression: the screen said "No base price available." directly above the
    base price the reviewer had just typed in, because the component's warning
    was collected whether or not it had been overridden.
    """
    from app.models import PricingBasis
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    # Nothing to price from: no landed cost on the stock, no mill offer.
    if item.matched_stock_item is not None:
        item.matched_stock_item.landed_cost_per_kg = None
    db.commit()

    service = PricingService(db, rule_set)
    before = service.price_line(item, quotation=quoted_quotation)
    assert NO_BASE_PRICE in (before.outcome.warnings or [])
    assert before.outcome.basis is PricingBasis.UNAVAILABLE

    after = service.set_override(item, component_code="base_price", amount=Decimal("200"))

    assert NO_BASE_PRICE not in (after.outcome.warnings or [])
    assert after.outcome.basis is PricingBasis.MANUAL
    assert after.outcome.base_rate == Decimal("200.00")


def test_a_warning_from_a_component_nobody_touched_still_stands(db, quoted_quotation, rule_set):
    """Overriding one figure must not silence an unrelated complaint."""
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    if item.matched_stock_item is not None:
        item.matched_stock_item.landed_cost_per_kg = None
    db.commit()

    service = PricingService(db, rule_set)
    service.price_line(item, quotation=quoted_quotation)

    # Override a *different* component; the base price is still unavailable.
    after = service.set_override(item, component_code="handling", amount=Decimal("500"))

    assert NO_BASE_PRICE in (after.outcome.warnings or [])


def test_the_stored_record_reflects_the_answered_warning(db, quoted_quotation, rule_set):
    """The screen reads the persisted row, so the fix has to reach the database.

    Checking the outcome object alone would pass while the panel still showed
    the stale warning from `QuotationPricing.warnings`.
    """
    from app.models import PricingBasis
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    if item.matched_stock_item is not None:
        item.matched_stock_item.landed_cost_per_kg = None
    db.commit()

    service = PricingService(db, rule_set)
    service.price_line(item, quotation=quoted_quotation)
    service.set_override(item, component_code="base_price", amount=Decimal("200"))
    db.commit()
    db.refresh(item)

    assert NO_BASE_PRICE not in (item.pricing.warnings or [])
    assert item.pricing.basis is PricingBasis.MANUAL
    assert item.pricing.base_rate == Decimal("200.00")


def test_repricing_an_already_overridden_line_clears_a_stale_warning(
    db, quoted_quotation, rule_set
):
    """A row written before the fix must heal on the next recalculation.

    The panel reads the stored row, so a quotation overridden earlier still
    carries the old warning until something re-prices it. Recalculate has to be
    enough - otherwise the only cure is deleting and re-entering the override.
    """
    from app.models import PricingBasis
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    if item.matched_stock_item is not None:
        item.matched_stock_item.landed_cost_per_kg = None
    db.commit()

    service = PricingService(db, rule_set)
    service.price_line(item, quotation=quoted_quotation)
    service.set_override(item, component_code="base_price", amount=Decimal("200"))
    db.commit()

    # Simulate the stale state a pre-fix row would be in.
    db.refresh(item)
    item.pricing.warnings = [NO_BASE_PRICE]
    item.pricing.basis = PricingBasis.UNAVAILABLE
    db.commit()

    service.price_line(item, quotation=quoted_quotation)
    db.commit()
    db.refresh(item)

    assert NO_BASE_PRICE not in (item.pricing.warnings or [])
    assert item.pricing.basis is PricingBasis.MANUAL


# ---------------------------------------------------------------------------
# Where the stock cost comes from
# ---------------------------------------------------------------------------


def test_a_lot_with_only_a_purchase_rate_still_prices(db, quoted_quotation, rule_set):
    """A stock sheet without a landed-cost column is ordinary.

    Regression: the line reported "no base price available" while the floor
    plainly held the material at a known cost, because only `landed_cost_per_kg`
    was consulted.
    """
    from app.models import PricingBasis
    from app.services.pricing.service import PricingService

    lot = quoted_quotation.line_items[0].matched_stock_item
    lot.landed_cost_per_kg = None
    lot.purchase_rate_per_kg = 52.0
    db.commit()

    result = PricingService(db, rule_set).price_line(
        quoted_quotation.line_items[0], quotation=quoted_quotation
    )

    assert NO_BASE_PRICE not in (result.outcome.warnings or [])
    assert result.outcome.basis is PricingBasis.STOCK
    assert result.outcome.base_rate == Decimal("52000.00")


def test_the_note_says_which_figure_it_priced_from(db, quoted_quotation, rule_set):
    """Purchase rate excludes freight and duty, so it must not read as landed."""
    from app.services.pricing.service import PricingService

    lot = quoted_quotation.line_items[0].matched_stock_item
    lot.landed_cost_per_kg = None
    lot.purchase_rate_per_kg = 52.0
    db.commit()

    result = PricingService(db, rule_set).price_line(
        quoted_quotation.line_items[0], quotation=quoted_quotation
    )
    base = next(c for c in result.outcome.components if c.kind == "BASE_PRICE")

    assert "purchase rate" in base.note
    assert "freight and duty are not included" in base.note


def test_landed_cost_is_preferred_when_both_are_recorded(db, quoted_quotation, rule_set):
    """Landed cost is what the material actually cost to have on the floor."""
    from app.services.pricing.service import PricingService

    lot = quoted_quotation.line_items[0].matched_stock_item
    lot.landed_cost_per_kg = 56.5
    lot.purchase_rate_per_kg = 52.0
    db.commit()

    result = PricingService(db, rule_set).price_line(
        quoted_quotation.line_items[0], quotation=quoted_quotation
    )
    base = next(c for c in result.outcome.components if c.kind == "BASE_PRICE")

    assert result.outcome.base_rate == Decimal("56500.00")
    assert "landed cost" in base.note


def test_a_lot_with_neither_figure_still_reports_honestly(db, quoted_quotation, rule_set):
    """The fallback must not invent a cost where none is recorded."""
    from app.services.pricing.service import PricingService

    lot = quoted_quotation.line_items[0].matched_stock_item
    lot.landed_cost_per_kg = None
    lot.purchase_rate_per_kg = None
    db.commit()

    result = PricingService(db, rule_set).price_line(
        quoted_quotation.line_items[0], quotation=quoted_quotation
    )

    assert NO_BASE_PRICE in (result.outcome.warnings or [])


def test_pricing_a_line_that_had_no_rate_marks_the_draft_stale(
    db, quoted_quotation, rule_set
):
    """Going from no price to a price is the largest change there is.

    Regression: the guard was `previous_rate is not None`, so a line that could
    not be priced at all never raised the warning - and a draft saying no rate
    was available could be sent over a line that now had one.
    """
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    lot = item.matched_stock_item
    lot.landed_cost_per_kg = None
    lot.purchase_rate_per_kg = None
    db.commit()

    service = PricingService(db, rule_set)
    first = service.price_line(item, quotation=quoted_quotation)
    assert first.record.quote_rate is None
    assert first.record.draft_stale is False

    after = service.set_override(item, component_code="base_price", amount=Decimal("200"))

    assert after.record.quote_rate is not None
    assert after.record.draft_stale is True


# --- Multi-location pricing options ------------------------------------------


def test_a_second_location_gets_its_own_priced_option(db, quoted_quotation, plate, rule_set):
    """Comparing sourcing from two warehouses must not blend their costs."""
    from app.models import StockItem
    from app.services.pricing.service import PricingService

    varanasi = StockItem(
        product_type=plate.product_type,
        grade=plate.grade,
        thickness_mm=plate.thickness_mm,
        width_mm=plate.width_mm,
        length_mm=plate.length_mm,
        location="VARANASI",
        balance_qty_kg=Decimal("10000.000"),
        landed_cost_per_kg=40.0,  # cheaper than plate's 56.5
        ageing_days=3,
    )
    db.add(varanasi)
    db.commit()

    item = quoted_quotation.line_items[0]
    service = PricingService(db, rule_set)

    main = service.price_line(item, quotation=quoted_quotation).record
    assert main.despatch_location is None
    assert main.is_selected is True

    second = service.price_line(
        item, quotation=quoted_quotation, despatch_location="VARANASI"
    ).record
    assert second.despatch_location == "VARANASI"
    assert second.is_selected is False  # first option keeps the selection
    assert second.base_rate != main.base_rate  # different warehouse, different cost

    db.refresh(item)
    assert len(item.pricing_options) == 2
    assert item.pricing is main  # unchanged until explicitly selected


def test_selecting_an_option_changes_what_item_pricing_resolves_to(
    db, quoted_quotation, plate, rule_set
):
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    service = PricingService(db, rule_set)
    main = service.price_line(item, quotation=quoted_quotation).record
    second = service.price_line(
        item, quotation=quoted_quotation, despatch_location="PUNE"
    ).record

    selected = service.select_option(item, second.id)

    assert selected.id == second.id
    db.refresh(item)
    assert item.pricing.id == second.id
    assert main.is_selected is False
    assert second.is_selected is True


def test_selecting_an_unknown_option_is_refused(db, quoted_quotation, rule_set):
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    service = PricingService(db, rule_set)
    service.price_line(item, quotation=quoted_quotation)

    with pytest.raises(ValueError):
        service.select_option(item, pricing_id=999999)


def test_a_manual_option_takes_whatever_the_trader_types_with_no_engine(
    db, quoted_quotation, rule_set
):
    """"Other": a despatch location with no matched stock, priced entirely
    by hand - the engine must never run for one of these."""
    from app.services.pricing.service import PricingService

    item = quoted_quotation.line_items[0]
    service = PricingService(db, rule_set)
    manual = service.add_manual_option(item, "Customer's own yard")

    assert manual.is_manual is True
    assert manual.components == []
    assert manual.quote_rate is None

    result = service.set_override(
        item, component_code="base_price", amount=Decimal("500"), despatch_location="Customer's own yard"
    )

    assert result.record.is_manual is True
    assert result.record.quote_rate == Decimal("500")
    assert result.record.components[0]["code"] == "base_price"
    assert result.record.components[0]["overridden"] is True


def test_known_locations_lists_distinct_stock_locations(db, plate, rule_set):
    from app.models import StockItem
    from app.services.pricing.service import PricingService

    db.add(
        StockItem(
            product_type="Plate", grade="E250", thickness_mm=8.0,
            location="VARANASI", balance_qty_kg=Decimal("1000"),
        )
    )
    db.commit()

    locations = PricingService(db, rule_set).known_locations()
    assert "NAGPUR" in locations
    assert "VARANASI" in locations
    assert len(locations) == len(set(locations))  # no duplicates
