"""A year of trading, day by day, for one mock business.

Produces the Tally-mirror layer: parties, items, godowns, vouchers and their
lines, bill-wise outstanding with allocations, and stock balances. Everything
follows from a few behaviours, so the numbers hang together the way real books
do:

* customers buy at their own pace, from their own short list of items;
* each pays the way their grade does (A on time, D late and in parts);
* we reorder an item when it runs low, from the supplier we usually trust;
* we pay suppliers around the due date.

The planted situations the agents must find (a customer slipping away, an
item about to run out, a short cash week ...) are set up here too, in
`Plan`, so `scenarios.json` can state what each agent should conclude.
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

import math
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from catalog import CONTACTS, HOLIDAYS, Company, Item

GRADES = ("A", "B", "C", "D")
GRADE_MIX = (0.36, 0.34, 0.2, 0.1)


def money(x: float) -> float:
    return round(x + 0.0, 2)


def fy_label(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def working_day(d: date) -> bool:
    return d.weekday() != 6 and d not in HOLIDAYS


def next_working(d: date) -> date:
    while not working_day(d):
        d += timedelta(days=1)
    return d


class Ids:
    """One counter per table across all companies, so ids never collide."""

    def __init__(self) -> None:
        self._n: dict[str, int] = defaultdict(int)

    def __call__(self, table: str) -> int:
        self._n[table] += 1
        return self._n[table]


@dataclass
class Store:
    """Rows per table, as plain dicts in column order."""

    rows: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    ids: Ids = field(default_factory=Ids)

    def add(self, table: str, **row) -> dict:
        if "id" in row and row["id"] is None:
            row["id"] = self.ids(table)
        self.rows[table].append(row)
        return row


@dataclass
class Customer:
    party: dict
    grade: str
    weight: float
    gap_days: float  # average days between orders
    items: list[Item]
    item_weights: list[float]
    credit_days: int
    rep_id: int
    starts: date
    stops: date | None = None
    late_override: tuple[date, float] | None = None  # bills after this date run this many days late
    next_order: date | None = None


@dataclass
class Plan:
    """The planted situations, chosen up front so the simulation can arrange them."""

    slipping: Customer | None = None  # regular buyer who quietly stopped
    grade_drop: Customer | None = None  # paid well, last bills ran late
    stockout_item: Item | None = None  # fast item about to run out
    idle_item: Item | None = None  # nothing sold for months
    idle_buyers: list[int] = field(default_factory=list)
    duplicate_of: dict | None = None  # same customer keyed twice in Tally
    bulk_purchase: dict | None = None  # the payable that makes week 3 short


class Simulation:
    def __init__(self, company: Company, store: Store, today: date, seed: int) -> None:
        self.c = company
        self.s = store
        self.today = today
        self.start = today - timedelta(days=365)
        self.r = random.Random(seed)
        self.org = company.id
        self.plan = Plan()
        self.alter = 1000 * company.id
        self.seq: dict[str, int] = defaultdict(int)
        self.stock: dict[int, float] = {}
        self.stock_history: dict[date, dict[int, float]] = {}
        self.item_rows: dict[str, dict] = {}
        self.item_by_id: dict[int, Item] = {}
        self.customers: list[Customer] = []
        self.suppliers: list[tuple[dict, object]] = []
        self.receipts_due: dict[date, list[tuple[dict, float]]] = defaultdict(list)
        self.payments_due: dict[date, list[tuple[dict, float]]] = defaultdict(list)
        self.pending_po: dict[int, date] = {}  # item id -> arrival date
        self.users: dict[str, dict] = {}
        self.godowns: list[dict] = []
        self.daily_sales: dict[date, float] = defaultdict(float)
        self.daily_collections: dict[date, float] = defaultdict(float)

    # ------------------------------------------------------------------ setup

    def guid(self, kind: str, key: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.c.slug}/{kind}/{key}"))

    def next_alter(self) -> int:
        self.alter += 1
        return self.alter

    def setup(self) -> None:
        c, s = self.c, self.s
        s.add(
            "organisations",
            id=c.id,
            slug=c.slug,
            name=c.name,
            trade=c.trade,
            city=c.city,
            tally_version=c.tally_version,
            fy_start=date(2026, 4, 1),
            language=c.language,
            created_at=f"{self.start - timedelta(days=30)} 10:00:00+05:30",
        )
        for name, role in c.team:
            u = s.add(
                "users",
                id=None,
                organisation_id=c.id,
                name=name,
                role=role,
                email=f"{name.split()[0].lower()}@{c.slug.replace('-', '')}.in",
                phone=f"9{self.r.randint(700000000, 999999999)}",
            )
            self.users.setdefault(role, u)
        for _i, name in enumerate(("Main Godown", "Yard 2")):
            self.godowns.append(
                s.add(
                    "godowns", id=None, organisation_id=c.id, tally_guid=self.guid("godown", name), name=name
                )
            )

        for it in c.items:
            row = s.add(
                "items",
                id=None,
                organisation_id=c.id,
                tally_guid=self.guid("item", it.key),
                name=it.name,
                stock_group=it.group,
                unit=it.unit,
                hsn=it.hsn or None,
                gst_rate=it.gst,
                standard_cost=it.cost,
                standard_rate=it.rate,
                reorder_level=None,
            )
            self.item_rows[it.key] = row
            self.item_by_id[row["id"]] = it

        self._suppliers()
        self._customers()
        self._plan()
        self._calibrate()
        # Opening stock: about 40 days of sales for every item that sells.
        for it in c.items:
            iid = self.item_rows[it.key]["id"]
            per_day = self.per_day_qty.get(it.key, 0)
            self.stock[iid] = round(per_day * self.r.uniform(32, 48), 3) if per_day else 0.0
            self.item_rows[it.key]["reorder_level"] = round(per_day * 12, 3) if per_day else None
        if self.plan.idle_item:
            iid = self.item_rows[self.plan.idle_item.key]["id"]
            lo, hi = self.plan.idle_item.qty
            self.stock[iid] = round(hi * 9, 3)

    def _suppliers(self) -> None:
        for _i, sup in enumerate(self.c.suppliers):
            p = self.s.add(
                "parties",
                id=None,
                organisation_id=self.org,
                tally_guid=self.guid("ledger", sup.name),
                name=sup.name,
                kind="supplier",
                tally_group="Sundry Creditors",
                contact_name=self.r.choice(CONTACTS),
                phone=f"9{self.r.randint(700000000, 999999999)}",
                email=None,
                gstin=self._gstin(),
                city=self.c.city,
                area=None,
                credit_days=sup.credit_days,
                credit_limit=None,
                salesperson_id=None,
                brand=sup.brand,
                since=date(self.r.randint(2012, 2022), self.r.randint(1, 12), 1),
            )
            self.suppliers.append((p, sup))

    def _gstin(self) -> str:
        state = {"Pune": "27", "Ahmedabad": "24", "Indore": "23"}.get(self.c.city, "27")
        letters = "".join(self.r.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))
        return f"{state}{letters}{self.r.randint(1000, 9999)}{self.r.choice('ABCDEFGHJK')}1Z{self.r.randint(1, 9)}"

    def _customers(self) -> None:
        c, r = self.c, self.r
        stems = list(c.customer_stems)
        r.shuffle(stems)
        used: set[str] = set()
        sellable = [it for it in c.items if it.share > 0]
        reps = [u for u in self.s.rows["users"] if u["organisation_id"] == c.id and u["role"] == "sales"]
        for i in range(c.customers):
            for k in range(20):
                name = f"{stems[(i + k * 11) % len(stems)]} {r.choice(c.customer_kinds)}"
                if name not in used:
                    break
            used.add(name)
            grade = r.choices(GRADES, GRADE_MIX)[0]
            weight = math.exp(r.gauss(0, 1.05))
            n_items = r.randint(2, min(6, len(sellable)))
            items = r.choices(sellable, weights=[it.share for it in sellable], k=n_items)
            items = list(dict.fromkeys(items))
            starts = self.start if r.random() > 0.08 else self.start + timedelta(days=r.randint(30, 300))
            stops = None
            if r.random() < 0.04:
                stops = self.start + timedelta(days=r.randint(90, 330))
            party = self.s.add(
                "parties",
                id=None,
                organisation_id=c.id,
                tally_guid=self.guid("ledger", name),
                name=name,
                kind="customer",
                tally_group="Sundry Debtors",
                contact_name=r.choice(CONTACTS),
                phone=f"9{r.randint(700000000, 999999999)}",
                email=f"accounts@{name.lower().replace(' ', '')[:18]}.in" if r.random() < 0.6 else None,
                gstin=self._gstin(),
                city=c.city,
                area=r.choice(c.areas),
                credit_days=r.choice(c.credit_days),
                credit_limit=None,
                salesperson_id=reps[i % len(reps)]["id"],
                brand=None,
                since=date(r.randint(2008, 2025), r.randint(1, 12), 1),
            )
            self.customers.append(
                Customer(
                    party=party,
                    grade=grade,
                    weight=weight,
                    gap_days=0,
                    items=items,
                    item_weights=[it.share * r.uniform(0.6, 1.6) for it in items],
                    credit_days=party["credit_days"],
                    rep_id=party["salesperson_id"],
                    starts=starts,
                    stops=stops,
                )
            )

    def _plan(self) -> None:
        """Pick who and what the planted situations happen to."""
        p = self.plan
        by_weight = sorted(self.customers, key=lambda x: -x.weight)
        # A big, reliable customer who stopped ordering 40 days ago.
        p.slipping = by_weight[3]
        p.slipping.grade = "A"
        p.slipping.stops = self.today - timedelta(days=40)
        p.slipping.starts = self.start
        # A mid-size B customer whose last bills ran late: the Score agent should move them to C.
        # A frequent buyer, so enough recent bills show the change.
        p.grade_drop = by_weight[6]
        p.grade_drop.grade = "B"
        p.grade_drop.credit_days = p.grade_drop.party["credit_days"] = 30
        p.grade_drop.starts = self.start
        p.grade_drop.stops = None
        p.grade_drop.late_override = (self.today - timedelta(days=80), 38.0)
        # The fastest item runs short: the last reorder is held back.
        fast = max((it for it in self.c.items if it.share > 0), key=lambda it: it.share)
        p.stockout_item = fast
        # The item with share 0 sold to a few customers early in the year and then stopped.
        p.idle_item = next((it for it in self.c.items if it.share == 0), None)
        # One customer keyed twice in Tally with a slightly different name.
        dup = by_weight[15]
        p.duplicate_of = dup.party
        for cu in self.customers:
            cu.party["credit_limit"] = None

    def _calibrate(self) -> None:
        """Work out order frequency and stock needs so the year hits the sales target.

        Customers order in proportion to their size, so the calibration samples
        invoices the same way: pick a customer weighted by size, build an invoice
        exactly as the simulation will, and average. From that come the invoices
        a day the business needs, each customer's gap between orders, and the
        quantity of each item sold per day.
        """
        r = random.Random(7)
        weights = [cu.weight for cu in self.customers]
        n = 6000
        total, qty = 0.0, defaultdict(float)
        for _ in range(n):
            cu = r.choices(self.customers, weights=weights)[0]
            for it, q in self._lines(cu, r):
                total += q * it.rate
                qty[it.key] += q
        self.mean_invoice = total / n
        days = sum(1 for k in range(365) if working_day(self.start + timedelta(days=k)))
        self.invoices_per_day = self.c.annual_sales / days / self.mean_invoice
        k = self.invoices_per_day / sum(weights)
        for cu in self.customers:
            cu.gap_days = max(1.0, 1 / (k * cu.weight))
        self.per_day_qty = {key: q / n * self.invoices_per_day for key, q in qty.items()}

    def _invoice_value(self, cu: Customer, r: random.Random) -> float:
        lines = self._lines(cu, r)
        return sum(q * it.rate for it, q in lines)

    def _lines(self, cu: Customer, r: random.Random) -> list[tuple[Item, float]]:
        n = min(len(cu.items), r.choices((1, 2, 3), (0.5, 0.33, 0.17))[0])
        chosen = list(dict.fromkeys(r.choices(cu.items, weights=cu.item_weights, k=n)))
        out = []
        size = min(2.5, max(0.4, cu.weight**0.35))
        for it in chosen:
            lo, hi = it.qty
            q = math.exp(r.uniform(math.log(lo), math.log(hi))) * size
            out.append((it, self._round_qty(it, q)))
        return out

    @staticmethod
    def _round_qty(it: Item, q: float) -> float:
        if it.unit == "MT":
            return round(max(0.5, q), 3 if q < 5 else 2)
        if it.unit in ("bag", "pc"):
            step = 50 if q > 500 else 10
            return float(max(step, round(q / step) * step))
        return float(max(1, round(q)))

    # --------------------------------------------------------------- prices

    def price_index(self, it: Item, d: date) -> float:
        """Steel moves with the market; other trades drift slowly."""
        t = (d - self.start).days / 365
        if self.c.trade == "steel":
            phase = sum(map(ord, it.group)) % 7 / 7  # each product group moves a little out of step
            return 1 + 0.045 * math.sin(2 * math.pi * (t * 1.6 + phase)) - 0.02 * t
        if self.c.trade == "building":
            return 1 + 0.02 * math.sin(2 * math.pi * t) + 0.015 * t
        return 1 + 0.03 * t  # pharma: price increases once a year, roughly

    # ----------------------------------------------------------------- vouchers

    def number(self, prefix: str, d: date) -> str:
        key = f"{prefix}/{fy_label(d)}"
        self.seq[key] += 1
        short = "".join(w[0] for w in self.c.name.split()).upper()
        return f"{short}/{prefix}/{fy_label(d)}/{self.seq[key]:05d}"

    def voucher(
        self,
        vtype: str,
        d: date,
        party: dict | None,
        amount: float,
        tax: float,
        narration: str | None,
        prefix: str,
    ) -> dict:
        number = self.number(prefix, d)
        return self.s.add(
            "vouchers",
            id=None,
            organisation_id=self.org,
            tally_guid=self.guid("voucher", number),
            alter_id=self.next_alter(),
            voucher_type=vtype,
            number=number,
            date=d,
            party_id=party["id"] if party else None,
            amount=money(amount),
            tax_amount=money(tax),
            narration=narration,
        )

    def sale(self, cu: Customer, d: date, lines: list[tuple[Item, float]] | None = None) -> dict | None:
        r = self.r
        lines = lines or self._lines(cu, r)
        rows, subtotal, tax = [], 0.0, 0.0
        cust_factor = 0.985 if cu.weight > 2.5 else 1.0 if cu.weight > 0.8 else 1.012
        for it, q in lines:
            iid = self.item_rows[it.key]["id"]
            if self.stock.get(iid, 0) < q:  # cannot sell what is not there
                q = self._round_qty(it, self.stock.get(iid, 0) * 0.8)
                if q <= 0 or self.stock.get(iid, 0) < q:
                    continue
            rate = round(it.rate * self.price_index(it, d) * cust_factor * r.uniform(0.993, 1.007), 2)
            amt = money(q * rate)
            rows.append((it, iid, q, rate, amt))
            subtotal += amt
            tax += amt * it.gst / 100
            self.stock[iid] = round(self.stock[iid] - q, 3)
        if not rows:
            return None
        v = self.voucher("sales", d, cu.party, subtotal + tax, tax, None, "S")
        for n, (_it, iid, q, rate, amt) in enumerate(rows, 1):
            self.s.add(
                "voucher_lines",
                id=None,
                organisation_id=self.org,
                voucher_id=v["id"],
                line_no=n,
                item_id=iid,
                godown_id=self.godowns[0 if r.random() < 0.8 else 1]["id"],
                qty=q,
                rate=rate,
                amount=amt,
            )
        bill = self.s.add(
            "bills",
            id=None,
            organisation_id=self.org,
            party_id=cu.party["id"],
            direction="receivable",
            bill_ref=v["number"],
            bill_date=d,
            due_date=d + timedelta(days=cu.credit_days),
            amount=v["amount"],
            pending_amount=v["amount"],
            voucher_id=v["id"],
        )
        self.daily_sales[d] += subtotal
        self._schedule_receipt(cu, bill, d)
        return v

    def _lateness(self, cu: Customer, bill_date: date) -> float:
        r = self.r
        if cu.late_override and bill_date >= cu.late_override[0]:
            return cu.late_override[1] + r.uniform(-3, 5)
        g = cu.grade
        if g == "A":
            return max(-4, min(6, r.gauss(1, 2)))
        if g == "B":
            return max(2, min(18, r.gauss(9, 4)))
        if g == "C":
            return max(10, min(45, r.gauss(24, 8)))
        return max(25, min(95, r.gauss(48, 16)))

    def _schedule_receipt(self, cu: Customer, bill: dict, d: date) -> None:
        late = self._lateness(cu, d)
        pay = next_working(bill["due_date"] + timedelta(days=round(late)))
        if cu.grade == "D" and self.r.random() < 0.45:
            # Pays part now, the rest a few weeks later.
            part = money(bill["amount"] * self.r.uniform(0.3, 0.6))
            self.receipts_due[pay].append((bill, part))
            self.receipts_due[next_working(pay + timedelta(days=self.r.randint(15, 40)))].append(
                (bill, money(bill["amount"] - part))
            )
        else:
            self.receipts_due[pay].append((bill, bill["amount"]))

    def receive(self, d: date) -> None:
        by_party: dict[int, list[tuple[dict, float]]] = defaultdict(list)
        for bill, amt in self.receipts_due.pop(d, []):
            by_party[bill["party_id"]].append((bill, amt))
        for pid, allocs in by_party.items():
            allocs = [(b, min(a, b["pending_amount"])) for b, a in allocs if b["pending_amount"] > 0.004]
            allocs = [(b, a) for b, a in allocs if a > 0]
            if not allocs:
                continue
            total = sum(a for _, a in allocs)
            party = next(cu.party for cu in self.customers if cu.party["id"] == pid)
            v = self.voucher(
                "receipt", d, party, total, 0, "NEFT" if self.r.random() < 0.7 else "Cheque", "R"
            )
            for b, a in allocs:
                self.s.add(
                    "bill_allocations",
                    id=None,
                    organisation_id=self.org,
                    bill_id=b["id"],
                    voucher_id=v["id"],
                    amount=money(a),
                    date=d,
                )
                b["pending_amount"] = money(b["pending_amount"] - a)
            self.daily_collections[d] += total

    def credit_note(self, d: date) -> None:
        """Now and then a rate difference is passed back on a recent bill."""
        recent = [
            b
            for b in self.s.rows["bills"][-60:]
            if b["organisation_id"] == self.org
            and b["direction"] == "receivable"
            and b["pending_amount"] > 1000
        ]
        if not recent:
            return
        b = self.r.choice(recent)
        amt = money(b["amount"] * self.r.uniform(0.008, 0.025))
        party = next(cu.party for cu in self.customers if cu.party["id"] == b["party_id"])
        v = self.voucher(
            "credit_note",
            d,
            party,
            amt,
            money(amt * 0.18 / 1.18),
            f"Rate difference on {b['bill_ref']}",
            "CN",
        )
        self.s.add(
            "bill_allocations",
            id=None,
            organisation_id=self.org,
            bill_id=b["id"],
            voucher_id=v["id"],
            amount=amt,
            date=d,
        )
        b["pending_amount"] = money(b["pending_amount"] - amt)

    # ---------------------------------------------------------------- buying

    def choose_supplier(self, it: Item):
        r = self.r
        scored = []
        for p, sup in self.suppliers:
            score = -sup.delta * 100 + (sup.on_time - 85) / 4 + r.uniform(-1.5, 1.5)
            scored.append((score, p, sup))
        scored.sort(key=lambda x: -x[0])
        return scored[0][1], scored[0][2]

    def maybe_reorder(self, d: date) -> None:
        for it in self.c.items:
            iid = self.item_rows[it.key]["id"]
            per_day = self.per_day_qty.get(it.key, 0)
            if not per_day or iid in self.pending_po:
                continue
            if self.plan.stockout_item is it and d >= self.today - timedelta(days=75):
                continue  # the planted stock-out: normal reordering stops, three planned top-ups (_stockout_step)
            if self.stock.get(iid, 0) < per_day * 12:
                p, sup = self.choose_supplier(it)
                self.pending_po[iid] = d + timedelta(days=sup.days)
                self._po_arrivals.append((d + timedelta(days=sup.days), it, p, sup, d))

    def receive_purchases(self, d: date) -> None:
        keep = []
        for arrive, it, p, sup, ordered in self._po_arrivals:
            if arrive > d:
                keep.append((arrive, it, p, sup, ordered))
                continue
            self.purchase(d, it, p, sup, self.per_day_qty[it.key] * self.r.uniform(28, 36), ordered)
            self.pending_po.pop(self.item_rows[it.key]["id"], None)
        self._po_arrivals = keep

    def purchase(
        self, d: date, it: Item, p: dict, sup, qty: float, ordered: date, narration: str | None = None
    ) -> dict:
        iid = self.item_rows[it.key]["id"]
        qty = self._round_qty(it, qty)
        rate = round(it.cost * self.price_index(it, d) * (1 + sup.delta) * self.r.uniform(0.995, 1.005), 2)
        amt = money(qty * rate)
        tax = money(amt * it.gst / 100)
        v = self.voucher("purchase", d, p, amt + tax, tax, narration or f"PO raised {ordered}", "P")
        self.s.add(
            "voucher_lines",
            id=None,
            organisation_id=self.org,
            voucher_id=v["id"],
            line_no=1,
            item_id=iid,
            godown_id=self.godowns[0]["id"],
            qty=qty,
            rate=rate,
            amount=amt,
        )
        bill = self.s.add(
            "bills",
            id=None,
            organisation_id=self.org,
            party_id=p["id"],
            direction="payable",
            bill_ref=f"{sup.brand.upper()[:4]}/{v['number'].split('/', 2)[-1]}",
            bill_date=d,
            due_date=d + timedelta(days=sup.credit_days),
            amount=v["amount"],
            pending_amount=v["amount"],
            voucher_id=v["id"],
        )
        self.stock[iid] = round(self.stock.get(iid, 0) + qty, 3)
        delay = 0 if self.r.random() < 0.75 else self.r.randint(2, 12)
        self.payments_due[next_working(bill["due_date"] + timedelta(days=delay))].append(
            (bill, bill["amount"])
        )
        self.s.add(
            "_purchase_meta",
            voucher_id=v["id"],
            ordered=ordered,
            item_id=iid,
            supplier_id=p["id"],
            qty=qty,
            rate=rate,
        )
        return v

    def pay_suppliers(self, d: date) -> None:
        by_party: dict[int, list[tuple[dict, float]]] = defaultdict(list)
        for bill, amt in self.payments_due.pop(d, []):
            by_party[bill["party_id"]].append((bill, amt))
        for pid, allocs in by_party.items():
            total = sum(a for _, a in allocs)
            party = next(p for p, _ in self.suppliers if p["id"] == pid)
            v = self.voucher("payment", d, party, total, 0, "RTGS", "PY")
            for b, a in allocs:
                self.s.add(
                    "bill_allocations",
                    id=None,
                    organisation_id=self.org,
                    bill_id=b["id"],
                    voucher_id=v["id"],
                    amount=money(a),
                    date=d,
                )
                b["pending_amount"] = money(b["pending_amount"] - a)

    # ------------------------------------------------------------------- run

    def run(self) -> None:
        self.setup()
        self._po_arrivals: list = []
        r = self.r
        for cu in self.customers:
            cu.next_order = cu.starts + timedelta(days=r.uniform(0, cu.gap_days))
        idle = self.plan.idle_item
        idle_sales_left = 7 if idle else 0
        d = self.start
        while d < self.today:
            if working_day(d):
                season = self.c.seasonality.get(d.month, 1.0)
                for cu in self.customers:
                    if cu.next_order and cu.next_order <= d:
                        active = cu.starts <= d and (cu.stops is None or d < cu.stops)
                        if active and r.random() < min(1.0, season):
                            self.sale(cu, d)
                        cu.next_order = d + timedelta(
                            days=max(
                                1,
                                r.expovariate(1 / cu.gap_days)
                                if cu.gap_days < 20
                                else r.gauss(cu.gap_days, cu.gap_days * 0.3),
                            )
                        )
                # The idle item: a handful of early sales, then nothing for months.
                if idle and idle_sales_left and d < self.start + timedelta(days=100) and r.random() < 0.09:
                    buyer = r.choice(self.customers[:60])
                    v = self.sale(buyer, d, [(idle, self._round_qty(idle, sum(idle.qty) / 2))])
                    if v:
                        idle_sales_left -= 1
                        self.plan.idle_buyers.append(buyer.party["id"])
                if r.random() < 0.012 * self.invoices_per_day:
                    self.credit_note(d)
                self.receive(d)
                self.pay_suppliers(d)
                self.receive_purchases(d)
                self.maybe_reorder(d)
                if d == self.today - timedelta(days=16):
                    self._bulk_buy(d)
                for days_out, cover in ((75, 35), (40, 33), (6, 11)):
                    if days_out not in self._stockout_steps_done and d >= self.today - timedelta(
                        days=days_out
                    ):
                        self._stockout_steps_done = self._stockout_steps_done | {days_out}
                        self._stockout_step(d, cover)
            else:
                # Money that would have come on a holiday comes the next working day.
                nd = next_working(d)
                self.receipts_due[nd].extend(self.receipts_due.pop(d, []))
                self.payments_due[nd].extend(self.payments_due.pop(d, []))
            if (d + timedelta(days=1)).day == 1 or d == self.today - timedelta(days=1):
                self.stock_history[d] = dict(self.stock)
            d += timedelta(days=1)
        self._duplicate_party()
        self._stock_balances()

    _stockout_steps_done: set[int] = frozenset()

    def _stockout_step(self, d: date, cover_days: float) -> None:
        """Bring the fast item up to `cover_days` of expected sales, buying only if short.

        Called 75 and 40 days out (cover to last until the next step, so it never
        runs out early and its sales rate stays honest) and 6 days out (11 days
        of cover, so it reaches today with about five left and no reorder placed).
        """
        it = self.plan.stockout_item
        iid = self.item_rows[it.key]["id"]
        self._po_arrivals = [a for a in self._po_arrivals if a[1] is not it]
        self.pending_po.pop(iid, None)
        per_day = self._recent_per_day(iid, d) or self.per_day_qty[it.key]
        need = per_day * cover_days - self.stock.get(iid, 0)
        if need > per_day:
            p, sup = self.choose_supplier(it)
            self.purchase(d, it, p, sup, need, d - timedelta(days=sup.days))

    def _recent_per_day(self, iid: int, d: date) -> float:
        """Average daily quantity sold over the 28 days before d."""
        since = d - timedelta(days=28)
        vids = {
            v["id"]
            for v in self.s.rows["vouchers"]
            if v["organisation_id"] == self.org and v["voucher_type"] == "sales" and since <= v["date"] < d
        }
        qty = sum(
            ln["qty"]
            for ln in self.s.rows["voucher_lines"]
            if ln["organisation_id"] == self.org and ln["item_id"] == iid and ln["voucher_id"] in vids
        )
        return qty / 28

    def _bulk_buy(self, d: date) -> None:
        """A big stock-up at a good rate, payable in week 3: the cash gap the Cash agent must catch."""
        weekly_sales = self.c.annual_sales / 52
        it = max(
            (x for x in self.c.items if x.share > 0 and x is not self.plan.stockout_item),
            key=lambda x: x.share,
        )
        p, sup = next(((p, s) for p, s in self.suppliers if 21 <= s.credit_days <= 30), self.suppliers[0])
        qty = weekly_sales * 2.0 / it.cost  # about two weeks of buying in one go
        due_target = self.today + timedelta(days=16)  # lands in week 3 of the forecast
        v = self.purchase(d, it, p, sup, qty, d - timedelta(days=sup.days), "Bulk buy at festive discount")
        bill = self.s.rows["bills"][-1]
        old_due = bill["due_date"]
        bill["due_date"] = due_target
        # Move its scheduled payment to the new due date (future, so it stays open).
        for k, lst in list(self.payments_due.items()):
            self.payments_due[k] = [(b, a) for b, a in lst if b is not bill]
        self.payments_due[due_target].append((bill, bill["amount"]))
        self.plan.bulk_purchase = {"voucher": v, "bill": bill, "item": it, "supplier": p, "was_due": old_due}

    def _duplicate_party(self) -> None:
        """The same customer, keyed a second time in Tally with a typo, with one bill on it."""
        orig = self.plan.duplicate_of
        name = orig["name"].rstrip("s") if orig["name"].endswith("s") else orig["name"] + "s"
        dup = self.s.add(
            "parties",
            id=None,
            organisation_id=self.org,
            tally_guid=self.guid("ledger", name + "-dup"),
            name=name,
            kind="customer",
            tally_group="Sundry Debtors",
            contact_name=orig["contact_name"],
            phone=orig["phone"],
            email=None,
            gstin=orig["gstin"],
            city=orig["city"],
            area=orig["area"],
            credit_days=orig["credit_days"],
            credit_limit=None,
            salesperson_id=orig["salesperson_id"],
            brand=None,
            since=self.today - timedelta(days=50),
        )
        cu = Customer(
            party=dup,
            grade="B",
            weight=0.5,
            gap_days=60,
            items=[self.c.items[0]],
            item_weights=[1],
            credit_days=dup["credit_days"],
            rep_id=dup["salesperson_id"],
            starts=self.today,
        )
        self.customers.append(cu)
        d = next_working(self.today - timedelta(days=48))
        it = next(x for x in self.c.items if x.share > 0)
        q = self._round_qty(it, sum(it.qty) / 2)
        self.stock[self.item_rows[it.key]["id"]] += q  # keep stock whole
        v = self.sale(cu, d, [(it, q)])
        # This bill is still open: nobody chases a ledger they don't know is there.
        for k, lst in list(self.receipts_due.items()):
            self.receipts_due[k] = [(b, a) for b, a in lst if b["voucher_id"] != v["id"]]
        self.plan.duplicate_of = {"original": orig, "duplicate": dup}

    def _stock_balances(self) -> None:
        for as_of, levels in sorted(self.stock_history.items()):
            for iid, qty in levels.items():
                it = self.item_by_id[iid]
                main = round(qty * 0.8, 3) if it.unit == "MT" else round(qty * 0.8)
                for g, q in ((self.godowns[0], main), (self.godowns[1], round(qty - main, 3))):
                    self.s.add(
                        "stock_balances",
                        organisation_id=self.org,
                        item_id=iid,
                        godown_id=g["id"],
                        as_of=as_of,
                        qty=max(0.0, q),
                        value=money(max(0.0, q) * it.cost * self.price_index(it, as_of)),
                    )
