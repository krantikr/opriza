"""The mock Tally: twelve months of books for a sample business.

Backed by the generator in `scripts/mock_business` (deterministic: the same
`today` always gives the same books). It plays two roles:

* As a `TallySource`, it returns the sample business's ledgers, items,
  vouchers, bill-wise details and stock exactly the way the real XML
  connector will, so the sync and everything after it run unchanged.
* `history()` returns the month of work that sits on top of the books
  (enquiries, quotes, promises, supplier rates...), which only a mock has:
  a real desk starts with an empty Inbox and builds its own history.

Replacing it: set the desk's `kb_business.source` to "tally_xml" and its
`source_url` to the connector address. Nothing else changes.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from app.kb.sources.base import (
    TallyBatch,
    TBillRef,
    TGodown,
    TItem,
    TLedger,
    TLine,
    TStock,
    TVoucher,
)

ROOT = Path(__file__).resolve().parents[4]
GENERATOR = ROOT / "scripts" / "mock_business"

#: The data's "today": 19 Oct 2026, 10:30 am in the business's time zone.
MOCK_TODAY = date(2026, 10, 19)


def _generator():
    if str(GENERATOR) not in sys.path:
        sys.path.insert(0, str(GENERATOR))
    import catalog  # type: ignore[import-not-found]
    import generate  # type: ignore[import-not-found]

    return catalog, generate


@lru_cache(maxsize=2)
def _build(today: date):
    """Run the generator once per process (about ten seconds)."""
    _, generate = _generator()
    store, scenarios, summary = generate.build(today)
    return store.rows, scenarios, summary


def mock_businesses() -> list[dict]:
    """The sample businesses a desk can be loaded with."""
    catalog, _ = _generator()
    return [
        {
            "key": c.slug,
            "name": c.name,
            "trade": c.trade,
            "city": c.city,
            "language": c.language,
            "tally_version": c.tally_version,
            "generator_id": c.id,
        }
        for c in catalog.COMPANIES
    ]


class MockTallySource:
    name = "mock"

    def __init__(self, key: str, today: date = MOCK_TODAY) -> None:
        self.key = key
        self.today = today
        biz = next((b for b in mock_businesses() if b["key"] == key), None)
        if biz is None:
            raise ValueError(f"No sample business called {key!r}")
        self.business = biz
        self.gen_org = biz["generator_id"]

    def describe(self) -> str:
        return f"Mock Tally ({self.business['name']}, books to {self.today:%d %b %Y})"

    # ------------------------------------------------------------- the rows

    def rows(self, table: str) -> list[dict]:
        rows, _, _ = _build(self.today)
        return [r for r in rows.get(table, []) if r.get("organisation_id") == self.gen_org]

    def scenarios(self) -> list[dict]:
        _, scenarios, _ = _build(self.today)
        return [s for s in scenarios if s["organisation_id"] == self.gen_org]

    def summary(self) -> dict:
        _, _, summary = _build(self.today)
        return next(s for s in summary if s["organisation_id"] == self.gen_org)

    def team(self) -> list[dict]:
        return [
            {"name": u["name"], "role": u["role"], "email": u["email"], "phone": u["phone"]}
            for u in self.rows("users")
        ]

    # -------------------------------------------------------------- source

    def pull(self, since_alter_id: int) -> TallyBatch:
        catalog, _ = _generator()
        company = next(c for c in catalog.COMPANIES if c.slug == self.key)
        aliases = {it.name: list(it.aliases) for it in company.items}
        users = {u["id"]: u["name"] for u in self.rows("users")}
        parties = {p["id"]: p for p in self.rows("parties")}
        items = {i["id"]: i for i in self.rows("items")}
        godowns = {g["id"]: g for g in self.rows("godowns")}

        batch = TallyBatch()
        if since_alter_id == 0:
            batch.godowns = [TGodown(guid=g["tally_guid"], name=g["name"]) for g in godowns.values()]
            batch.items = [
                TItem(
                    guid=i["tally_guid"],
                    name=i["name"],
                    group=i["stock_group"],
                    unit=i["unit"],
                    gst_rate=i["gst_rate"],
                    standard_cost=i["standard_cost"],
                    standard_rate=i["standard_rate"],
                    hsn=i["hsn"],
                    reorder_level=i["reorder_level"],
                    aliases=aliases.get(i["name"], []),
                )
                for i in items.values()
            ]
            batch.ledgers = [
                TLedger(
                    guid=p["tally_guid"],
                    name=p["name"],
                    kind=p["kind"],
                    group=p["tally_group"],
                    contact_name=p["contact_name"],
                    phone=p["phone"],
                    email=p["email"],
                    gstin=p["gstin"],
                    city=p["city"],
                    area=p["area"],
                    credit_days=p["credit_days"],
                    credit_limit=p["credit_limit"],
                    brand=p["brand"],
                    since=p["since"],
                    salesperson=users.get(p["salesperson_id"]),
                )
                for p in parties.values()
            ]
            # Month-end stock and today's, by godown.
            batch.stock = [
                TStock(
                    item_guid=items[s["item_id"]]["tally_guid"],
                    godown_guid=godowns[s["godown_id"]]["tally_guid"],
                    as_of=s["as_of"],
                    qty=s["qty"],
                    value=s["value"],
                )
                for s in self.rows("stock_balances")
            ]
            batch.bank_balance = self.summary()["bank_balance"]

        lines = defaultdict(list)
        for ln in self.rows("voucher_lines"):
            lines[ln["voucher_id"]].append(ln)
        bills = {b["id"]: b for b in self.rows("bills")}
        bill_of_voucher = {b["voucher_id"]: b for b in bills.values() if b["voucher_id"]}
        allocs = defaultdict(list)
        for a in self.rows("bill_allocations"):
            allocs[a["voucher_id"]].append(a)

        for v in self.rows("vouchers"):
            if v["alter_id"] <= since_alter_id:
                continue
            tv = TVoucher(
                guid=v["tally_guid"],
                alter_id=v["alter_id"],
                vtype=v["voucher_type"],
                number=v["number"],
                date=v["date"],
                party_guid=parties[v["party_id"]]["tally_guid"] if v["party_id"] else None,
                amount=v["amount"],
                tax_amount=v["tax_amount"],
                narration=v["narration"],
                lines=[
                    TLine(
                        item_guid=items[ln["item_id"]]["tally_guid"],
                        qty=ln["qty"],
                        rate=ln["rate"],
                        amount=ln["amount"],
                        godown_guid=godowns[ln["godown_id"]]["tally_guid"] if ln["godown_id"] else None,
                    )
                    for ln in sorted(lines[v["id"]], key=lambda x: x["line_no"])
                ],
            )
            if v["voucher_type"] in ("sales", "purchase") and v["id"] in bill_of_voucher:
                b = bill_of_voucher[v["id"]]
                tv.bills.append(
                    TBillRef(ref=b["bill_ref"], kind="new", amount=b["amount"], due_date=b["due_date"])
                )
            for a in allocs.get(v["id"], []):
                tv.bills.append(
                    TBillRef(ref=bills[a["bill_id"]]["bill_ref"], kind="agst", amount=a["amount"])
                )
            batch.vouchers.append(tv)
            batch.max_alter_id = max(batch.max_alter_id, v["alter_id"])
        batch.max_alter_id = max(batch.max_alter_id, since_alter_id)
        return batch

    # ------------------------------------------------- work-state history

    def history(self) -> dict[str, list[dict]]:
        """The month of work before today, in generator ids.

        Deliberately leaves out what the agents produce themselves - tasks,
        approvals, chat, today's agent runs - so loading a desk and running
        its agents once rebuilds today's Inbox from the data, which is the
        whole test of whether the agents work.
        """
        keep = (
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
            "agent_rules",
            "item_aliases",
            "memories",
            "documents",
            "document_chunks",
        )
        return {t: self.rows(t) for t in keep} | {
            "_parties": self.rows("parties"),
            "_items": self.rows("items"),
            "_users": self.rows("users"),
            "_vouchers": self.rows("vouchers"),
        }


def days_ago(n: int, today: date = MOCK_TODAY) -> date:
    return today - timedelta(days=n)
