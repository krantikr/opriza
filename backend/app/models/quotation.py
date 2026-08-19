"""The enquiry workflow: request -> line items -> stock check -> draft -> approval.

The line-item split is deliberate. Real steel enquiries routinely list several
materials in one email, and stock availability is inherently per-material.
Modelling an enquiry as a header with N checked lines from the start costs
almost nothing now and avoids rewriting the checking, drafting and the UI
later.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import (
    ApprovalAction,
    ConfidenceLevel,
    DraftStatus,
    MatchStatus,
    QuantityUnit,
    QuotationStatus,
)
from app.models.mixins import CreatedAtMixin, TimestampMixin, enum_col
from app.models.types import Money, Quantity


class QuotationRequest(Base, TimestampMixin):
    """Header record for one enquiry email that the MVP will act on."""

    __tablename__ = "quotation_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    email_id: Mapped[int] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)

    # What the email said, kept separate from the resolved customer record so a
    # mis-resolution is always visible next to the original wording.
    customer_name_raw: Mapped[str | None] = mapped_column(String(200))
    customer_company_raw: Mapped[str | None] = mapped_column(String(200))
    customer_email: Mapped[str | None] = mapped_column(String(255), index=True)

    status: Mapped[QuotationStatus] = mapped_column(
        enum_col(QuotationStatus), default=QuotationStatus.NEW, nullable=False, index=True
    )
    confidence: Mapped[ConfidenceLevel | None] = mapped_column(enum_col(ConfidenceLevel))

    delivery_location: Mapped[str | None] = mapped_column(String(120))
    required_delivery_date: Mapped[str | None] = mapped_column(String(120))
    payment_terms: Mapped[str | None] = mapped_column(String(200))
    additional_requirements: Mapped[list | None] = mapped_column(JSON)
    missing_information: Mapped[list | None] = mapped_column(JSON)

    review_notes: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)

    # --- Send outcome -----------------------------------------------------
    sent_at: Mapped[datetime | None] = mapped_column()
    sent_message_id: Mapped[str | None] = mapped_column(String(255))
    send_error: Mapped[str | None] = mapped_column(Text)

    email: Mapped["Email"] = relationship(  # noqa: F821
        back_populates="quotation_request", foreign_keys="[QuotationRequest.email_id]"
    )
    replies: Mapped[list["Email"]] = relationship(  # noqa: F821
        back_populates="replied_to_quotation",
        foreign_keys="Email.replied_to_quotation_id",
        order_by="Email.received_at",
    )
    customer: Mapped["Customer | None"] = relationship()  # noqa: F821
    line_items: Mapped[list["QuotationLineItem"]] = relationship(
        back_populates="quotation_request",
        cascade="all, delete-orphan",
        order_by="QuotationLineItem.line_no",
    )
    drafts: Mapped[list["QuotationDraft"]] = relationship(
        back_populates="quotation_request",
        cascade="all, delete-orphan",
        order_by="QuotationDraft.version",
    )
    follow_ups: Mapped[list["FollowUp"]] = relationship(
        back_populates="quotation_request",
        cascade="all, delete-orphan",
        order_by="FollowUp.created_at",
    )
    follow_up_schedules: Mapped[list["FollowUpSchedule"]] = relationship(  # noqa: F821
        back_populates="quotation_request",
        cascade="all, delete-orphan",
        order_by="FollowUpSchedule.due_at",
    )

    @property
    def current_draft(self) -> "QuotationDraft | None":
        return next((d for d in self.drafts if d.is_current), None)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<QuotationRequest {self.quotation_number} {self.status}>"


class QuotationLineItem(Base, TimestampMixin):
    """One requested material, with its extraction and matching outcome."""

    __tablename__ = "quotation_line_items"
    __table_args__ = (
        UniqueConstraint("quotation_request_id", "line_no", name="uq_quotation_line_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_request_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- As extracted from the email (stage 3) ---------------------------
    raw_text: Mapped[str | None] = mapped_column(Text)
    product_type: Mapped[str | None] = mapped_column(String(80))
    grade: Mapped[str | None] = mapped_column(String(60))
    standard: Mapped[str | None] = mapped_column(String(60))
    thickness_mm: Mapped[float | None] = mapped_column()
    width_mm: Mapped[float | None] = mapped_column()
    length_mm: Mapped[float | None] = mapped_column()
    diameter_mm: Mapped[float | None] = mapped_column()
    quantity: Mapped[Decimal | None] = mapped_column(Quantity)
    quantity_unit: Mapped[QuantityUnit] = mapped_column(
        enum_col(QuantityUnit), default=QuantityUnit.UNKNOWN, nullable=False
    )
    remarks: Mapped[str | None] = mapped_column(Text)

    # --- Deterministic conversion (stage 5 input) ------------------------
    quantity_mt: Mapped[Decimal | None] = mapped_column(Quantity)
    conversion_basis: Mapped[str | None] = mapped_column(String(255))

    # --- Deterministic spec match (stage 5) -------------------------------
    # Points at one representative lot of the matched spec (grade + dims);
    # several lots typically share that spec, and `stock_availability` holds
    # the figures aggregated across all of them.
    matched_stock_item_id: Mapped[int | None] = mapped_column(ForeignKey("stock_items.id"))
    match_status: Mapped[MatchStatus] = mapped_column(
        enum_col(MatchStatus), default=MatchStatus.PENDING, nullable=False
    )
    match_score: Mapped[float | None] = mapped_column()
    # Ranked alternatives shown to the reviewer when the match is ambiguous.
    match_candidates: Mapped[list | None] = mapped_column(JSON)

    quotation_request: Mapped[QuotationRequest] = relationship(back_populates="line_items")
    matched_stock_item: Mapped["StockItem | None"] = relationship()  # noqa: F821
    stock_availability: Mapped["StockAvailability | None"] = relationship(
        back_populates="line_item", cascade="all, delete-orphan", uselist=False
    )
    pricing: Mapped["QuotationPricing | None"] = relationship(  # noqa: F821
        back_populates="line_item", cascade="all, delete-orphan", uselist=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<QuotationLineItem q={self.quotation_request_id} #{self.line_no}>"


class StockAvailability(Base, CreatedAtMixin):
    """Output of the deterministic stock-availability check for one line item.

    `breakdown` holds the ordered list of steps with the figure and reason
    each contributed, the same self-documenting pattern the old pricing engine
    used - so "why did the system say this?" (spec section 22) stays
    answerable from stored data alone. `suggested_rate` is always a cost-plus
    suggestion (landed cost + markup), never an approved price list figure -
    the owner reviews or overrides it before anything sends.
    """

    __tablename__ = "stock_availability"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_line_item_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_line_items.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    available_qty_mt: Mapped[Decimal | None] = mapped_column(Quantity)
    available_nop: Mapped[float | None] = mapped_column()
    # None when the requested quantity is unknown - there is nothing to judge
    # sufficiency against, so this is left unanswered rather than guessed.
    sufficient: Mapped[bool | None] = mapped_column()
    # [{"location": str, "balance_qty_mt": float}, ...]
    locations: Mapped[list | None] = mapped_column(JSON)
    ageing_min_days: Mapped[int | None] = mapped_column()
    ageing_max_days: Mapped[int | None] = mapped_column()
    lot_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    suggested_rate: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    unit: Mapped[QuantityUnit] = mapped_column(
        enum_col(QuantityUnit), default=QuantityUnit.MT, nullable=False
    )

    rules_version: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[ConfidenceLevel | None] = mapped_column(enum_col(ConfidenceLevel))
    requires_manual_review: Mapped[bool] = mapped_column(default=False, nullable=False)
    review_reasons: Mapped[list | None] = mapped_column(JSON)
    breakdown: Mapped[list | None] = mapped_column(JSON)
    explanation: Mapped[str | None] = mapped_column(Text)
    stock_as_of: Mapped[date | None] = mapped_column()

    line_item: Mapped[QuotationLineItem] = relationship(back_populates="stock_availability")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<StockAvailability line={self.quotation_line_item_id} {self.available_qty_mt}MT>"


class QuotationDraft(Base, TimestampMixin):
    """A generated reply. Versioned, because regeneration must not destroy
    the previous text a reviewer may have been reading."""

    __tablename__ = "quotation_drafts"
    __table_args__ = (
        UniqueConstraint("quotation_request_id", "version", name="uq_draft_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_request_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(default=True, nullable=False)

    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DraftStatus] = mapped_column(
        enum_col(DraftStatus), default=DraftStatus.GENERATED, nullable=False
    )
    generated_by: Mapped[str | None] = mapped_column(String(120))
    llm_call_id: Mapped[int | None] = mapped_column(ForeignKey("llm_calls.id"))

    quotation_request: Mapped[QuotationRequest] = relationship(back_populates="drafts")
    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<QuotationDraft q={self.quotation_request_id} v{self.version}>"


class FollowUp(Base, CreatedAtMixin):
    """A nudge sent after a quotation went out, chasing a reply.

    Only reachable once a quotation has actually been sent - see
    `FollowUpService.send`, which enforces that the same way `approve_and_send`
    enforces spec Rule 4. Threaded onto the original email's Gmail thread so it
    lands as a continuation of the conversation, not a new message.
    """

    __tablename__ = "follow_ups"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_request_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)
    sent: Mapped[bool] = mapped_column(default=False, nullable=False)
    sent_message_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)

    quotation_request: Mapped[QuotationRequest] = relationship(back_populates="follow_ups")
    user: Mapped["User | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FollowUp q={self.quotation_request_id} sent={self.sent}>"


class Approval(Base, CreatedAtMixin):
    """A recorded human decision.

    Both the original AI text and the final text are stored. The difference
    between them is the edit-rate signal in section 22, and it is the only
    honest record of what the customer actually received versus what the model
    proposed.
    """

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_draft_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[ApprovalAction] = mapped_column(enum_col(ApprovalAction), nullable=False)
    comments: Mapped[str | None] = mapped_column(Text)

    original_subject: Mapped[str | None] = mapped_column(String(500))
    original_body: Mapped[str | None] = mapped_column(Text)
    final_subject: Mapped[str | None] = mapped_column(String(500))
    final_body: Mapped[str | None] = mapped_column(Text)
    was_edited: Mapped[bool] = mapped_column(default=False, nullable=False)

    acted_at: Mapped[datetime | None] = mapped_column()

    draft: Mapped[QuotationDraft] = relationship(back_populates="approvals")
    user: Mapped["User | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Approval {self.action} draft={self.quotation_draft_id}>"
