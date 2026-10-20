"""Layer B: business facts, worked out by plain code from the books.

Every agent reads these instead of re-deriving them, so the Sales agent, the
Collections agent and the morning brief never disagree about a customer's
grade or next week's cash. No LLM is involved: each number can be reproduced
and each grade comes with the reasons behind it.

The logic is the same as `scripts/mock_business/facts.py`, which produced the
expected answers in the test scenarios; this version reads the database.

    refresh(db)   after every sync, and nightly
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.kb import clock, rules
from app.kb.models import (
    KbBill,
    KbBillAllocation,
    KbCashWeek,
    KbCustomerProfile,
    KbItem,
    KbItemMetric,
    KbKpi,
    KbParty,
    KbPricePoint,
    KbPromise,
    KbQuote,
    KbQuoteLine,
    KbStockBalance,
    KbSupplierQuote,
    KbVoucher,
    KbVoucherLine,
)

#: Grading thresholds on average days late (last six months, weighted by amount).
GRADE_BANDS = ((5, "A"), (15, "B"), (35, "C"))
WATCH_DAYS = 20
LIMIT_FACTOR = {"A": 1.5, "B": 1.2, "C": 0.8, "D": 0.4}


def grade_for(avg_late: float, oldest_overdue: int, promise_miss_rate: float | None) -> str:
    grade = next((g for limit, g in GRADE_BANDS if avg_late <= limit), "D")
    order = "ABCD"
    if oldest_overdue > 60:
        grade = "D"
    elif oldest_overdue > 30 and order.index(grade) < 2:
        grade = "C"
    if promise_miss_rate is not None and promise_miss_rate > 0.5 and grade != "D":
        grade = order[order.index(grade) + 1]
    return grade


class Books:
    """The mirror loaded once into memory for one desk."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.today = clock.today(db)
        self.parties = {p.id: p for p in db.scalars(select(KbParty))}
        self.items = {i.id: i for i in db.scalars(select(KbItem))}
        self.vouchers = {v.id: v for v in db.scalars(select(KbVoucher))}
        self.bills = list(db.scalars(select(KbBill)))
        self.bills_by_party = defaultdict(list)
        for b in self.bills:
            self.bills_by_party[b.party_id].append(b)
        self.allocs = defaultdict(list)
        for a in db.scalars(select(KbBillAllocation)):
            self.allocs[a.bill_id].append(a)
        self.lines = list(db.scalars(select(KbVoucherLine)))
        self.sales_by_party = defaultdict(list)
        for v in self.vouchers.values():
            if v.voucher_type == "sales" and v.party_id:
                self.sales_by_party[v.party_id].append(v)

    # ------------------------------------------------------------ customers

    def payment_picture(self, party_id: int, as_of: date):
        since = as_of - timedelta(days=180)
        late, pay_days, oldest, outstanding, overdue = [], [], 0, 0.0, 0.0
        for b in self.bills_by_party.get(party_id, ()):
            if b.direction != "receivable" or b.bill_date > as_of:
                continue
            paid = [a for a in self.allocs[b.id] if a.date <= as_of]
            pending = round(float(b.amount) - sum(float(a.amount) for a in paid), 2)
            if pending <= 1:
                if not paid:
                    continue
                cleared = max(a.date for a in paid)
                if cleared >= since:
                    late.append(((cleared - b.due_date).days, float(b.amount)))
                pay_days.append((cleared - b.bill_date).days)
            else:
                outstanding += pending
                if b.due_date < as_of:
                    days = (as_of - b.due_date).days
                    overdue += pending
                    oldest = max(oldest, days)
                    late.append((days, pending))
        total = sum(w for _, w in late)
        avg_late = sum(d * w for d, w in late) / total if total else 0.0
        return avg_late, pay_days, oldest, outstanding, overdue

    def customer_profiles(self, promises: list[KbPromise]) -> list[dict]:
        out = []
        by_party = defaultdict(list)
        for p in promises:
            by_party[p.party_id].append(p)
        for pid, p in self.parties.items():
            if p.kind != "customer":
                continue
            avg_late, pay_days, oldest, outstanding, overdue = self.payment_picture(pid, self.today)
            prev_avg, _, prev_oldest, _, _ = self.payment_picture(pid, self.today - timedelta(days=30))
            mine = [x for x in by_party[pid] if x.status != "open"]
            kept = sum(1 for x in mine if x.status in ("kept", "part_kept"))
            miss_rate = (1 - kept / len(mine)) if len(mine) >= 2 else None
            grade = grade_for(avg_late, oldest, miss_rate)
            prev = grade_for(prev_avg, prev_oldest, None)
            vs = sorted(self.sales_by_party[pid], key=lambda v: v.date)
            net = [(v.date, float(v.amount) - float(v.tax_amount)) for v in vs]
            s12 = sum(a for d, a in net if d >= self.today - timedelta(days=365))
            s90 = sum(a for d, a in net if d >= self.today - timedelta(days=90))
            last = vs[-1].date if vs else None
            dates = sorted({d for d, _ in net})
            gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
            gap = round(statistics.mean(gaps), 1) if gaps else None
            prior_q = (s12 - s90) / 3 if s12 > s90 else 0
            since_last = (self.today - last).days if last else None
            if since_last is not None and gap and since_last > max(21, 3 * gap):
                trend = "down"
            elif prior_q and s90 < 0.6 * prior_q:
                trend = "down"
            elif prior_q and s90 > 1.2 * prior_q:
                trend = "up"
            else:
                trend = "flat"
            monthly = s12 / 12 * 1.18
            limit = round(monthly * LIMIT_FACTOR[grade] / 1e5) * 1e5 if monthly else None
            reasons = []
            if grade != prev:
                reasons.append(f"Moved from {prev} to {grade} in the last 30 days")
            reasons.append(
                f"Pays {avg_late:.0f} days after the due date on average (last 6 months)"
                if avg_late >= 1
                else "Pays on or before the due date"
            )
            if oldest:
                reasons.append(f"Oldest unpaid bill is {oldest} days overdue")
            if miss_rate is not None:
                reasons.append(f"Kept {kept} of {len(mine)} payment promises")
            if trend == "down" and since_last is not None:
                reasons.append(
                    f"No order for {since_last} days (usually every {gap:.0f})"
                    if gap
                    else f"No order for {since_last} days"
                )
            out.append(
                {
                    "party_id": pid,
                    "grade": grade,
                    "previous_grade": prev,
                    "avg_days_late": round(avg_late, 1),
                    "usual_pay_day": int(statistics.median(pay_days)) if pay_days else p.credit_days,
                    "promises_made": len(by_party[pid]),
                    "promises_kept": kept,
                    "sales_12m": round(s12, 2),
                    "sales_90d": round(s90, 2),
                    "outstanding": round(outstanding, 2),
                    "overdue": round(overdue, 2),
                    "oldest_overdue_days": oldest,
                    "last_order_on": last,
                    "avg_order_gap_days": gap,
                    "trend": trend,
                    "suggested_credit_limit": limit,
                    "reasons": reasons,
                }
            )
        return out

    # ----------------------------------------------------------------- items

    def stock_now(self) -> dict[int, float]:
        latest: dict[int, date] = {}
        rows = list(self.db.scalars(select(KbStockBalance)))
        for s in rows:
            latest[s.item_id] = max(latest.get(s.item_id, s.as_of), s.as_of)
        out = defaultdict(float)
        for s in rows:
            if s.as_of == latest[s.item_id]:
                out[s.item_id] += float(s.qty)
        return out

    def cost_of(self) -> dict[int, float]:
        """Stock is valued at the last purchase rate, else the item's standard cost."""
        last: dict[int, tuple[date, float]] = {}
        for ln in self.lines:
            v = self.vouchers[ln.voucher_id]
            if v.voucher_type == "purchase" and (ln.item_id not in last or v.date >= last[ln.item_id][0]):
                last[ln.item_id] = (v.date, float(ln.rate))
        return {
            iid: last[iid][1] if iid in last else float(it.standard_cost) for iid, it in self.items.items()
        }

    def item_metrics(self, reorder_days: float, idle_days_rule: int) -> list[dict]:
        sold7, sold28, last = defaultdict(float), defaultdict(float), {}
        for ln in self.lines:
            v = self.vouchers[ln.voucher_id]
            if v.voucher_type != "sales":
                continue
            d = v.date
            if d >= self.today - timedelta(days=7):
                sold7[ln.item_id] += float(ln.qty)
            if d >= self.today - timedelta(days=28):
                sold28[ln.item_id] += float(ln.qty)
            last[ln.item_id] = max(last.get(ln.item_id, d), d)
        stock = self.stock_now()
        cost = self.cost_of()
        out = []
        for iid in self.items:
            per_day = sold28[iid] / 28
            qty_ = stock.get(iid, 0.0)
            days_left = round(qty_ / per_day, 1) if per_day > 0 else None
            idle = (self.today - last[iid]).days if iid in last else 365
            if qty_ > 0 and idle >= idle_days_rule:
                status = "idle"
            elif days_left is not None and days_left < reorder_days:
                status = "reorder"
            elif days_left is not None and days_left < WATCH_DAYS:
                status = "watch"
            else:
                status = "ok"
            out.append(
                {
                    "item_id": iid,
                    "sold_7d": round(sold7[iid], 3),
                    "sold_28d": round(sold28[iid], 3),
                    "per_day": round(per_day, 3),
                    "stock_qty": round(qty_, 3),
                    "stock_value": round(qty_ * cost[iid], 2),
                    "days_left": days_left,
                    "last_sale_on": last.get(iid),
                    "idle_days": idle,
                    "reorder_qty": round(per_day * 30, 3) if per_day else None,
                    "status": status,
                }
            )
        return out

    # ----------------------------------------------------------------- prices

    def price_points(self) -> list[dict]:
        out = []
        for ln in self.lines:
            v = self.vouchers[ln.voucher_id]
            if v.voucher_type in ("sales", "purchase"):
                out.append(
                    {
                        "item_id": ln.item_id,
                        "party_id": v.party_id,
                        "source": "sale" if v.voucher_type == "sales" else "purchase",
                        "date": v.date,
                        "rate": float(ln.rate),
                        "qty": float(ln.qty),
                    }
                )
        quotes = {q.id: q for q in self.db.scalars(select(KbQuote))}
        for ql in self.db.scalars(select(KbQuoteLine)):
            q = quotes.get(ql.quote_id)
            if q is not None:
                out.append(
                    {
                        "item_id": ql.item_id,
                        "party_id": q.party_id,
                        "source": "quote",
                        "date": q.created_at.date(),
                        "rate": float(ql.rate),
                        "qty": float(ql.qty),
                    }
                )
        for sq in self.db.scalars(select(KbSupplierQuote)):
            out.append(
                {
                    "item_id": sq.item_id,
                    "party_id": sq.supplier_id,
                    "source": "supplier_quote",
                    "date": sq.received_at.date(),
                    "rate": float(sq.rate),
                    "qty": None,
                }
            )
        return out

    # ------------------------------------------------------------------- cash

    def monthly_sales(self) -> float:
        since = self.today - timedelta(days=365)
        return (
            sum(
                float(v.amount) - float(v.tax_amount)
                for v in self.vouchers.values()
                if v.voucher_type == "sales" and v.date >= since
            )
            / 12
        )

    def cash_forecast(self, profiles: list[dict], bank_balance: float, weeks: int = 4) -> list[dict]:
        habit = {p["party_id"]: p for p in profiles}
        start = self.today
        monthly_sales = self.monthly_sales()
        buckets = [
            {
                "in": 0.0,
                "out": 0.0,
                "in_top": defaultdict(float),
                "out_top": defaultdict(float),
                "in_rows": defaultdict(float),
                "out_rows": defaultdict(float),
            }
            for _ in range(weeks)
        ]

        def put(d: date, side: str, amount: float, label: str, party_id: int | None = None) -> None:
            k = (d - start).days // 7
            if 0 <= k < weeks:
                buckets[k][side] += amount
                buckets[k][f"{side}_top"][label] += amount
                if party_id:
                    buckets[k][f"{side}_rows"][party_id] += amount

        late_wait = {"A": 3, "B": 7, "C": 14, "D": 30}
        for b in self.bills:
            pending = float(b.amount) - sum(float(a.amount) for a in self.allocs[b.id])
            if pending <= 1:
                continue
            name = self.parties[b.party_id].name
            if b.direction == "receivable":
                h = habit.get(b.party_id)
                grade = h["grade"] if h else "B"
                expected = b.bill_date + timedelta(days=h["usual_pay_day"] if h else 45)
                if expected < start:
                    expected = start + timedelta(days=late_wait[grade])
                weight = 0.6 if grade == "D" else 0.9 if grade == "C" else 1.0
                put(expected, "in", pending * weight, name, b.party_id)
            else:
                put(max(b.due_date, start), "out", pending, name, b.party_id)

        buyers = [p for p in profiles if p["sales_12m"] > 0]
        total_12m = sum(p["sales_12m"] for p in buyers) or 1
        daily_in = monthly_sales * 1.18 * 12 / 312
        recent = [
            v
            for v in self.vouchers.values()
            if v.voucher_type == "purchase" and v.date >= self.today - timedelta(days=90)
        ]
        daily_out = sum(float(v.amount) for v in recent) / 78
        sup_share = defaultdict(float)
        for v in recent:
            sup_share[v.party_id] += float(v.amount)
        sup_total = sum(sup_share.values()) or 1
        for k in range(weeks * 7):
            d = start + timedelta(days=k)
            if d.weekday() == 6:
                continue
            for p in buyers:
                weight = 0.6 if p["grade"] == "D" else 0.9 if p["grade"] == "C" else 1.0
                put(
                    d + timedelta(days=p["usual_pay_day"]),
                    "in",
                    daily_in * p["sales_12m"] / total_12m * weight,
                    "New sales collected",
                )
            for sid, amt in sup_share.items():
                put(
                    d + timedelta(days=self.parties[sid].credit_days),
                    "out",
                    daily_out * amt / sup_total,
                    "New purchases falling due",
                )
        for k in range(weeks * 7):
            d = start + timedelta(days=k)
            if d.day == 1:
                put(d, "out", monthly_sales * 0.018, "Salaries")
            if d.day == 5:
                put(d, "out", monthly_sales * 0.004, "Rent and utilities")
            if d.day == 20:
                put(d, "out", monthly_sales * 0.012, "GST payment")

        out, balance = [], bank_balance
        for k, bk in enumerate(buckets):

            def top(side: str, bk=bk) -> list[dict]:
                return [
                    {"name": n, "amount": round(a, 2)}
                    for n, a in sorted(bk[f"{side}_top"].items(), key=lambda x: -x[1])[:6]
                ]

            opening = balance
            balance = opening + bk["in"] - bk["out"]
            out.append(
                {
                    "week_start": start + timedelta(days=7 * k),
                    "scenario": "base",
                    "opening_balance": round(opening, 2),
                    "inflow": round(bk["in"], 2),
                    "outflow": round(bk["out"], 2),
                    "closing_balance": round(balance, 2),
                    "detail": {
                        "in": top("in"),
                        "out": top("out"),
                        "in_parties": {str(p): round(a, 2) for p, a in bk["in_rows"].items()},
                        "out_parties": {str(p): round(a, 2) for p, a in bk["out_rows"].items()},
                    },
                }
            )
        return out

    # ------------------------------------------------------------------- kpis

    def kpis(self, days: int, history_days: int) -> list[dict]:
        sales, coll = defaultdict(float), defaultdict(float)
        for v in self.vouchers.values():
            if v.voucher_type == "sales":
                sales[v.date] += float(v.amount) - float(v.tax_amount)
            elif v.voucher_type == "receipt":
                coll[v.date] += float(v.amount)
        out = []
        for k in range(days, 0, -1):
            d = self.today - timedelta(days=k)
            out.append({"day": d, "metric": "sales", "value": round(sales.get(d, 0), 2)})
            out.append({"day": d, "metric": "collections", "value": round(coll.get(d, 0), 2)})
        recv = [b for b in self.bills if b.direction == "receivable"]
        for k in range(history_days, -1, -1):
            day = self.today - timedelta(days=k)
            total = overdue = 0.0
            for b in recv:
                if b.bill_date > day:
                    continue
                pending = float(b.amount) - sum(float(a.amount) for a in self.allocs[b.id] if a.date <= day)
                if pending > 1:
                    total += pending
                    if b.due_date < day:
                        overdue += pending
            out.append({"day": day, "metric": "receivable", "value": round(total, 2)})
            out.append({"day": day, "metric": "overdue", "value": round(overdue, 2)})
        return out


def refresh(db: Session, *, kpi_history: bool | None = None) -> dict:
    """Recompute every fact for the bound desk. Returns a short summary."""
    org = db.info["organisation_id"]
    books = Books(db)
    biz = clock.business(db)
    now = clock.now(db)

    promises = list(db.scalars(select(KbPromise)))
    profiles = books.customer_profiles(promises)
    db.execute(delete(KbCustomerProfile))
    if profiles:
        db.execute(
            insert(KbCustomerProfile), [{"organisation_id": org, "computed_at": now, **p} for p in profiles]
        )

    metrics = books.item_metrics(
        float(rules.get(db, "stock", "reorder_days")), int(rules.get(db, "stock", "idle_days"))
    )
    db.execute(delete(KbItemMetric))
    if metrics:
        db.execute(insert(KbItemMetric), [{"organisation_id": org, "computed_at": now, **m} for m in metrics])

    points = books.price_points()
    db.execute(delete(KbPricePoint))
    for i in range(0, len(points), 5000):
        db.execute(insert(KbPricePoint), [{"organisation_id": org, **p} for p in points[i : i + 5000]])

    weeks = int(rules.get(db, "cash", "horizon_weeks"))
    forecast = books.cash_forecast(profiles, float(biz.bank_balance or 0), weeks)
    db.execute(delete(KbCashWeek))
    db.execute(insert(KbCashWeek), [{"organisation_id": org, "computed_at": now, **w} for w in forecast])

    full = kpi_history if kpi_history is not None else db.scalar(select(KbKpi.id).limit(1)) is None
    kpis = books.kpis(365 if full else 7, 90 if full else 1)
    days = {k["day"] for k in kpis}
    db.execute(delete(KbKpi).where(KbKpi.day.in_(days)))
    for i in range(0, len(kpis), 5000):
        db.execute(insert(KbKpi), [{"organisation_id": org, **k} for k in kpis[i : i + 5000]])
    db.flush()
    return {
        "customers": len(profiles),
        "items": len(metrics),
        "price_points": len(points),
        "weeks": len(forecast),
    }
