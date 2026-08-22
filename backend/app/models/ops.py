"""Operational tables: notifications, follow-up rules, stock movement.

These three are grouped because they share a shape - each is a rule the trader
configures plus the record of what that rule caused. Keeping the configuration
and its consequences adjacent is what makes "why did this happen?" answerable
without reading application code.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import (
    FollowUpStatus,
    FollowUpTrigger,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
    RecordStatus,
    StockMovementKind,
)
from app.models.mixins import CreatedAtMixin, TenantMixin, TimestampMixin, enum_col
from app.models.types import Money, Quantity

# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class NotificationRule(Base, TimestampMixin, TenantMixin):
    """Who gets told about what, on which channel.

    Kept as data rather than settings so a trading desk can route its own
    traffic - the owner on WhatsApp for a new enquiry, the whole team by email
    for the morning digest - without a deployment.
    """

    __tablename__ = "notification_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[NotificationKind] = mapped_column(enum_col(NotificationKind), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_col(NotificationChannel), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Explicit destinations. Empty means "every active user", resolved at send
    # time so a new joiner is covered without editing every rule.
    recipient_user_ids: Mapped[list | None] = mapped_column(JSON)
    recipient_emails: Mapped[list | None] = mapped_column(JSON)
    recipient_phones: Mapped[list | None] = mapped_column(JSON)

    # e.g. {"min_confidence": "LOW"} - only notify when it needs attention.
    conditions: Mapped[dict | None] = mapped_column(JSON)
    quiet_hours: Mapped[dict | None] = mapped_column(JSON)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<NotificationRule {self.kind}/{self.channel}>"


class Notification(Base, CreatedAtMixin, TenantMixin):
    """One message raised for one person on one channel.

    Written even when delivery fails, because a notification nobody received is
    exactly the thing an operator needs to be able to see.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_unread", "user_id", "read_at"),
        Index("ix_notifications_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("notification_rules.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"), index=True)

    kind: Mapped[NotificationKind] = mapped_column(enum_col(NotificationKind), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_col(NotificationChannel), default=NotificationChannel.IN_APP, nullable=False
    )
    status: Mapped[NotificationStatus] = mapped_column(
        enum_col(NotificationStatus), default=NotificationStatus.PENDING, nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))

    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[int | None] = mapped_column(Integer)

    destination: Mapped[str | None] = mapped_column(String(255))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)

    sent_at: Mapped[datetime | None] = mapped_column()
    read_at: Mapped[datetime | None] = mapped_column()

    user: Mapped["User | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Notification {self.kind}/{self.channel} {self.status}>"


class PushDevice(Base, TimestampMixin, TenantMixin):
    """A browser or phone registered to receive push notifications.

    One row per *device*, not per user: a trader with a phone and a desk
    machine expects the buzz on both, and Firebase issues a separate
    registration token for each.

    Tokens rotate. Firebase reissues one whenever the browser decides to -
    a reinstall, a cleared cache, a long absence - so the token is the
    natural key and `last_seen_at` is refreshed on every registration. A
    token Firebase reports as dead is deactivated rather than deleted, so
    "why did this device stop buzzing" stays answerable.
    """

    __tablename__ = "push_devices"
    __table_args__ = (
        UniqueConstraint("organisation_id", "token", name="uq_push_device_token"),
        Index("ix_push_devices_user", "user_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The FCM registration token. Long, and not a secret in the usual sense,
    #: but it addresses a specific device so it is not shown in the UI.
    token: Mapped[str] = mapped_column(String(512), nullable=False)

    #: For the Settings list, so a person can tell which device is which
    #: before turning one off.
    label: Mapped[str | None] = mapped_column(String(120))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column()
    #: Why it stopped: the provider's own words, kept for diagnosis.
    disabled_reason: Mapped[str | None] = mapped_column(String(300))

    user: Mapped["User"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PushDevice user={self.user_id} {'active' if self.is_active else 'off'}>"


# ---------------------------------------------------------------------------
# Follow-ups
# ---------------------------------------------------------------------------


class FollowUpRule(Base, TimestampMixin, TenantMixin):
    """When to chase a quotation that has gone quiet.

    Two shapes of rule, because a desk needs both:

    * **Elapsed** - "chase 24 hours after sending, then every 5 days". Timed
      from when the quotation went out, and measured in *hours* so a same-day
      confirmation is expressible; a day is just 24 of them.
    * **Promised date** - "the customer said they would decide on the 14th, so
      remind me on the 14th". Timed from what the customer actually said,
      which is a far better moment to call than an arbitrary interval.

    `auto_send` exists and defaults to False on purpose. The rule decides
    *when* a nudge is owed and drafts it; a human still presses send. Turning
    it on is a deliberate, per-rule, auditable choice - not a global setting
    someone flips without noticing that the system now mails customers on its
    own.
    """

    __tablename__ = "follow_up_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    trigger: Mapped[FollowUpTrigger] = mapped_column(
        enum_col(FollowUpTrigger), default=FollowUpTrigger.ELAPSED, nullable=False
    )
    #: Hours after sending before the first nudge. Kept in hours rather than
    #: days so "confirm within 24 hours" is a rule, not an approximation.
    first_after_hours: Mapped[int] = mapped_column(Integer, default=72, nullable=False)
    #: For PROMISED_DATE: how long before the date the reminder is raised.
    #: Zero means on the day itself.
    remind_before_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    first_after_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    stop_after_days: Mapped[int | None] = mapped_column(Integer, default=30)

    auto_send: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Marked cold once the attempts are spent, so the pipeline reflects reality.
    mark_cold_when_exhausted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # e.g. {"min_value": 100000, "customer_tier": ["A"]}
    conditions: Mapped[dict | None] = mapped_column(JSON)
    subject_template: Mapped[str | None] = mapped_column(String(300))
    body_template: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FollowUpRule {self.label} +{self.first_after_days}d x{self.max_attempts}>"


class FollowUpSchedule(Base, TimestampMixin, TenantMixin):
    """A nudge a rule says is owed, waiting for a human to send it."""

    __tablename__ = "follow_up_schedules"
    __table_args__ = (Index("ix_follow_up_due", "status", "due_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_request_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("follow_up_rules.id"))
    follow_up_id: Mapped[int | None] = mapped_column(ForeignKey("follow_ups.id"))

    attempt_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    due_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    status: Mapped[FollowUpStatus] = mapped_column(
        enum_col(FollowUpStatus), default=FollowUpStatus.SCHEDULED, nullable=False, index=True
    )

    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)

    resolved_at: Mapped[datetime | None] = mapped_column()
    resolution_note: Mapped[str | None] = mapped_column(String(300))

    quotation_request: Mapped["QuotationRequest"] = relationship(  # noqa: F821
        back_populates="follow_up_schedules"
    )
    rule: Mapped[FollowUpRule | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FollowUpSchedule q={self.quotation_request_id} #{self.attempt_no} {self.status}>"


# ---------------------------------------------------------------------------
# Stock movement
# ---------------------------------------------------------------------------


class StockMovement(Base, CreatedAtMixin, TenantMixin):
    """A change in stock that did not come from re-importing the sheet.

    The stock import replaces the table wholesale, because the file is a full
    snapshot. Movements are therefore kept *separately* and replayed on top of
    the imported balance, rather than mutating `StockItem.balance_qty_kg` - if
    they mutated it, the next import would silently erase every receipt and
    reservation recorded since.
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_item", "stock_item_id", "created_at"),
        Index("ix_stock_movements_spec", "product_type", "grade", "thickness_mm"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_item_id: Mapped[int | None] = mapped_column(ForeignKey("stock_items.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"))

    kind: Mapped[StockMovementKind] = mapped_column(enum_col(StockMovementKind), nullable=False)
    # Signed: positive adds to balance, negative removes. Stored in kg to match
    # the stock sheet's own unit and avoid a conversion at every read.
    quantity_kg: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    nop: Mapped[float | None] = mapped_column()

    # Denormalised so a movement survives the wholesale re-import that will
    # replace the `stock_items` row it originally pointed at.
    product_type: Mapped[str | None] = mapped_column(String(80), index=True)
    grade: Mapped[str | None] = mapped_column(String(60), index=True)
    thickness_mm: Mapped[float | None] = mapped_column()
    width_mm: Mapped[float | None] = mapped_column()
    length_mm: Mapped[float | None] = mapped_column()
    diameter_mm: Mapped[float | None] = mapped_column()
    location: Mapped[str | None] = mapped_column(String(120))

    rate_per_kg: Mapped[Decimal | None] = mapped_column(Money)
    reference: Mapped[str | None] = mapped_column(String(120))
    quotation_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_requests.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    movement_date: Mapped[date | None] = mapped_column()

    # A reservation stops counting once it is released or converted.
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<StockMovement {self.kind} {self.quantity_kg}kg>"


class CustomerNote(Base, TimestampMixin, TenantMixin):
    """A dated note against a customer - the interaction timeline."""

    __tablename__ = "customer_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[RecordStatus] = mapped_column(
        enum_col(RecordStatus), default=RecordStatus.ACTIVE, nullable=False
    )

    user: Mapped["User | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CustomerNote c={self.customer_id}>"


__all__ = [
    "NotificationRule",
    "Notification",
    "FollowUpRule",
    "FollowUpSchedule",
    "StockMovement",
    "CustomerNote",
]
