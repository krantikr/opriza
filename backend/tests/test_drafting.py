"""Draft generation and the guardrail that verifies it.

The rule "the model must not modify the price" is only worth anything if
something checks. These tests are that check's check.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from ai.config import LLMConfig
from ai.guards import find_unsupported_claims, money_fact, quantity_fact, verify_draft_facts
from ai.llm.openrouter import OpenRouterClient
from app.models import DraftStatus, QuotationDraft
from app.services.quotations.draft_context import build_draft_context, format_inr, format_quantity
from app.services.quotations.drafting import DraftingService

GOOD_BODY = """Dear Rajesh Kumar,

Thank you for your enquiry. We are pleased to offer the following:

1. IS 2062 E250 Plate 10 x 1500 x 6000 mm
   Quantity: 20 MT
   Rate: Rs 59,200.00 per MT
   Line total: Rs 11,84,000.00

Terms:
- Prices are valid for 3 days from the date of this quotation.
- GST extra as applicable.

Please confirm at your convenience.

Regards,
Sales Team
"""

ROUNDED_BODY = GOOD_BODY.replace("59,200.00", "59,000.00")


class ScriptedDrafter(OpenRouterClient):
    """Returns pre-written drafts instead of calling a model."""

    def __init__(self, bodies: list[str]) -> None:
        super().__init__(LLMConfig(api_key="test-key"))
        self.bodies = list(bodies)
        self.prompts: list[list[dict]] = []

    def _call(self, *, model, messages, response_format, max_tokens):  # type: ignore[override]
        self.prompts.append(messages)
        body = self.bodies.pop(0) if self.bodies else GOOD_BODY
        payload = json.dumps({"subject": "Re: Enquiry - IS 2062 E250 Plate 10mm", "body": body})
        return payload, {
            "prompt_tokens": 800,
            "completion_tokens": 200,
            "total_tokens": 1000,
            "generation_id": "gen-draft",
            "cost_usd": 0.001,
        }


# --- Formatting ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("59200"), "59,200.00"),
        (Decimal("1184000"), "11,84,000.00"),
        (Decimal("100"), "100.00"),
        (Decimal("12345678"), "1,23,45,678.00"),
    ],
)
def test_currency_uses_indian_digit_grouping(value, expected):
    assert format_inr(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"), [(Decimal("20.000"), "20"), (Decimal("6.096"), "6.096")]
)
def test_quantities_drop_trailing_zeros(value, expected):
    assert format_quantity(value) == expected


# --- The guardrail ---------------------------------------------------------


def test_a_rounded_price_is_caught():
    """'about 59,000' instead of 59,200 is a misstated price, not a paraphrase."""
    violations = verify_draft_facts(ROUNDED_BODY, [money_fact("Rate on line 1", Decimal("59200.00"))])

    assert len(violations) == 1
    assert "Rate on line 1" in violations[0]


@pytest.mark.parametrize(
    "rendering",
    ["Rs 59,200.00 per MT", "₹59,200 per MT", "INR 59200.00", "59,200/- per MT", "Rate: 59200"],
)
def test_formatting_variants_are_accepted(rendering):
    """The value must be right; how it is typeset is the model's business."""
    body = f"We offer 20 MT at {rendering}."
    assert verify_draft_facts(body, [money_fact("Rate", Decimal("59200.00"))]) == []


def test_a_dropped_line_total_is_caught():
    body = GOOD_BODY.replace("   Line total: Rs 11,84,000.00\n", "")
    violations = verify_draft_facts(body, [money_fact("Line total", Decimal("1184000.00"))])
    assert violations


def test_a_number_inside_a_longer_number_does_not_count():
    """A quantity of 20 must not be satisfied by '2026' in the date line."""
    body = "Thank you for your enquiry dated 12 August 2026. Rate is 59,200.00 per MT."
    violations = verify_draft_facts(body, [quantity_fact("Quantity", Decimal("20"))])
    assert violations


def test_an_empty_draft_is_rejected():
    assert verify_draft_facts("   ", [money_fact("Rate", Decimal("100"))])


@pytest.mark.parametrize(
    "phrase",
    ["Material is in stock", "ready for dispatch", "We offer a special discount", "price is negotiable"],
)
def test_unsupported_commitments_are_flagged(phrase):
    assert find_unsupported_claims(f"Dear Sir,\n\n{phrase}.\n\nRegards")


def test_a_plain_draft_raises_no_warnings():
    assert find_unsupported_claims(GOOD_BODY) == []


# --- Context assembly ------------------------------------------------------


def test_context_carries_every_figure_the_model_must_reproduce(db, priced_quotation):
    context = build_draft_context(priced_quotation)

    assert "59,200.00" in context.facts
    assert "11,84,000.00" in context.facts
    assert "20 MT" in context.facts
    assert "IS 2062 E250 Plate" in context.facts
    assert context.priced_line_count == 1
    assert {f.label for f in context.required_facts} == {
        "Quantity on line 1",
        "Rate on line 1",
        "Line total on line 1",
    }


def test_context_includes_configured_terms_not_invented_ones(db, priced_quotation):
    facts = build_draft_context(priced_quotation).facts
    assert "Prices are valid for 3 days" in facts
    assert "GST extra as applicable." in facts


def test_unpriced_lines_say_so_rather_than_guessing(db, priced_quotation):
    priced_quotation.line_items[0].pricing.recommended_price = None
    db.commit()

    context = build_draft_context(priced_quotation)

    assert "Rate: to be confirmed" in context.facts
    assert context.unpriced_line_count == 1


# --- The service -----------------------------------------------------------


def test_a_clean_draft_is_stored_as_version_one(db, priced_quotation):
    result = DraftingService(db, client=ScriptedDrafter([GOOD_BODY])).generate(priced_quotation)

    assert result.ok
    assert result.violations == []
    assert result.draft.version == 1
    assert result.draft.is_current is True
    assert result.draft.status is DraftStatus.GENERATED
    assert result.draft.subject.startswith("Re:")


def test_an_altered_price_triggers_one_regeneration(db, priced_quotation):
    """First attempt rounds the rate; the retry is told exactly what it broke."""
    client = ScriptedDrafter([ROUNDED_BODY, GOOD_BODY])

    result = DraftingService(db, client=client).generate(priced_quotation)

    assert result.regenerated is True
    assert result.violations == []
    assert "59,200.00" in result.draft.body
    # The retry prompt must name the specific figure that was altered.
    retry_prompt = client.prompts[-1][-1]["content"]
    assert "Rate on line 1" in retry_prompt


def test_a_draft_that_fails_twice_is_kept_but_flagged(db, priced_quotation):
    """Never silently sent, never silently discarded - the reviewer decides."""
    result = DraftingService(db, client=ScriptedDrafter([ROUNDED_BODY, ROUNDED_BODY])).generate(
        priced_quotation
    )

    assert result.ok is False
    assert result.violations
    assert result.draft is not None
    assert any("did not reproduce the calculated figures" in n for n in result.review_notes)


def test_regenerating_supersedes_rather_than_overwrites(db, priced_quotation):
    service = DraftingService(db, client=ScriptedDrafter([GOOD_BODY, GOOD_BODY]))
    first = service.generate(priced_quotation)
    second = service.generate(priced_quotation)

    db.refresh(first.draft)
    assert first.draft.is_current is False
    assert first.draft.status is DraftStatus.SUPERSEDED
    assert second.draft.version == 2
    assert second.draft.is_current is True
    assert db.query(QuotationDraft).count() == 2


def test_generation_is_recorded_in_telemetry_and_audit(db, priced_quotation):
    from app.models import AuditLog, LLMCall

    DraftingService(db, client=ScriptedDrafter([GOOD_BODY])).generate(priced_quotation)

    call = db.query(LLMCall).filter_by(task="draft").one()
    assert call.total_tokens == 1000
    assert call.quotation_request_id == priced_quotation.id

    entry = db.query(AuditLog).filter_by(entity_type="quotation_draft").one()
    assert entry.action == "GENERATED"
    assert entry.details["fact_violations"] == []
