"""Reports over the enquiry pipeline, stock and customers.

Every figure here is counted from stored rows, never recomputed from live
rules. A quotation priced under rules v3 is reported at the margin it actually
carried, not at what today's rules would have produced - otherwise last
quarter's numbers would change every time a trader edits a percentage.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Customer,
    Email,
    EmailCategory,
    QuotationLineItem,
    QuotationPricing,
    QuotationRequest,
    QuotationStatus,
    StockItem,
)

#: Statuses that mean the customer said yes, and that a quote actually went out.
WON = (QuotationStatus.CUSTOMER_ACCEPTED,)
LOST = (QuotationStatus.CUSTOMER_DECLINED,)
SENT_ONWARDS = (
    QuotationStatus.SENT,
    QuotationStatus.CUSTOMER_ACCEPTED,
    QuotationStatus.CUSTOMER_DECLINED,
)


@dataclass(slots=True)
class DateRange:
    start: date
    end: date

    @classmethod
    def last_days(cls, days: int) -> DateRange:
        today = date.today()
        return cls(start=today - timedelta(days=days), end=today)

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start, time.min)

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.end, time.max)

    def label(self) -> str:
        return f"{self.start:%d %b %Y} to {self.end:%d %b %Y}"


@dataclass(slots=True)
class FunnelStage:
    stage: str
    count: int
    note: str = ""


@dataclass(slots=True)
class Report:
    title: str
    period: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)

    def to_csv(self) -> str:
        if not self.rows:
            return ""
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(self.rows[0].keys()))
        writer.writeheader()
        writer.writerows(self.rows)
        return buffer.getvalue()


class ReportService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Funnel -----------------------------------------------------------

    def funnel(self, period: DateRange) -> list[FunnelStage]:
        """Enquiry to order, stage by stage.

        The drop between stages is the operational question a trading desk
        actually asks: how many enquiries never became a quote, and how many
        quotes never became a reply.
        """
        received = self._count(
            select(func.count()).select_from(Email).where(
                Email.received_at.between(period.start_dt, period.end_dt)
            )
        )
        enquiries = self._count(
            select(func.count()).select_from(Email).where(
                Email.received_at.between(period.start_dt, period.end_dt),
                Email.category == EmailCategory.QUOTATION_REQUEST,
            )
        )
        quoted = self._count(self._in_period(select(func.count()).select_from(QuotationRequest), period))
        sent = self._count(
            self._in_period(select(func.count()).select_from(QuotationRequest), period).where(
                QuotationRequest.status.in_(SENT_ONWARDS)
            )
        )
        accepted = self._count(
            self._in_period(select(func.count()).select_from(QuotationRequest), period).where(
                QuotationRequest.status.in_(WON)
            )
        )
        declined = self._count(
            self._in_period(select(func.count()).select_from(QuotationRequest), period).where(
                QuotationRequest.status.in_(LOST)
            )
        )

        awaiting = sent - accepted - declined
        return [
            FunnelStage("Emails received", received),
            FunnelStage("Enquiries identified", enquiries, _rate(enquiries, received)),
            FunnelStage("Quotations raised", quoted, _rate(quoted, enquiries)),
            FunnelStage("Quotations sent", sent, _rate(sent, quoted)),
            FunnelStage("Awaiting reply", max(awaiting, 0)),
            FunnelStage("Accepted", accepted, _rate(accepted, sent)),
            FunnelStage("Declined", declined, _rate(declined, sent)),
        ]

    # --- Win / loss -------------------------------------------------------

    def win_loss(self, period: DateRange) -> Report:
        rows: list[dict[str, Any]] = []
        won = lost = open_count = 0
        won_value = Decimal(0)
        lost_value = Decimal(0)

        for quotation in self.db.scalars(
            self._in_period(select(QuotationRequest), period).where(
                QuotationRequest.status.in_(SENT_ONWARDS)
            )
        ):
            value = _quotation_value(quotation)
            outcome = (
                "Won"
                if quotation.status in WON
                else "Lost"
                if quotation.status in LOST
                else "Open"
            )
            if outcome == "Won":
                won += 1
                won_value += value
            elif outcome == "Lost":
                lost += 1
                lost_value += value
            else:
                open_count += 1

            rows.append(
                {
                    "quotation": quotation.quotation_number,
                    "customer": quotation.customer_company_raw
                    or quotation.customer_name_raw
                    or "",
                    "sent": quotation.sent_at.strftime("%Y-%m-%d") if quotation.sent_at else "",
                    "outcome": outcome,
                    "value_inr": str(value),
                }
            )

        decided = won + lost
        return Report(
            title="Win / loss",
            period=period.label(),
            rows=rows,
            totals={
                "won": won,
                "lost": lost,
                "open": open_count,
                "win_rate_pct": round(won / decided * 100, 1) if decided else None,
                "won_value_inr": str(won_value),
                "lost_value_inr": str(lost_value),
            },
        )

    # --- Margin -----------------------------------------------------------

    def margin(self, period: DateRange) -> Report:
        """Margin actually quoted, and how often a human moved it.

        The gap between the suggested figure and what went out is the honest
        measure of whether the rules are set correctly. A high override rate
        is the rules being wrong, not the traders being difficult.
        """
        rows: list[dict[str, Any]] = []
        total_cost = Decimal(0)
        total_quote = Decimal(0)
        overridden = 0

        query = (
            select(QuotationPricing, QuotationRequest)
            .join(QuotationLineItem, QuotationPricing.quotation_line_item_id == QuotationLineItem.id)
            .join(QuotationRequest, QuotationLineItem.quotation_request_id == QuotationRequest.id)
            .where(QuotationRequest.created_at.between(period.start_dt, period.end_dt))
        )

        for pricing, quotation in self.db.execute(query):
            if pricing.quote_rate is None or pricing.total_cost is None:
                continue
            quantity = pricing.quantity_mt or Decimal(0)
            cost_value = pricing.total_cost * quantity
            quote_value = pricing.quote_rate * quantity
            total_cost += cost_value
            total_quote += quote_value
            if pricing.has_overrides:
                overridden += 1

            margin_pct = (
                (pricing.quote_rate - pricing.total_cost) / pricing.total_cost * 100
                if pricing.total_cost
                else Decimal(0)
            )
            rows.append(
                {
                    "quotation": quotation.quotation_number,
                    "rules_version": pricing.rules_version or "",
                    "quantity_mt": str(quantity),
                    "cost_per_mt": str(pricing.total_cost),
                    "quote_per_mt": str(pricing.quote_rate),
                    "margin_pct": f"{margin_pct:.2f}",
                    "overridden": "yes" if pricing.has_overrides else "no",
                }
            )

        overall = (
            (total_quote - total_cost) / total_cost * 100 if total_cost else Decimal(0)
        )
        return Report(
            title="Margin realised",
            period=period.label(),
            rows=rows,
            totals={
                "lines": len(rows),
                "overridden_lines": overridden,
                "override_rate_pct": round(overridden / len(rows) * 100, 1) if rows else None,
                "total_cost_inr": str(total_cost),
                "total_quoted_inr": str(total_quote),
                "blended_margin_pct": f"{overall:.2f}",
            },
        )

    # --- Stock ------------------------------------------------------------

    def stock_ageing(self, *, dead_after_days: int = 90) -> Report:
        """What is sitting still. Deadstock is cash on the floor."""
        buckets = {"0-30 days": 0, "31-60 days": 0, "61-90 days": 0, "Over 90 days": 0}
        bucket_value: dict[str, Decimal] = {k: Decimal(0) for k in buckets}
        rows: list[dict[str, Any]] = []

        for lot in self.db.scalars(select(StockItem)):
            balance = lot.balance_qty_kg or Decimal(0)
            if balance <= 0:
                continue
            age = lot.ageing_days or 0
            bucket = (
                "0-30 days"
                if age <= 30
                else "31-60 days"
                if age <= 60
                else "61-90 days"
                if age <= 90
                else "Over 90 days"
            )
            value = balance * Decimal(str(lot.landed_cost_per_kg or 0))
            buckets[bucket] += 1
            bucket_value[bucket] += value

            if age >= dead_after_days:
                rows.append(
                    {
                        "spec": lot.display_name,
                        "location": lot.location or "",
                        "ageing_days": age,
                        "balance_mt": str((balance / Decimal(1000)).quantize(Decimal("0.001"))),
                        "value_inr": str(value.quantize(Decimal("0.01"))),
                    }
                )

        rows.sort(key=lambda r: r["ageing_days"], reverse=True)
        return Report(
            title=f"Stock ageing (deadstock over {dead_after_days} days)",
            period=f"As at {date.today():%d %b %Y}",
            rows=rows,
            totals={
                "buckets": buckets,
                "bucket_value_inr": {k: str(v.quantize(Decimal("0.01"))) for k, v in bucket_value.items()},
                "deadstock_lots": len(rows),
                "deadstock_value_inr": str(
                    sum((Decimal(r["value_inr"]) for r in rows), Decimal(0)).quantize(Decimal("0.01"))
                ),
            },
        )

    # --- Customers and products -------------------------------------------

    def customer_performance(self, period: DateRange, *, limit: int = 50) -> Report:
        rows: list[dict[str, Any]] = []
        for customer in self.db.scalars(select(Customer)):
            quotations = list(
                self.db.scalars(
                    self._in_period(select(QuotationRequest), period).where(
                        QuotationRequest.customer_id == customer.id
                    )
                )
            )
            if not quotations:
                continue
            won = sum(1 for q in quotations if q.status in WON)
            lost = sum(1 for q in quotations if q.status in LOST)
            value = sum((_quotation_value(q) for q in quotations), Decimal(0))
            decided = won + lost
            rows.append(
                {
                    "customer": customer.company or customer.name,
                    "enquiries": len(quotations),
                    "won": won,
                    "lost": lost,
                    "win_rate_pct": round(won / decided * 100, 1) if decided else "",
                    "quoted_value_inr": str(value),
                    "verified": "yes" if customer.is_verified else "no",
                }
            )

        rows.sort(key=lambda r: Decimal(r["quoted_value_inr"]), reverse=True)
        return Report(
            title="Customer performance",
            period=period.label(),
            rows=rows[:limit],
            totals={"customers": len(rows)},
        )

    def product_performance(self, period: DateRange, *, limit: int = 50) -> Report:
        tally: dict[str, dict[str, Any]] = {}

        query = (
            select(QuotationLineItem, QuotationRequest)
            .join(QuotationRequest, QuotationLineItem.quotation_request_id == QuotationRequest.id)
            .where(QuotationRequest.created_at.between(period.start_dt, period.end_dt))
        )
        for item, quotation in self.db.execute(query):
            key = " ".join(filter(None, [item.grade, item.product_type])) or "Unspecified"
            entry = tally.setdefault(
                key,
                {
                    "product": key,
                    "lines": 0,
                    "quantity_mt": Decimal(0),
                    "value_inr": Decimal(0),
                    "won": 0,
                },
            )
            entry["lines"] += 1
            entry["quantity_mt"] += item.quantity_mt or Decimal(0)
            if item.pricing and item.pricing.line_total:
                entry["value_inr"] += item.pricing.line_total
            if quotation.status in WON:
                entry["won"] += 1

        rows = [
            {
                "product": e["product"],
                "lines": e["lines"],
                "quantity_mt": str(e["quantity_mt"]),
                "value_inr": str(e["value_inr"]),
                "won": e["won"],
            }
            for e in tally.values()
        ]
        rows.sort(key=lambda r: Decimal(r["value_inr"]), reverse=True)
        return Report(
            title="Product performance",
            period=period.label(),
            rows=rows[:limit],
            totals={"products": len(rows)},
        )

    # --- Internals --------------------------------------------------------

    def _count(self, query) -> int:
        return self.db.scalar(query) or 0

    @staticmethod
    def _in_period(query, period: DateRange):
        return query.where(QuotationRequest.created_at.between(period.start_dt, period.end_dt))


def _quotation_value(quotation: QuotationRequest) -> Decimal:
    total = Decimal(0)
    for item in quotation.line_items:
        if item.pricing and item.pricing.line_total:
            total += item.pricing.line_total
    return total


def _rate(part: int, whole: int) -> str:
    return f"{part / whole * 100:.0f}% of previous stage" if whole else ""


__all__ = ["ReportService", "Report", "DateRange", "FunnelStage"]
