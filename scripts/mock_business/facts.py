"""Layer B: business facts, computed by plain code from the Tally mirror.

These are the numbers every agent reads instead of working them out again, so
the Sales agent, the Collections agent and the morning brief always agree.
The same functions are the reference for the real nightly/after-sync job:
deterministic, explainable, no LLM involved.

    customer_profiles  grade, payment habit, trend, suggested limit, reasons
    item_metrics       sales rate, days of stock left, idle days, status
    price_points       every rate seen: sold, bought, quoted, offered
    cash_forecast      next four weeks of money in and out
    kpi_snapshots      daily headline numbers, for "what changed"
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

#: Grading thresholds on average days late (recent six months, weighted by amount).
GRADE_BANDS = ((5, "A"), (15, "B"), (35, "C"))
#: Days of stock below which an item is due for reorder (agent_rules stock.reorder_days).
REORDER_DAYS = 12
WATCH_DAYS = 20
IDLE_DAYS = 60


def _org(rows, org):
    return [r for r in rows if r["organisation_id"] == org]


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


class Facts:
    def __init__(self, rows: dict[str, list[dict]], org: int, today: date) -> None:
        self.rows, self.org, self.today = rows, org, today
        self.parties = {p["id"]: p for p in _org(rows["parties"], org)}
        self.vouchers = {v["id"]: v for v in _org(rows["vouchers"], org)}
        self.bills = _org(rows["bills"], org)
        self.allocs = defaultdict(list)
        for a in _org(rows["bill_allocations"], org):
            self.allocs[a["bill_id"]].append(a)
        self.lines = _org(rows["voucher_lines"], org)
        self.items = {i["id"]: i for i in _org(rows["items"], org)}

    # --------------------------------------------------------------- customers

    def _payment_picture(self, party_id: int, as_of: date):
        """Days late per bill as of a date: paid bills by when they were cleared,
        open overdue bills by how late they are so far."""
        since = as_of - timedelta(days=180)
        late, pay_days, oldest, outstanding, overdue = [], [], 0, 0.0, 0.0
        for b in self.bills:
            if b["party_id"] != party_id or b["direction"] != "receivable" or b["bill_date"] > as_of:
                continue
            paid = [a for a in self.allocs[b["id"]] if a["date"] <= as_of]
            paid_amt = sum(a["amount"] for a in paid)
            pending = round(b["amount"] - paid_amt, 2)
            if pending <= 1:
                cleared = max(a["date"] for a in paid)
                if cleared >= since:
                    late.append(((cleared - b["due_date"]).days, b["amount"]))
                pay_days.append((cleared - b["bill_date"]).days)
            else:
                outstanding += pending
                if b["due_date"] < as_of:
                    days = (as_of - b["due_date"]).days
                    overdue += pending
                    oldest = max(oldest, days)
                    late.append((days, pending))
        total = sum(w for _, w in late)
        avg_late = sum(d * w for d, w in late) / total if total else 0.0
        return avg_late, pay_days, oldest, outstanding, overdue

    def customer_profiles(self, promises: list[dict] | None = None) -> list[dict]:
        promises = promises or []
        sales = defaultdict(list)
        for v in self.vouchers.values():
            if v["voucher_type"] == "sales":
                sales[v["party_id"]].append(v)
        out = []
        for pid, p in self.parties.items():
            if p["kind"] != "customer":
                continue
            avg_late, pay_days, oldest, outstanding, overdue = self._payment_picture(pid, self.today)
            prev_avg, _, prev_oldest, _, _ = self._payment_picture(pid, self.today - timedelta(days=30))
            mine = [x for x in promises if x["party_id"] == pid and x["status"] != "open"]
            kept = sum(1 for x in mine if x["status"] in ("kept", "part_kept"))
            miss_rate = (1 - kept / len(mine)) if len(mine) >= 2 else None
            grade = grade_for(avg_late, oldest, miss_rate)
            prev = grade_for(prev_avg, prev_oldest, None)
            vs = sorted(sales[pid], key=lambda v: v["date"])
            net = [(v["date"], v["amount"] - v["tax_amount"]) for v in vs]
            s12 = sum(a for d, a in net if d >= self.today - timedelta(days=365))
            s90 = sum(a for d, a in net if d >= self.today - timedelta(days=90))
            last = vs[-1]["date"] if vs else None
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
            factor = {"A": 1.5, "B": 1.2, "C": 0.8, "D": 0.4}[grade]
            limit = round(monthly * factor / 1e5) * 1e5 if monthly else None
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
                    "organisation_id": self.org,
                    "grade": grade,
                    "previous_grade": prev,
                    "avg_days_late": round(avg_late, 1),
                    "usual_pay_day": int(statistics.median(pay_days)) if pay_days else p["credit_days"],
                    "promises_made": len(mine)
                    + sum(1 for x in promises if x["party_id"] == pid and x["status"] == "open"),
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
                    "computed_at": f"{self.today} 06:00:00+05:30",
                }
            )
        return out

    # ------------------------------------------------------------------- items

    def item_metrics(self, stock_now: dict[int, float], cost_of: dict[int, float]) -> list[dict]:
        sold7, sold28, last = defaultdict(float), defaultdict(float), {}
        for ln in self.lines:
            v = self.vouchers[ln["voucher_id"]]
            if v["voucher_type"] != "sales":
                continue
            d = v["date"]
            if d >= self.today - timedelta(days=7):
                sold7[ln["item_id"]] += ln["qty"]
            if d >= self.today - timedelta(days=28):
                sold28[ln["item_id"]] += ln["qty"]
            last[ln["item_id"]] = max(last.get(ln["item_id"], d), d)
        out = []
        for iid, _it in self.items.items():
            per_day = sold28[iid] / 28
            stock = stock_now.get(iid, 0.0)
            days_left = round(stock / per_day, 1) if per_day > 0 else None
            idle = (self.today - last[iid]).days if iid in last else 365
            if stock > 0 and idle >= IDLE_DAYS:
                status = "idle"
            elif days_left is not None and days_left < REORDER_DAYS:
                status = "reorder"
            elif days_left is not None and days_left < WATCH_DAYS:
                status = "watch"
            else:
                status = "ok"
            out.append(
                {
                    "item_id": iid,
                    "organisation_id": self.org,
                    "sold_7d": round(sold7[iid], 3),
                    "sold_28d": round(sold28[iid], 3),
                    "per_day": round(per_day, 3),
                    "stock_qty": round(stock, 3),
                    "stock_value": round(stock * cost_of[iid], 2),
                    "days_left": days_left,
                    "last_sale_on": last.get(iid),
                    "idle_days": idle,
                    "reorder_qty": round(per_day * 30, 3) if per_day else None,
                    "status": status,
                    "computed_at": f"{self.today} 06:00:00+05:30",
                }
            )
        return out

    # ------------------------------------------------------------------- prices

    def price_points(self, extra: list[dict]) -> list[dict]:
        out = []
        for ln in self.lines:
            v = self.vouchers[ln["voucher_id"]]
            if v["voucher_type"] in ("sales", "purchase"):
                out.append(
                    {
                        "organisation_id": self.org,
                        "item_id": ln["item_id"],
                        "party_id": v["party_id"],
                        "source": "sale" if v["voucher_type"] == "sales" else "purchase",
                        "date": v["date"],
                        "rate": ln["rate"],
                        "qty": ln["qty"],
                    }
                )
        return out + extra

    # --------------------------------------------------------------------- cash

    def cash_forecast(
        self, profiles: list[dict], monthly_sales: float, bank_balance: float = 0.0, weeks: int = 4
    ) -> list[dict]:
        """Money in and out over the next weeks, from open bills, payment habits
        and the usual fixed outgoings, carried on from today's bank balance.
        Week 1 starts today."""
        habit = {p["party_id"]: p for p in profiles}
        start = self.today
        buckets = [
            {"in": 0.0, "out": 0.0, "in_top": defaultdict(float), "out_top": defaultdict(float)}
            for _ in range(weeks)
        ]

        def put(d: date, side: str, amount: float, label: str) -> None:
            k = (d - start).days // 7
            if 0 <= k < weeks:
                buckets[k][side] += amount
                buckets[k][f"{side}_top"][label] += amount

        late_wait = {"A": 3, "B": 7, "C": 14, "D": 30}
        for b in self.bills:
            pending = b["amount"] - sum(a["amount"] for a in self.allocs[b["id"]])
            if pending <= 1:
                continue
            name = self.parties[b["party_id"]]["name"]
            if b["direction"] == "receivable":
                h = habit.get(b["party_id"])
                grade = h["grade"] if h else "B"
                expected = b["bill_date"] + timedelta(days=h["usual_pay_day"] if h else 45)
                if expected < start:
                    expected = start + timedelta(days=late_wait[grade])
                weight = 0.6 if grade == "D" else 0.9 if grade == "C" else 1.0
                put(expected, "in", pending * weight, name)
            else:
                put(max(b["due_date"], start), "out", pending, name)

        # Sales made during the forecast, collected on each customer's own habit;
        # purchases made during it, paid on each supplier's credit terms.
        buyers = [p for p in profiles if p["sales_12m"] > 0]
        total_12m = sum(p["sales_12m"] for p in buyers) or 1
        daily_in = monthly_sales * 1.18 * 12 / 312  # with tax, per working day
        recent = [
            v
            for v in self.vouchers.values()
            if v["voucher_type"] == "purchase" and v["date"] >= self.today - timedelta(days=90)
        ]
        daily_out = sum(v["amount"] for v in recent) / 78
        sup_share = defaultdict(float)
        for v in recent:
            sup_share[v["party_id"]] += v["amount"]
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
                    d + timedelta(days=self.parties[sid]["credit_days"]),
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

            def top(side: str, bk: dict = bk) -> list[dict]:
                return [
                    {"name": n, "amount": round(a, 2)}
                    for n, a in sorted(bk[f"{side}_top"].items(), key=lambda x: -x[1])[:5]
                ]

            opening = balance
            balance = opening + bk["in"] - bk["out"]
            out.append(
                {
                    "organisation_id": self.org,
                    "week_start": start + timedelta(days=7 * k),
                    "scenario": "base",
                    "opening_balance": round(opening, 2),
                    "inflow": round(bk["in"], 2),
                    "outflow": round(bk["out"], 2),
                    "closing_balance": round(balance, 2),
                    "detail": {"in": top("in"), "out": top("out")},
                    "computed_at": f"{self.today} 06:00:00+05:30",
                }
            )
        return out

    # ---------------------------------------------------------------------- kpis

    def kpi_snapshots(
        self, daily_sales: dict[date, float], daily_collections: dict[date, float]
    ) -> list[dict]:
        out = []
        start = self.today - timedelta(days=365)
        d = start
        while d < self.today:
            out.append(
                {
                    "organisation_id": self.org,
                    "day": d,
                    "metric": "sales",
                    "value": round(daily_sales.get(d, 0), 2),
                }
            )
            out.append(
                {
                    "organisation_id": self.org,
                    "day": d,
                    "metric": "collections",
                    "value": round(daily_collections.get(d, 0), 2),
                }
            )
            d += timedelta(days=1)
        # Receivable and overdue, end of each of the last 90 days.
        recv = [b for b in self.bills if b["direction"] == "receivable"]
        for k in range(90, 0, -1):
            day = self.today - timedelta(days=k)
            total = overdue = 0.0
            for b in recv:
                if b["bill_date"] > day:
                    continue
                pending = b["amount"] - sum(a["amount"] for a in self.allocs[b["id"]] if a["date"] <= day)
                if pending > 1:
                    total += pending
                    if b["due_date"] < day:
                        overdue += pending
            out.append(
                {"organisation_id": self.org, "day": day, "metric": "receivable", "value": round(total, 2)}
            )
            out.append(
                {"organisation_id": self.org, "day": day, "metric": "overdue", "value": round(overdue, 2)}
            )
        return out
