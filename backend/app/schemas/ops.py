"""API shapes for notifications, follow-up rules, stock movement and customers."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    FollowUpStatus,
    FollowUpTrigger,
    LostReason,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
    StockMovementKind,
)
from app.schemas.common import ORMModel

# --- Notifications ---------------------------------------------------------


class NotificationOut(ORMModel):
    id: int
    kind: NotificationKind
    channel: NotificationChannel
    status: NotificationStatus
    title: str
    body: str | None = None
    link: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    error: str | None = None
    created_at: datetime
    sent_at: datetime | None = None
    read_at: datetime | None = None


class NotificationRuleIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    kind: NotificationKind
    channel: NotificationChannel
    is_active: bool = True
    recipient_user_ids: list[int] | None = None
    recipient_emails: list[str] | None = None
    recipient_phones: list[str] | None = None
    conditions: dict[str, Any] | None = None


class NotificationRuleOut(ORMModel):
    id: int
    label: str
    kind: NotificationKind
    channel: NotificationChannel
    is_active: bool
    recipient_user_ids: list[int] | None = None
    recipient_emails: list[str] | None = None
    recipient_phones: list[str] | None = None
    conditions: dict[str, Any] | None = None


# --- Follow-ups ------------------------------------------------------------


class FollowUpRuleIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    is_active: bool = True
    trigger: FollowUpTrigger = FollowUpTrigger.ELAPSED
    #: Hours, so "confirm within 24 hours" is a rule rather than a rounding.
    first_after_hours: int = Field(default=72, ge=1, le=8760)
    #: PROMISED_DATE only: how far ahead of the customer's date to remind.
    remind_before_hours: int = Field(default=0, ge=0, le=720)
    first_after_days: int = Field(default=3, ge=1, le=365)
    interval_days: int = Field(default=5, ge=1, le=365)
    max_attempts: int = Field(default=2, ge=1, le=10)
    stop_after_days: int | None = Field(default=30, ge=1, le=365)
    auto_send: bool = False
    mark_cold_when_exhausted: bool = True
    conditions: dict[str, Any] | None = None
    subject_template: str | None = Field(default=None, max_length=300)
    body_template: str | None = None


class FollowUpRuleOut(ORMModel):
    id: int
    label: str
    is_active: bool
    trigger: FollowUpTrigger
    first_after_hours: int
    remind_before_hours: int
    first_after_days: int
    interval_days: int
    max_attempts: int
    stop_after_days: int | None = None
    auto_send: bool
    mark_cold_when_exhausted: bool
    conditions: dict[str, Any] | None = None
    subject_template: str | None = None
    body_template: str | None = None


class FollowUpScheduleOut(ORMModel):
    id: int
    quotation_request_id: int
    attempt_no: int
    due_at: datetime
    status: FollowUpStatus
    subject: str | None = None
    body: str | None = None
    resolution_note: str | None = None


# --- Stock movement --------------------------------------------------------


class StockMovementIn(BaseModel):
    kind: StockMovementKind
    quantity_kg: Decimal = Field(gt=0)
    stock_item_id: int | None = None
    nop: float | None = None
    location: str | None = Field(default=None, max_length=120)
    rate_per_kg: Decimal | None = None
    reference: str | None = Field(default=None, max_length=120)
    note: str | None = None
    movement_date: date | None = None


class StockMovementOut(ORMModel):
    id: int
    kind: StockMovementKind
    quantity_kg: Decimal
    nop: float | None = None
    product_type: str | None = None
    grade: str | None = None
    thickness_mm: float | None = None
    location: str | None = None
    reference: str | None = None
    note: str | None = None
    movement_date: date | None = None
    is_open: bool
    created_at: datetime


class BalanceOut(BaseModel):
    on_hand_mt: Decimal
    available_mt: Decimal
    reserved_mt: Decimal


# --- Customers -------------------------------------------------------------


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    company: str | None = Field(default=None, max_length=200)
    customer_code: str | None = Field(default=None, max_length=40)
    billing_address: str | None = None
    shipping_address: str | None = None
    default_delivery_location: str | None = Field(default=None, max_length=120)
    tier: str = Field(default="B", pattern="^[ABC]$")
    payment_terms: str | None = Field(default=None, max_length=200)
    is_verified: bool = False


class CustomerNoteIn(BaseModel):
    body: str = Field(min_length=1)
    pinned: bool = False


class CustomerNoteOut(ORMModel):
    id: int
    body: str
    pinned: bool
    created_at: datetime


class TimelineEntry(BaseModel):
    at: datetime
    kind: str
    title: str
    detail: str | None = None
    link: str | None = None


# --- Chase board -----------------------------------------------------------


class ScoreFactorOut(BaseModel):
    """One named multiplier behind a row's ranking.

    Returned so the UI can show its working: a ranking a trader cannot
    interrogate is one he stops trusting, and then he goes back to scrolling
    his inbox.
    """

    label: str
    factor: float


class ChaseRowOut(BaseModel):
    quotation_id: int
    quotation_number: str
    turn: str

    customer_name: str
    customer_email: str | None = None
    contact_name: str | None = None
    customer_note: str
    quotes_total: int
    quotes_won: int

    material: str
    quantity: str
    quoted_rate: float | None = None
    value: float

    reason: str
    next_step: str

    last_at: datetime | None = None
    last_direction: str | None = None
    last_actor: str
    last_subject: str | None = None
    message_count: int

    sent_at: datetime | None = None
    quote_age_days: int
    days_waiting: int
    waiting_note: str
    chase_until: date | None = None
    chase_note: str | None = None

    delivery_location: str | None = None
    required_by: str | None = None
    payment_terms: str | None = None

    stock_note: str | None = None
    stock_short: bool

    promised_date: date | None = None
    promised_words: str | None = None
    snoozed_until: date | None = None
    has_attachment: bool
    attempts: int
    last_chased_at: datetime | None = None
    schedule_id: int | None = None

    value_at_risk: float
    factors: list[ScoreFactorOut]


class ChaseBoardOut(BaseModel):
    """The whole board plus the header figures, in one round trip.

    Counts come from the same rows the list is built from, so a tab's number
    can never disagree with what opening the tab shows.
    """

    rows: list[ChaseRowOut]
    counts: dict[str, int]
    #: Total money sitting in the YOURS bucket - the header sentence.
    value_awaiting_you: float
    quiet_over_a_week: int


class SnoozeIn(BaseModel):
    until: date
    note: str | None = Field(default=None, max_length=300)


class MarkLostIn(BaseModel):
    reason: LostReason
    note: str | None = Field(default=None, max_length=300)


class ChaseSendIn(BaseModel):
    """A follow-up composed in the drawer.

    Subject and body arrive from the screen rather than from a schedule: the
    trader read the thread and edited the draft, so what he saw is what sends.
    """

    subject: str | None = Field(default=None, max_length=500)
    body: str = Field(min_length=1)
    schedule_id: int | None = None


# --- Push devices ----------------------------------------------------------


class PushDeviceIn(BaseModel):
    """A browser registering itself for push.

    Called on every load once permission is granted, not only the first time:
    Firebase rotates tokens whenever it likes, and a desk that only registered
    once would silently stop receiving anything.
    """

    token: str = Field(min_length=16, max_length=512)
    label: str | None = Field(default=None, max_length=120)
    user_agent: str | None = Field(default=None, max_length=300)


class PushDeviceOut(ORMModel):
    id: int
    label: str | None = None
    user_agent: str | None = None
    is_active: bool
    last_seen_at: datetime | None = None
    disabled_reason: str | None = None
    created_at: datetime


class PushStatusOut(BaseModel):
    """Whether push can work at all, so the UI can say why it cannot."""

    configured: bool
    devices: int


class StockImportOut(BaseModel):
    """What one uploaded stock file did.

    Row counts and the per-row reasons are both returned because an import is
    rarely all-or-nothing: a trader needs to see that 412 lots landed *and*
    which three rows were rejected, with the row numbers, so the file can be
    corrected rather than guessed at.
    """

    status: str
    source_file: str
    rows_total: int
    rows_imported: int
    rows_failed: int
    rows_skipped: int
    errors: list[dict[str, Any]] = Field(default_factory=list)
    batch_id: int | None = None
    #: The import replaces the stock table wholesale, which detaches every
    #: quotation line matched to it. Open quotations are re-matched and
    #: re-priced afterwards, and the trader is told how many moved - a silent
    #: repriced book is worse than none, because a draft may now understate.
    quotations_repriced: int = 0
    drafts_to_rewrite: int = 0
