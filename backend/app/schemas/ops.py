"""API shapes for notifications, follow-up rules, stock movement and customers."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    FollowUpStatus,
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
