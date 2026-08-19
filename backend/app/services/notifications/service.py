"""Raising notifications from workflow events.

One rule governs everything here: **a notification must never be able to break
the thing it is reporting on.** Every delivery failure is recorded on the row
and swallowed, because an enquiry that processed correctly but could not be
announced is a delivery problem, not a processing failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import utcnow
from app.core.logging import get_logger
from app.models import (
    ConfidenceLevel,
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationRule,
    NotificationStatus,
    QuotationRequest,
    RecordStatus,
    User,
)
from app.services.notifications.channels import get_channel

logger = get_logger(__name__)

CONFIDENCE_ORDER = {ConfidenceLevel.LOW: 0, ConfidenceLevel.MEDIUM: 1, ConfidenceLevel.HIGH: 2}


@dataclass(slots=True)
class NotifyResult:
    raised: list[Notification] = field(default_factory=list)

    @property
    def sent(self) -> int:
        return sum(1 for n in self.raised if n.status is NotificationStatus.SENT)

    @property
    def failed(self) -> int:
        return sum(1 for n in self.raised if n.status is NotificationStatus.FAILED)


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Public -----------------------------------------------------------

    def notify(
        self,
        kind: NotificationKind,
        *,
        title: str,
        body: str | None = None,
        link: str | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        context: dict | None = None,
    ) -> NotifyResult:
        """Raise one event across every rule that wants it."""
        result = NotifyResult()
        if not settings.notifications_enabled:
            return result

        rules = list(
            self.db.scalars(
                select(NotificationRule).where(
                    NotificationRule.kind == kind,
                    NotificationRule.is_active.is_(True),
                )
            )
        )
        if not rules:
            # No rule configured means the in-app record is still written, so
            # the dashboard bell works out of the box on a fresh install.
            rules = [NotificationRule(label="default", kind=kind, channel=NotificationChannel.IN_APP)]

        for rule in rules:
            if not self._conditions_hold(rule, context or {}):
                continue
            for destination, user_id in self._recipients(rule):
                result.raised.append(
                    self._deliver(
                        rule=rule,
                        destination=destination,
                        user_id=user_id,
                        title=title,
                        body=body,
                        link=link,
                        entity_type=entity_type,
                        entity_id=entity_id,
                    )
                )

        self.db.commit()
        return result

    def quotation_ready(self, quotation: QuotationRequest) -> NotifyResult:
        """An enquiry has been processed and is waiting for a human."""
        customer = quotation.customer_company_raw or quotation.customer_name_raw or "an enquiry"
        value = _headline_value(quotation)
        body_lines = [
            f"{quotation.quotation_number} from {customer} is ready for review.",
        ]
        if value:
            body_lines.append(f"Indicative value: {value}")
        if quotation.review_notes:
            body_lines.append(quotation.review_notes)

        return self.notify(
            NotificationKind.QUOTATION_READY,
            title=f"Quotation ready: {quotation.quotation_number}",
            body="\n".join(body_lines),
            link=f"/quotations/{quotation.id}",
            entity_type="quotation_request",
            entity_id=quotation.id,
            context={"confidence": quotation.confidence, "quotation": quotation},
        )

    def new_enquiry(self, quotation: QuotationRequest) -> NotifyResult:
        customer = quotation.customer_company_raw or quotation.customer_name_raw or "a new sender"
        return self.notify(
            NotificationKind.NEW_ENQUIRY,
            title=f"New enquiry from {customer}",
            body=(quotation.email.subject if quotation.email else None),
            link=f"/quotations/{quotation.id}",
            entity_type="quotation_request",
            entity_id=quotation.id,
            context={"confidence": quotation.confidence, "quotation": quotation},
        )

    def customer_replied(self, quotation: QuotationRequest, intent: str) -> NotifyResult:
        return self.notify(
            NotificationKind.CUSTOMER_REPLIED,
            title=f"{quotation.quotation_number}: customer {intent.lower()}",
            body=f"The customer replied on {quotation.quotation_number}.",
            link=f"/quotations/{quotation.id}",
            entity_type="quotation_request",
            entity_id=quotation.id,
        )

    def follow_up_due(self, quotation: QuotationRequest, attempt: int) -> NotifyResult:
        return self.notify(
            NotificationKind.FOLLOW_UP_DUE,
            title=f"Follow-up due: {quotation.quotation_number}",
            body=(
                f"Attempt {attempt} on {quotation.quotation_number} is due and waiting "
                "for you to send it."
            ),
            link=f"/quotations/{quotation.id}",
            entity_type="quotation_request",
            entity_id=quotation.id,
        )

    def mark_read(self, notification_id: int, user_id: int | None = None) -> Notification | None:
        row = self.db.get(Notification, notification_id)
        if row is None:
            return None
        row.read_at = utcnow()
        row.status = NotificationStatus.READ
        self.db.commit()
        return row

    def mark_all_read(self, user_id: int | None = None) -> int:
        query = select(Notification).where(Notification.read_at.is_(None))
        if user_id is not None:
            query = query.where(Notification.user_id == user_id)
        rows = list(self.db.scalars(query))
        for row in rows:
            row.read_at = utcnow()
            row.status = NotificationStatus.READ
        self.db.commit()
        return len(rows)

    def unread_count(self, user_id: int | None = None) -> int:
        from sqlalchemy import func

        query = select(func.count()).select_from(Notification).where(
            Notification.read_at.is_(None),
            Notification.channel == NotificationChannel.IN_APP,
        )
        if user_id is not None:
            query = query.where(Notification.user_id == user_id)
        return self.db.scalar(query) or 0

    # --- Internals --------------------------------------------------------

    def _deliver(
        self,
        *,
        rule: NotificationRule,
        destination: str | None,
        user_id: int | None,
        title: str,
        body: str | None,
        link: str | None,
        entity_type: str | None,
        entity_id: int | None,
    ) -> Notification:
        notification = Notification(
            rule_id=rule.id,
            user_id=user_id,
            kind=rule.kind,
            channel=rule.channel,
            title=title[:200],
            body=body,
            link=link,
            entity_type=entity_type,
            entity_id=entity_id,
            destination=destination,
        )

        channel = get_channel(rule.channel)
        outcome = channel.send(destination=destination or "", title=title, body=body or "")

        notification.status = NotificationStatus.SENT if outcome.sent else NotificationStatus.FAILED
        notification.provider_message_id = outcome.provider_message_id
        notification.destination = outcome.destination or destination
        notification.error = outcome.error
        if outcome.sent:
            notification.sent_at = utcnow()
        else:
            logger.warning("Notification %s failed: %s", rule.kind, outcome.error)

        self.db.add(notification)
        self.db.flush()
        return notification

    def _recipients(self, rule: NotificationRule) -> list[tuple[str | None, int | None]]:
        """Who this rule reaches, as (destination, user_id) pairs."""
        if rule.channel is NotificationChannel.IN_APP:
            users = self._target_users(rule)
            return [(None, u.id) for u in users] or [(None, None)]

        if rule.channel is NotificationChannel.EMAIL:
            explicit = [(e, None) for e in (rule.recipient_emails or [])]
            if explicit:
                return explicit
            return [(u.email, u.id) for u in self._target_users(rule) if u.email]

        explicit_phones = [(p, None) for p in (rule.recipient_phones or [])]
        return explicit_phones

    def _target_users(self, rule: NotificationRule) -> list[User]:
        """Named users, or every active user when none are named.

        Resolving "everyone" at send time means a new joiner is covered without
        anyone having to remember to edit each rule.
        """
        ids = rule.recipient_user_ids or []
        query = select(User).where(User.status == RecordStatus.ACTIVE)
        if ids:
            query = query.where(User.id.in_(ids))
        return list(self.db.scalars(query))

    @staticmethod
    def _conditions_hold(rule: NotificationRule, context: dict) -> bool:
        conditions = rule.conditions or {}
        if not conditions:
            return True

        # "Only tell me when it needs attention" - the most useful filter a
        # trading desk has, since a HIGH-confidence quote needs no interruption.
        max_confidence = conditions.get("max_confidence")
        confidence = context.get("confidence")
        if max_confidence and confidence is not None:
            ceiling = CONFIDENCE_ORDER.get(ConfidenceLevel(max_confidence), 2)
            if CONFIDENCE_ORDER.get(confidence, 2) > ceiling:
                return False

        return True


def _headline_value(quotation: QuotationRequest) -> str | None:
    total = None
    for item in quotation.line_items:
        pricing = item.pricing
        if pricing and pricing.line_total is not None:
            total = (total or 0) + pricing.line_total
    return f"INR {total:,.2f}" if total else None


__all__ = ["NotificationService", "NotifyResult"]
