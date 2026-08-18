"""Confidence scoring and manual-review routing for stock availability.

This is a checklist, not a judgement. Every input is a fact the system
already knows - did the spec match exactly, is there stock at all, how many
lots back the figure, is the customer on file, is there enough for what was
asked. The thresholds live in `business_rules.yaml`.

Deliberately conservative: a reply is HIGH confidence only when every
condition holds. Anything else routes to a human, because a wrong "we have
this in stock" is a promise the business cannot keep.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.rules import BusinessRules, get_rules
from app.models import ConfidenceLevel, MatchStatus


@dataclass(slots=True)
class ConfidenceInputs:
    match_status: MatchStatus = MatchStatus.PENDING
    stock_found: bool = False
    lot_count: int = 0
    customer_known: bool = False
    quantity_known: bool = False
    has_missing_information: bool = False
    # None when the requested quantity is unknown, so sufficiency was never judged.
    sufficient: bool | None = None


@dataclass(slots=True)
class ConfidenceResult:
    level: ConfidenceLevel
    reasons: list[str] = field(default_factory=list)
    requires_manual_review: bool = False
    review_reasons: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"{self.level.value}: " + "; ".join(self.reasons)


def assess(inputs: ConfidenceInputs, rules: BusinessRules | None = None) -> ConfidenceResult:
    """Grade a stock check and decide whether it may proceed without a human."""
    rules = rules or get_rules()
    high = rules.confidence.high
    medium = rules.confidence.medium
    triggers = rules.review.force_manual_when

    reasons: list[str] = []
    review_reasons: list[str] = []

    exact = inputs.match_status is MatchStatus.MATCH_FOUND
    insufficient = inputs.sufficient is False

    # --- HIGH -----------------------------------------------------------
    high_failures: list[str] = []
    if high.require_exact_match and not exact:
        high_failures.append(f"spec match is {inputs.match_status.value}")
    if high.require_stock_match and not inputs.stock_found:
        high_failures.append("no matching stock found")
    if inputs.lot_count < high.min_lots:
        high_failures.append(f"only {inputs.lot_count} lot(s), {high.min_lots} needed")
    if high.require_customer_known and not inputs.customer_known:
        high_failures.append("customer not recognised")
    if not inputs.quantity_known:
        high_failures.append("quantity not established")
    if inputs.has_missing_information:
        high_failures.append("enquiry is missing required information")
    if insufficient:
        high_failures.append("available balance is below the requested quantity")

    if not high_failures:
        level = ConfidenceLevel.HIGH
        reasons.append("exact spec match with stock on hand")
        reasons.append(f"{inputs.lot_count} stock lot(s) backing the figure")
        reasons.append("customer on file")
    else:
        # --- MEDIUM -------------------------------------------------------
        medium_failures: list[str] = []
        if not inputs.stock_found:
            medium_failures.append("no matching stock found")
        if inputs.match_status in (MatchStatus.NO_MATCH, MatchStatus.PENDING):
            medium_failures.append(f"spec match is {inputs.match_status.value}")
        if inputs.lot_count < medium.min_lots:
            medium_failures.append("no stock lots at all")
        if not inputs.quantity_known:
            medium_failures.append("quantity not established")

        if medium_failures:
            level = ConfidenceLevel.LOW
            reasons = medium_failures
        else:
            level = ConfidenceLevel.MEDIUM
            reasons = high_failures

    # --- Manual review triggers ------------------------------------------
    if triggers.missing_information and inputs.has_missing_information:
        review_reasons.append("Enquiry is missing information the stock check needs.")
    if triggers.no_stock_match and not inputs.stock_found:
        review_reasons.append("No stock currently matches this spec.")
    if triggers.ambiguous_product_match and inputs.match_status is MatchStatus.MULTIPLE_MATCHES:
        review_reasons.append("More than one stock spec matches the enquiry equally well.")
    if triggers.no_product_match and inputs.match_status in (
        MatchStatus.NO_MATCH,
        MatchStatus.PENDING,
    ):
        review_reasons.append("No stock spec matches the enquiry.")
    if triggers.insufficient_balance and insufficient:
        review_reasons.append("Available balance is below what was requested.")
    if triggers.low_confidence and level is ConfidenceLevel.LOW:
        review_reasons.append("Overall confidence is LOW.")

    return ConfidenceResult(
        level=level,
        reasons=reasons,
        requires_manual_review=bool(review_reasons),
        review_reasons=review_reasons,
    )
