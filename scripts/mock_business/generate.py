"""Generate the Oprisa mock knowledge base.

    uv run python scripts/mock_business/generate.py            # writes data/mock_business/
    uv run python scripts/mock_business/generate.py --today 2026-10-19 --out /tmp/kb

Three sample businesses, twelve months of Tally-shaped books each, the last
month of agent and team work on top, the business facts computed from both,
and a set of planted situations with the answer each agent should give
(scenarios.json): the golden test set for the agents.

Same seed, same data: every run with the same --today produces identical files.

Load into Postgres (pgvector needed for the schema):

    psql "$DB" -f docs/agents/schema.sql
    cd data/mock_business && psql "$DB" -f load.sql
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog import COMPANIES, DEFAULT_TODAY  # noqa: E402
from facts import Facts  # noqa: E402
from simulate import Simulation, Store, money  # noqa: E402
from work import Work  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

#: Load order: every table after the tables it points to.
TABLES = (
    "organisations",
    "users",
    "tally_sync_runs",
    "godowns",
    "parties",
    "items",
    "vouchers",
    "voucher_lines",
    "bills",
    "bill_allocations",
    "stock_balances",
    "customer_profiles",
    "item_metrics",
    "price_points",
    "cash_forecast",
    "kpi_snapshots",
    "enquiries",
    "quotes",
    "quote_lines",
    "promises",
    "messages",
    "share_links",
    "rfqs",
    "supplier_quotes",
    "purchase_orders",
    "po_lines",
    "tasks",
    "approvals",
    "agent_rules",
    "events",
    "event_deliveries",
    "item_aliases",
    "memories",
    "documents",
    "document_chunks",
    "chat_threads",
    "agent_runs",
)
JSON_COLUMNS = {"parsed", "payload", "reasons", "detail", "response", "outcome", "value"}
JSON_TABLES_FOR_VALUE = {"agent_rules"}  # kpi_snapshots.value is numeric, agent_rules.value is jsonb


def build(today: date) -> tuple[Store, list[dict], list[dict]]:
    store = Store()
    scenarios, summary = [], []
    for company in COMPANIES:
        sim = Simulation(company, store, today, seed=company.id * 101)
        sim.run()
        work = Work(sim, store, seed=company.id * 103)
        work.enquiries_and_quotes()
        promises = work.promises()
        work.reminders()
        work.purchasing()

        facts = Facts(store.rows, company.id, today)
        profiles = facts.customer_profiles(promises)
        metrics = facts.item_metrics(sim.stock, work.cost_now)
        last_year = [a for d, a in sim.daily_sales.items() if d >= today - timedelta(days=365)]
        monthly_sales = sum(last_year) / 12
        forecast = facts.cash_forecast(
            profiles, monthly_sales, _bank_balance(facts.cash_forecast(profiles, monthly_sales))
        )
        extra = [
            {k: v for k, v in p.items()}
            for p in store.rows["_quote_prices"]
            if p["organisation_id"] == company.id
        ]
        for p in facts.price_points(extra):
            store.add("price_points", id=None, **p)
        for table, rows in (
            ("customer_profiles", profiles),
            ("item_metrics", metrics),
            ("cash_forecast", forecast),
            ("kpi_snapshots", facts.kpi_snapshots(sim.daily_sales, sim.daily_collections)),
        ):
            store.rows[table].extend(rows)
        _tally_credit_limits(sim, profiles)

        work.inbox_and_scenarios(profiles, metrics, promises, forecast)
        work.memory()
        work.runs_and_sync()
        work.write_events()

        for s in work.scenarios + _ask_golden(store, company, today, profiles, metrics):
            scenarios.append({"organisation_id": company.id, "business": company.name, **s})
        summary.append(_summary(store, company, sim, profiles, metrics, forecast))
    return store, scenarios, summary


def _bank_balance(dry_run: list[dict]) -> float:
    """Today's bank balance (the Bank ledger in Tally), set so the planted week-3
    gap is the first week the balance goes below zero: enough to cover weeks 1-2,
    not enough for the big supplier bill in week 3."""
    cum, running = [], 0.0
    for w in dry_run:
        running += w["inflow"] - w["outflow"]
        cum.append(running)
    floor = max(0.0, -min(cum[0], cum[1]))
    gap = -cum[2]
    if gap <= floor:
        nets = [round(w["inflow"] - w["outflow"]) for w in dry_run]
        raise SystemExit(
            f"cash scenario not planted: week 3 ({gap:.0f}) is not short beyond weeks 1-2 ({floor:.0f}); "
            f"weekly nets {nets}"
        )
    return round((floor + gap) / 2 / 1e5) * 1e5


def _tally_credit_limits(sim: Simulation, profiles: list[dict]) -> None:
    """What the owner typed into Tally long ago: generous, based on last year's buying."""
    prof = {p["party_id"]: p for p in profiles}
    for cu in sim.customers:
        p = prof.get(cu.party["id"])
        if not p or not p["sales_12m"]:
            continue
        monthly = p["sales_12m"] / 12 * 1.18
        if sim.r.random() < 0.7 or cu is sim.plan.grade_drop:
            cu.party["credit_limit"] = max(1e5, round(monthly * 2.5 / 1e5) * 1e5)


# --------------------------------------------------------------------- ask golden set


def _ask_golden(store: Store, company, today: date, profiles: list[dict], metrics: list[dict]) -> list[dict]:
    """Questions an owner asks, with the answer worked out from the data.

    The Ask agent passes if its answer contains the expected figure (within 1%)
    and names the right party or item. The SQL is what a correct tool call returns.
    """
    org = company.id
    parties = {p["id"]: p for p in store.rows["parties"] if p["organisation_id"] == org}
    items = {i["id"]: i for i in store.rows["items"] if i["organisation_id"] == org}
    out = []

    top = max(profiles, key=lambda p: p["outstanding"])
    out.append(
        _ask(
            "ask_top_debtor",
            "Who owes me the most?",
            {"party": parties[top["party_id"]]["name"], "amount": top["outstanding"]},
            f"select p.name, sum(b.pending_amount) from kb.bills b join kb.parties p on p.id=b.party_id "
            f"where b.organisation_id={org} and b.direction='receivable' group by p.name order by 2 desc limit 1",
        )
    )

    overdue = round(sum(p["overdue"] for p in profiles), 2)
    out.append(
        _ask(
            "ask_total_overdue",
            "How much is overdue right now?",
            {"amount": overdue},
            f"select sum(pending_amount) from kb.overdue_bills where organisation_id={org}",
        )
    )

    first = today.replace(day=1)
    last_month_start = (first - timedelta(days=1)).replace(day=1)
    net = sum(
        v["amount"] - v["tax_amount"]
        for v in store.rows["vouchers"]
        if v["organisation_id"] == org
        and v["voucher_type"] == "sales"
        and last_month_start <= v["date"] < first
    )
    out.append(
        _ask(
            "ask_last_month_sales",
            f"What were my sales in {last_month_start:%B}?",
            {"amount": round(net, 2), "before_tax": True},
            f"select sum(amount - tax_amount) from kb.vouchers where organisation_id={org} and voucher_type='sales' "
            f"and date >= '{last_month_start}' and date < '{first}'",
        )
    )

    short = sorted(
        (m for m in metrics if m["days_left"] is not None and m["days_left"] < 7),
        key=lambda m: m["days_left"],
    )
    out.append(
        _ask(
            "ask_running_out",
            "Which items will run out this week?",
            {"items": [items[m["item_id"]]["name"] for m in short]},
            f"select i.name from kb.item_metrics m join kb.items i on i.id=m.item_id "
            f"where m.organisation_id={org} and m.days_left < 7 order by m.days_left",
        )
    )

    week = today + timedelta(days=7)
    pay = sum(
        b["pending_amount"]
        for b in store.rows["bills"]
        if b["organisation_id"] == org
        and b["direction"] == "payable"
        and b["pending_amount"] > 1
        and b["due_date"] < week
    )
    out.append(
        _ask(
            "ask_payables_week",
            "How much do I have to pay suppliers this week?",
            {"amount": money(pay)},
            f"select coalesce(sum(pending_amount), 0) from kb.bills where organisation_id={org} and direction='payable' "
            f"and pending_amount > 1 and due_date < '{week}'",
        )
    )

    big = max(profiles, key=lambda p: p["sales_12m"])
    last_sale = {}
    vids = {
        v["id"]: v["date"]
        for v in store.rows["vouchers"]
        if v["organisation_id"] == org and v["voucher_type"] == "sales" and v["party_id"] == big["party_id"]
    }
    for ln in store.rows["voucher_lines"]:
        if ln["voucher_id"] in vids:
            d = vids[ln["voucher_id"]]
            if ln["item_id"] not in last_sale or d >= last_sale[ln["item_id"]][0]:
                last_sale[ln["item_id"]] = (d, ln["rate"])
    iid, (d, rate) = max(last_sale.items(), key=lambda kv: kv[1][0])
    out.append(
        _ask(
            "ask_last_rate",
            f"What rate did {parties[big['party_id']]['name']} pay for {items[iid]['name']} last time?",
            {"rate": rate, "date": str(d)},
            f"select rate, date from kb.last_sale_rate where party_id={big['party_id']} and item_id={iid}",
        )
    )

    grades = defaultdict(int)
    for p in profiles:
        if p["sales_12m"] > 0:
            grades[p["grade"]] += 1
    out.append(
        _ask(
            "ask_grade_mix",
            "How many of my customers are grade D?",
            {"count": grades["D"]},
            f"select count(*) from kb.customer_profiles where organisation_id={org} and grade='D' and sales_12m > 0",
        )
    )
    return out


def _ask(id_: str, question: str, expect: dict, sql: str) -> dict:
    return {
        "id": id_,
        "agent": "ask",
        "title": question,
        "situation": "Owner asks in chat.",
        "expect": expect,
        "check_sql": sql,
    }


def _summary(store, company, sim, profiles, metrics, forecast) -> dict:
    org = company.id
    count = {
        t: sum(1 for r in rows if r.get("organisation_id") == org)
        for t, rows in store.rows.items()
        if not t.startswith("_")
    }
    sales = sum(sim.daily_sales.values())
    recv = sum(p["outstanding"] for p in profiles)
    return {
        "organisation_id": org,
        "business": company.name,
        "trade": company.trade,
        "city": company.city,
        "sales_12m_before_tax": round(sales, 2),
        "receivable": round(recv, 2),
        "overdue": round(sum(p["overdue"] for p in profiles), 2),
        "dso_days": round(recv / (sales * 1.18 / 365), 1) if sales else None,
        "customers_buying": sum(1 for p in profiles if p["sales_12m"] > 0),
        "grades": {g: sum(1 for p in profiles if p["grade"] == g and p["sales_12m"] > 0) for g in "ABCD"},
        "items_reorder": sum(1 for m in metrics if m["status"] == "reorder"),
        "bank_balance": forecast[0]["opening_balance"],
        "cash_weeks": [
            {"week_start": str(f["week_start"]), "closing": f["closing_balance"]} for f in forecast
        ],
        "rows": {t: n for t, n in sorted(count.items()) if n},
    }


# --------------------------------------------------------------------------- output


def _cell(table: str, col: str, v):
    if v is None:
        return ""
    if col in JSON_COLUMNS and (col != "value" or table in JSON_TABLES_FOR_VALUE):
        return json.dumps(v, default=str, ensure_ascii=False)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def write_csv(store: Store, out: Path) -> dict[str, list[str]]:
    csv_dir = out / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    columns = {}
    for table in TABLES:
        rows = store.rows.get(table, [])
        cols = list(dict.fromkeys(k for r in rows[:1] for k in r)) if rows else []
        for r in rows:  # same columns on every row
            for k in r:
                if k not in cols:
                    cols.append(k)
        cols = [c for c in cols if c != "tsv"]
        columns[table] = cols
        with open(csv_dir / f"{table}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow([_cell(table, c, r.get(c)) for c in cols])
    return columns


def write_load_sql(columns: dict[str, list[str]], out: Path) -> None:
    lines = [
        "-- Load the mock knowledge base. Run from this folder after docs/agents/schema.sql:",
        '--   psql "$DB" -f load.sql',
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
        "SET search_path = kb, public;",
    ]
    for table in TABLES:
        cols = columns.get(table)
        if not cols:
            continue
        lines.append(
            f"\\copy kb.{table} ({', '.join(cols)}) FROM 'csv/{table}.csv' WITH (FORMAT csv, HEADER true)"
        )
    lines += ["COMMIT;", "ANALYZE;", ""]
    (out / "load.sql").write_text("\n".join(lines))


def write_tally_xml(store: Store, out: Path, org: int = 1, n_vouchers: int = 12) -> None:
    """A small export in the shape TallyPrime returns over XML on port 9000.

    Approximate: it follows the ENVELOPE / BODY / DATA / TALLYMESSAGE layout and
    the common tag names (LEDGER, STOCKITEM, VOUCHER, ALLINVENTORYENTRIES.LIST,
    BILLALLOCATIONS.LIST), but it is not a byte-for-byte Tally export. Its job is
    to give the sync parser a realistic fixture.
    """
    rows = store.rows
    parties = {p["id"]: p for p in rows["parties"] if p["organisation_id"] == org}
    items = {i["id"]: i for i in rows["items"] if i["organisation_id"] == org}
    org_row = next(o for o in rows["organisations"] if o["id"] == org)
    vouchers = [v for v in rows["vouchers"] if v["organisation_id"] == org]
    picked, seen = [], set()
    for v in sorted(vouchers, key=lambda v: (v["date"], v["id"]), reverse=True):
        if (
            v["voucher_type"] in ("sales", "receipt", "purchase")
            and (v["voucher_type"], len(picked) // 3) not in seen
        ):
            picked.append(v)
            seen.add((v["voucher_type"], len(picked) // 3))
        if len(picked) >= n_vouchers:
            break
    lines_by_v = defaultdict(list)
    for ln in rows["voucher_lines"]:
        if ln["voucher_id"] in {v["id"] for v in picked}:
            lines_by_v[ln["voucher_id"]].append(ln)
    allocs = defaultdict(list)
    bills = {b["id"]: b for b in rows["bills"] if b["organisation_id"] == org}
    for a in rows["bill_allocations"]:
        if a["organisation_id"] == org:
            allocs[a["voucher_id"]].append(a)
    used_parties = {v["party_id"] for v in picked}
    used_items = {ln["item_id"] for v in picked for ln in lines_by_v[v["id"]]}

    def amt(x: float, debit: bool) -> str:  # Tally writes debits negative
        return f"{-x:.2f}" if debit else f"{x:.2f}"

    x = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Mock TallyPrime export (approximate shape) for the Oprisa sync parser tests. -->",
        "<ENVELOPE>",
        " <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE>"
        "<ID>Oprisa Sync</ID></HEADER>",
        " <BODY><DESC><STATICVARIABLES>"
        f"<SVCURRENTCOMPANY>{escape(org_row['name'])}</SVCURRENTCOMPANY><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"
        "</STATICVARIABLES></DESC>",
        "  <DATA>",
    ]
    for pid in sorted(used_parties):
        p = parties[pid]
        x += [
            f'   <TALLYMESSAGE><LEDGER NAME="{escape(p["name"])}" ACTION="Create">',
            f"    <GUID>{p['tally_guid']}</GUID><PARENT>{p['tally_group']}</PARENT>",
            f"    <PARTYGSTIN>{p['gstin']}</PARTYGSTIN><LEDGERPHONE>{p['phone']}</LEDGERPHONE>",
            f"    <BILLCREDITPERIOD>{p['credit_days']} Days</BILLCREDITPERIOD><ISBILLWISEON>Yes</ISBILLWISEON>",
            "   </LEDGER></TALLYMESSAGE>",
        ]
    for iid in sorted(used_items):
        i = items[iid]
        x += [
            f'   <TALLYMESSAGE><STOCKITEM NAME="{escape(i["name"])}" ACTION="Create">',
            f"    <GUID>{i['tally_guid']}</GUID><PARENT>{escape(i['stock_group'])}</PARENT>"
            f"<BASEUNITS>{i['unit']}</BASEUNITS>",
            f"    <GSTDETAILS.LIST><HSNCODE>{i['hsn'] or ''}</HSNCODE><TAXABILITY>Taxable</TAXABILITY>"
            f"<RATE>{i['gst_rate']}</RATE></GSTDETAILS.LIST>",
            "   </STOCKITEM></TALLYMESSAGE>",
        ]
    vt = {"sales": "Sales", "purchase": "Purchase", "receipt": "Receipt"}
    for v in sorted(picked, key=lambda v: v["date"]):
        p = parties[v["party_id"]]
        party_debit = v["voucher_type"] == "sales"
        x += [
            f'   <TALLYMESSAGE><VOUCHER VCHTYPE="{vt[v["voucher_type"]]}" ACTION="Create">',
            f"    <GUID>{v['tally_guid']}</GUID><ALTERID>{v['alter_id']}</ALTERID>",
            f"    <DATE>{v['date']:%Y%m%d}</DATE><VOUCHERTYPENAME>{vt[v['voucher_type']]}</VOUCHERTYPENAME>",
            f"    <VOUCHERNUMBER>{escape(v['number'])}</VOUCHERNUMBER><PARTYLEDGERNAME>{escape(p['name'])}</PARTYLEDGERNAME>",
            f"    <NARRATION>{escape(v['narration'] or '')}</NARRATION>",
            "    <LEDGERENTRIES.LIST>",
            f"     <LEDGERNAME>{escape(p['name'])}</LEDGERNAME><ISDEEMEDPOSITIVE>{'Yes' if party_debit else 'No'}"
            f"</ISDEEMEDPOSITIVE><AMOUNT>{amt(v['amount'], party_debit)}</AMOUNT>",
        ]
        if v["voucher_type"] == "receipt":
            for a in allocs[v["id"]]:
                x.append(
                    f"     <BILLALLOCATIONS.LIST><NAME>{escape(bills[a['bill_id']]['bill_ref'])}</NAME>"
                    f"<BILLTYPE>Agst Ref</BILLTYPE><AMOUNT>{a['amount']:.2f}</AMOUNT></BILLALLOCATIONS.LIST>"
                )
        elif v["voucher_type"] == "sales":
            x.append(
                f"     <BILLALLOCATIONS.LIST><NAME>{escape(v['number'])}</NAME><BILLTYPE>New Ref</BILLTYPE>"
                f"<BILLCREDITPERIOD>{p['credit_days']} Days</BILLCREDITPERIOD>"
                f"<AMOUNT>{-v['amount']:.2f}</AMOUNT></BILLALLOCATIONS.LIST>"
            )
        x.append("    </LEDGERENTRIES.LIST>")
        for ln in lines_by_v[v["id"]]:
            i = items[ln["item_id"]]
            x += [
                "    <ALLINVENTORYENTRIES.LIST>",
                f"     <STOCKITEMNAME>{escape(i['name'])}</STOCKITEMNAME>",
                f"     <RATE>{ln['rate']:.2f}/{i['unit']}</RATE><ACTUALQTY> {ln['qty']:g} {i['unit']}</ACTUALQTY>"
                f"<BILLEDQTY> {ln['qty']:g} {i['unit']}</BILLEDQTY>",
                f"     <AMOUNT>{amt(ln['amount'], not party_debit)}</AMOUNT>",
                "    </ALLINVENTORYENTRIES.LIST>",
            ]
        x.append("   </VOUCHER></TALLYMESSAGE>")
    x += ["  </DATA>", " </BODY>", "</ENVELOPE>", ""]
    (out / "tally_sample_shree_balaji.xml").write_text("\n".join(x), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--today", type=date.fromisoformat, default=DEFAULT_TODAY)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "mock_business")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    store, scenarios, summary = build(args.today)
    columns = write_csv(store, args.out)
    write_load_sql(columns, args.out)
    write_tally_xml(store, args.out)
    (args.out / "scenarios.json").write_text(
        json.dumps(
            {
                "today": str(args.today),
                "note": "Planted situations and the result each agent should reach. "
                "check_sql runs against the loaded kb schema.",
                "scenarios": scenarios,
            },
            indent=2,
            default=str,
            ensure_ascii=False,
        )
    )
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str, ensure_ascii=False))
    for s in summary:
        print(
            f"{s['business']:<28} sales {s['sales_12m_before_tax'] / 1e7:6.1f} Cr  DSO {s['dso_days']:5.1f}  "
            f"grades {s['grades']}  reorder {s['items_reorder']}  "
            f"bank {s['bank_balance'] / 1e5:.0f} L, closing {[round(w['closing'] / 1e5) for w in s['cash_weeks']]} L"
        )
    total = sum(len(v) for k, v in store.rows.items() if not k.startswith("_"))
    print(f"{len(scenarios)} scenarios, {total:,} rows -> {args.out}")


if __name__ == "__main__":
    main()
