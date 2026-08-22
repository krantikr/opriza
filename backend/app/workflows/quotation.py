"""The enquiry workflow, orchestrated with LangGraph.

The graph is the *only* place the stages are sequenced. Each node is thin: it
calls a service that already knows how to do one job, records what happened, and
returns state. That keeps the interesting logic - matching, stock checking,
drafting - independently testable, and it is what makes the later move to a
supervisor with specialised agents (spec section 26) a rewiring rather than a
rewrite.

    classify ─┬─ not a quotation ──────────────────► unsupported
              └─ quotation ─► extract ─┬─ failed ──► failed
                                       └─ ok ─► assemble ─► match ─► check_stock ─┐
                                                                                  │
              ready for review ◄─── draft ◄─── something was checked ◄───────────┤
              needs information / review ◄────── nothing could be matched ◄──────┘

Two properties are deliberate:

* **The AI steps can fail without losing the enquiry.** A failed extraction
  marks the email FAILED and leaves it visible, rather than discarding it.
* **The stock check runs even when the enquiry is incomplete.** A missing
  quantity still permits availability to be reported, which is exactly what the
  reviewer needs in order to finish the job by hand.
"""

from __future__ import annotations

import operator
import time
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai.classifier import classify_email
from ai.extractor import extract_requirement
from ai.llm.base import LLMClient, LLMError
from ai.reply_classifier import classify_reply
from ai.schemas import EmailCategory, ReplyIntent
from app.core.db import utcnow
from app.core.logging import get_logger
from app.core.rules import BusinessRules, get_rules
from app.models import (
    ConfidenceLevel,
    Email,
    MatchStatus,
    ProcessingStatus,
    QuotationRequest,
    QuotationStatus,
    StockAvailability,
)
from app.services import audit, telemetry
from app.services.dates import parse_promised_date
from app.services.notifications.service import NotificationService
from app.services.pricing.service import PricingService
from app.services.products.matcher import ProductMatcher
from app.services.products.weights import Dimensions, convert_to_mt
from app.services.quotations.assembly import create_quotation, quotation_numbers_in
from app.services.quotations.draft_context import build_draft_context
from app.services.quotations.drafting import DraftingService
from app.services.stock.availability import StockAvailabilityService

# A quotation on this thread already went out, so a new inbound message on
# the same thread is a reply to it, not a fresh enquiry.
#: Categories that are not quotation requests but still need somebody. Setting
#: `awaiting_us` is what puts them in a pending tab rather than leaving them
#: recorded and unseen.
NEEDS_A_PERSON = (
    EmailCategory.DELIVERY_QUERY,
    EmailCategory.PAYMENT_QUERY,
    EmailCategory.COMPLAINT,
    EmailCategory.ORDER,
    EmailCategory.PRICE_NEGOTIATION,
)

#: Quotations this system knows reached the customer. Used for *thread*
#: matching, where sharing a conversation is weak evidence on its own: a
#: second enquiry on the same thread is a new enquiry, not a reply to
#: something never sent.
SENT_STATUSES = (
    QuotationStatus.SENT,
    QuotationStatus.CUSTOMER_ACCEPTED,
    QuotationStatus.CUSTOMER_DECLINED,
)

#: Quotations a message may be a reply to when it *names the reference*.
#:
#: Wider, because quoting a number is strong evidence on its own - the number
#: appears nowhere unless we wrote it. A trader may have sent a quotation by
#: hand or read it out on the phone while the record still says review, and a
#: reply arriving before our own record catches up is exactly the message a
#: desk must not lose. `NEW` and `PROCESSING` are excluded: a quotation still
#: being assembled has no reference anybody could quote.
REPLIABLE_STATUSES = (
    QuotationStatus.NEEDS_INFORMATION,
    QuotationStatus.READY_FOR_REVIEW,
    QuotationStatus.EDITED,
    QuotationStatus.APPROVED,
    QuotationStatus.SENT,
    QuotationStatus.CUSTOMER_ACCEPTED,
    QuotationStatus.CUSTOMER_DECLINED,
)

logger = get_logger(__name__)

#: A reviewer facing thirty notes reads none of them, and the older ones are
#: the least likely to still be true.
MAX_REVIEW_NOTES = 8

CONFIDENCE_ORDER = {ConfidenceLevel.LOW: 0, ConfidenceLevel.MEDIUM: 1, ConfidenceLevel.HIGH: 2}


class WorkflowState(TypedDict, total=False):
    email_id: int
    category: str | None
    classification_confidence: float | None
    quotation_id: int | None
    quotation_number: str | None
    status: str | None
    outcome: str
    checked_lines: int
    total_lines: int
    # Set by `_detect_reply` when this email lands on a thread that already
    # has a sent quotation - the id of the quotation being replied to.
    replied_quotation_id: int | None
    reply_intent: str | None
    reply_reason: str | None
    # The extraction is carried in state rather than on the workflow instance,
    # so a node never depends on a sibling having run against the same object.
    extracted: Any
    # Line item id -> ids of every stock lot sharing its matched spec, handed
    # from `_match` to `_check_stock` so the availability sum isn't limited to
    # a single representative lot.
    lot_ids_by_line: dict[int, list[int]]
    errors: Annotated[list[str], operator.add]
    notes: Annotated[list[str], operator.add]


@dataclass(slots=True)
class WorkflowResult:
    email_id: int
    outcome: str
    category: str | None = None
    quotation_id: int | None = None
    quotation_number: str | None = None
    status: str | None = None
    errors: list[str] | None = None
    notes: list[str] | None = None
    duration_ms: int = 0

    def summary(self) -> str:
        parts = [f"email={self.email_id}", f"outcome={self.outcome}"]
        if self.quotation_number:
            parts.append(f"quotation={self.quotation_number}")
        if self.status:
            parts.append(f"status={self.status}")
        parts.append(f"{self.duration_ms}ms")
        return " ".join(parts)


def _merge_notes(existing: str | None, notes: list[str]) -> str | None:
    """Combine review notes without repeating or accumulating empties.

    Three things were going wrong and each showed up on screen:

    * **Duplicates.** Every processing run appended its notes to the previous
      run's, so re-processing an enquiry showed "No stock matches this spec"
      twice, then three times.
    * **Empty entries.** A note like ``f"Line {n}: {reason}"`` with a blank
      reason stored a bare ``Line 1:``, which reads as a truncated error.
    * **No ceiling.** The column grew without limit, and a reviewer facing a
      wall of notes reads none of them.

    Order is preserved - the first mention of a problem is the one with
    context around it - and the newest notes win when the cap is hit, because
    a note from three runs ago is the least likely to still be true.
    """
    seen: dict[str, None] = {}
    for note in [*(existing or "").splitlines(), *notes]:
        cleaned = note.strip()
        # A "Line 3:" with nothing after the colon is not a note.
        if not cleaned or cleaned.rstrip().endswith(":"):
            continue
        seen[cleaned] = None

    kept = list(seen)[-MAX_REVIEW_NOTES:]
    return "\n".join(kept) or None


class QuotationWorkflow:
    def __init__(
        self,
        db: Session,
        client: LLMClient | None = None,
        rules: BusinessRules | None = None,
    ) -> None:
        self.db = db
        self.client = client
        self.rules = rules or get_rules()
        self.matcher = ProductMatcher(db, self.rules)
        self.stock = StockAvailabilityService(db, self.rules)
        self.drafting = DraftingService(db, client=client, rules=self.rules)
        self.graph = self._build_graph()

    # --- Graph ------------------------------------------------------------

    def _build_graph(self):
        graph = StateGraph(WorkflowState)

        graph.add_node("detect_reply", self._detect_reply)
        graph.add_node("classify", self._classify)
        graph.add_node("classify_reply", self._classify_reply)
        graph.add_node("handle_accepted", self._handle_accepted)
        graph.add_node("handle_declined", self._handle_declined)
        graph.add_node("handle_needs_review", self._handle_needs_review)
        graph.add_node("extract", self._extract)
        graph.add_node("assemble", self._assemble)
        graph.add_node("match", self._match)
        graph.add_node("check_stock", self._check_stock)
        graph.add_node("draft", self._draft)
        graph.add_node("review", self._review)
        graph.add_node("unsupported", self._unsupported)
        graph.add_node("failed", self._failed)

        graph.add_edge(START, "detect_reply")
        graph.add_conditional_edges(
            "detect_reply",
            self._route_after_detect_reply,
            {"classify": "classify", "classify_reply": "classify_reply", "failed": "failed"},
        )
        graph.add_conditional_edges(
            "classify",
            self._route_after_classify,
            {"extract": "extract", "unsupported": "unsupported", "failed": "failed"},
        )
        graph.add_conditional_edges(
            "classify_reply",
            self._route_after_classify_reply,
            {
                "handle_accepted": "handle_accepted",
                "handle_declined": "handle_declined",
                "handle_needs_review": "handle_needs_review",
                "failed": "failed",
            },
        )
        graph.add_conditional_edges(
            "extract", self._route_after_extract, {"assemble": "assemble", "failed": "failed"}
        )
        graph.add_edge("assemble", "match")
        graph.add_edge("match", "check_stock")
        graph.add_conditional_edges(
            "check_stock", self._route_after_stock_check, {"draft": "draft", "review": "review"}
        )
        graph.add_edge("draft", END)
        graph.add_edge("review", END)
        graph.add_edge("unsupported", END)
        graph.add_edge("failed", END)
        graph.add_edge("handle_accepted", END)
        graph.add_edge("handle_declined", END)
        graph.add_edge("handle_needs_review", END)

        return graph.compile()

    def run(self, email_id: int) -> WorkflowResult:
        started = time.perf_counter()
        final: dict[str, Any] = self.graph.invoke(
            {"email_id": email_id, "errors": [], "notes": []}
        )
        duration = int((time.perf_counter() - started) * 1000)

        email = self.db.get(Email, email_id)
        if email:
            email.processing_ms = duration
            email.processed_at = utcnow()
            self.db.commit()

        result = WorkflowResult(
            email_id=email_id,
            outcome=final.get("outcome", "UNKNOWN"),
            category=final.get("category"),
            quotation_id=final.get("quotation_id"),
            quotation_number=final.get("quotation_number"),
            status=final.get("status"),
            errors=final.get("errors") or [],
            notes=final.get("notes") or [],
            duration_ms=duration,
        )
        logger.info(result.summary())
        return result

    # --- Nodes ------------------------------------------------------------

    def _find_replied_quotation(self, email: Email) -> QuotationRequest | None:
        """Which quotation, if any, this email is a response to.

        Two matchers, tried strongest first:

        1. **Same Gmail thread.** Ground truth for "same conversation", so it
           is a lookup rather than a guess. This is what happens when somebody
           presses Reply.

        2. **The quotation number in the text.** Customers routinely start a
           fresh email quoting the reference - "Response to Quotation
           KK-000004" - which shares no thread with anything. Matching on a
           reference the customer wrote is still deterministic: the number
           appears nowhere unless we put it there.

        Sender is *not* used as a matcher on its own. One customer with three
        open quotations would have their reply attached to an arbitrary one,
        and a reply filed against the wrong quotation is worse than one left
        unattached, because nobody goes looking for it.
        """
        threaded = self._match_by_thread(email)
        if threaded is not None:
            return threaded
        return self._match_by_reference(email)

    def _match_by_thread(self, email: Email) -> QuotationRequest | None:
        """A reply in the same conversation.

        Restricted to quotations that actually reached the customer. Sharing a
        thread with a quotation still in review does not make a message a
        reply to it - a customer sending a second enquiry on the same thread
        is enquiring again, not responding to something they never received.

        `Email.id != email.id` excludes the enquiry itself, which shares its
        own thread_id with the row being checked.
        """
        if not email.thread_id:
            return None
        return self.db.scalars(
            select(QuotationRequest)
            .join(Email, QuotationRequest.email_id == Email.id)
            .where(
                Email.thread_id == email.thread_id,
                Email.id != email.id,
                QuotationRequest.status.in_(SENT_STATUSES),
            )
            .order_by(QuotationRequest.sent_at.desc())
            .limit(1)
        ).first()

    def _match_by_reference(self, email: Email) -> QuotationRequest | None:
        """A quotation number quoted in the subject or body.

        Scoped by row-level security, so a reference belonging to another
        desk cannot be matched even if a customer quotes one.
        """
        numbers = quotation_numbers_in(f"{email.subject or ''}\n{email.full_text or ''}")
        if not numbers:
            return None
        return self.db.scalars(
            select(QuotationRequest)
            .where(
                QuotationRequest.quotation_number.in_(numbers),
                QuotationRequest.status.in_(REPLIABLE_STATUSES),
            )
            .order_by(QuotationRequest.sent_at.desc().nullslast())
            .limit(1)
        ).first()

    def _detect_reply(self, state: WorkflowState) -> WorkflowState:
        email = self.db.get(Email, state["email_id"])
        if email is None:
            return {"outcome": "FAILED", "errors": [f"email {state['email_id']} not found"]}

        quotation = self._find_replied_quotation(email)
        if quotation is None:
            return {}
        return {"replied_quotation_id": quotation.id}

    def _classify(self, state: WorkflowState) -> WorkflowState:
        email = self.db.get(Email, state["email_id"])
        if email is None:
            return {"outcome": "FAILED", "errors": [f"email {state['email_id']} not found"]}

        email.processing_status = ProcessingStatus.PROCESSING
        self.db.commit()

        try:
            outcome = classify_email(
                subject=email.subject,
                body=email.full_text,
                sender_name=email.sender_name,
                sender_email=email.sender_email,
                client=self.client,
            )
        except LLMError as exc:
            telemetry.record_failure(
                self.db, task="classify", model="unknown", error=str(exc), email_id=email.id
            )
            self.db.commit()
            return {"outcome": "FAILED", "errors": [f"classification failed: {exc}"]}

        telemetry.record_call(self.db, outcome.usage, email_id=email.id)

        result = outcome.value
        email.category = result.category
        email.classification_confidence = result.confidence
        email.classification_reason = result.reason
        self.db.commit()

        return {
            "category": result.category.value,
            "classification_confidence": result.confidence,
        }

    def _classify_reply(self, state: WorkflowState) -> WorkflowState:
        email = self.db.get(Email, state["email_id"])
        quotation = self.db.get(QuotationRequest, state["replied_quotation_id"])

        email.processing_status = ProcessingStatus.PROCESSING
        self.db.commit()

        # Same facts block the original quotation was drafted from - the
        # reply classifier is told what was quoted, not just what was asked.
        quotation_summary = build_draft_context(quotation, self.rules).facts

        try:
            outcome = classify_reply(
                subject=email.subject,
                body=email.full_text,
                quotation_summary=quotation_summary,
                sender_name=email.sender_name,
                sender_email=email.sender_email,
                client=self.client,
            )
        except LLMError as exc:
            telemetry.record_failure(
                self.db, task="classify_reply", model="unknown", error=str(exc), email_id=email.id
            )
            self.db.commit()
            return {"outcome": "FAILED", "errors": [f"reply classification failed: {exc}"]}

        telemetry.record_call(self.db, outcome.usage, email_id=email.id)

        result = outcome.value
        email.replied_to_quotation_id = quotation.id
        email.reply_intent = result.intent
        email.reply_intent_confidence = result.confidence
        email.reply_intent_reason = result.reason

        # What the customer said about coming back, and whether the ball is
        # now in our court. Both drive the mailbox and the follow-up rules.
        email.awaiting_us = bool(result.awaiting_us)
        email.promised_date_raw = result.promised_date
        if result.promised_date:
            parsed = parse_promised_date(result.promised_date, email.received_at)
            email.promised_date = parsed
            if parsed:
                quotation.promised_date = parsed
        self.db.commit()

        return {
            "replied_quotation_id": quotation.id,
            "reply_intent": result.intent.value,
            "reply_reason": result.reason,
        }

    def _handle_accepted(self, state: WorkflowState) -> WorkflowState:
        """Customer wants to proceed. Highlighted for a human to close - no
        automated reply, because closing a deal (PO, invoice, dispatch) is
        outside what this system does on its own."""
        quotation = self.db.get(QuotationRequest, state["replied_quotation_id"])
        quotation.status = QuotationStatus.CUSTOMER_ACCEPTED
        quotation.review_notes = _merge_notes(
            quotation.review_notes, [f"Customer replied: {state.get('reply_reason', '')}"]
        )
        self.db.commit()
        self._finish_email(state["email_id"], ProcessingStatus.PROCESSED)

        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="CUSTOMER_ACCEPTED",
            details={"quotation_number": quotation.quotation_number, "reason": state.get("reply_reason")},
        )
        self.db.commit()
        self._stop_chasing(quotation, "The customer accepted.")
        self._notify_reply(quotation, "accepted")
        return {"outcome": "CUSTOMER_ACCEPTED", "status": quotation.status.value}

    def _stop_chasing(self, quotation: QuotationRequest, reason: str) -> None:
        """A customer who has replied must never be chased again."""
        from app.services.quotations.followup_rules import FollowUpScheduler

        try:
            FollowUpScheduler(self.db).cancel_for(quotation, reason)
        except Exception:  # noqa: BLE001 - never break reply handling
            logger.exception("Could not cancel follow-ups for %s", quotation.quotation_number)

    def _notify_reply(self, quotation: QuotationRequest, intent: str) -> None:
        try:
            NotificationService(self.db).customer_replied(quotation, intent)
        except Exception:  # noqa: BLE001 - reporting must not break processing
            logger.exception("Could not raise a reply notification")

    def _handle_declined(self, state: WorkflowState) -> WorkflowState:
        """Customer said no. Draft a courtesy reply for a human to review and
        send - never sent automatically (spec Rule 4 applies here too)."""
        email = self.db.get(Email, state["email_id"])
        quotation = self.db.get(QuotationRequest, state["replied_quotation_id"])
        quotation.status = QuotationStatus.CUSTOMER_DECLINED
        quotation.review_notes = _merge_notes(
            quotation.review_notes, [f"Customer declined: {state.get('reply_reason', '')}"]
        )
        self.db.commit()

        result = self.drafting.generate_decline_reply(quotation, customer_reply_text=email.full_text)
        notes = list(result.review_notes) if result.error else []
        if result.error:
            notes.append(f"Courtesy reply generation failed: {result.error}")
            quotation.review_notes = _merge_notes(quotation.review_notes, notes)
            self.db.commit()

        self._finish_email(state["email_id"], ProcessingStatus.PROCESSED)

        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="CUSTOMER_DECLINED",
            details={"quotation_number": quotation.quotation_number, "reason": state.get("reply_reason")},
        )
        self.db.commit()
        self._stop_chasing(quotation, "The customer declined.")
        self._notify_reply(quotation, "declined")
        return {"outcome": "CUSTOMER_DECLINED", "status": quotation.status.value, "notes": notes}

    def _handle_needs_review(self, state: WorkflowState) -> WorkflowState:
        """Neither a clear yes nor no - left for a human to read and decide,
        status unchanged so it stays visible wherever it already was."""
        quotation = self.db.get(QuotationRequest, state["replied_quotation_id"])
        quotation.review_notes = _merge_notes(
            quotation.review_notes,
            [f"Customer replied (needs review): {state.get('reply_reason', '')}"],
        )
        self.db.commit()
        self._finish_email(state["email_id"], ProcessingStatus.PROCESSED)

        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="REPLY_NEEDS_REVIEW",
            details={"quotation_number": quotation.quotation_number, "reason": state.get("reply_reason")},
        )
        self.db.commit()
        return {"outcome": "REPLY_NEEDS_REVIEW", "status": quotation.status.value}

    def _extract(self, state: WorkflowState) -> WorkflowState:
        email = self.db.get(Email, state["email_id"])

        try:
            outcome = extract_requirement(
                subject=email.subject,
                body=email.full_text,
                sender_name=email.sender_name,
                sender_email=email.sender_email,
                received_at=email.received_at.isoformat() if email.received_at else None,
                client=self.client,
            )
        except LLMError as exc:
            telemetry.record_failure(
                self.db, task="extract", model="unknown", error=str(exc), email_id=email.id
            )
            self.db.commit()
            return {"outcome": "FAILED", "errors": [f"extraction failed: {exc}"]}

        telemetry.record_call(self.db, outcome.usage, email_id=email.id)
        self.db.commit()

        notes = []
        if outcome.value.missing_information:
            notes.append("Missing: " + "; ".join(outcome.value.missing_information))

        return {
            "extracted": outcome.value,
            "total_lines": len(outcome.value.line_items),
            "notes": notes,
        }

    def _assemble(self, state: WorkflowState) -> WorkflowState:
        email = self.db.get(Email, state["email_id"])
        quotation = create_quotation(self.db, email, state["extracted"])

        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="CREATED",
            details={
                "quotation_number": quotation.quotation_number,
                "email_id": email.id,
                "line_items": len(quotation.line_items),
                "customer_id": quotation.customer_id,
            },
        )
        self.db.commit()

        return {
            "quotation_id": quotation.id,
            "quotation_number": quotation.quotation_number,
            "status": quotation.status.value,
        }

    def _match(self, state: WorkflowState) -> WorkflowState:
        quotation = self.db.get(QuotationRequest, state["quotation_id"])
        notes: list[str] = []
        lot_ids_by_line: dict[int, list[int]] = {}

        for item in quotation.line_items:
            outcome = self.matcher.match_line_item(item)
            item.match_status = outcome.status
            item.match_score = outcome.score
            item.match_candidates = outcome.candidates_as_json()
            item.matched_stock_item_id = outcome.stock_item.id if outcome.stock_item else None
            lot_ids_by_line[item.id] = outcome.lot_ids if outcome.status is MatchStatus.MATCH_FOUND else []

            if outcome.status is not MatchStatus.MATCH_FOUND:
                notes.append(f"Line {item.line_no}: {outcome.reason}")

            # Convert to tonnes using the matched spec's real dimensions where
            # possible, falling back to what the enquiry itself stated.
            source = outcome.stock_item or item
            conversion = convert_to_mt(item.quantity, item.quantity_unit, Dimensions.from_obj(source))
            if conversion:
                item.quantity_mt = conversion.quantity_mt
                item.conversion_basis = conversion.basis[:255]
            elif item.quantity is not None:
                notes.append(
                    f"Line {item.line_no}: cannot convert "
                    f"{item.quantity:g} {item.quantity_unit.value} to MT."
                )

        self.db.commit()
        return {"notes": notes, "lot_ids_by_line": lot_ids_by_line}

    def _check_stock(self, state: WorkflowState) -> WorkflowState:
        quotation = self.db.get(QuotationRequest, state["quotation_id"])
        has_missing = bool(quotation.missing_information)
        lot_ids_by_line = state.get("lot_ids_by_line") or {}
        checked = 0
        notes: list[str] = []
        confidences: list[ConfidenceLevel] = []
        needs_review = False

        for item in quotation.line_items:
            outcome = self.stock.check(
                lot_ids=lot_ids_by_line.get(item.id, []),
                quantity_mt=item.quantity_mt,
                customer=quotation.customer,
                match_status=item.match_status,
                has_missing_information=has_missing,
            )

            self.db.add(
                StockAvailability(
                    quotation_line_item_id=item.id,
                    available_qty_mt=outcome.available_qty_mt,
                    on_hand_qty_mt=outcome.on_hand_qty_mt,
                    reserved_qty_mt=outcome.reserved_qty_mt,
                    available_nop=outcome.available_nop,
                    sufficient=outcome.sufficient,
                    locations=outcome.locations_as_json(),
                    ageing_min_days=outcome.ageing_min_days,
                    ageing_max_days=outcome.ageing_max_days,
                    lot_count=outcome.lot_count,
                    suggested_rate=outcome.suggested_rate,
                    currency=outcome.currency,
                    unit=outcome.unit,
                    rules_version=outcome.rules_version,
                    confidence=outcome.confidence,
                    requires_manual_review=outcome.requires_manual_review,
                    review_reasons=outcome.review_reasons,
                    breakdown=outcome.breakdown(),
                    explanation=outcome.explanation,
                    stock_as_of=outcome.stock_as_of,
                )
            )

            # Price the line from the trader's published rules. Availability
            # and price are separate questions: a line with no stock can still
            # be quoted off a mill offer, and a line with stock still needs a
            # rate before anything can be drafted.
            self.db.flush()
            pricing = PricingService(self.db).price_line(
                item,
                quotation=quotation,
                lot_ids=lot_ids_by_line.get(item.id, []),
            )
            if pricing.outcome.warnings:
                notes += [f"Line {item.line_no}: {w}" for w in pricing.outcome.warnings]
                needs_review = True

            confidences.append(outcome.confidence)
            needs_review = needs_review or outcome.requires_manual_review
            if outcome.matched:
                checked += 1
            notes += [f"Line {item.line_no}: {reason}" for reason in outcome.review_reasons]

        # A reply is only as trustworthy as its weakest line.
        quotation.confidence = (
            min(confidences, key=lambda c: CONFIDENCE_ORDER[c]) if confidences else ConfidenceLevel.LOW
        )
        if checked == 0:
            quotation.status = (
                QuotationStatus.NEEDS_INFORMATION if has_missing else QuotationStatus.READY_FOR_REVIEW
            )
        else:
            quotation.status = QuotationStatus.PROCESSING

        quotation.review_notes = _merge_notes(None, notes)
        self.db.commit()

        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="STOCK_CHECKED",
            details={
                "checked_lines": checked,
                "total_lines": len(quotation.line_items),
                "confidence": quotation.confidence.value,
                "requires_manual_review": needs_review,
            },
        )
        self.db.commit()

        return {"checked_lines": checked, "notes": notes, "status": quotation.status.value}

    def _draft(self, state: WorkflowState) -> WorkflowState:
        quotation = self.db.get(QuotationRequest, state["quotation_id"])
        result = self.drafting.generate(quotation)

        notes = list(result.review_notes)
        if result.error:
            notes.append(f"Draft generation failed: {result.error}")

        # A draft exists, but an enquiry with acknowledged gaps is not simply
        # "ready" - the reviewer has something to chase before sending.
        quotation.status = (
            QuotationStatus.NEEDS_INFORMATION
            if quotation.missing_information
            else QuotationStatus.READY_FOR_REVIEW
        )
        if notes:
            quotation.review_notes = _merge_notes(quotation.review_notes, notes)
        self.db.commit()

        self._finish_email(state["email_id"], ProcessingStatus.PROCESSED)

        self._announce(quotation)
        return {
            "outcome": quotation.status.value,
            "status": quotation.status.value,
            "notes": notes,
        }

    def _review(self, state: WorkflowState) -> WorkflowState:
        """Nothing could be checked, so there is no reply to draft.

        The quotation still reaches the reviewer - with the matched candidates,
        the reasons, and the original email - because the alternative is an
        enquiry that quietly disappears.
        """
        quotation = self.db.get(QuotationRequest, state["quotation_id"])
        self._finish_email(state["email_id"], ProcessingStatus.PROCESSED)

        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="NEEDS_REVIEW",
            details={"status": quotation.status.value, "reason": "no line could be stock-checked"},
        )
        self.db.commit()
        self._announce(quotation)

        return {"outcome": quotation.status.value, "status": quotation.status.value}

    def _announce(self, quotation: QuotationRequest) -> None:
        """Tell the desk. A failed notification never fails the enquiry."""
        try:
            NotificationService(self.db).quotation_ready(quotation)
        except Exception:  # noqa: BLE001 - reporting must not break processing
            logger.exception("Could not raise a notification for %s", quotation.quotation_number)

    def _unsupported(self, state: WorkflowState) -> WorkflowState:
        """Recorded and shown, but not answered automatically.

        `SKIPPED` means "this system will not draft a reply", not "nobody
        needs to look at it". A delivery query or a complaint is real work for
        a person, so `awaiting_us` is set and the mailbox routes it to the
        right tab - previously these were recorded and then invisible, which
        is the worst of both.
        """
        category = state.get("category") or "UNKNOWN"

        email = self.db.get(Email, state["email_id"])
        if email is not None and email.category in NEEDS_A_PERSON:
            email.awaiting_us = True
            self.db.commit()

        self._finish_email(state["email_id"], ProcessingStatus.SKIPPED)

        audit.record(
            self.db,
            entity_type="email",
            entity_id=state["email_id"],
            action="SKIPPED",
            details={"category": category, "reason": "not supported in the MVP"},
        )
        self.db.commit()

        return {
            "outcome": "SKIPPED",
            "notes": [f"{category} is recorded but not actioned by the MVP."],
        }

    def _failed(self, state: WorkflowState) -> WorkflowState:
        errors = state.get("errors") or ["unknown error"]
        email = self.db.get(Email, state["email_id"])
        if email:
            email.processing_status = ProcessingStatus.FAILED
            email.error_message = "; ".join(errors)[:2000]
            self.db.commit()

        audit.record(
            self.db,
            entity_type="email",
            entity_id=state["email_id"],
            action="FAILED",
            details={"errors": errors},
        )
        self.db.commit()
        return {"outcome": "FAILED"}

    # --- Routing ----------------------------------------------------------

    @staticmethod
    def _route_after_detect_reply(state: WorkflowState) -> str:
        if state.get("outcome") == "FAILED":
            return "failed"
        return "classify_reply" if state.get("replied_quotation_id") else "classify"

    @staticmethod
    def _route_after_classify_reply(state: WorkflowState) -> str:
        if state.get("outcome") == "FAILED":
            return "failed"
        intent = state.get("reply_intent")
        if intent == ReplyIntent.ACCEPTED.value:
            return "handle_accepted"
        if intent == ReplyIntent.DECLINED.value:
            return "handle_declined"
        return "handle_needs_review"

    @staticmethod
    def _route_after_classify(state: WorkflowState) -> str:
        if state.get("outcome") == "FAILED":
            return "failed"
        return "extract" if state.get("category") == EmailCategory.QUOTATION_REQUEST else "unsupported"

    @staticmethod
    def _route_after_extract(state: WorkflowState) -> str:
        return "failed" if state.get("outcome") == "FAILED" else "assemble"

    @staticmethod
    def _route_after_stock_check(state: WorkflowState) -> str:
        # A reply is drafted even when nothing matched stock. The customer
        # asked for material and is owed an answer either way: the table lists
        # exactly what they requested, with the rate and amount left blank
        # where there is no figure to state. Withholding the draft meant the
        # commonest real case - an enquiry for something not held - produced
        # no reply at all, which is the one outcome a sales desk cannot have.
        #
        # An unmatched line still routes to review afterwards, so the draft is
        # never sent unseen; it is a starting point, not an approval.
        return "draft"

    # --- Helpers ----------------------------------------------------------

    def _finish_email(self, email_id: int, status: ProcessingStatus) -> None:
        email = self.db.get(Email, email_id)
        if email:
            email.processing_status = status
            email.processed_at = utcnow()
            self.db.commit()


def process_pending_emails(
    db: Session, limit: int = 25, client: LLMClient | None = None
) -> list[WorkflowResult]:
    """Run the workflow over every email awaiting processing."""
    from sqlalchemy import select

    workflow = QuotationWorkflow(db, client=client)
    pending = db.scalars(
        select(Email.id)
        .where(Email.processing_status == ProcessingStatus.PENDING)
        .order_by(Email.received_at.asc())
        .limit(limit)
    ).all()

    results = []
    for email_id in pending:
        try:
            results.append(workflow.run(email_id))
        except Exception as exc:  # noqa: BLE001 - one email must not stop the batch
            db.rollback()
            logger.exception("Workflow crashed on email %s", email_id)
            results.append(WorkflowResult(email_id=email_id, outcome="FAILED", errors=[str(exc)]))
    return results
