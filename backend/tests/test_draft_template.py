"""The LLM writes the reply once; the figures follow the calculator for ever.

The model is called to understand what this customer asked and to word a reply
to it. The money was never its to author, so the text it produces is stored
with every figure held behind a placeholder. A later price change - terms
supplied, a component overridden, stock re-costed - re-renders the body in
code: no second generation, no wording lost, and no figure reaching a customer
by a route nothing verifies.
"""

from __future__ import annotations

import re
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
from app.services.quotations.approval import ApprovalService
from app.services.quotations.draft_figures import (
    refresh_draft_figures,
    stale_prices_in_draft,
)
from app.services.quotations.table import (
    TABLE_PLACEHOLDER,
    build_rows,
    format_inr,
    splice_text,
    totals,
)
from app.services.quotations.templates import render_quotation_body, templatise


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


def _rate(quotation) -> Decimal:
    return Decimal(str(quotation.line_items[0].pricing.quote_rate))


def _llm_style_draft(db, quotation) -> QuotationDraft:
    """A draft as the model writes them: the rate stated in prose *and* a table.

    The prompt tells it not to restate figures in prose. Models do it anyway,
    which is exactly the case this design has to survive.
    """
    rate = _rate(quotation)
    body = splice_text(
        f"Dear Sir,\n\nThank you for your enquiry. We are pleased to offer at "
        f"INR {format_inr(rate)} per MT.\n\n{TABLE_PLACEHOLDER}\n\nRegards",
        build_rows(quotation),
    )
    draft = QuotationDraft(
        quotation_request_id=quotation.id, version=1, is_current=True,
        subject="Re: Enquiry", body=body,
        body_template=templatise(body, quotation),
        status=DraftStatus.GENERATED, generated_by="test/model",
    )
    db.add(draft)
    db.commit()
    return draft


# --- Templatising -----------------------------------------------------------


def test_a_figure_the_model_echoed_is_put_behind_a_placeholder(db, quoted_quotation, live_rules):
    q = _priced(db, quoted_quotation)
    rate = _rate(q)

    out = templatise(f"We offer at INR {format_inr(rate)} per MT.", q)

    assert format_inr(rate) not in out
    assert "{{line_1_rate}}" in out


def test_the_prose_itself_is_untouched(db, quoted_quotation, live_rules):
    q = _priced(db, quoted_quotation)
    out = templatise("Thank you for your enquiry. Happy to help.", q)
    assert out == "Thank you for your enquiry. Happy to help."


def test_a_figure_the_model_altered_is_left_alone(db, quoted_quotation, live_rules):
    """Rewriting a wrong number into a right-looking placeholder would hide it."""
    q = _priced(db, quoted_quotation)
    out = templatise("We offer at INR 1.00 per MT.", q)
    assert "1.00" in out
    assert "{{" not in out


def test_a_total_is_not_mangled_by_a_rate_that_shares_its_digits(db, quoted_quotation, live_rules):
    """Longest-first substitution: 12,20,000.00 must not be eaten by 20,000.00."""
    q = _priced(db, quoted_quotation)
    _, total = totals(build_rows(q))
    if total is None:
        pytest.skip("nothing priced")

    out = templatise(f"Total {format_inr(total)}.", q)

    # On a single-line quotation the order total and that line's amount are
    # the same number, so either placeholder is correct - both render to the
    # same figure. What matters is that the whole figure was replaced and no
    # stranded digits are left behind by a partial match.
    assert "{{" in out
    stripped = re.sub(r"\{\{[a-z0-9_]+\}\}", "", out)
    assert not any(ch.isdigit() for ch in stripped)


# --- The behaviour that was asked for --------------------------------------


def test_a_price_change_updates_the_prose_without_calling_the_model(db, quoted_quotation, live_rules):
    """The whole point: one LLM call, then figures follow the calculator."""
    q = _priced(db, quoted_quotation)
    draft = _llm_style_draft(db, q)
    old_rate = _rate(q)
    assert format_inr(old_rate) in draft.body

    PricingService(db).set_override(
        q.line_items[0], component_code="base_price", amount=Decimal("70000")
    )
    db.commit()
    refresh_draft_figures(db, q)
    db.commit()

    db.expire_all()
    fresh = db.get(type(q), q.id)
    body = db.get(QuotationDraft, draft.id).body
    new_rate = _rate(fresh)

    assert new_rate != old_rate, "the override should have moved the rate"
    # The sentence follows the calculator, not just the table.
    assert format_inr(new_rate) in body
    assert format_inr(old_rate) not in body
    # And the prose survives.
    assert "Thank you for your enquiry" in body


def test_no_stale_price_remains_after_a_change(db, quoted_quotation, live_rules):
    """The check that used to fire on exactly this flow now finds nothing."""
    q = _priced(db, quoted_quotation)
    draft = _llm_style_draft(db, q)

    PricingService(db).set_override(
        q.line_items[0], component_code="base_price", amount=Decimal("70000")
    )
    db.commit()
    refresh_draft_figures(db, q)
    db.commit()

    db.expire_all()
    fresh = db.get(type(q), q.id)
    assert stale_prices_in_draft(fresh, db.get(QuotationDraft, draft.id).body) == []


def test_supplying_terms_updates_the_whole_reply(db, client, quoted_quotation, live_rules):
    """The reported flow, end to end, through the real endpoint."""
    q = quoted_quotation
    q.delivery_location = None
    q.payment_terms = None
    db.commit()
    _priced(db, q)
    draft = _llm_style_draft(db, q)
    before = _rate(q)

    response = client.put(
        f"/api/v1/quotations/{q.id}/details",
        json={"delivery_location": "Patna", "payment_terms": "30 days"},
    )
    assert response.status_code == 200

    db.expire_all()
    fresh = db.get(type(q), q.id)
    body = db.get(QuotationDraft, draft.id).body
    after = _rate(fresh)

    if after != before:
        assert format_inr(after) in body
        assert format_inr(before) not in body


# --- What must not be trampled ---------------------------------------------


def test_a_reviewers_wording_survives_a_later_price_change(db, quoted_quotation, live_rules, default_user):
    q = _priced(db, quoted_quotation)
    _llm_style_draft(db, q)

    edited = (
        f"Dear Mr Kumar,\n\nAs discussed on the phone, our rate is "
        f"INR {format_inr(_rate(q))} per MT.\n\n{TABLE_PLACEHOLDER}\n\n"
        f"Please confirm by Friday.\n\nRegards"
    )
    ApprovalService(db).edit_draft(
        q, subject="Re: Enquiry", body=splice_text(edited, build_rows(q)),
        user_id=default_user.id,
    )
    db.commit()

    PricingService(db).set_override(
        q.line_items[0], component_code="base_price", amount=Decimal("70000")
    )
    db.commit()
    refresh_draft_figures(db, q)
    db.commit()

    db.expire_all()
    fresh = db.get(type(q), q.id)
    body = fresh.current_draft.body

    # Their words, kept.
    assert "As discussed on the phone" in body
    assert "Please confirm by Friday." in body
    # Their figure, updated.
    assert format_inr(_rate(fresh)) in body


def test_a_draft_without_a_template_still_gets_its_table_updated(db, quoted_quotation, live_rules):
    """Drafts written before this existed must keep working."""
    q = _priced(db, quoted_quotation)
    body = splice_text(f"Dear Sir,\n\n{TABLE_PLACEHOLDER}\n\nRegards", build_rows(q))
    draft = QuotationDraft(
        quotation_request_id=q.id, version=1, is_current=True,
        subject="Re:", body=body, body_template=None,
        status=DraftStatus.GENERATED, generated_by="old",
    )
    db.add(draft)
    db.commit()

    PricingService(db).set_override(
        q.line_items[0], component_code="base_price", amount=Decimal("70000")
    )
    db.commit()
    refresh_draft_figures(db, q)
    db.commit()

    db.expire_all()
    fresh = db.get(type(q), q.id)
    assert format_inr(_rate(fresh)) in db.get(QuotationDraft, draft.id).body


def test_a_sent_draft_is_never_re_rendered(db, quoted_quotation, live_rules):
    q = _priced(db, quoted_quotation)
    draft = _llm_style_draft(db, q)
    draft.status = DraftStatus.APPROVED
    db.commit()
    before = draft.body

    PricingService(db).set_override(
        q.line_items[0], component_code="base_price", amount=Decimal("70000")
    )
    db.commit()

    assert refresh_draft_figures(db, q) is None
    assert db.get(QuotationDraft, draft.id).body == before
