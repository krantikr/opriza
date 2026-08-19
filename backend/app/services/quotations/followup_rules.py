"""Deciding when a quotation is owed a nudge.

The scheduler's only job is to work out that a follow-up is **due** and to draft
it. Sending remains a human action, exactly as `approve_and_send` does for the
quotation itself - `FollowUpService.send` is still the only function that mails
a customer, and it still refuses anything that is not `SENT`.

`FollowUpRule.auto_send` exists for the desk that eventually wants unattended
chasing, but it is opt-in per rule and asserted against here rather than being
a global switch someone flips without noticing the consequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import utcnow
from app.core.logging import get_logger
from app.models import (
    FollowUpRule,
    FollowUpSchedule,
    FollowUpStatus,
    QuotationRequest,
    QuotationStatus,
)
from app.services import audit
from app.services.notifications.service import NotificationService

logger = get_logger(__name__)

#: A quotation stops being chased the moment the customer engages, whatever
#: they said. Chasing someone who already replied is the fastest way to make
#: an automated system look broken.
SETTLED_STATUSES = (
    QuotationStatus.CUSTOMER_ACCEPTED,
    QuotationStatus.CUSTOMER_DECLINED,
    QuotationStatus.REJECTED,
)


@dataclass(slots=True)
class SchedulerResult:
    scheduled: list[FollowUpSchedule] = field(default_factory=list)
    due: list[FollowUpSchedule] = field(default_factory=list)
    cancelled: list[FollowUpSchedule] = field(default_factory=list)
    marked_cold: int = 0

    def summary(self) -> str:
        return (
            f"scheduled={len(self.scheduled)} due={len(self.due)} "
            f"cancelled={len(self.cancelled)} cold={self.marked_cold}"
        )


class FollowUpScheduler:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.notifications = NotificationService(db)

    # --- Public -----------------------------------------------------------

    def run(self) -> SchedulerResult:
        """One pass: cancel what is settled, schedule what is owed, mark due."""
        result = SchedulerResult()
        if not settings.follow_ups_enabled:
            return result

        rules = list(
            self.db.scalars(select(FollowUpRule).where(FollowUpRule.is_active.is_(True)))
        )
        if not rules:
            return result

        self._cancel_settled(result)

        for quotation in self._chaseable():
            rule = self._rule_for(quotation, rules)
            if rule is None:
                continue
            self._schedule_next(quotation, rule, result)

        self._mark_due(result)
        self.db.commit()

        if result.scheduled or result.due or result.cancelled:
            logger.info("Follow-up scheduler: %s", result.summary())
        return result

    def schedule_for(self, quotation: QuotationRequest) -> FollowUpSchedule | None:
        """Schedule the first nudge for a quotation that has just gone out."""
        rules = list(
            self.db.scalars(select(FollowUpRule).where(FollowUpRule.is_active.is_(True)))
        )
        rule = self._rule_for(quotation, rules)
        if rule is None:
            return None
        result = SchedulerResult()
        schedule = self._schedule_next(quotation, rule, result)
        self.db.commit()
        return schedule

    def cancel_for(self, quotation: QuotationRequest, reason: str) -> int:
        """Stop chasing - the customer replied, or a human closed it."""
        pending = [
            s
            for s in quotation.follow_up_schedules
            if s.status in (FollowUpStatus.SCHEDULED, FollowUpStatus.DUE)
        ]
        for schedule in pending:
            schedule.status = FollowUpStatus.CANCELLED
            schedule.resolved_at = utcnow()
            schedule.resolution_note = reason
        if pending:
            self.db.commit()
        return len(pending)

    # --- Internals --------------------------------------------------------

    def _chaseable(self) -> list[QuotationRequest]:
        """Quotations that have been sent and have heard nothing back."""
        return list(
            self.db.scalars(
                select(QuotationRequest).where(
                    QuotationRequest.status == QuotationStatus.SENT,
                    QuotationRequest.sent_at.is_not(None),
                )
            )
        )

    def _cancel_settled(self, result: SchedulerResult) -> None:
        pending = list(
            self.db.scalars(
                select(FollowUpSchedule).where(
                    FollowUpSchedule.status.in_(
                        [FollowUpStatus.SCHEDULED, FollowUpStatus.DUE]
                    )
                )
            )
        )
        for schedule in pending:
            quotation = schedule.quotation_request
            if quotation is None or quotation.status in SETTLED_STATUSES:
                schedule.status = FollowUpStatus.CANCELLED
                schedule.resolved_at = utcnow()
                schedule.resolution_note = "The customer replied, so chasing stopped."
                result.cancelled.append(schedule)

    def _schedule_next(
        self, quotation: QuotationRequest, rule: FollowUpRule, result: SchedulerResult
    ) -> FollowUpSchedule | None:
        # Queried rather than read off the relationship: within one scheduler
        # pass a nudge may already have been added and promoted to DUE, and a
        # stale collection would let a duplicate through.
        schedules = list(
            self.db.scalars(
                select(FollowUpSchedule).where(
                    FollowUpSchedule.quotation_request_id == quotation.id
                )
            )
        )

        # Never queue a second nudge while one is still waiting to be sent.
        if any(s.status in (FollowUpStatus.SCHEDULED, FollowUpStatus.DUE) for s in schedules):
            return None

        sent = [s for s in schedules if s.status is FollowUpStatus.SENT]
        attempt = len(sent) + 1

        if attempt > rule.max_attempts:
            if rule.mark_cold_when_exhausted and quotation.status is QuotationStatus.SENT:
                # The pipeline should reflect reality: this one has gone quiet.
                quotation.review_notes = _append_note(
                    quotation.review_notes,
                    f"No reply after {len(sent)} follow-up(s); treated as cold.",
                )
                result.marked_cold += 1
            return None

        anchor = sent[-1].resolved_at if sent else quotation.sent_at
        if anchor is None:
            return None

        delay = rule.first_after_days if attempt == 1 else rule.interval_days
        due_at = anchor + timedelta(days=delay)

        if rule.stop_after_days is not None:
            deadline = quotation.sent_at + timedelta(days=rule.stop_after_days)
            if due_at > deadline:
                return None

        schedule = FollowUpSchedule(
            quotation_request_id=quotation.id,
            rule_id=rule.id,
            attempt_no=attempt,
            due_at=due_at,
            status=FollowUpStatus.SCHEDULED,
        )
        self.db.add(schedule)
        self.db.flush()
        result.scheduled.append(schedule)
        return schedule

    def _mark_due(self, result: SchedulerResult) -> None:
        """Promote scheduled nudges whose time has come, and draft them."""
        from app.services.quotations.followup import default_body, default_subject

        now = utcnow()
        ready = list(
            self.db.scalars(
                select(FollowUpSchedule).where(
                    FollowUpSchedule.status == FollowUpStatus.SCHEDULED,
                    FollowUpSchedule.due_at <= now,
                )
            )
        )

        for schedule in ready:
            quotation = schedule.quotation_request
            if quotation is None or quotation.status is not QuotationStatus.SENT:
                continue

            rule = schedule.rule
            schedule.status = FollowUpStatus.DUE
            schedule.subject = _render(
                rule.subject_template if rule else None, quotation
            ) or default_subject(quotation)
            schedule.body = _render(
                rule.body_template if rule else None, quotation
            ) or default_body(quotation)

            audit.record(
                self.db,
                entity_type="quotation_request",
                entity_id=quotation.id,
                action="FOLLOW_UP_DUE",
                details={
                    "quotation_number": quotation.quotation_number,
                    "attempt": schedule.attempt_no,
                    "rule": rule.label if rule else None,
                },
            )
            self.notifications.follow_up_due(quotation, schedule.attempt_no)
            result.due.append(schedule)

    @staticmethod
    def _rule_for(
        quotation: QuotationRequest, rules: list[FollowUpRule]
    ) -> FollowUpRule | None:
        """The first rule whose conditions the quotation satisfies."""
        for rule in rules:
            conditions = rule.conditions or {}
            if not conditions:
                return rule

            tiers = conditions.get("customer_tier")
            if tiers:
                tier = quotation.customer.tier.value if quotation.customer else None
                if not tier or tier not in tiers:
                    continue

            min_value = conditions.get("min_value")
            if min_value is not None:
                total = sum(
                    (item.pricing.line_total or 0)
                    for item in quotation.line_items
                    if item.pricing is not None
                )
                if total < min_value:
                    continue

            return rule
        return None


def _render(template: str | None, quotation: QuotationRequest) -> str | None:
    """Fill a trader's template. Unknown placeholders are left alone."""
    if not template:
        return None
    values = {
        "quotation_number": quotation.quotation_number,
        "customer_name": quotation.customer_name_raw or "there",
        "customer_company": quotation.customer_company_raw or "",
        "sent_date": quotation.sent_at.strftime("%d %b %Y") if quotation.sent_at else "recently",
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def _append_note(existing: str | None, note: str) -> str:
    return f"{existing}\n{note}" if existing else note


__all__ = ["FollowUpScheduler", "SchedulerResult"]
