"""Time series and period-over-period comparison for the dashboard.

Two separate questions a desk asks every morning, answered from stored rows:

* **"What is the shape of the last N days?"** - a daily series, gap-filled, so
  a chart does not silently skip the quiet days and misrepresent the trend.
* **"Is that better or worse than before?"** - the same window immediately
  preceding, compared like for like. A 30-day figure against a 30-day figure,
  never against a partial period, because that flatters or damns unfairly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Email,
    EmailCategory,
    QuotationRequest,
    QuotationStatus,
)

WON = (QuotationStatus.CUSTOMER_ACCEPTED,)
LOST = (QuotationStatus.CUSTOMER_DECLINED,)
SENT_ONWARDS = (
    QuotationStatus.SENT,
    QuotationStatus.CUSTOMER_ACCEPTED,
    QuotationStatus.CUSTOMER_DECLINED,
)


@dataclass(slots=True)
class Point:
    day: str
    enquiries: int = 0
    quotations: int = 0
    sent: int = 0
    won: int = 0
    value: Decimal = Decimal(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "enquiries": self.enquiries,
            "quotations": self.quotations,
            "sent": self.sent,
            "won": self.won,
            "value": str(self.value),
        }


@dataclass(slots=True)
class Delta:
    """One metric, this period against the last."""

    key: str
    label: str
    current: float
    previous: float
    #: True when a fall is the good direction (e.g. time to first reply).
    lower_is_better: bool = False
    unit: str = ""

    @property
    def change_pct(self) -> float | None:
        if self.previous == 0:
            return None if self.current == 0 else 100.0
        return round((self.current - self.previous) / abs(self.previous) * 100, 1)

    @property
    def direction(self) -> str:
        """`up`, `down` or `flat` - the movement, not the judgement."""
        if self.current == self.previous:
            return "flat"
        return "up" if self.current > self.previous else "down"

    @property
    def good(self) -> bool | None:
        """Whether the movement is the welcome one. None when it is neutral."""
        if self.direction == "flat":
            return None
        rising = self.direction == "up"
        return not rising if self.lower_is_better else rising

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "current": self.current,
            "previous": self.previous,
            "change_pct": self.change_pct,
            "direction": self.direction,
            "good": self.good,
            "unit": self.unit,
        }


@dataclass(slots=True)
class Trends:
    days: int
    series: list[Point] = field(default_factory=list)
    deltas: list[Delta] = field(default_factory=list)
    period_label: str = ""
    previous_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "period_label": self.period_label,
            "previous_label": self.previous_label,
            "series": [p.to_dict() for p in self.series],
            "deltas": [d.to_dict() for d in self.deltas],
        }


class TrendService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def build(self, days: int = 30) -> Trends:
        today = date.today()
        start = today - timedelta(days=days - 1)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)

        trends = Trends(
            days=days,
            series=self._series(start, today),
            period_label=f"{start:%d %b} – {today:%d %b}",
            previous_label=f"{prev_start:%d %b} – {prev_end:%d %b}",
        )
        trends.deltas = self._deltas(start, today, prev_start, prev_end)
        return trends

    # --- Series -----------------------------------------------------------

    def _series(self, start: date, end: date) -> list[Point]:
        """One point per day, including the days nothing happened.

        Gap-filling matters: a chart drawn only from days with rows shows a
        continuous line where there was actually a weekend of silence.
        """
        buckets: dict[str, Point] = {}
        day = start
        while day <= end:
            key = day.isoformat()
            buckets[key] = Point(day=key)
            day += timedelta(days=1)

        window = (_start_of(start), _end_of(end))

        for received, category in self.db.execute(
            select(Email.received_at, Email.category).where(Email.received_at.between(*window))
        ):
            if received is None:
                continue
            point = buckets.get(received.date().isoformat())
            if point and category is EmailCategory.QUOTATION_REQUEST:
                point.enquiries += 1

        for quotation in self.db.scalars(
            select(QuotationRequest).where(QuotationRequest.created_at.between(*window))
        ):
            point = buckets.get(quotation.created_at.date().isoformat())
            if point is None:
                continue
            point.quotations += 1
            point.value += _value_of(quotation)

        for quotation in self.db.scalars(
            select(QuotationRequest).where(
                QuotationRequest.sent_at.is_not(None),
                QuotationRequest.sent_at.between(*window),
            )
        ):
            point = buckets.get(quotation.sent_at.date().isoformat())
            if point is None:
                continue
            point.sent += 1
            if quotation.status in WON:
                point.won += 1

        return list(buckets.values())

    # --- Comparison -------------------------------------------------------

    def _deltas(
        self, start: date, end: date, prev_start: date, prev_end: date
    ) -> list[Delta]:
        now = self._snapshot(start, end)
        before = self._snapshot(prev_start, prev_end)

        return [
            Delta("enquiries", "Enquiries", now["enquiries"], before["enquiries"]),
            Delta("quotations", "Quotations raised", now["quotations"], before["quotations"]),
            Delta("sent", "Quotations sent", now["sent"], before["sent"]),
            Delta("won", "Deals won", now["won"], before["won"]),
            Delta(
                "value",
                "Quoted value",
                now["value"],
                before["value"],
                unit="INR",
            ),
            Delta("win_rate", "Win rate", now["win_rate"], before["win_rate"], unit="%"),
            Delta(
                "response_hours",
                "Time to quote",
                now["response_hours"],
                before["response_hours"],
                lower_is_better=True,
                unit="h",
            ),
        ]

    def _snapshot(self, start: date, end: date) -> dict[str, float]:
        window = (_start_of(start), _end_of(end))

        enquiries = self.db.scalar(
            select(func.count())
            .select_from(Email)
            .where(
                Email.received_at.between(*window),
                Email.category == EmailCategory.QUOTATION_REQUEST,
            )
        ) or 0

        quotations = list(
            self.db.scalars(
                select(QuotationRequest).where(QuotationRequest.created_at.between(*window))
            )
        )
        sent = [q for q in quotations if q.status in SENT_ONWARDS]
        won = [q for q in quotations if q.status in WON]
        decided = [q for q in quotations if q.status in WON or q.status in LOST]

        value = sum((_value_of(q) for q in quotations), Decimal(0))

        # How long a customer waited between writing in and being quoted.
        hours: list[float] = []
        for quotation in sent:
            received = quotation.email.received_at if quotation.email else None
            if received and quotation.sent_at:
                delta = quotation.sent_at - received
                hours.append(max(delta.total_seconds() / 3600, 0))

        return {
            "enquiries": float(enquiries),
            "quotations": float(len(quotations)),
            "sent": float(len(sent)),
            "won": float(len(won)),
            "value": float(value),
            "win_rate": round(len(won) / len(decided) * 100, 1) if decided else 0.0,
            "response_hours": round(sum(hours) / len(hours), 1) if hours else 0.0,
        }


def _value_of(quotation: QuotationRequest) -> Decimal:
    total = Decimal(0)
    for item in quotation.line_items:
        if item.pricing and item.pricing.line_total:
            total += item.pricing.line_total
    return total


def _start_of(day: date) -> datetime:
    return datetime.combine(day, time.min)


def _end_of(day: date) -> datetime:
    return datetime.combine(day, time.max)


__all__ = ["TrendService", "Trends", "Point", "Delta"]
