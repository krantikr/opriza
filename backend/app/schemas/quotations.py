"""Email, quotation, stock-availability, draft and approval DTOs.

The detail response is deliberately fat. The review screen has to show the
original email, what the AI understood, the full availability derivation and
the draft on one page - a reviewer who has to click around to reconstruct the
reasoning will stop reading it, and an unread justification is no
justification.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.pricing import PricingOut


class AttachmentOut(ORMModel):
    id: int
    filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    has_text: bool = False
    extraction_error: str | None = None


class EmailOut(ORMModel):
    id: int
    message_id: str
    thread_id: str | None = None
    source: str
    sender_email: str | None = None
    sender_name: str | None = None
    subject: str | None = None
    snippet: str | None = None
    received_at: datetime | None = None
    category: str | None = None
    classification_confidence: float | None = None
    classification_reason: str | None = None
    processing_status: str
    processing_ms: int | None = None
    error_message: str | None = None
    has_attachments: bool = False
    quotation_id: int | None = None
    quotation_number: str | None = None
    # Lets the mailbox show which enquiries are still waiting on a person
    # without a second request per message.
    quotation_status: str | None = None
    #: True when a follow-up rule says this quotation is owed a nudge now.
    follow_up_due: bool = False
    #: When the next nudge falls due, so the mailbox can say "in 22 hours"
    #: rather than leaving a trader to guess why nothing has happened yet.
    follow_up_at: datetime | None = None
    #: The single pipeline stage this message is stuck at, or DONE.
    state: str = "DONE"
    replied_to_quotation_id: int | None = None
    reply_intent: str | None = None
    reply_intent_confidence: float | None = None
    reply_intent_reason: str | None = None
    promised_date_raw: str | None = None
    promised_date: Any | None = None
    awaiting_us: bool = False
    answered_at: datetime | None = None


class EmailDetailOut(EmailOut):
    body_text: str | None = None
    attachments: list[AttachmentOut] = Field(default_factory=list)


class MatchCandidateOut(BaseModel):
    stock_item_id: int
    display_name: str
    score: float
    lot_count: int = 0
    fields: list[dict[str, Any]] = Field(default_factory=list)


class StockAvailabilityOut(ORMModel):
    available_qty_mt: Decimal | None = None
    available_nop: float | None = None
    on_hand_qty_mt: Decimal | None = None
    reserved_qty_mt: Decimal | None = None
    sufficient: bool | None = None
    locations: list[dict[str, Any]] = Field(default_factory=list)
    ageing_min_days: int | None = None
    ageing_max_days: int | None = None
    lot_count: int = 0
    suggested_rate: Decimal | None = None
    currency: str = "INR"
    unit: str = "MT"
    confidence: str | None = None
    requires_manual_review: bool = False
    rules_version: str | None = None
    explanation: str | None = None
    breakdown: list[dict[str, Any]] = Field(default_factory=list)
    stock_as_of: date | None = None


class LineItemOut(ORMModel):
    id: int
    line_no: int
    raw_text: str | None = None
    product_type: str | None = None
    grade: str | None = None
    standard: str | None = None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    diameter_mm: float | None = None
    quantity: Decimal | None = None
    quantity_unit: str
    quantity_mt: Decimal | None = None
    conversion_basis: str | None = None
    remarks: str | None = None
    match_status: str
    match_score: float | None = None
    matched_stock_item_id: int | None = None
    matched_stock_item_name: str | None = None
    matched_stock_item_make: str | None = None
    match_candidates: list[MatchCandidateOut] = Field(default_factory=list)
    stock_availability: StockAvailabilityOut | None = None
    pricing: PricingOut | None = None


class DraftOut(ORMModel):
    id: int
    version: int
    is_current: bool
    subject: str | None = None
    body: str | None = None
    status: str
    generated_by: str | None = None
    created_at: datetime


class FollowUpOut(ORMModel):
    id: int
    subject: str | None = None
    body: str | None = None
    sent: bool
    sent_message_id: str | None = None
    error: str | None = None
    created_at: datetime
    user_name: str | None = None


class ApprovalOut(ORMModel):
    id: int
    action: str
    comments: str | None = None
    was_edited: bool = False
    acted_at: datetime | None = None
    user_name: str | None = None


class QuotationOut(ORMModel):
    id: int
    quotation_number: str
    email_id: int
    customer_id: int | None = None
    customer_name: str | None = None
    customer_company: str | None = None
    customer_email: str | None = None
    status: str
    #: The working stage this status derives to (`stages.py::stage_of`), or
    #: null once a deal is lost/rejected and has nothing left to work.
    #: Computed here rather than re-derived in the frontend, so the two
    #: never drift.
    stage: str | None = None
    confidence: str | None = None
    delivery_location: str | None = None
    line_count: int = 0
    total_suggested_value: Decimal | None = None
    headline_product: str | None = None
    headline_availability: str | None = None
    requires_manual_review: bool = False
    not_sent_reason: str | None = None
    not_sent_note: str | None = None
    is_priority_customer: bool = False
    is_priority_product: bool = False
    line_items: list[LineItemOut] = Field(default_factory=list)
    created_at: datetime
    sent_at: datetime | None = None


class ThreadMessageOut(BaseModel):
    """One message in the conversation with a customer."""

    id: str
    direction: str
    kind: str
    at: datetime | None = None
    sender_name: str | None = None
    sender_email: str | None = None
    subject: str | None = None
    body: str | None = None
    sent: bool = True
    outcome: str | None = None
    email_id: int | None = None
    has_attachments: bool = False


class ThreadOut(BaseModel):
    """The whole correspondence, with where it stands now."""

    quotation_id: int
    quotation_number: str
    #: The pipeline stage this conversation is waiting at, so the thread and
    #: the mailbox tabs can never disagree about what is outstanding.
    state: str
    status: str
    customer_name: str | None = None
    customer_email: str | None = None
    messages: list[ThreadMessageOut] = Field(default_factory=list)


class QuotationDetailOut(QuotationOut):
    required_delivery_date: str | None = None
    payment_terms: str | None = None
    additional_requirements: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    review_notes: str | None = None
    send_error: str | None = None
    email: EmailDetailOut | None = None
    replies: list[EmailDetailOut] = Field(default_factory=list)
    line_items: list[LineItemOut] = Field(default_factory=list)
    current_draft: DraftOut | None = None
    drafts: list[DraftOut] = Field(default_factory=list)
    approvals: list[ApprovalOut] = Field(default_factory=list)
    follow_ups: list[FollowUpOut] = Field(default_factory=list)


# --- Requests --------------------------------------------------------------


class DraftUpdateIn(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    comments: str | None = None


class ApproveIn(BaseModel):
    """Approve, optionally with final edits applied in the same action."""

    subject: str | None = Field(default=None, max_length=500)
    body: str | None = None
    comments: str | None = None


class RejectIn(BaseModel):
    reason: str | None = None


class FollowUpIn(BaseModel):
    """Optional overrides; omit either to use the generated default."""

    subject: str | None = Field(default=None, max_length=500)
    body: str | None = None


class AuditLogOut(ORMModel):
    id: int
    entity_type: str
    entity_id: int | None = None
    action: str
    details: dict[str, Any] | None = None
    user_id: int | None = None
    created_at: datetime


class StageIn(BaseModel):
    """A manual move to one of the working stages."""

    stage: str
    #: Why, where a trader wants to say. Kept on the audit entry rather than
    #: the quotation: it explains one move, not the current state.
    reason: str | None = Field(default=None, max_length=500)


class NotSentReasonIn(BaseModel):
    """Why a quotation still sitting in "received" hasn't gone out.

    Independent of the stage-move endpoint: the reason can be set, changed,
    or cleared without the quotation itself moving anywhere.
    """

    not_sent_reason: str | None = None
    not_sent_note: str | None = Field(default=None, max_length=300)


class QuotationDetailsIn(BaseModel):
    """Commercial terms a reviewer supplies when the enquiry did not state them."""

    delivery_location: str | None = Field(default=None, max_length=120)
    required_delivery_date: str | None = Field(default=None, max_length=120)
    payment_terms: str | None = Field(default=None, max_length=200)


# --- Past orders -----------------------------------------------------------


class PastInvoiceOut(BaseModel):
    """A sale already billed, for judging today's rate against."""

    invoice_no: str | None = None
    invoice_date: date | None = None
    material: str
    quantity_mt: Decimal | None = None
    rate_per_mt: Decimal | None = None
    line_total: Decimal | None = None
    delivery_location: str | None = None
    #: True when this line matches the specification being quoted, not just
    #: the customer. Those are the rows that actually anchor a price.
    same_material: bool = False


class PastQuotationOut(BaseModel):
    """An earlier quotation to the same customer, and how it ended."""

    id: int
    quotation_number: str
    created_at: datetime
    sent_at: datetime | None = None
    status: str
    material: str
    quantity_mt: Decimal | None = None
    rate_per_mt: Decimal | None = None
    value: Decimal | None = None
    won: bool = False
    same_material: bool = False


class PastOrdersOut(BaseModel):
    """What this customer has bought and been quoted before.

    Assembled for one question: is the rate about to go out consistent with
    what this buyer has actually paid? The figures are what a trader would
    otherwise dig out of a spreadsheet before picking up the phone.
    """

    customer_name: str | None = None
    invoices: list[PastInvoiceOut]
    quotations: list[PastQuotationOut]

    #: Headline figures over the invoices returned.
    orders_count: int = 0
    total_value: Decimal | None = None
    total_quantity_mt: Decimal | None = None
    last_order_at: date | None = None

    #: Win rate over the earlier quotations, which is what says whether this
    #: buyer converts or shops the desk around.
    quotes_count: int = 0
    quotes_won: int = 0

    #: Average rate paid for *this* material, and how today's compares.
    avg_rate_same_material: Decimal | None = None
    current_rate: Decimal | None = None
    rate_delta: Decimal | None = None
