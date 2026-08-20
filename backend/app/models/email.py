"""Inbound email storage.

The uniqueness constraint on `message_id` is the duplicate-quotation guard
(spec section 10). It is enforced by the database rather than by an
"is this processed?" check in application code, because two poller runs
overlapping in time would both pass such a check.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import (
    EmailCategory,
    EmailSourceType,
    MailDirection,
    ProcessingStatus,
    ReplyIntent,
)
from app.models.mixins import CreatedAtMixin, TenantMixin, TimestampMixin, enum_col


class Email(Base, TimestampMixin, TenantMixin):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Gmail's immutable message id, or a stable hash for locally sourced files.
    message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(255), index=True)
    # RFC 5322 Message-ID header, needed to thread the reply correctly on send.
    rfc822_message_id: Mapped[str | None] = mapped_column(String(400))
    source: Mapped[EmailSourceType] = mapped_column(
        enum_col(EmailSourceType), default=EmailSourceType.LOCAL, nullable=False
    )

    sender_email: Mapped[str | None] = mapped_column(String(255), index=True)
    sender_name: Mapped[str | None] = mapped_column(String(200))
    recipient_email: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(500))
    body_text: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime | None] = mapped_column(index=True)

    has_attachments: Mapped[bool] = mapped_column(default=False, nullable=False)

    # --- Classification outcome (stage 2) --------------------------------
    category: Mapped[EmailCategory | None] = mapped_column(enum_col(EmailCategory), index=True)
    classification_confidence: Mapped[float | None] = mapped_column()
    classification_reason: Mapped[str | None] = mapped_column(Text)

    # --- Reply-to-quotation outcome ---------------------------------------
    # Set only when this email lands on the same Gmail thread as a quotation
    # we already sent (see `QuotationWorkflow._find_replied_quotation`). A
    # separate FK from `quotation_request` below, which is the *original*
    # enquiry email a quotation was created from - a reply is a different
    # email row on the same thread, not that same row.
    replied_to_quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_requests.id"), index=True
    )
    reply_intent: Mapped[ReplyIntent | None] = mapped_column(enum_col(ReplyIntent))
    reply_intent_confidence: Mapped[float | None] = mapped_column()
    reply_intent_reason: Mapped[str | None] = mapped_column(Text)
    #: A date the customer named for coming back, in their own words. Used to
    #: follow up on the day they chose rather than on an arbitrary interval.
    promised_date_raw: Mapped[str | None] = mapped_column(String(120))
    promised_date: Mapped[date | None] = mapped_column()
    #: True when the reply asks something that needs an answer from us.
    awaiting_us: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Cleared once someone has replied or explicitly dismissed it.
    answered_at: Mapped[datetime | None] = mapped_column()

    # --- Pipeline state ---------------------------------------------------
    #: Which way the message went. Outbound mail is stored so the thread is
    #: complete and so a reply sent from Gmail counts as a reply.
    direction: Mapped[MailDirection] = mapped_column(
        enum_col(MailDirection), default=MailDirection.INBOUND, nullable=False, index=True
    )

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        enum_col(ProcessingStatus), default=ProcessingStatus.PENDING, nullable=False, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    processed_at: Mapped[datetime | None] = mapped_column()

    attachments: Mapped[list["EmailAttachment"]] = relationship(
        back_populates="email", cascade="all, delete-orphan"
    )
    quotation_request: Mapped["QuotationRequest | None"] = relationship(  # noqa: F821
        back_populates="email",
        uselist=False,
        foreign_keys="QuotationRequest.email_id",
    )
    replied_to_quotation: Mapped["QuotationRequest | None"] = relationship(  # noqa: F821
        back_populates="replies",
        foreign_keys="Email.replied_to_quotation_id",
    )

    @property
    def full_text(self) -> str:
        """Body plus any text extracted from attachments.

        This is what the classifier and extractor read, so a requirement stated
        only inside a PDF is not invisible to the pipeline.
        """
        parts = [self.body_text or ""]
        for att in self.attachments:
            if att.extracted_text:
                parts.append(f"\n\n--- Attachment: {att.filename} ---\n{att.extracted_text}")
        return "".join(parts).strip()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Email {self.id} {self.subject!r}>"


class EmailAttachment(Base, CreatedAtMixin, TenantMixin):
    """Attachment metadata plus extracted text.

    Extraction failures are recorded rather than raised: an unreadable PDF must
    not lose the enquiry, it must be visible to the reviewer.
    """

    __tablename__ = "email_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_error: Mapped[str | None] = mapped_column(Text)

    email: Mapped[Email] = relationship(back_populates="attachments")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<EmailAttachment {self.filename}>"
