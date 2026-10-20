"""Check a loaded mock knowledge base: the books reconcile and every planted
situation can be found with plain SQL.

    python scripts/mock_business/verify.py "postgresql://user@host/db"
    python scripts/mock_business/verify.py "-h /tmp -U pgu -d kbtest"     # psql arguments also work

Exit code 0 when everything passes. Uses psql, so no Python driver is needed.
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RECONCILE = {
    "sale and purchase bills match their vouchers": "select count(*) from kb.bills b join kb.vouchers v on v.id=b.voucher_id where b.amount <> v.amount",
    "pending = amount - allocations, on every bill": "select count(*) from kb.bills b left join (select bill_id, sum(amount) s from kb.bill_allocations group by 1) a "
    "on a.bill_id=b.id where abs(b.amount - coalesce(a.s,0) - b.pending_amount) > 0.05",
    "no bill is over-paid": "select count(*) from kb.bills where pending_amount < -0.05",
    "receipts and payments equal what they settle": "select count(*) from kb.vouchers v join (select voucher_id, sum(amount) s from kb.bill_allocations group by 1) a "
    "on a.voucher_id=v.id where v.voucher_type in ('receipt','payment') and abs(v.amount - a.s) > 0.05",
    "invoice totals = lines + tax": "select count(*) from kb.vouchers v join (select voucher_id, sum(amount) s from kb.voucher_lines group by 1) l "
    "on l.voucher_id=v.id where v.voucher_type in ('sales','purchase') and abs(v.amount - v.tax_amount - l.s) > 1",
    "stock on hand = latest godown balances": "select count(*) from kb.item_metrics m join (select item_id, sum(qty) q from kb.stock_balances sb "
    "where as_of = (select max(as_of) from kb.stock_balances x where x.organisation_id = sb.organisation_id) "
    "group by 1) s on s.item_id=m.item_id where abs(s.q - m.stock_qty) > 1",
    "no negative stock": "select count(*) from kb.stock_balances where qty < 0",
    "won quotes point at a real sale": "select count(*) from kb.quotes q left join kb.vouchers v on v.id=q.sales_voucher_id "
    "where q.sales_voucher_id is not null and (v.voucher_type <> 'sales' or v.party_id <> q.party_id)",
    "every event is delivered to its subscribers": "select count(*) from kb.events e where e.type <> 'message.sent' and not exists "
    "(select 1 from kb.event_deliveries d where d.event_id=e.id)",
    "every row belongs to one business (parties)": "select count(*) from kb.voucher_lines l join kb.vouchers v on v.id=l.voucher_id "
    "where l.organisation_id <> v.organisation_id",
}


def psql(conn: str, sql: str) -> list[list[str]]:
    args = ["psql", conn] if "://" in conn else ["psql", *shlex.split(conn)]
    out = subprocess.run(
        [*args, "-At", "-F", "\t", "-v", "ON_ERROR_STOP=1", "-c", sql],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line.split("\t") for line in out.splitlines() if line]


def near(a: float, b: float, rel: float = 0.01) -> bool:
    return abs(a - b) <= max(1.0, abs(b) * rel)


def check(s: dict, rows: list[list[str]]) -> tuple[bool, str]:
    e, sid = s["expect"], s["id"]
    if not rows:
        return False, "no rows"
    r = rows[0]
    if sid == "cold_quote":
        return r[1] == "sent" and r[2] == "t", f"status {r[1]}, unopened {r[2]}"
    if sid == "below_margin_quote":
        return r[1] == "pending_approval" and r[2] == "waiting", f"quote {r[1]}, approval {r[2]}"
    if sid == "missed_promise":
        return r[1] == "missed", f"{r[0]}: {r[1]} due {r[2]}"
    if sid == "stock_out":
        return r[1] == "reorder" and float(r[2]) < e["days_left_below"], f"{r[0]}: {r[1]}, {r[2]} days left"
    if sid == "rate_drop":
        return r[0] == e["supplier"] and near(float(r[1]), e["rate"], 0.0001), f"cheapest {r[0]} at {r[1]}"
    if sid == "slipping_customer":
        return r[1] == "down", f"{r[0]}: trend {r[1]}, last order {r[2]}"
    if sid == "grade_drop":
        worse = "ABCD".index(r[2]) > "ABCD".index(r[1])
        return r[1] == e["previous_grade"] and r[2] == e[
            "grade"
        ] and worse, f"{r[0]}: {r[1]} -> {r[2]}, {r[3]} days late"
    if sid == "idle_stock":
        return r[1] == "idle", f"{r[0]}: {r[1]}, {r[2]} idle days"
    if sid == "cash_gap":
        return r[0] == e["short_week_start"] and e[
            "short_week_number"
        ] == 3, f"first short week {r[0]} closing {r[1]}"
    if sid == "duplicate_ledger":
        return int(r[0]) == 2, f"{r[0]} ledgers with that GSTIN"
    if sid in ("ask_top_debtor",):
        return r[0] == e["party"] and near(float(r[1]), e["amount"]), f"{r[0]} {r[1]}"
    if sid in ("ask_total_overdue", "ask_last_month_sales", "ask_payables_week"):
        return near(float(r[0] or 0), e["amount"]), f"{r[0]} vs {e['amount']}"
    if sid == "ask_running_out":
        got = [x[0] for x in rows]
        return got == e["items"], f"{got}"
    if sid == "ask_last_rate":
        return near(float(r[0]), e["rate"], 0.0001) and r[1] == e["date"], f"{r[0]} on {r[1]}"
    if sid == "ask_grade_mix":
        return int(r[0]) == e["count"], f"{r[0]}"
    return False, "no checker"


def main() -> int:
    conn = sys.argv[1] if len(sys.argv) > 1 else "-h /tmp -U pgu -d kbtest"
    data = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "mock_business"
    failed = 0
    print("Books")
    for name, sql in RECONCILE.items():
        n = int(psql(conn, sql)[0][0])
        failed += n > 0
        print(f"  {'ok ' if n == 0 else 'BAD'} {name}" + (f"  ({n} rows)" if n else ""))
    print("Scenarios")
    for s in json.loads((data / "scenarios.json").read_text())["scenarios"]:
        rows = psql(conn, s["check_sql"]) if s["id"] != "ask_running_out" or s["expect"]["items"] else [[""]]
        ok, note = (
            (True, "none expected")
            if s["id"] == "ask_running_out" and not s["expect"]["items"] and rows == [[""]]
            else check(s, rows)
        )
        failed += not ok
        print(f"  {'ok ' if ok else 'BAD'} [{s['organisation_id']}] {s['id']:<20} {note}")
    print("all good" if not failed else f"{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
