"""The end-to-end quotation workflow.

The language model is replaced by a stub returning fixed structured values. The
transport and the fallback ladder are covered elsewhere; what is under test here
is the routing - which branch an email takes, what state it lands in, and what
the system refuses to do on the way.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ai.llm.base import LLMClient, LLMError
from ai.schemas import (
    AIOutcome,
    ClassificationResult,
    DraftEmail,
    EmailCategory,
    ExtractedEnquiry,
    LLMUsage,
    QuantityUnit,
    SteelLineItem,
)
from app.models import (
    ConfidenceLevel,
    Email,
    EmailSourceType,
    MatchStatus,
    ProcessingStatus,
    QuotationRequest,
    QuotationStatus,
)
from app.workflows.quotation import QuotationWorkflow, process_pending_emails


class FakeLLM(LLMClient):
    """Returns scripted structured values, keyed by task.

    An exhausted queue repeats its last value. Several tests here exercise
    pricing paths whose figures differ from the fixed draft body, which makes
    the drafting guardrail correctly ask for a regeneration; repeating keeps
    those tests about what they are testing. Draft content itself is covered in
    `test_drafting.py`.
    """

    def __init__(self, **by_task: list[object]) -> None:
        self.by_task = {task: list(values) for task, values in by_task.items()}
        self.last: dict[str, object] = {}
        self.calls: list[str] = []

    def structured(self, *, task, messages, schema, model=None, max_tokens=None):
        self.calls.append(task)
        queue = self.by_task.get(task) or []
        if queue:
            value = queue.pop(0)
            self.last[task] = value
        elif task in self.last:
            value = self.last[task]
        else:
            raise AssertionError(f"no scripted response for task {task!r}")
        if isinstance(value, Exception):
            raise value
        return AIOutcome(
            value=value,
            usage=LLMUsage(model="fake/model", task=task, total_tokens=100, latency_ms=5),
        )

    def complete(self, *, task, messages, model=None, max_tokens=None):  # pragma: no cover
        raise NotImplementedError


def line(**overrides) -> SteelLineItem:
    base = {
        "raw_text": "IS 2062 E250 plate, 10mm x 1500 x 6000, quantity 20 MT",
        "product_type": "Plate",
        "grade": "E250",
        "standard": "IS 2062",
        "thickness_mm": 10.0,
        "width_mm": 1500.0,
        "length_mm": 6000.0,
        "diameter_mm": None,
        "quantity": 20.0,
        "quantity_unit": QuantityUnit.MT,
        "remarks": None,
    }
    return SteelLineItem(**{**base, **overrides})


def enquiry(**overrides) -> ExtractedEnquiry:
    base = {
        "customer_name": "Rajesh Kumar",
        "customer_company": "ABC Industries Pvt Ltd",
        "delivery_location": "Patna",
        "required_delivery_date": None,
        "payment_terms": None,
        "additional_requirements": [],
        "line_items": [line()],
        "missing_information": [],
    }
    return ExtractedEnquiry(**{**base, **overrides})


def classified(category=EmailCategory.QUOTATION_REQUEST, confidence=0.96) -> ClassificationResult:
    return ClassificationResult(category=category, confidence=confidence, reason="Asks for a rate.")


DRAFT = DraftEmail(
    subject="Re: Enquiry - IS 2062 E250 Plate 10mm",
    body=(
        "Dear Rajesh Kumar,\n\nThank you for your enquiry.\n\n"
        "1. IS 2062 E250 Plate 10 x 1500 x 6000 mm\n"
        "   Quantity: 20 MT\n"
        "   Available: 28.26 MT\n"
        "   Rate: Rs 61,000.00 per MT\n"
        "   Line total: Rs 12,20,000.00\n\n"
        "- Prices are valid for 3 days from the date of this quotation.\n\n"
        "Regards,\nSales Team\n"
    ),
)


@pytest.fixture()
def inbound(db, customer):
    counter = itertools.count(1)

    def _make(subject="Enquiry - plate", body="Please quote 20 MT of 10mm plate.", sender=None):
        email = Email(
            message_id=f"local:{subject[:20]}-{next(counter)}",
            thread_id="local-thread:1",
            source=EmailSourceType.LOCAL,
            sender_email=sender if sender is not None else customer.email,
            sender_name="Rajesh Kumar",
            subject=subject,
            body_text=body,
            received_at=datetime.now(UTC),
            processing_status=ProcessingStatus.PENDING,
        )
        db.add(email)
        db.commit()
        return email

    return _make


# --- The happy path --------------------------------------------------------


def test_quotation_email_runs_the_full_pipeline(db, plate, customer, inbound):
    email = inbound()
    llm = FakeLLM(classify=[classified()], extract=[enquiry()], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)

    assert result.outcome == "READY_FOR_REVIEW"
    assert llm.calls == ["classify", "extract", "draft"]

    quotation = db.get(QuotationRequest, result.quotation_id)
    # Prefixed with the desk's own initials ("Test Desk"), and numbered from
    # one within that desk rather than from a shared row id.
    assert quotation.quotation_number == "TE-000001"
    assert quotation.status is QuotationStatus.READY_FOR_REVIEW
    assert quotation.confidence is ConfidenceLevel.HIGH
    assert quotation.customer_id == customer.id

    item = quotation.line_items[0]
    assert item.match_status is MatchStatus.MATCH_FOUND
    assert item.matched_stock_item_id == plate.id
    assert item.stock_availability.suggested_rate == pytest.approx(Decimal("61000.00"))
    assert item.stock_availability.explanation

    assert quotation.current_draft is not None
    assert "61,000.00" in quotation.current_draft.body

    db.refresh(email)
    assert email.processing_status is ProcessingStatus.PROCESSED
    assert email.category is EmailCategory.QUOTATION_REQUEST
    assert email.processing_ms >= 0


def test_stock_evidence_is_persisted_for_later_explanation(db, plate, customer, inbound):
    """Section 22: the check must survive as evidence, not as a bare number.

    Every step records the reason it contributed, so "why did the system say
    this?" stays answerable from the stored row alone, without re-running the
    check against stock that may since have moved.
    """
    email = inbound()
    llm = FakeLLM(classify=[classified()], extract=[enquiry()], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)
    availability = db.get(QuotationRequest, result.quotation_id).line_items[0].stock_availability

    assert availability.lot_count == 1
    assert availability.available_qty_mt == pytest.approx(Decimal("28.260"))
    assert availability.rules_version == "1.0"

    steps = [step["id"] for step in availability.breakdown]
    assert steps[0] == "stock_lookup"
    assert "suggested_rate" in steps

    # 56.5/kg landed -> 56,500.00/MT, +8% markup -> 61,020.00, rounded to 61,000.00
    assert availability.suggested_rate == pytest.approx(Decimal("61000.00"))
    assert "landed cost" in availability.explanation
    assert "not an approved price" in availability.explanation


# --- Branches that must not produce a quotation ----------------------------


@pytest.mark.parametrize(
    "category",
    [
        EmailCategory.PRICE_NEGOTIATION,
        EmailCategory.ORDER,
        EmailCategory.DELIVERY_QUERY,
        EmailCategory.PAYMENT_QUERY,
        EmailCategory.SPAM,
    ],
)
def test_non_quotation_email_is_recorded_but_not_answered(db, inbound, category):
    email = inbound(subject=f"{category.value} message")
    llm = FakeLLM(classify=[classified(category, 0.93)])

    result = QuotationWorkflow(db, client=llm).run(email.id)

    assert result.outcome == "SKIPPED"
    assert result.quotation_id is None
    assert llm.calls == ["classify"]  # no extraction, no drafting, no spend

    db.refresh(email)
    assert email.processing_status is ProcessingStatus.SKIPPED
    assert email.category is category


def test_extraction_failure_leaves_the_email_visible(db, inbound):
    email = inbound()
    llm = FakeLLM(classify=[classified()], extract=[LLMError("model refused")])

    result = QuotationWorkflow(db, client=llm).run(email.id)

    assert result.outcome == "FAILED"
    assert result.quotation_id is None

    db.refresh(email)
    assert email.processing_status is ProcessingStatus.FAILED
    assert "model refused" in email.error_message


def test_classification_failure_is_recorded_as_failed(db, inbound):
    email = inbound()
    llm = FakeLLM(classify=[LLMError("gateway timeout")])

    result = QuotationWorkflow(db, client=llm).run(email.id)

    assert result.outcome == "FAILED"
    db.refresh(email)
    assert email.processing_status is ProcessingStatus.FAILED


# --- Incomplete and ambiguous enquiries ------------------------------------


def test_missing_quantity_is_flagged_rather_than_invented(
    db, plate, customer, inbound
):
    email = inbound()
    incomplete = enquiry(
        line_items=[line(quantity=None, quantity_unit=QuantityUnit.UNKNOWN)],
        missing_information=["quantity not stated"],
    )
    llm = FakeLLM(classify=[classified()], extract=[incomplete], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)
    quotation = db.get(QuotationRequest, result.quotation_id)

    assert quotation.status is QuotationStatus.NEEDS_INFORMATION
    assert quotation.missing_information == ["quantity not stated"]

    item = quotation.line_items[0]
    assert item.quantity is None
    assert item.quantity_mt is None
    # Availability is still reported; only sufficiency is left unanswered,
    # because there is no requested quantity to judge it against.
    assert item.stock_availability.available_qty_mt is not None
    assert item.stock_availability.sufficient is None
    # A rate is still offered - that is what the reviewer needs to finish by hand.
    assert item.stock_availability.suggested_rate is not None


def test_ambiguous_product_is_never_priced(db, plate, wide_plate, customer, inbound):
    """Two plates fit '10mm plate'. The system must not choose one and price it.

    A draft is still written: the customer asked for material and is owed a
    reply. What must not happen is a *price* being invented for a spec the
    system could not resolve, so the rate stays empty and the ambiguity is
    raised in the review notes.
    """
    email = inbound()
    ambiguous = enquiry(line_items=[line(width_mm=None, length_mm=None)])
    llm = FakeLLM(classify=[classified()], extract=[ambiguous], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)
    quotation = db.get(QuotationRequest, result.quotation_id)
    item = quotation.line_items[0]

    assert item.match_status is MatchStatus.MULTIPLE_MATCHES
    assert item.matched_stock_item_id is None
    assert item.stock_availability.suggested_rate is None
    assert len(item.match_candidates) >= 2
    assert "More than one stock spec" in quotation.review_notes


def test_unstocked_material_is_never_priced(db, plate, customer, inbound):
    email = inbound()
    unknown = enquiry(
        line_items=[
            line(
                product_type="Sheet",
                grade="SS 304",
                thickness_mm=3.0,
                width_mm=None,
                length_mm=None,
            )
        ]
    )
    llm = FakeLLM(classify=[classified()], extract=[unknown], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)
    item = db.get(QuotationRequest, result.quotation_id).line_items[0]

    assert item.match_status is MatchStatus.NO_MATCH
    # The guarantee is about the *price*, not the reply: material the desk does
    # not hold still earns an answer, with the rate left blank.
    assert item.stock_availability.suggested_rate is None


def test_unmatched_material_still_gets_a_reply_with_a_blank_rate(db, plate, customer, inbound):
    """The case a sales desk cannot afford to get wrong.

    An enquiry for material the desk does not hold is the commonest real one.
    It must still produce a reply listing exactly what was asked for, with the
    rate and amount blank - not silence.
    """
    from app.services.quotations.table import build_rows, totals

    email = inbound()
    unknown = enquiry(
        line_items=[line(product_type="Sheet", grade="SS 304", thickness_mm=3.0,
                         width_mm=None, length_mm=None)]
    )
    llm = FakeLLM(classify=[classified()], extract=[unknown], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)
    quotation = db.get(QuotationRequest, result.quotation_id)

    assert quotation.current_draft is not None
    assert "draft" in llm.calls

    rows = build_rows(quotation)
    assert len(rows) == 1
    # The customer's own request is listed back to them...
    assert rows[0].grade == "SS 304"
    # ...with no price invented for it.
    assert rows[0].rate is None
    assert rows[0].amount is None
    _, total_amount = totals(rows)
    assert total_amount is None


def test_unknown_sender_is_added_as_an_unverified_customer(db, plate, inbound):
    """A new sender gets a record, but not the standing of a known account."""
    from app.models import Customer

    before = db.query(Customer).count()
    email = inbound(sender="imran@newhorizonfab.co.in")
    first_contact = enquiry(
        customer_name="Imran Sheikh", customer_company="New Horizon Fabrication"
    )
    llm = FakeLLM(classify=[classified()], extract=[first_contact], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)
    quotation = db.get(QuotationRequest, result.quotation_id)

    assert db.query(Customer).count() == before + 1
    created = db.get(Customer, quotation.customer_id)
    assert created.email == "imran@newhorizonfab.co.in"
    assert created.name == "Imran Sheikh"
    assert created.company == "New Horizon Fabrication"
    assert created.is_verified is False
    # Nothing was invented: tier and terms stay at their defaults.
    assert created.payment_terms is None
    assert quotation.customer_name_raw == "Imran Sheikh"
    # An unconfirmed record must not buy the confidence of an established one.
    assert quotation.confidence is not ConfidenceLevel.HIGH


def test_a_repeat_enquiry_reuses_the_auto_created_customer(db, plate, inbound):
    """The second email from a new sender must not create a duplicate."""
    from app.models import Customer

    # `inbound` seeds the known customer, so the new sender is the *second*
    # record; the point of the test is that the repeat does not make a third.
    before = db.query(Customer).count()
    for _ in range(2):
        email = inbound(sender="imran@newhorizonfab.co.in")
        llm = FakeLLM(
            classify=[classified()],
            extract=[
                enquiry(
                    customer_name="Imran Sheikh",
                    # A different company, or `find_customer` resolves this to
                    # the seeded account by name and never creates a record.
                    customer_company="New Horizon Fabrication",
                )
            ],
            draft=[DRAFT],
        )
        QuotationWorkflow(db, client=llm).run(email.id)

    assert db.query(Customer).count() == before + 1


def test_a_known_company_resolves_even_from_a_new_address(db, plate, customer, inbound):
    """A colleague writing from a different mailbox is still the same account."""
    email = inbound(sender="purchase2@abcindustries.co.in")
    llm = FakeLLM(classify=[classified()], extract=[enquiry()], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)

    assert db.get(QuotationRequest, result.quotation_id).customer_id == customer.id


# --- Multi-item enquiries --------------------------------------------------


def test_multi_item_enquiry_prices_each_line(db, plate, wide_plate, customer, inbound):
    email = inbound()
    multi = enquiry(
        line_items=[
            line(),
            line(
                raw_text="IS 2062 E250 Plate 10mm x 2000 x 6300 - 30 MT",
                width_mm=2000.0,
                length_mm=6300.0,
                quantity=30.0,
            ),
        ]
    )
    llm = FakeLLM(classify=[classified()], extract=[multi], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)
    quotation = db.get(QuotationRequest, result.quotation_id)

    assert len(quotation.line_items) == 2
    assert [i.line_no for i in quotation.line_items] == [1, 2]
    assert quotation.line_items[0].matched_stock_item_id == plate.id
    assert quotation.line_items[1].matched_stock_item_id == wide_plate.id
    assert all(i.stock_availability.suggested_rate is not None for i in quotation.line_items)


def test_quotation_confidence_is_the_weakest_line(db, plate, customer, inbound):
    """One shaky line drags the whole quotation down; it is one document."""
    email = inbound()
    mixed = enquiry(
        line_items=[
            line(),
            line(raw_text="SS 304 sheet 3mm - 5 MT", product_type="Sheet", grade="SS 304"),
        ]
    )
    llm = FakeLLM(classify=[classified()], extract=[mixed], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)
    quotation = db.get(QuotationRequest, result.quotation_id)

    assert quotation.confidence is ConfidenceLevel.LOW


# --- Unit conversion through the pipeline ----------------------------------


def test_a_piece_quantity_is_converted_before_pricing(db, plate, customer, inbound):
    """40 plates at 706.5 kg each = 28.26 MT, which lands in a different slab."""
    email = inbound()
    in_pieces = enquiry(
        line_items=[line(quantity=40.0, quantity_unit=QuantityUnit.PCS, raw_text="40 plates")]
    )
    llm = FakeLLM(classify=[classified()], extract=[in_pieces], draft=[DRAFT])

    result = QuotationWorkflow(db, client=llm).run(email.id)
    item = db.get(QuotationRequest, result.quotation_id).line_items[0]

    assert float(item.quantity_mt) == pytest.approx(28.26, abs=0.01)
    assert "706.500 kg/pc" in item.conversion_basis
    assert item.stock_availability.suggested_rate is not None


# --- Batch processing ------------------------------------------------------


def test_batch_processing_handles_a_mixed_inbox(db, plate, customer, inbound):
    inbound(subject="Enquiry one")
    inbound(subject="Order confirmation")

    llm = FakeLLM(
        classify=[classified(), classified(EmailCategory.ORDER)],
        extract=[enquiry()],
        draft=[DRAFT],
    )

    results = process_pending_emails(db, client=llm)

    assert len(results) == 2
    assert {r.outcome for r in results} == {"READY_FOR_REVIEW", "SKIPPED"}
    assert db.query(QuotationRequest).count() == 1


def test_already_processed_emails_are_not_reprocessed(db, plate, customer, inbound):
    inbound(subject="Enquiry one")
    llm = FakeLLM(classify=[classified()], extract=[enquiry()], draft=[DRAFT])

    assert len(process_pending_emails(db, client=llm)) == 1
    assert process_pending_emails(db, client=llm) == []


# --- Matching a reply that is not in the same thread ------------------------


def test_a_quotation_reference_is_found_in_a_customers_words():
    """Customers answer a quotation by starting a fresh email that quotes the
    reference. It shares no mail thread, so the number is the only link."""
    from app.services.quotations.assembly import quotation_numbers_in

    assert quotation_numbers_in("Response to Quotation KK-000004") == ["KK-000004"]
    assert quotation_numbers_in("Re: al-000013 revised") == ["AL-000013"]
    assert quotation_numbers_in("Please quote for 20 MT plate") == []
    assert quotation_numbers_in(None) == []


def test_every_reference_in_a_message_is_found():
    """A customer consolidating two quotations mentions both."""
    from app.services.quotations.assembly import quotation_numbers_in

    found = quotation_numbers_in("Regarding KK-000001 and KK-000002, please revise")
    assert found == ["KK-000001", "KK-000002"]


def test_naming_the_reference_matches_more_widely_than_sharing_a_thread():
    """The two matchers carry different weight, deliberately.

    Quoting a number we wrote is strong evidence, so it matches a quotation a
    trader may have sent by hand while the record still says review. Merely
    sharing a mail thread is weak - a second enquiry on the same thread is a
    new enquiry, not a reply to something never sent.
    """
    from app.models import QuotationStatus
    from app.workflows.quotation import REPLIABLE_STATUSES, SENT_STATUSES

    assert QuotationStatus.NEEDS_INFORMATION in REPLIABLE_STATUSES
    assert QuotationStatus.NEEDS_INFORMATION not in SENT_STATUSES

    # Still being assembled: no reference exists for anybody to quote.
    assert QuotationStatus.NEW not in REPLIABLE_STATUSES
    assert QuotationStatus.PROCESSING not in REPLIABLE_STATUSES

    # Everything the thread matcher accepts, the reference matcher does too.
    assert set(SENT_STATUSES) <= set(REPLIABLE_STATUSES)


# ---------------------------------------------------------------------------
# Review notes
#
# A trader reported four "errors" on a quotation whose desk had pricing rules
# published and stock loaded. Two of the notes were stale snapshots, two were
# duplicated, and one was a bare "Line 1:". All three are fixed here.
# ---------------------------------------------------------------------------


def test_review_notes_never_repeat():
    """Re-processing appended to the previous run, so the same problem showed
    twice, then three times."""
    from app.workflows.quotation import _merge_notes

    merged = _merge_notes("Line 1: no stock", ["Line 1: no stock", "Line 2: no rate"])

    assert merged == "Line 1: no stock\nLine 2: no rate"


def test_a_note_with_no_reason_is_not_stored():
    """`f"Line {n}: {reason}"` with a blank reason stored a bare "Line 1:",
    which reads as a truncated error."""
    from app.workflows.quotation import _merge_notes

    assert _merge_notes(None, ["Line 1:", "   ", ""]) is None


def test_notes_are_capped_newest_first():
    """A reviewer facing thirty notes reads none of them, and the oldest are
    the least likely to still be true."""
    from app.workflows.quotation import MAX_REVIEW_NOTES, _merge_notes

    merged = _merge_notes(None, [f"note {i}" for i in range(30)])
    lines = (merged or "").splitlines()

    assert len(lines) == MAX_REVIEW_NOTES
    assert lines[-1] == "note 29"
