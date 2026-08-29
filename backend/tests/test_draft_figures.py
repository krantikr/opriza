"""The drafted reply must show the figures the calculator currently holds.

The case these pin is the ordinary one, not an edge: an enquiry that arrives
without a delivery location or payment terms cannot be priced, so its draft
goes out with a blank Rate column. Supplying those terms re-prices every line -
and used to leave the draft saying exactly what it said before.
"""

from decimal import Decimal

import pytest

from app.models import (
    DraftStatus,
    PricingComponentKind,
    PricingRule,
    PricingRuleSet,
    QuotationDraft,
)
from app.services.pricing.service import PricingService
from app.services.quotations.draft_figures import refresh_draft_figures
from app.services.quotations.table import (
    TABLE_PLACEHOLDER,
    build_rows,
    render_text,
    retable_text,
    splice_text,
)


@pytest.fixture()
def live_rules(db) -> PricingRuleSet:
    """A published rule set, so lines can actually reach a quoted rate."""

    def rule(code, kind, priority, config=None):
        return PricingRule(
            code=code,
            label=code,
            kind=kind,
            priority=priority,
            is_active=True,
            config=config or {},
            conditions=None,
        )

    rs = PricingRuleSet(version=1, label="Live", is_active=True)
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
def unpriceable(db, quoted_quotation):
    """The screenshot's situation: no terms stated, no cost basis on the lot."""
    q = quoted_quotation
    q.delivery_location = None
    q.payment_terms = None
    q.required_delivery_date = None
    lot = q.line_items[0].matched_stock_item
    lot.landed_cost_per_kg = None
    lot.purchase_rate_per_kg = None
    q.line_items[0].stock_availability.suggested_rate = None
    db.commit()
    return q


def _store_draft(db, quotation, body: str) -> QuotationDraft:
    draft = QuotationDraft(
        quotation_request_id=quotation.id,
        version=1,
        is_current=True,
        subject="Re: Enquiry",
        body=body,
        status=DraftStatus.GENERATED,
        generated_by="test",
    )
    db.add(draft)
    db.commit()
    return draft


def _draft_with_current_table(db, quotation) -> QuotationDraft:
    body = splice_text(
        f"Dear Sir,\n\n{TABLE_PLACEHOLDER}\n\nRegards", build_rows(quotation)
    )
    return _store_draft(db, quotation, body)


# --- retable_text, on its own ----------------------------------------------


def test_a_spliced_table_is_replaced_where_it_stands(db, quoted_quotation, live_rules):
    q = quoted_quotation
    body = splice_text(f"Dear Sir,\n\n{TABLE_PLACEHOLDER}\n\nRegards", build_rows(q))

    for item in q.line_items:
        PricingService(db).price_line(item, quotation=q)
    db.commit()

    out = retable_text(body, build_rows(q))
    assert render_text(build_rows(q)) in out
    # The prose either side survives untouched - that is the whole reason this
    # exists rather than a regeneration.
    assert out.startswith("Dear Sir,")
    assert out.rstrip().endswith("Regards")


def test_a_body_that_never_had_a_table_still_gets_one(db, quoted_quotation):
    out = retable_text("Dear Sir,\n\nRegards", build_rows(quoted_quotation))
    assert render_text(build_rows(quoted_quotation)) in out


def test_a_placeholder_still_present_is_spliced_normally(db, quoted_quotation):
    out = retable_text(
        f"Dear Sir,\n\n{TABLE_PLACEHOLDER}\n\nRegards", build_rows(quoted_quotation)
    )
    assert TABLE_PLACEHOLDER not in out
    assert render_text(build_rows(quoted_quotation)) in out


def test_replacing_twice_does_not_stack_tables(db, quoted_quotation):
    rows = build_rows(quoted_quotation)
    once = retable_text(f"Dear Sir,\n\n{TABLE_PLACEHOLDER}\n\nRegards", rows)
    twice = retable_text(once, rows)
    assert once == twice
    assert twice.count("Sr  Description") == 1


# --- The reported flow, end to end -----------------------------------------


def test_supplying_terms_puts_the_rate_into_the_drafted_reply(
    db, client, unpriceable, live_rules
):
    q = unpriceable
    for item in q.line_items:
        PricingService(db).price_line(item, quotation=q)
    db.commit()

    draft = _draft_with_current_table(db, q)
    assert "Rate (INR/MT)" not in draft.body  # the reported symptom

    # The lot gains a cost and the trader states the terms.
    q.line_items[0].matched_stock_item.landed_cost_per_kg = 56.5
    db.commit()

    response = client.put(
        f"/api/v1/quotations/{q.id}/details",
        json={
            "delivery_location": "Patna",
            "required_delivery_date": "2026-09-15",
            "payment_terms": "30 days",
        },
    )
    assert response.status_code == 200
    assert "drafted reply" in response.json()["detail"]

    db.expire_all()
    body = db.get(QuotationDraft, draft.id).body
    rate = db.get(type(q), q.id).line_items[0].pricing.quote_rate
    assert rate is not None
    assert "Rate (INR/MT)" in body
    assert "Amount (INR)" in body
    # The document and the calculator agree on the actual number.
    assert render_text(build_rows(db.get(type(q), q.id))) in body


def test_the_pdf_and_the_draft_quote_the_same_figures(db, client, unpriceable, live_rules):
    """The two surfaces are built by different code; they must not diverge."""
    q = unpriceable
    for item in q.line_items:
        PricingService(db).price_line(item, quotation=q)
    db.commit()
    draft = _draft_with_current_table(db, q)

    q.line_items[0].matched_stock_item.landed_cost_per_kg = 56.5
    db.commit()
    client.put(
        f"/api/v1/quotations/{q.id}/details",
        json={"delivery_location": "Patna", "payment_terms": "30 days"},
    )

    db.expire_all()
    fresh = db.get(type(q), q.id)
    from app.services.quotations import pdf as quotation_pdf

    html = quotation_pdf.build_html(fresh, build_rows(fresh))
    rate = fresh.line_items[0].pricing.quote_rate
    from app.services.quotations.table import format_inr

    printed = format_inr(rate)
    assert printed in html
    assert printed in db.get(QuotationDraft, draft.id).body


def test_an_override_flows_into_the_drafted_reply(db, client, quoted_quotation, live_rules):
    q = quoted_quotation
    for item in q.line_items:
        PricingService(db).price_line(item, quotation=q)
    db.commit()
    draft = _draft_with_current_table(db, q)

    response = client.post(
        f"/api/v1/quotations/{q.id}/lines/{q.line_items[0].id}/pricing/override",
        json={"component_code": "transportation", "amount": "9999", "reason": "actual freight"},
    )
    assert response.status_code == 200

    db.expire_all()
    fresh = db.get(type(q), q.id)
    assert render_text(build_rows(fresh)) in db.get(QuotationDraft, draft.id).body


# --- What must not be rewritten --------------------------------------------


def test_a_sent_draft_is_never_rewritten(db, quoted_quotation, live_rules):
    """An approved draft is the record of what was promised."""
    q = quoted_quotation
    draft = _draft_with_current_table(db, q)
    draft.status = DraftStatus.APPROVED
    db.commit()
    before = draft.body

    for item in q.line_items:
        PricingService(db).price_line(item, quotation=q)
    db.commit()

    assert refresh_draft_figures(db, q) is None
    assert db.get(QuotationDraft, draft.id).body == before


def test_no_change_reports_nothing_to_do(db, quoted_quotation, live_rules):
    q = quoted_quotation
    for item in q.line_items:
        PricingService(db).price_line(item, quotation=q)
    db.commit()
    _draft_with_current_table(db, q)
    # Nothing moved since the draft was written.
    assert refresh_draft_figures(db, q) is None


def test_a_reviewers_edits_to_the_prose_survive(db, client, unpriceable, live_rules):
    q = unpriceable
    for item in q.line_items:
        PricingService(db).price_line(item, quotation=q)
    db.commit()

    body = splice_text(
        f"Dear Mr Kumar,\n\nAs discussed on the phone this morning.\n\n"
        f"{TABLE_PLACEHOLDER}\n\nPlease confirm by Friday.\n\nRegards",
        build_rows(q),
    )
    draft = _store_draft(db, q, body)

    q.line_items[0].matched_stock_item.landed_cost_per_kg = 56.5
    db.commit()
    client.put(
        f"/api/v1/quotations/{q.id}/details",
        json={"delivery_location": "Patna", "payment_terms": "30 days"},
    )

    db.expire_all()
    updated = db.get(QuotationDraft, draft.id).body
    assert "As discussed on the phone this morning." in updated
    assert "Please confirm by Friday." in updated
    assert "Rate (INR/MT)" in updated
