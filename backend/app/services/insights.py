"""Business insight: what the numbers mean, not just what they are.

A count is not an insight. "4 quotations" tells a trader nothing; "4 quotations,
down a third on last month, and the two largest are still unanswered after a
week" tells them what to do this morning.

So everything here is built around three questions:

* **Compared with what?** Every headline carries the same window immediately
  preceding it, like for like - 30 days against 30 days, never against a
  partial period, because that flatters or damns for no reason.
* **Where is the money?** Value concentrated in a handful of quotations is a
  different business from the same value spread across fifty.
* **What needs me?** Quotations going stale, deadstock ageing, customers who
  have gone quiet - the things that cost money by sitting still.

Every figure is counted from stored rows and from the rules in force at the
time, so last quarter's margin does not move when a trader edits a percentage
this morning.
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
    QuotationLineItem,
    QuotationRequest,
    QuotationStatus,
    StockItem,
)

WON = (QuotationStatus.CUSTOMER_ACCEPTED,)
LOST = (QuotationStatus.CUSTOMER_DECLINED,)
SENT_ONWARDS = (
    QuotationStatus.SENT,
    QuotationStatus.CUSTOMER_ACCEPTED,
    QuotationStatus.CUSTOMER_DECLINED,
)
OPEN_STATUSES = (
    QuotationStatus.READY_FOR_REVIEW,
    QuotationStatus.NEEDS_INFORMATION,
    QuotationStatus.EDITED,
    QuotationStatus.APPROVED,
)


def _start(day: date) -> datetime:
    return datetime.combine(day, time.min)


def _end(day: date) -> datetime:
    return datetime.combine(day, time.max)


@dataclass(slots=True)
class Metric:
    """One figure against the same window before it."""

    key: str
    label: str
    current: float
    previous: float
    unit: str = ""
    lower_is_better: bool = False
    hint: str = ""

    @property
    def change_pct(self) -> float | None:
        if self.previous == 0:
            return None if self.current == 0 else 100.0
        return round((self.current - self.previous) / abs(self.previous) * 100, 1)

    @property
    def direction(self) -> str:
        if self.current == self.previous:
            return "flat"
        return "up" if self.current > self.previous else "down"

    @property
    def good(self) -> bool | None:
        """Whether the movement is welcome. None when it is merely neutral."""
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
            "hint": self.hint,
        }


@dataclass(slots=True)
class Insight:
    """A sentence worth putting in front of a person."""

    tone: str  # "good" | "warn" | "bad" | "info"
    title: str
    detail: str
    link: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"tone": self.tone, "title": self.title, "detail": self.detail, "link": self.link}


@dataclass(slots=True)
class Insights:
    period_label: str = ""
    previous_label: str = ""
    metrics: list[Metric] = field(default_factory=list)
    highlights: list[Insight] = field(default_factory=list)
    series: list[dict[str, Any]] = field(default_factory=list)
    by_status: list[dict[str, Any]] = field(default_factory=list)
    top_customers: list[dict[str, Any]] = field(default_factory=list)
    top_products: list[dict[str, Any]] = field(default_factory=list)
    ageing_buckets: list[dict[str, Any]] = field(default_factory=list)
    attention: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_label": self.period_label,
            "previous_label": self.previous_label,
            "metrics": [m.to_dict() for m in self.metrics],
            "highlights": [h.to_dict() for h in self.highlights],
            "series": self.series,
            "by_status": self.by_status,
            "top_customers": self.top_customers,
            "top_products": self.top_products,
            "ageing_buckets": self.ageing_buckets,
            "attention": self.attention,
        }


class InsightService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def build(self, days: int = 30) -> Insights:
        today = date.today()
        start = today - timedelta(days=days - 1)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)

        now = self._snapshot(start, today)
        before = self._snapshot(prev_start, prev_end)

        result = Insights(
            period_label=f"{start:%d %b} – {today:%d %b %Y}",
            previous_label=f"{prev_start:%d %b} – {prev_end:%d %b}",
            metrics=self._metrics(now, before, days),
            series=self._series(start, today, days),
            by_status=self._by_status(start, today),
            top_customers=self._top_customers(start, today),
            top_products=self._top_products(start, today),
            ageing_buckets=self._ageing(),
            attention=self._attention(),
        )
        result.highlights = self._highlights(result, now, before)
        return result

    # --- Headline metrics -------------------------------------------------

    def _metrics(self, now: dict, before: dict, days: int) -> list[Metric]:
        return [
            Metric(
                "quoted_value",
                "Quoted value",
                now["value"],
                before["value"],
                unit="INR",
                hint="Indicative value of everything raised",
            ),
            Metric("enquiries", "Enquiries", now["enquiries"], before["enquiries"]),
            Metric("quotations", "Quotations raised", now["quotations"], before["quotations"]),
            Metric("sent", "Sent to customers", now["sent"], before["sent"]),
            Metric(
                "win_rate",
                "Win rate",
                now["win_rate"],
                before["win_rate"],
                unit="%",
                hint="Of the quotations that got an answer",
            ),
            Metric(
                "avg_value",
                "Average quotation",
                now["avg_value"],
                before["avg_value"],
                unit="INR",
            ),
            Metric(
                "margin_pct",
                "Blended margin",
                now["margin_pct"],
                before["margin_pct"],
                unit="%",
                hint="Quoted against cost, at the rules in force then",
            ),
            Metric(
                "response_hours",
                "Time to quote",
                now["response_hours"],
                before["response_hours"],
                unit="h",
                lower_is_better=True,
                hint="From the enquiry arriving to the reply going out",
            ),
            Metric(
                "override_rate",
                "Prices overridden",
                now["override_rate"],
                before["override_rate"],
                unit="%",
                lower_is_better=True,
                hint="How often a human had to correct the rules",
            ),
        ]

    def _snapshot(self, start: date, end: date) -> dict[str, float]:
        window = (_start(start), _end(end))

        enquiries = (
            self.db.scalar(
                select(func.count())
                .select_from(Email)
                .where(
                    Email.received_at.between(*window),
                    Email.category == EmailCategory.QUOTATION_REQUEST,
                )
            )
            or 0
        )

        quotations = list(
            self.db.scalars(
                select(QuotationRequest).where(QuotationRequest.created_at.between(*window))
            )
        )
        sent = [q for q in quotations if q.status in SENT_ONWARDS]
        won = [q for q in quotations if q.status in WON]
        decided = [q for q in quotations if q.status in WON or q.status in LOST]

        value = sum((_value_of(q) for q in quotations), Decimal(0))

        # Margin and override rate come from the stored build-ups, so they
        # reflect the rules that actually priced each line.
        total_cost = Decimal(0)
        total_quote = Decimal(0)
        lines = 0
        overridden = 0
        for quotation in quotations:
            for item in quotation.line_items:
                pricing = item.pricing
                if not pricing or pricing.quote_rate is None or pricing.total_cost is None:
                    continue
                qty = pricing.quantity_mt or Decimal(0)
                total_cost += pricing.total_cost * qty
                total_quote += pricing.quote_rate * qty
                lines += 1
                if pricing.has_overrides:
                    overridden += 1

        hours: list[float] = []
        for quotation in sent:
            received = quotation.email.received_at if quotation.email else None
            if received and quotation.sent_at:
                hours.append(max((quotation.sent_at - received).total_seconds() / 3600, 0))

        return {
            "enquiries": float(enquiries),
            "quotations": float(len(quotations)),
            "sent": float(len(sent)),
            "won": float(len(won)),
            "value": float(value),
            "avg_value": float(value / len(quotations)) if quotations else 0.0,
            "win_rate": round(len(won) / len(decided) * 100, 1) if decided else 0.0,
            "margin_pct": (
                round(float((total_quote - total_cost) / total_cost * 100), 2)
                if total_cost
                else 0.0
            ),
            "override_rate": round(overridden / lines * 100, 1) if lines else 0.0,
            "response_hours": round(sum(hours) / len(hours), 1) if hours else 0.0,
        }

    # --- Series -----------------------------------------------------------

    def _series(self, start: date, end: date, days: int) -> list[dict[str, Any]]:
        """Daily for a short window, weekly for a long one.

        Ninety daily points is a picket fence; the shape is what matters, so
        the bucket widens with the period rather than the chart getting denser.
        """
        weekly = days > 45
        step = 7 if weekly else 1

        buckets: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            close = min(cursor + timedelta(days=step - 1), end)
            buckets.append(
                {
                    "label": cursor.strftime("%d %b"),
                    "start": cursor.isoformat(),
                    "end": close.isoformat(),
                    "quotations": 0,
                    "sent": 0,
                    "won": 0,
                    "value": 0.0,
                }
            )
            cursor = close + timedelta(days=1)

        for quotation in self.db.scalars(
            select(QuotationRequest).where(
                QuotationRequest.created_at.between(_start(start), _end(end))
            )
        ):
            day = quotation.created_at.date()
            for bucket in buckets:
                if date.fromisoformat(bucket["start"]) <= day <= date.fromisoformat(bucket["end"]):
                    bucket["quotations"] += 1
                    bucket["value"] += float(_value_of(quotation))
                    if quotation.status in SENT_ONWARDS:
                        bucket["sent"] += 1
                    if quotation.status in WON:
                        bucket["won"] += 1
                    break

        return buckets

    def _by_status(self, start: date, end: date) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for quotation in self.db.scalars(
            select(QuotationRequest).where(
                QuotationRequest.created_at.between(_start(start), _end(end))
            )
        ):
            key = quotation.status.value
            counts[key] = counts.get(key, 0) + 1
        return [
            {"label": k.replace("_", " ").title(), "value": v}
            for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
        ]

    # --- Leaderboards -----------------------------------------------------

    def _top_customers(self, start: date, end: date, limit: int = 6) -> list[dict[str, Any]]:
        tally: dict[int, dict[str, Any]] = {}
        for quotation in self.db.scalars(
            select(QuotationRequest).where(
                QuotationRequest.created_at.between(_start(start), _end(end)),
                QuotationRequest.customer_id.is_not(None),
            )
        ):
            entry = tally.setdefault(
                quotation.customer_id,
                {
                    "name": quotation.customer_company_raw
                    or quotation.customer_name_raw
                    or "Unknown",
                    "quotations": 0,
                    "value": 0.0,
                    "won": 0,
                    "lost": 0,
                },
            )
            entry["quotations"] += 1
            entry["value"] += float(_value_of(quotation))
            if quotation.status in WON:
                entry["won"] += 1
            elif quotation.status in LOST:
                entry["lost"] += 1

        rows = sorted(tally.values(), key=lambda r: -r["value"])[:limit]
        for row in rows:
            decided = row["won"] + row["lost"]
            row["win_rate"] = round(row["won"] / decided * 100, 1) if decided else None
        return rows

    def _top_products(self, start: date, end: date, limit: int = 6) -> list[dict[str, Any]]:
        tally: dict[str, dict[str, Any]] = {}
        query = (
            select(QuotationLineItem, QuotationRequest)
            .join(QuotationRequest, QuotationLineItem.quotation_request_id == QuotationRequest.id)
            .where(QuotationRequest.created_at.between(_start(start), _end(end)))
        )
        for item, quotation in self.db.execute(query):
            key = " ".join(filter(None, [item.grade, item.product_type])) or "Unspecified"
            entry = tally.setdefault(
                key, {"name": key, "lines": 0, "quantity_mt": 0.0, "value": 0.0, "won": 0}
            )
            entry["lines"] += 1
            entry["quantity_mt"] += float(item.quantity_mt or 0)
            if item.pricing and item.pricing.line_total:
                entry["value"] += float(item.pricing.line_total)
            if quotation.status in WON:
                entry["won"] += 1

        return sorted(tally.values(), key=lambda r: -r["value"])[:limit]

    # --- Stock ------------------------------------------------------------

    def _ageing(self) -> list[dict[str, Any]]:
        buckets: dict[str, list[float]] = {
            "0-30 days": [0, 0.0],
            "31-60 days": [0, 0.0],
            "61-90 days": [0, 0.0],
            "Over 90 days": [0, 0.0],
        }
        for lot in self.db.scalars(select(StockItem)):
            balance = lot.balance_qty_kg or Decimal(0)
            if balance <= 0:
                continue
            age = lot.ageing_days or 0
            key = (
                "0-30 days"
                if age <= 30
                else "31-60 days"
                if age <= 60
                else "61-90 days"
                if age <= 90
                else "Over 90 days"
            )
            buckets[key][0] += 1
            buckets[key][1] += float(balance) / 1000 * float(lot.landed_cost_per_kg or 0) * 1000

        return [
            {"label": label, "lots": lots, "value": round(value, 2)}
            for label, (lots, value) in buckets.items()
        ]

    # --- What needs a person ---------------------------------------------

    def _attention(self, limit: int = 8) -> list[dict[str, Any]]:
        """Quotations sitting still. Ordered by value, because that is the cost."""
        rows: list[dict[str, Any]] = []
        now = datetime.now()

        for quotation in self.db.scalars(
            select(QuotationRequest).where(QuotationRequest.status.in_(OPEN_STATUSES))
        ):
            created = quotation.created_at
            age_days = max((now - created.replace(tzinfo=None)).days, 0)
            rows.append(
                {
                    "id": quotation.id,
                    "number": quotation.quotation_number,
                    "customer": quotation.customer_company_raw
                    or quotation.customer_name_raw
                    or "Unknown",
                    "status": quotation.status.value,
                    "value": float(_value_of(quotation)),
                    "age_days": age_days,
                    "link": f"/quotations/{quotation.id}",
                }
            )

        return sorted(rows, key=lambda r: (-r["value"], -r["age_days"]))[:limit]

    # --- The sentences ----------------------------------------------------

    def _highlights(self, data: Insights, now: dict, before: dict) -> list[Insight]:
        """Only what is worth saying. An empty list is a valid answer."""
        out: list[Insight] = []

        value = next((m for m in data.metrics if m.key == "quoted_value"), None)
        if value and value.change_pct is not None and abs(value.change_pct) >= 15:
            rising = value.direction == "up"
            out.append(
                Insight(
                    "good" if rising else "warn",
                    f"Quoted value {'up' if rising else 'down'} {abs(value.change_pct):g}%",
                    f"INR {value.current:,.0f} this period against INR {value.previous:,.0f} before it.",
                )
            )

        stalled = [r for r in data.attention if r["age_days"] >= 3]
        if stalled:
            total = sum(r["value"] for r in stalled)
            out.append(
                Insight(
                    "warn",
                    f"{len(stalled)} quotation{'s' if len(stalled) > 1 else ''} waiting three days or more",
                    f"INR {total:,.0f} of indicative value has not gone out yet.",
                    link="/quotations",
                )
            )

        override = next((m for m in data.metrics if m.key == "override_rate"), None)
        if override and override.current >= 25:
            out.append(
                Insight(
                    "warn",
                    f"{override.current:g}% of prices were overridden",
                    "A high override rate usually means the rules are wrong, not that the "
                    "traders are being difficult. Worth revisiting the build-up.",
                    link="/pricing",
                )
            )

        dead = next((b for b in data.ageing_buckets if b["label"] == "Over 90 days"), None)
        if dead and dead["lots"]:
            out.append(
                Insight(
                    "warn",
                    f"{dead['lots']} lots have been held over 90 days",
                    f"INR {dead['value']:,.0f} of stock is not moving.",
                    link="/stock",
                )
            )

        if data.top_customers:
            top = data.top_customers[0]
            total = sum(c["value"] for c in data.top_customers) or 1
            share = top["value"] / total * 100
            if share >= 50 and len(data.top_customers) > 1:
                out.append(
                    Insight(
                        "info",
                        f"{top['name']} is {share:.0f}% of quoted value",
                        "Concentration like this is worth knowing about before it becomes a risk.",
                        link="/customers",
                    )
                )

        response = next((m for m in data.metrics if m.key == "response_hours"), None)
        if response and response.current > 24 and response.current > 0:
            out.append(
                Insight(
                    "warn",
                    f"Quotes are taking {response.current:g} hours on average",
                    "Enquiries answered the same day convert materially better.",
                )
            )

        margin = next((m for m in data.metrics if m.key == "margin_pct"), None)
        if margin and margin.current and margin.change_pct is not None:
            if margin.direction == "down" and abs(margin.change_pct) >= 10:
                out.append(
                    Insight(
                        "bad",
                        f"Blended margin down to {margin.current:g}%",
                        f"It was {margin.previous:g}% in the previous period.",
                        link="/pricing",
                    )
                )

        return out


def _value_of(quotation: QuotationRequest) -> Decimal:
    total = Decimal(0)
    for item in quotation.line_items:
        if item.pricing and item.pricing.line_total:
            total += item.pricing.line_total
    return total


__all__ = ["InsightService", "Insights", "Metric", "Insight"]
