"""A quotation must not state a price the calculator no longer holds.

The item table is re-rendered from the pricing on every change, so it is always
current. Prose is not: a rate the model wrote into a sentence is
indistinguishable from wording a reviewer chose, so nothing rewrites it. The
failure is an email whose opening line and whose table quote different prices,
with the customer reading the stale one first.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ai.guards import find_stale_prices
from app.models import (
    DraftStatus,
    PricingComponentKind,
    PricingRule,
    PricingRuleSet,
    QuotationDraft,
)
from app.services.pricing.service import PricingService
from app.services.quotations.approval import ApprovalService
from app.services.quotations.draft_figures import (
    refresh_draft_figures,
    stale_prices_in_draft,
)
from app.services.quotations.table import TABLE_PLACEHOLDER, build_rows, splice_text


@pytest.fixture()
def live_rules(db) -> PricingRuleSet:
    def rule(code, kind, priority, config=None):
        return PricingRule(
            code=code, label=code, kind=kind, priority=priority,
            is_active=True, config=config or {}, conditions=None,
        )

    rs = PricingRuleSet(version=1, label="Live", is_active=True)
    rs.rules = [
        rule("base_price", PricingComponentKind.BASE_PRICE, 10),
        rule("transportation", PricingComponentKind.TRANSPORTATION, 20, {"amount_per_mt": 2000}),
        rule("target_margin", PricingComponentKind.TARGET_MARGIN, 100, {"pct": 3.0}),
    ]
    db.add(rs)
    db.commit()
    return rs


def _priced(db, quotation):
    for item in quotation.line_items:
        PricingService(db).price_line(item, quotation=quotation)
    db.commit()
    return quotation


def _draft(db, quotation, prose: str) -> QuotationDraft:
    body = splice_text(prose, build_rows(quotation))
    draft = QuotationDraft(
        quotation_request_id=quotation.id, version=1, is_current=True,
        subject="Re: Enquiry", body=body, status=DraftStatus.GENERATED,
        generated_by="test",
    )
    db.add(draft)
    db.commit()
    return draft


# --- The detector, on its own ----------------------------------------------


def test_a_figure_that_matches_current_pricing_is_not_stale():
    assert find_stale_prices("We offer at INR 61,000.00 per MT.", [Decimal("61000")]) == []


def test_a_figure_the_pricing_no_longer_holds_is_reported():
    assert find_stale_prices(
        "We offer at INR 61,000.00 per MT.", [Decimal("72100")]
    ) == ["61000.00"]


def test_dimensions_are_not_mistaken_for_prices():
    """"10 x 2500 x 7000 mm" is a specification, not three stale rates."""
    body = "Item: E250BR Plate, Dimensions: 10 x 2500 x 7000 mm, 20 MT required."
    assert find_stale_prices(body, []) == []


def test_a_bare_year_is_not_a_price():
    assert find_stale_prices("Valid until 30 September 2026.", []) == []


def test_quantities_and_reference_numbers_are_left_alone():
    body = "Quotation KK-000006 for 20 MT, 40 pieces, delivered to Nagpur."
    assert find_stale_prices(body, []) == []


def test_formatting_does_not_change_the_verdict():
    """Indian grouping, plain digits and a decimal are the same price."""
    for text in ("INR 61,000.00", "Rs 61000", "₹61,000"):
        assert find_stale_prices(text, [Decimal("61000")]) == [], text


# --- Against a real quotation ----------------------------------------------


def test_the_table_itself_is_never_flagged(db, quoted_quotation, live_rules):
    """The table holds current figures by construction; checking it is circular."""
    q = _priced(db, quoted_quotation)
    draft = _draft(db, q, f"Dear Sir,\n\n{TABLE_PLACEHOLDER}\n\nRegards")
    assert stale_prices_in_draft(q, draft.body) == []


def test_a_stale_prose_rate_is_caught_after_a_price_change(db, quoted_quotation, live_rules):
    q = _priced(db, quoted_quotation)
    rate_before = q.line_items[0].pricing.quote_rate
    draft = _draft(
        db, q,
        f"Dear Sir,\n\nWe are pleased to offer at INR {rate_before:,.2f} per MT.\n\n"
        f"{TABLE_PLACEHOLDER}\n\nRegards",
    )

    PricingService(db).set_override(
        q.line_items[0], component_code="base_price", amount=Decimal("70000")
    )
    db.commit()
    refresh_draft_figures(db, q)
    db.commit()

    stale = stale_prices_in_draft(q, db.get(QuotationDraft, draft.id).body)
    assert stale, "the superseded prose rate should have been caught"
    assert str(rate_before).rstrip("0").rstrip(".") in " ".join(stale).replace(",", "")


def test_a_component_figure_in_prose_is_allowed(db, quoted_quotation, live_rules):
    """Freight is a current figure even though the table never shows it."""
    q = _priced(db, quoted_quotation)
    draft = _draft(
        db, q,
        f"Dear Sir,\n\nFreight is INR 2,000.00 per MT.\n\n{TABLE_PLACEHOLDER}\n\nRegards",
    )
    assert stale_prices_in_draft(q, draft.body) == []


# --- The send block ---------------------------------------------------------


def test_sending_warns_when_a_stale_price_remains(db, quoted_quotation, live_rules, default_user):
    q = _priced(db, quoted_quotation)
    rate_before = q.line_items[0].pricing.quote_rate
    _draft(
        db, q,
        f"Dear Sir,\n\nWe are pleased to offer at INR {rate_before:,.2f} per MT.\n\n"
        f"{TABLE_PLACEHOLDER}\n\nRegards",
    )

    PricingService(db).set_override(
        q.line_items[0], component_code="base_price", amount=Decimal("70000")
    )
    db.commit()
    refresh_draft_figures(db, q)
    db.commit()

    # The send proceeds - a reviewer may legitimately state a negotiated
    # figure - but the discrepancy is named rather than passing silently.
    result = ApprovalService(db).approve_and_send(q, user_id=default_user.id)

    assert result.warnings, "a superseded prose price should have been reported"
    message = " ".join(result.warnings)
    assert "does not hold" in message
    # The reviewer is told which figure to check - the one in the wording.
    assert f"{rate_before:.2f}" in message.replace(",", "")


def test_a_clean_draft_sends_without_warnings(db, quoted_quotation, live_rules, default_user):
    """The check must not shout about an ordinary correct quotation."""
    q = _priced(db, quoted_quotation)
    _draft(db, q, f"Dear Sir,\n\n{TABLE_PLACEHOLDER}\n\nRegards")

    result = ApprovalService(db).approve_and_send(q, user_id=default_user.id)
    assert result.draft is not None
    assert result.warnings == []
