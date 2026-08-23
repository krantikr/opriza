"""The trading desk's own report: did we make money, and where did it go?

Everything already in `reports.py` measures *activity* - how many enquiries
arrived, how many quotes went out, where they stalled. Activity is not the
business. A trader buys metal, holds it, sells it at a spread, and gets paid;
the questions that decide whether the desk is working are:

* **What did we earn?** Gross profit in rupees, not just a margin percentage.
  Twelve percent on four lakh is a worse month than six percent on four crore,
  and a percentage alone cannot tell those apart.
* **Why did we lose?** Losing on PRICE means the margin is set wrong. Losing
  on NO_STOCK means the buying is wrong. Those are opposite fixes, and the
  reason is already captured on every declined quote.
* **Where is the cash stuck?** Deadstock is money on the floor at landed cost,
  ageing every day nobody sells it.
* **How exposed are we?** Half the book in one customer is a different risk
  from the same value spread over twenty.
* **Do we deliver when we said?** A promise kept is the whole of a trader's
  reputation, and `promised_date` against `despatched_at` measures it.

Every figure is counted from stored rows and the rules in force at the time,
so last quarter does not move when somebody edits a percentage this morning.
"""

from __future__ import annotations

from collections import defaultdict
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
    QuotationRequest,
    QuotationStatus,
    StockItem,
    StockMovement,
    StockMovementKind,
)
from app.services.periods import Period
from app.services.reports import DateRange

WON = (QuotationStatus.CUSTOMER_ACCEPTED,)
LOST = (QuotationStatus.CUSTOMER_DECLINED,)
SENT_ONWARDS = (
    QuotationStatus.SENT,
    QuotationStatus.CUSTOMER_ACCEPTED,
    QuotationStatus.CUSTOMER_DECLINED,
)

#: Plain words for the closed set of loss reasons, and what each one implies.
LOST_REASON_LABELS = {
    "PRICE": "Too expensive",
    "COMPETITOR": "Went to a competitor",
    "DELAYED": "We were too slow",
    "NO_STOCK": "We had no stock",
    "NO_RESPONSE": "Customer went quiet",
    "OTHER": "Other",
}

LOST_REASON_ACTIONS = {
    "PRICE": "Margin may be set too high for this grade - check the rules.",
    "COMPETITOR": "Lost on relationship or terms, not on the number alone.",
    "DELAYED": "Quotes are going out too slowly to compete.",
    "NO_STOCK": "Demand exists that the floor cannot serve - a buying signal.",
    "NO_RESPONSE": "Chase earlier; these were never actually declined.",
    "OTHER": "No pattern recorded.",
}


def _start(day: date) -> datetime:
    return datetime.combine(day, time.min)


def _end(day: date) -> datetime:
    return datetime.combine(day, time.max)


@dataclass(slots=True)
class Money:
    """Revenue, cost and the spread between them, for one slice of business."""

    revenue: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)
    tonnes: Decimal = Decimal(0)
    deals: int = 0

    @property
    def profit(self) -> Decimal:
        return self.revenue - self.cost

    @property
    def margin_pct(self) -> float:
        return float(self.profit / self.cost * 100) if self.cost else 0.0

    @property
    def profit_per_mt(self) -> float:
        return float(self.profit / self.tonnes) if self.tonnes else 0.0

    def add(self, revenue: Decimal, cost: Decimal, tonnes: Decimal) -> None:
        self.revenue += revenue
        self.cost += cost
        self.tonnes += tonnes

    def to_dict(self) -> dict[str, Any]:
        return {
            "revenue": float(self.revenue),
            "cost": float(self.cost),
            "profit": float(self.profit),
            "margin_pct": round(self.margin_pct, 2),
            "tonnes": float(self.tonnes),
            "profit_per_mt": round(self.profit_per_mt, 2),
            "deals": self.deals,
        }


@dataclass(slots=True)
class DeskReport:
    """One period of trading, as a person would want it read to them."""

    period_key: str = ""
    period_label: str = ""
    period_range: str = ""
    previous_label: str = ""
    grain: str = "day"

    won: dict[str, Any] = field(default_factory=dict)
    won_previous: dict[str, Any] = field(default_factory=dict)
    open_book: dict[str, Any] = field(default_factory=dict)
    quoted: dict[str, Any] = field(default_factory=dict)

    trend: list[dict[str, Any]] = field(default_factory=list)
    lost_reasons: list[dict[str, Any]] = field(default_factory=list)
    customers: list[dict[str, Any]] = field(default_factory=list)
    products: list[dict[str, Any]] = field(default_factory=list)
    concentration: dict[str, Any] = field(default_factory=dict)
    stock: dict[str, Any] = field(default_factory=dict)
    delivery: dict[str, Any] = field(default_factory=dict)
    quiet_customers: list[dict[str, Any]] = field(default_factory=list)
    enquiries: dict[str, Any] = field(default_factory=dict)
    stock_movement: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_key": self.period_key,
            "period_label": self.period_label,
            "period_range": self.period_range,
            "previous_label": self.previous_label,
            "grain": self.grain,
            "won": self.won,
            "won_previous": self.won_previous,
            "open_book": self.open_book,
            "quoted": self.quoted,
            "trend": self.trend,
            "lost_reasons": self.lost_reasons,
            "customers": self.customers,
            "products": self.products,
            "concentration": self.concentration,
            "stock": self.stock,
            "delivery": self.delivery,
            "quiet_customers": self.quiet_customers,
            "enquiries": self.enquiries,
            "stock_movement": self.stock_movement,
        }


class DeskService:
    """Builds the trading view of a period from stored rows only."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Entry point ------------------------------------------------------

    def build(self, period: Period) -> DeskReport:
        current = self._quotations(period.current)
        previous = self._quotations(period.previous)

        report = DeskReport(
            period_key=period.key,
            period_label=period.label,
            period_range=period.current.label(),
            previous_label=period.previous_label,
            grain=period.grain,
        )

        report.won = self._money(q for q in current if q.status in WON).to_dict()
        report.won_previous = self._money(q for q in previous if q.status in WON).to_dict()
        report.open_book = self._money(
            q for q in current if q.status == QuotationStatus.SENT
        ).to_dict()
        report.quoted = self._money(current).to_dict()

        report.trend = self._trend(current, period)
        report.lost_reasons = self._lost_reasons(current)
        report.customers = self._customers(current)
        report.products = self._products(current)
        report.concentration = self._concentration(report.customers)
        report.stock = self._stock()
        report.delivery = self._delivery(current)
        report.quiet_customers = self._quiet_customers(period.current.end)
        report.enquiries = self._enquiries(current, period)
        report.stock_movement = self._stock_movement(period)
        return report

    # --- Money ------------------------------------------------------------

    def _money(self, quotations) -> Money:
        """Revenue, cost and tonnage rolled up from the stored build-ups.

        A line with no cost recorded contributes nothing rather than being
        counted as pure profit - an unpriced line is unknown, not free.
        """
        total = Money()
        for quotation in quotations:
            counted = False
            for item in quotation.line_items:
                pricing = item.pricing
                if not pricing or pricing.quote_rate is None or pricing.total_cost is None:
                    continue
                qty = pricing.quantity_mt or Decimal(0)
                total.add(pricing.quote_rate * qty, pricing.total_cost * qty, qty)
                counted = True
            if counted:
                total.deals += 1
        return total

    # --- Trend ------------------------------------------------------------

    def _trend(self, quotations: list[QuotationRequest], period: Period) -> list[dict[str, Any]]:
        """Won revenue and profit, bucketed so the shape is readable.

        Buckets follow the period's grain: days inside a month, weeks inside a
        quarter, months inside a year. Sixty daily columns is a smear.
        """
        buckets: dict[date, Money] = defaultdict(Money)
        quoted: dict[date, Money] = defaultdict(Money)

        for quotation in quotations:
            day = quotation.created_at.date()
            key = self._bucket(day, period.grain)
            money = self._money([quotation])
            quoted[key].add(money.revenue, money.cost, money.tonnes)
            if quotation.status in WON:
                buckets[key].add(money.revenue, money.cost, money.tonnes)

        keys = sorted(set(buckets) | set(quoted))
        return [
            {
                "label": self._bucket_label(k, period.grain),
                "revenue": float(buckets[k].revenue),
                "profit": float(buckets[k].profit),
                "quoted": float(quoted[k].revenue),
                "tonnes": float(buckets[k].tonnes),
            }
            for k in keys
        ]

    @staticmethod
    def _bucket(day: date, grain: str) -> date:
        if grain == "week":
            return day - timedelta(days=day.weekday())
        if grain == "month":
            return day.replace(day=1)
        return day

    @staticmethod
    def _bucket_label(day: date, grain: str) -> str:
        if grain == "month":
            return f"{day:%b %y}"
        if grain == "week":
            return f"w/c {day:%d %b}"
        return f"{day:%d %b}"

    # --- Why we lost ------------------------------------------------------

    def _lost_reasons(self, quotations: list[QuotationRequest]) -> list[dict[str, Any]]:
        """The declined book, grouped by the reason a human recorded.

        This is the only report that tells a trader *which* lever to pull, so
        it names the implication next to each count rather than leaving the
        reader to infer it.
        """
        tally: dict[str, dict[str, Any]] = {}
        for quotation in quotations:
            if quotation.status not in LOST:
                continue
            reason = str(quotation.lost_reason) if quotation.lost_reason else "OTHER"
            entry = tally.setdefault(
                reason,
                {
                    "reason": reason,
                    "label": LOST_REASON_LABELS.get(reason, reason.title()),
                    "action": LOST_REASON_ACTIONS.get(reason, ""),
                    "count": 0,
                    "value": Decimal(0),
                    "profit_missed": Decimal(0),
                },
            )
            money = self._money([quotation])
            entry["count"] += 1
            entry["value"] += money.revenue
            entry["profit_missed"] += money.profit

        rows = [
            {
                **entry,
                "value": float(entry["value"]),
                "profit_missed": float(entry["profit_missed"]),
            }
            for entry in tally.values()
        ]
        rows.sort(key=lambda r: r["value"], reverse=True)
        return rows

    # --- Who and what -----------------------------------------------------

    def _customers(self, quotations: list[QuotationRequest], limit: int = 15
                   ) -> list[dict[str, Any]]:
        tally: dict[str, dict[str, Any]] = {}
        for quotation in quotations:
            name = (
                quotation.customer_company_raw
                or quotation.customer_name_raw
                or quotation.customer_email
                or "Unknown"
            )
            entry = tally.setdefault(
                name,
                {"customer": name, "quotes": 0, "won": 0, "lost": 0,
                 "quoted": Money(), "earned": Money()},
            )
            money = self._money([quotation])
            entry["quotes"] += 1
            entry["quoted"].add(money.revenue, money.cost, money.tonnes)
            if quotation.status in WON:
                entry["won"] += 1
                entry["earned"].add(money.revenue, money.cost, money.tonnes)
            elif quotation.status in LOST:
                entry["lost"] += 1

        rows = []
        for entry in tally.values():
            decided = entry["won"] + entry["lost"]
            rows.append(
                {
                    "customer": entry["customer"],
                    "quotes": entry["quotes"],
                    "won": entry["won"],
                    "lost": entry["lost"],
                    "win_rate": round(entry["won"] / decided * 100, 1) if decided else None,
                    "quoted_value": float(entry["quoted"].revenue),
                    "revenue": float(entry["earned"].revenue),
                    "profit": float(entry["earned"].profit),
                    "margin_pct": round(entry["earned"].margin_pct, 2),
                    "tonnes": float(entry["earned"].tonnes),
                }
            )
        rows.sort(key=lambda r: (r["revenue"], r["quoted_value"]), reverse=True)
        return rows[:limit]

    def _products(self, quotations: list[QuotationRequest], limit: int = 15
                  ) -> list[dict[str, Any]]:
        """Spread per product line - the number that says what to buy more of."""
        tally: dict[str, dict[str, Any]] = {}
        for quotation in quotations:
            is_won = quotation.status in WON
            for item in quotation.line_items:
                pricing = item.pricing
                if not pricing or pricing.quote_rate is None or pricing.total_cost is None:
                    continue
                key = " ".join(filter(None, [item.grade, item.product_type])) or "Unspecified"
                entry = tally.setdefault(
                    key,
                    {"product": key, "lines": 0, "won_lines": 0,
                     "quoted": Money(), "earned": Money()},
                )
                qty = pricing.quantity_mt or Decimal(0)
                revenue = pricing.quote_rate * qty
                cost = pricing.total_cost * qty
                entry["lines"] += 1
                entry["quoted"].add(revenue, cost, qty)
                if is_won:
                    entry["won_lines"] += 1
                    entry["earned"].add(revenue, cost, qty)

        rows = [
            {
                "product": e["product"],
                "lines": e["lines"],
                "won_lines": e["won_lines"],
                "quoted_value": float(e["quoted"].revenue),
                "tonnes_quoted": float(e["quoted"].tonnes),
                "tonnes_won": float(e["earned"].tonnes),
                "revenue": float(e["earned"].revenue),
                "profit": float(e["earned"].profit),
                "margin_pct": round(e["earned"].margin_pct, 2),
                "profit_per_mt": round(e["earned"].profit_per_mt, 2),
            }
            for e in tally.values()
        ]
        rows.sort(key=lambda r: (r["revenue"], r["quoted_value"]), reverse=True)
        return rows[:limit]

    def _concentration(self, customers: list[dict[str, Any]]) -> dict[str, Any]:
        """How much of the book rides on the largest few names.

        Reported against quoted value rather than won, because the exposure a
        trader carries is in the pipeline as much as in the closed business.
        """
        total = sum(c["quoted_value"] for c in customers)
        if not total:
            return {"top_1_pct": 0.0, "top_3_pct": 0.0, "top_5_pct": 0.0, "customers": 0}
        ranked = sorted((c["quoted_value"] for c in customers), reverse=True)
        return {
            "top_1_pct": round(sum(ranked[:1]) / total * 100, 1),
            "top_3_pct": round(sum(ranked[:3]) / total * 100, 1),
            "top_5_pct": round(sum(ranked[:5]) / total * 100, 1),
            "customers": len(customers),
        }

    # --- Cash on the floor ------------------------------------------------

    def _stock(self) -> dict[str, Any]:
        """Stock at landed cost, by age. Over ninety days is cash not working."""
        buckets = {"0-30 days": Money(), "31-60 days": Money(),
                   "61-90 days": Money(), "Over 90 days": Money()}
        oldest: list[dict[str, Any]] = []

        for lot in self.db.scalars(select(StockItem)):
            balance = lot.balance_qty_kg or Decimal(0)
            if balance <= 0:
                continue
            age = lot.ageing_days or 0
            name = ("0-30 days" if age <= 30 else "31-60 days" if age <= 60
                    else "61-90 days" if age <= 90 else "Over 90 days")
            value = balance * Decimal(str(lot.landed_cost_per_kg or 0))
            tonnes = balance / Decimal(1000)
            buckets[name].add(value, Decimal(0), tonnes)
            buckets[name].deals += 1

            if age > 90:
                oldest.append(
                    {
                        "spec": lot.display_name,
                        "location": lot.location or "",
                        "ageing_days": age,
                        "tonnes": float(tonnes),
                        "value": float(value),
                    }
                )

        oldest.sort(key=lambda r: r["ageing_days"], reverse=True)
        total_value = sum(b.revenue for b in buckets.values())
        dead = buckets["Over 90 days"]
        return {
            "buckets": [
                {"label": k, "lots": v.deals, "value": float(v.revenue),
                 "tonnes": float(v.tonnes)}
                for k, v in buckets.items()
            ],
            "total_value": float(total_value),
            "deadstock_value": float(dead.revenue),
            "deadstock_pct": round(float(dead.revenue / total_value * 100), 1)
            if total_value else 0.0,
            "deadstock_lots": dead.deals,
            "oldest": oldest[:10],
        }

    # --- Promises kept ----------------------------------------------------

    def _delivery(self, quotations: list[QuotationRequest]) -> dict[str, Any]:
        """Did we despatch by the date we promised?

        Only quotations carrying both a promise and a despatch can be judged;
        the rest are counted separately rather than being scored as failures,
        because an unrecorded despatch is missing data, not a late delivery.
        """
        on_time = late = 0
        late_days: list[int] = []
        pending_promise = 0
        today = date.today()

        for quotation in quotations:
            if quotation.promised_date is None:
                continue
            if quotation.despatched_at is None:
                if quotation.status in WON and quotation.promised_date < today:
                    pending_promise += 1
                continue
            slip = (quotation.despatched_at.date() - quotation.promised_date).days
            if slip <= 0:
                on_time += 1
            else:
                late += 1
                late_days.append(slip)

        judged = on_time + late
        return {
            "on_time": on_time,
            "late": late,
            "on_time_pct": round(on_time / judged * 100, 1) if judged else None,
            "avg_days_late": round(sum(late_days) / len(late_days), 1) if late_days else 0.0,
            "overdue_now": pending_promise,
        }

    # --- Customers going quiet --------------------------------------------

    def _quiet_customers(self, as_of: date, limit: int = 10) -> list[dict[str, Any]]:
        """Names that used to buy and have not been heard from.

        A trading desk loses customers silently. Nobody sends a note saying
        they have moved their business, so the only signal is an absence.
        """
        rows: list[dict[str, Any]] = []
        cutoff = as_of - timedelta(days=60)

        for customer in self.db.scalars(select(Customer)):
            quotations = list(
                self.db.scalars(
                    select(QuotationRequest)
                    .where(QuotationRequest.customer_id == customer.id)
                    .order_by(QuotationRequest.created_at.desc())
                )
            )
            if not quotations:
                continue
            last = quotations[0].created_at.date()
            if last > cutoff:
                continue
            earned = self._money(q for q in quotations if q.status in WON)
            if earned.revenue <= 0:
                continue
            rows.append(
                {
                    "customer": customer.company or customer.name,
                    "last_seen": last.isoformat(),
                    "days_quiet": (as_of - last).days,
                    "lifetime_revenue": float(earned.revenue),
                    "lifetime_profit": float(earned.profit),
                    "orders": earned.deals,
                }
            )

        rows.sort(key=lambda r: r["lifetime_revenue"], reverse=True)
        return rows[:limit]

    # --- Statement 1: enquiry and quotation -------------------------------

    def _enquiries(self, quotations: list[QuotationRequest], period: Period) -> dict[str, Any]:
        """How much work came in, and how much of it we answered.

        A trading desk lives on the ratio between these lines: mail that turned
        out to be an enquiry, enquiries that became a quotation, quotations that
        actually went out. Each line is a subset of the one above it, so the
        statement subtracts rather than merely listing - the gap is the part
        worth explaining.
        """
        window = (_start(period.current.start), _end(period.current.end))

        received = self.db.scalar(
            select(func.count()).select_from(Email).where(Email.received_at.between(*window))
        ) or 0
        identified = self.db.scalar(
            select(func.count())
            .select_from(Email)
            .where(
                Email.received_at.between(*window),
                Email.category == EmailCategory.QUOTATION_REQUEST,
            )
        ) or 0

        raised = len(quotations)
        sent = sum(1 for q in quotations if q.status in SENT_ONWARDS)
        won = sum(1 for q in quotations if q.status in WON)
        lost = sum(1 for q in quotations if q.status in LOST)
        awaiting = sent - won - lost
        decided = won + lost

        return {
            "received": received,
            "identified": identified,
            "not_enquiries": max(received - identified, 0),
            "raised": raised,
            "not_raised": max(identified - raised, 0),
            "sent": sent,
            "not_sent": max(raised - sent, 0),
            "awaiting": max(awaiting, 0),
            "won": won,
            "lost": lost,
            "win_rate": round(won / decided * 100, 1) if decided else None,
            "conversion_rate": round(won / identified * 100, 1) if identified else None,
        }

    # --- Statement 4: stock reconciliation --------------------------------

    def _stock_movement(self, period: Period) -> dict[str, Any]:
        """Opening, receipts, issues, closing - a statement that must balance.

        The closing figure is what the floor holds today, taken from the stock
        sheet. Receipts and issues inside the window come from the movement
        ledger, so opening is derived backwards from closing rather than stored:
        a stored opening would drift out of step with a re-imported sheet, and a
        stock statement that does not reconcile is worse than none.
        """
        movements = list(
            self.db.scalars(
                select(StockMovement).where(
                    func.coalesce(StockMovement.movement_date, func.date(StockMovement.created_at))
                    .between(period.current.start, period.current.end)
                )
            )
        )

        receipts_kg = Decimal(0)
        issues_kg = Decimal(0)
        receipts_value = Decimal(0)
        issues_value = Decimal(0)
        receipt_count = issue_count = 0

        for m in movements:
            # Reservations and blocks are holds, not movements of ownership, so
            # they never enter a statement of what came in and what went out.
            if m.kind not in (
                StockMovementKind.RECEIPT,
                StockMovementKind.ISSUE,
                StockMovementKind.ADJUSTMENT,
            ):
                continue
            qty = m.quantity_kg or Decimal(0)
            value = qty * (m.rate_per_kg or Decimal(0))
            if qty >= 0:
                receipts_kg += qty
                receipts_value += value
                receipt_count += 1
            else:
                issues_kg += -qty
                issues_value += -value
                issue_count += 1

        closing_kg = Decimal(0)
        closing_value = Decimal(0)
        for lot in self.db.scalars(select(StockItem)):
            balance = lot.balance_qty_kg or Decimal(0)
            if balance <= 0:
                continue
            closing_kg += balance
            closing_value += balance * Decimal(str(lot.landed_cost_per_kg or 0))

        opening_kg = closing_kg - receipts_kg + issues_kg
        thousand = Decimal(1000)

        return {
            "opening_mt": float(opening_kg / thousand),
            "receipts_mt": float(receipts_kg / thousand),
            "issues_mt": float(issues_kg / thousand),
            "closing_mt": float(closing_kg / thousand),
            "receipts_value": float(receipts_value),
            "issues_value": float(issues_value),
            "closing_value": float(closing_value),
            "receipt_count": receipt_count,
            "issue_count": issue_count,
            "movements": receipt_count + issue_count,
        }

    # --- Internals --------------------------------------------------------

    def _quotations(self, window: DateRange) -> list[QuotationRequest]:
        return list(
            self.db.scalars(
                select(QuotationRequest).where(
                    QuotationRequest.created_at.between(
                        _start(window.start), _end(window.end)
                    )
                )
            )
        )


__all__ = ["DeskService", "DeskReport", "Money", "LOST_REASON_LABELS"]
