"""Layers C, D and E: what the agents and the team have been doing.

The last 30 days of enquiries, quotes, promises, messages, links, supplier
rates and purchase orders, plus today's open Inbox and approvals, the event
timeline, what the agents have learned, documents, and run logs. Built on top
of the simulated books, so a quote's "last rate" is the customer's real last
rate and a "kept" promise has a real receipt behind it.
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from datetime import date, datetime, timedelta

from catalog import ENQUIRY_TEMPLATES
from simulate import Simulation, Store, money, next_working, working_day

IST = "+05:30"


def ts(d: date, minutes: int) -> str:
    """A timestamp `minutes` after midnight on day d, in IST."""
    h, m = divmod(int(minutes), 60)
    return f"{d} {min(h, 23):02d}:{m:02d}:00{IST}"


def as_dt(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


class Work:
    def __init__(self, sim: Simulation, store: Store, seed: int) -> None:
        self.sim, self.s, self.c = sim, store, sim.c
        self.org, self.today = sim.org, sim.today
        self.r = random.Random(seed)
        self.events: list[dict] = []
        self.scenarios: list[dict] = []
        self.quote_seq = 1180
        self.po_seq = 870
        self.cost_now = {iid: it.cost * sim.price_index(it, self.today) for iid, it in sim.item_by_id.items()}
        self.users = {u["role"]: u for u in reversed(store.rows["users"]) if u["organisation_id"] == self.org}
        self.rules = self._rules()
        self.now = as_dt(ts(self.today, 10 * 60 + 30))  # "now" in the data: mid-morning on the last day
        # Indexes over the books.
        self.vouchers = [v for v in store.rows["vouchers"] if v["organisation_id"] == self.org]
        self.lines_by_v = defaultdict(list)
        for ln in store.rows["voucher_lines"]:
            if ln["organisation_id"] == self.org:
                self.lines_by_v[ln["voucher_id"]].append(ln)
        self.bills = [b for b in store.rows["bills"] if b["organisation_id"] == self.org]
        self.party_by_id = {p["id"]: p for p in store.rows["parties"] if p["organisation_id"] == self.org}
        self.last_rate: dict[tuple[int, int], float] = {}
        for v in sorted(self.vouchers, key=lambda v: v["date"]):
            if v["voucher_type"] == "sales":
                for ln in self.lines_by_v[v["id"]]:
                    self.last_rate[(v["party_id"], ln["item_id"])] = ln["rate"]

    # ----------------------------------------------------------------- helpers

    def event(
        self, at: str, type_: str, entity_type: str, entity_id: int, source: str, actor: str | None, **payload
    ) -> None:
        self.events.append(
            {
                "occurred_at": at,
                "type": type_,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "source": source,
                "actor": actor,
                "payload": payload,
            }
        )

    def add(self, table: str, **row) -> dict:
        return self.s.add(table, id=None, organisation_id=self.org, **row)

    def _rules(self) -> dict:
        po_limit = round(self.c.annual_sales / 400 / 1e5) * 1e5
        rules = {
            ("sales", "margin_floor_pct"): 3.0,
            ("sales", "max_discount_pct"): 1.5,
            ("sales", "auto_send_in_band"): True,
            ("sales", "nudge_after_hours"): 24,
            ("collect", "remind_days_before_due"): 3,
            ("collect", "language"): self.c.language,
            ("collect", "statement_every_days"): 7,
            ("collect", "quiet_hours"): "21:00-09:00",
            ("stock", "reorder_days"): 12,
            ("stock", "rfq_suppliers"): 3,
            ("stock", "po_limit"): po_limit,
            ("cash", "horizon_weeks"): 4,
            ("cash", "alert_weeks_ahead"): 3,
            ("brief", "send_at"): "08:00",
            ("brief", "weekly_report"): False,
            ("score", "regrade_on"): "payment",
            ("score", "ask_before_lowering_limit"): True,
            ("ask", "read_only"): True,
        }
        owner = next(
            u for u in self.s.rows["users"] if u["organisation_id"] == self.org and u["role"] == "owner"
        )
        for (agent, key), value in rules.items():
            self.s.add(
                "agent_rules",
                organisation_id=self.org,
                agent=agent,
                key=key,
                value=value,
                updated_by=owner["id"],
                updated_at=ts(self.today - timedelta(days=40), 600),
            )
        return {k[1]: v for k, v in rules.items()}

    def active_customers(self):
        return [
            cu for cu in self.sim.customers if cu.stops is None or cu.stops > self.today - timedelta(days=30)
        ]

    # ------------------------------------------------------------ enquiries / quotes

    def enquiries_and_quotes(self) -> None:
        r, c = self.r, self.c
        per_day = {"steel": 6, "building": 9, "pharma": 4}[c.trade]
        custs = [cu for cu in self.active_customers() if cu is not self.sim.plan.slipping]
        weights = [cu.weight for cu in custs]
        sites = list(c.areas)
        self.quotes: list[dict] = []
        for k in range(30, -1, -1):
            d = self.today - timedelta(days=k)
            if not working_day(d):
                continue
            n = max(0, round(r.gauss(per_day, per_day * 0.3))) if k else 3
            for _ in range(n):
                cu = r.choices(custs, weights=weights)[0]
                items = list(
                    dict.fromkeys(r.choices(cu.items, weights=cu.item_weights, k=r.choice((1, 1, 2))))
                )
                self._one_enquiry(d, cu, items, sites, k, now=(k == 0))
        self._planted_quotes()

    def _enquiry_text(self, items, sites, d) -> tuple[str, list[dict]]:
        r = self.r
        lang = self.c.language if r.random() < 0.7 else "English"
        parts, parsed = [], []
        for it in items:
            lo, hi = it.qty
            q = self._said_qty(it, r.uniform(lo, hi))
            word = r.choice(it.aliases) if it.aliases and r.random() < 0.6 else it.name
            unit = {
                "MT": "MT",
                "bag": "bags",
                "pc": "pcs",
                "box": "boxes",
                "can": "cans",
                "sheet": "sheets",
                "length": "lengths",
            }.get(it.unit, it.unit)
            qs = f"{q:g}"
            parts.append((qs, unit, word))
            parsed.append({"item": it.name, "qty": q, "unit": it.unit, "said_as": word})
        tpl = r.choice(ENQUIRY_TEMPLATES[lang])
        q, u, w = parts[0]
        text = tpl.format(
            q=q, u=u, i=w, site=r.choice(sites), d=(d + timedelta(days=r.randint(1, 4))).strftime("%d %b")
        )
        if len(parts) > 1:
            q2, u2, w2 = parts[1]
            text += f" Also {q2} {u2} {w2}." if lang == "English" else f" Saath mein {q2} {u2} {w2} bhi."
        return text, parsed

    @staticmethod
    def _said_qty(it, q: float) -> float:
        """Quantities as people say them: 12 MT, 2.5 MT, 150 bags, 40 boxes."""
        if it.unit == "MT":
            return float(round(q)) if q >= 5 else max(0.5, round(q * 2) / 2)
        step = 50 if q >= 500 else 10 if q >= 50 else 5 if q >= 20 else 1
        return float(max(step, round(q / step) * step))

    def _one_enquiry(self, d: date, cu, items, sites, age: int, now: bool = False) -> None:
        r = self.r
        text, parsed = self._enquiry_text(items, sites, d)
        channel = r.choices(
            ("whatsapp_paste", "email", "phone_note", "link", "chat"), (0.45, 0.25, 0.2, 0.05, 0.05)
        )[0]
        minute = r.randint(9 * 60 + 5, 19 * 60) if not now else r.randint(8 * 60 + 30, 9 * 60 + 20)
        received = ts(d, minute)
        enq = self.add(
            "enquiries",
            party_id=cu.party["id"],
            channel=channel,
            raw_text=text,
            received_at=received,
            parsed={"items": parsed, "site": None},
            status="new",
            assigned_to=cu.rep_id,
        )
        self.event(
            received,
            "enquiry.received",
            "enquiry",
            enq["id"],
            "agent" if channel != "chat" else "user",
            "sales",
            channel=channel,
            party=cu.party["name"],
        )
        if channel == "email":
            self._email_document(enq, cu)
        # Today's latest enquiries are still waiting for a quote.
        if now and r.random() < 0.6:
            return
        status = self._quote_status(age)
        self._make_quote(enq, cu, items, parsed, d, minute, status)

    def _quote_status(self, age: int) -> str:
        r = self.r
        if age > 10:
            return r.choices(("won", "lost", "expired"), (0.28, 0.22, 0.5))[0]
        if age >= 4:
            return r.choices(
                ("won", "lost", "negotiating", "opened", "sent", "expired"),
                (0.2, 0.1, 0.15, 0.25, 0.15, 0.15),
            )[0]
        if age >= 1:
            return r.choices(("sent", "opened", "negotiating", "won", "lost"), (0.35, 0.35, 0.15, 0.1, 0.05))[
                0
            ]
        return r.choices(("draft", "sent", "opened"), (0.3, 0.5, 0.2))[0]

    def _make_quote(self, enq, cu, items, parsed, d, minute, status, rate_factor=None, number=None) -> dict:
        r = self.r
        lines, subtotal, tax, margin_num = [], 0.0, 0.0, 0.0
        for it, p in zip(items, parsed, strict=False):
            iid = self.sim.item_rows[it.key]["id"]
            last = self.last_rate.get((cu.party["id"], iid))
            base = last or it.rate * self.sim.price_index(it, d)
            rate = round(base * (rate_factor or r.uniform(0.995, 1.01)), 2)
            cost = self.cost_now[iid]
            if rate_factor is None:  # the Sales agent never drafts below the owner's floor on its own
                rate = max(
                    rate, round(cost / (1 - (self.rules["margin_floor_pct"] + r.uniform(0.2, 1.5)) / 100), 2)
                )
            amt = p["qty"] * rate
            subtotal += amt
            tax += amt * it.gst / 100
            margin_num += amt - p["qty"] * cost
            lines.append((iid, p["qty"], rate, last, (rate - cost) / rate * 100))
        freight = money(subtotal * 0.004) if self.c.trade != "pharma" else 0.0
        created = minute + r.randint(4, 25)
        qn = number or f"Q-{self.quote_seq}"
        self.quote_seq += 1
        q = self.add(
            "quotes",
            number=qn,
            party_id=cu.party["id"],
            enquiry_id=enq["id"],
            status=status,
            created_at=ts(d, created),
            sent_at=None,
            opened_at=None,
            decided_at=None,
            valid_until=d + timedelta(days=3),
            subtotal=money(subtotal),
            freight=freight,
            tax=money(tax),
            total=money(subtotal + tax + freight),
            margin_pct=round(margin_num / subtotal * 100, 2),
            lost_reason=None,
            owner_id=cu.rep_id,
            sales_voucher_id=None,
        )
        for iid, qty, rate, last, mg in lines:
            self.add(
                "quote_lines",
                quote_id=q["id"],
                item_id=iid,
                qty=qty,
                rate=rate,
                last_rate=last,
                margin_pct=round(mg, 2),
            )
            self.s.add(
                "_quote_prices",
                organisation_id=self.org,
                item_id=iid,
                party_id=cu.party["id"],
                source="quote",
                date=d,
                rate=rate,
                qty=qty,
            )
        enq["status"] = "quoted"
        self.event(
            q["created_at"], "quote.created", "quote", q["id"], "agent", "sales", number=qn, total=q["total"]
        )
        self._advance_quote(q, cu, d, created)
        self.quotes.append(q)
        return q

    def _advance_quote(self, q, cu, d, created) -> None:
        r, st = self.r, q["status"]
        if st in ("draft", "pending_approval"):
            return
        sent = created + r.randint(1, 20)
        q["sent_at"] = ts(d, sent)
        link = self._link("quote", cu.party["id"], "quote", q["id"], q["sent_at"])
        self._message(
            cu.party["id"],
            "sales",
            "quote",
            f"Quote {q['number']}: total {q['total']:.0f}. Open to accept: oprisa.link/q",
            q["sent_at"],
            "read" if st != "sent" else "delivered",
            "quote",
            q["id"],
        )
        self.event(q["sent_at"], "quote.sent", "quote", q["id"], "agent", "sales", number=q["number"])
        if st == "sent":
            return
        sent_dt = as_dt(q["sent_at"])
        opened = sent_dt + timedelta(minutes=r.randint(10, 60 * 20))
        if opened >= self.now:
            opened = min(self.now - timedelta(minutes=5), sent_dt + timedelta(minutes=r.randint(5, 40)))
        q["opened_at"] = opened.isoformat()
        link["first_opened_at"] = q["opened_at"]
        self.event(q["opened_at"], "quote.opened", "quote", q["id"], "link", None, number=q["number"])
        if st in ("opened", "negotiating"):
            return
        decided = opened + timedelta(hours=r.randint(2, 70))
        if decided >= self.now:
            decided = opened + (self.now - opened) / 2
        q["decided_at"] = decided.isoformat()
        if st == "won":
            link["responded_at"] = q["decided_at"]
            link["response"] = {"accepted": True}
            sale = self._matching_sale(cu.party["id"], decided.date())
            q["sales_voucher_id"] = sale["id"] if sale else None
        elif st == "lost":
            q["lost_reason"] = r.choice(
                (
                    "Price higher than another supplier",
                    "Customer postponed the project",
                    "Needed delivery sooner",
                    "Bought from the mill directly",
                )
            )
        self.event(
            q["decided_at"],
            f"quote.{st}",
            "quote",
            q["id"],
            "link" if st == "won" else "agent",
            None,
            number=q["number"],
        )

    def _matching_sale(self, party_id: int, after: date):
        for v in self.vouchers:
            if (
                v["voucher_type"] == "sales"
                and v["party_id"] == party_id
                and after <= v["date"] <= after + timedelta(days=4)
            ):
                return v
        return None

    def _planted_quotes(self) -> None:
        r = self.r
        # A big quote sent three days ago that nobody has opened: the Sales agent should nudge.
        d = next_working(self.today - timedelta(days=3))
        big = max(self.active_customers(), key=lambda cu: cu.weight)
        it = big.items[0]
        lo, hi = it.qty
        parsed = [{"item": it.name, "qty": self._said_qty(it, hi * 1.6), "unit": it.unit, "said_as": it.name}]
        enq = self.add(
            "enquiries",
            party_id=big.party["id"],
            channel="email",
            raw_text=f"Please quote {parsed[0]['qty']:g} {it.unit} {it.name} for our new project, delivery in two lots.",
            received_at=ts(d, 10 * 60 + 12),
            parsed={"items": parsed, "site": None},
            status="new",
            assigned_to=big.rep_id,
        )
        self.event(
            enq["received_at"],
            "enquiry.received",
            "enquiry",
            enq["id"],
            "agent",
            "sales",
            channel="email",
            party=big.party["name"],
        )
        cold = self._make_quote(enq, big, [it], parsed, d, 10 * 60 + 12, "sent")
        self.scenarios.append(
            {
                "id": "cold_quote",
                "agent": "sales",
                "title": "A big quote has gone quiet",
                "situation": f"{cold['number']} to {big.party['name']} ({cold['total']:.0f} with tax) was sent three days ago and has not been opened.",
                "expect": {
                    "quote": cold["number"],
                    "action": "send_nudge",
                    "status": "sent",
                    "opened": False,
                },
                "check_sql": f"select number, status, opened_at is null as unopened from kb.quotes where organisation_id={self.org} and number='{cold['number']}'",
            }
        )
        # A quote the sales team priced below the owner's margin floor: must wait for approval.
        cu = r.choice([x for x in self.active_customers() if x.grade in ("A", "B")])
        it2 = cu.items[0]
        parsed2 = [
            {
                "item": it2.name,
                "qty": self._said_qty(it2, sum(it2.qty) / 2),
                "unit": it2.unit,
                "said_as": it2.name,
            }
        ]
        enq2 = self.add(
            "enquiries",
            party_id=cu.party["id"],
            channel="whatsapp_paste",
            raw_text=f"{parsed2[0]['qty']:g} {it2.unit} {it2.name} - match the rate from the other dealer please",
            received_at=ts(self.today, 8 * 60 + 41),
            parsed={"items": parsed2, "site": None},
            status="new",
            assigned_to=cu.rep_id,
        )
        iid2 = self.sim.item_rows[it2.key]["id"]
        floor = self.rules["margin_floor_pct"]
        target_rate = self.cost_now[iid2] / (1 - (floor - 0.9) / 100)
        base = self.last_rate.get((cu.party["id"], iid2)) or it2.rate * self.sim.price_index(it2, self.today)
        low = self._make_quote(
            enq2,
            cu,
            [it2],
            parsed2,
            self.today,
            8 * 60 + 41,
            "pending_approval",
            rate_factor=target_rate / base,
        )
        sales_user = next(u for u in self.s.rows["users"] if u["id"] == cu.rep_id)
        ap = self.add(
            "approvals",
            agent="sales",
            action_type="send_quote",
            title=f"{low['number']} for {cu.party['name']}: {parsed2[0]['qty']:g} {it2.unit} {it2.name}",
            reason=f"Margin {low['margin_pct']:.1f}% is below your {floor:.1f}% floor",
            amount=low["total"],
            payload={"quote": low["number"], "send_via": "link"},
            requested_by=sales_user["id"],
            requested_at=ts(self.today, 8 * 60 + 52),
            status="waiting",
            decided_by=None,
            decided_at=None,
            graph_thread_id=f"sales:{self.org}:{low['number']}",
        )
        self.event(
            ap["requested_at"],
            "approval.requested",
            "approval",
            ap["id"],
            "agent",
            "sales",
            reason=ap["reason"],
        )
        self.scenarios.append(
            {
                "id": "below_margin_quote",
                "agent": "sales",
                "title": "A quote below the margin floor waits for the owner",
                "situation": f"{low['number']} is priced at {low['margin_pct']:.1f}% margin; the floor is {floor:.1f}%.",
                "expect": {"quote": low["number"], "status": "pending_approval", "approval_waiting": True},
                "check_sql": f"select q.number, q.status, a.status as approval from kb.quotes q join kb.approvals a on a.payload->>'quote'=q.number where q.organisation_id={self.org} and q.number='{low['number']}'",
            }
        )

    # ------------------------------------------------------------------- promises

    def promises(self) -> list[dict]:
        r, out = self.r, []
        since = self.today - timedelta(days=45)
        cust = {cu.party["id"]: cu for cu in self.sim.customers}
        receipts = [v for v in self.vouchers if v["voucher_type"] == "receipt" and v["date"] >= since]
        for v in receipts:
            cu = cust.get(v["party_id"])
            if not cu or cu.grade not in ("C", "D") or r.random() > 0.35:
                continue
            made = v["date"] - timedelta(days=r.randint(2, 8))
            promised = v["amount"] if r.random() < 0.75 else money(v["amount"] * r.uniform(1.2, 1.5))
            status = "kept" if promised == v["amount"] else "part_kept"
            out.append(self._promise(cu, promised, made, v["date"], status, v["amount"]))
        # Who is overdue now, and has not paid in the last two weeks.
        overdue = defaultdict(float)
        for b in self.bills:
            if b["direction"] == "receivable" and b["pending_amount"] > 1 and b["due_date"] < self.today:
                overdue[b["party_id"]] += b["pending_amount"]
        paid_recently = {v["party_id"] for v in receipts if v["date"] >= self.today - timedelta(days=14)}
        stuck = [pid for pid in overdue if pid not in paid_recently and pid in cust]
        stuck.sort(key=lambda pid: -overdue[pid])
        missed_pids, open_pids = stuck[:4], stuck[4:9]
        for k, pid in enumerate(missed_pids):
            cu = cust[pid]
            due = next_working(self.today - timedelta(days=2 if k == 0 else r.randint(3, 9)))
            p = self._promise(
                cu,
                money(overdue[pid] * (1 if k == 0 else r.uniform(0.4, 1))),
                due - timedelta(days=r.randint(4, 8)),
                due,
                "missed",
                0,
            )
            out.append(p)
            if k == 0:
                self.scenarios.append(
                    {
                        "id": "missed_promise",
                        "agent": "collect",
                        "title": "A payment promise was missed",
                        "situation": f"{cu.party['name']} promised {p['amount']:.0f} for {due}, and nothing has come in.",
                        "expect": {
                            "party": cu.party["name"],
                            "promise_status": "missed",
                            "action": "call_today",
                            "task_kind": "missed_promise",
                        },
                        "check_sql": f"select p.name, pr.status, pr.due_date from kb.promises pr join kb.parties p on p.id=pr.party_id where pr.id={p['id']}",
                    }
                )
        for pid in open_pids:
            cu = cust[pid]
            due = next_working(self.today + timedelta(days=r.randint(0, 7)))
            out.append(
                self._promise(
                    cu,
                    money(overdue[pid] * r.uniform(0.5, 1)),
                    self.today - timedelta(days=r.randint(1, 5)),
                    due,
                    "open",
                    0,
                    via_link=r.random() < 0.6,
                )
            )
        return out

    def _promise(self, cu, amount, made, due, status, settled, via_link=False) -> dict:
        source = "link" if via_link else self.r.choice(("call", "call", "link", "chat"))
        p = self.add(
            "promises",
            party_id=cu.party["id"],
            amount=amount,
            made_on=made,
            due_date=due,
            source=source,
            status=status,
            settled_amount=settled,
        )
        at = ts(made, self.r.randint(10 * 60, 18 * 60))
        self.event(
            at,
            "promise.made",
            "promise",
            p["id"],
            "link" if source == "link" else "user",
            None,
            party=cu.party["name"],
            amount=amount,
            due=str(due),
        )
        if source == "link":
            link = self._link(
                "statement", cu.party["id"], "party", cu.party["id"], ts(made - timedelta(days=1), 10 * 60)
            )
            link["first_opened_at"] = at
            link["responded_at"] = at
            link["response"] = {"pay_on": str(due), "amount": amount}
        if status in ("kept", "part_kept", "missed"):
            self.event(
                ts(due, 19 * 60 + 30),
                f"promise.{status}",
                "promise",
                p["id"],
                "agent",
                "collect",
                party=cu.party["name"],
            )
        return p

    # ------------------------------------------------------------ messages, links

    def _link(self, purpose, party_id, entity_type, entity_id, created) -> dict:
        token = hashlib.sha256(
            f"{self.org}-{purpose}-{entity_id}-{created}-{self.r.random()}".encode()
        ).hexdigest()
        return self.add(
            "share_links",
            token_hash=token,
            purpose=purpose,
            party_id=party_id,
            entity_type=entity_type,
            entity_id=entity_id,
            created_at=created,
            expires_at=(as_dt(created) + timedelta(days=7)).isoformat(),
            first_opened_at=None,
            responded_at=None,
            response=None,
        )

    def _message(
        self, party_id, agent, purpose, body, at, status, entity_type=None, entity_id=None, channel=None
    ) -> dict:
        # Customers get a secure link: by email when we have one, otherwise by SMS.
        channel = channel or ("email" if self.party_by_id[party_id]["email"] else "sms")
        m = self.add(
            "messages",
            party_id=party_id,
            agent=agent,
            purpose=purpose,
            channel=channel,
            language=self.c.language,
            body=body,
            status=status,
            created_at=at,
            sent_at=at,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        self.event(at, "message.sent", "message", m["id"], "agent", agent, purpose=purpose)
        return m

    def reminders(self) -> None:
        days = self.rules["remind_days_before_due"]
        hi = self.c.language == "Hinglish"
        parties = {p["id"]: p for p in self.s.rows["parties"] if p["organisation_id"] == self.org}
        for b in self.bills:
            if b["direction"] != "receivable":
                continue
            send = b["due_date"] - timedelta(days=days)
            if not (self.today - timedelta(days=30) <= send <= self.today):
                continue
            send = next_working(send)
            if send > self.today:
                continue
            p = parties[b["party_id"]]
            body = (
                f"Namaste {p['contact_name']} ji, bill {b['bill_ref']} ka {b['amount']:.0f} {b['due_date']:%d %b} ko due hai."
                if hi
                else f"Dear {p['contact_name']}, bill {b['bill_ref']} for {b['amount']:.0f} is due on {b['due_date']:%d %b}."
            )
            self._message(
                p["id"],
                "collect",
                "reminder",
                body,
                ts(send, 9 * 60 + self.r.randint(5, 40)),
                self.r.choice(("read", "read", "delivered")),
                "bill",
                b["id"],
            )

    # ------------------------------------------------------------- buying side

    def purchasing(self) -> None:
        r, sim = self.r, self.sim
        vmap = {v["id"]: v for v in self.vouchers}
        metas = [m for m in self.s.rows["_purchase_meta"] if m["voucher_id"] in vmap]
        for m in metas:
            v = vmap[m["voucher_id"]]
            if v["date"] < self.today - timedelta(days=60):
                continue
            po = self._po(
                m["supplier_id"], m["item_id"], m["qty"], m["rate"], m["ordered"], "received", v["id"]
            )
            self.event(
                ts(v["date"], 15 * 60),
                "po.received",
                "purchase_order",
                po["id"],
                "tally_sync",
                None,
                number=po["number"],
            )
            if v["date"] >= self.today - timedelta(days=30):
                self._rfq(
                    m["item_id"],
                    m["qty"],
                    m["ordered"] - timedelta(days=1),
                    chosen=(m["supplier_id"], m["rate"]),
                )
        for _arrive, it, p, sup, ordered in sim._po_arrivals:
            iid = sim.item_rows[it.key]["id"]
            rate = round(it.cost * sim.price_index(it, ordered) * (1 + sup.delta), 2)
            qty = sim._round_qty(it, sim.per_day_qty[it.key] * 30)
            self._po(p["id"], iid, qty, rate, ordered, "sent", None)
        # The fast item: rates came in this morning, one supplier is cheaper. Nothing ordered yet.
        it = sim.plan.stockout_item
        iid = sim.item_rows[it.key]["id"]
        last_buy = max((m for m in metas if m["item_id"] == iid), key=lambda m: m["ordered"])
        rfq = self.add(
            "rfqs",
            item_id=iid,
            qty=sim._round_qty(it, sim._recent_per_day(iid, self.today) * 30),
            created_at=ts(self.today - timedelta(days=1), 16 * 60),
            status="open",
        )
        offers = []
        asked = sim.suppliers[:4]
        cheapest = max(
            range(len(asked)), key=lambda k: asked[k][1].on_time
        )  # a reliable one, so the saving is real
        for k, (p, sup) in enumerate(asked):
            if k == cheapest:
                rate, best = round(last_buy["rate"] * 0.97, 2), True
            else:
                rate, best = round(last_buy["rate"] * r.uniform(0.99, 1.025), 2), False
            q = self.add(
                "supplier_quotes",
                rfq_id=rfq["id"],
                supplier_id=p["id"],
                item_id=iid,
                rate=rate,
                delivery_days=sup.days,
                received_at=ts(self.today, 8 * 60 + r.randint(0, 50)),
                valid_until=self.today + timedelta(days=2),
            )
            offers.append((p, sup, best, rate))
            self.s.add(
                "_quote_prices",
                organisation_id=self.org,
                item_id=iid,
                party_id=p["id"],
                source="supplier_quote",
                date=self.today,
                rate=rate,
                qty=None,
            )
            self.event(
                q["received_at"],
                "supplier_quote.received",
                "supplier_quote",
                q["id"],
                "link",
                None,
                supplier=p["name"],
                rate=rate,
            )
        best = next(o for o in offers if o[2])
        self.scenarios.append(
            {
                "id": "stock_out",
                "agent": "stock",
                "title": "The fastest item is about to run out",
                "situation": f"{it.name} has only a few days of stock left, no purchase order is open, and four supplier rates came in this morning.",
                "expect": {
                    "item": it.name,
                    "status": "reorder",
                    "days_left_below": self.rules["reorder_days"],
                    "best_supplier": best[0]["name"],
                    "best_rate": best[3],
                    "action": "draft_po",
                    "needs_approval_above": self.rules["po_limit"],
                },
                "check_sql": f"select i.name, m.status, m.days_left from kb.item_metrics m join kb.items i on i.id=m.item_id where m.item_id={iid}",
            }
        )
        self.scenarios.append(
            {
                "id": "rate_drop",
                "agent": "stock",
                "title": "A supplier is cheaper than our last buy",
                "situation": f"{best[0]['name']} quoted {best[3]:.2f} for {it.name}, 3% below our last purchase at {last_buy['rate']:.2f}.",
                "expect": {
                    "supplier": best[0]["name"],
                    "rate": best[3],
                    "last_purchase_rate": last_buy["rate"],
                    "saving_pct": 3.0,
                },
                "check_sql": f"select p.name, sq.rate from kb.supplier_quotes sq join kb.parties p on p.id=sq.supplier_id where sq.rfq_id={rfq['id']} order by sq.rate limit 1",
            }
        )

    def _po(self, supplier_id, item_id, qty, rate, ordered, status, voucher_id) -> dict:
        self.po_seq += 1
        total = money(qty * rate * (1 + self.sim.item_by_id[item_id].gst / 100))
        po = self.add(
            "purchase_orders",
            number=f"PO-{self.po_seq:04d}",
            supplier_id=supplier_id,
            status=status,
            created_at=ts(ordered, 11 * 60),
            total=total,
            purchase_voucher_id=voucher_id,
        )
        self.add("po_lines", po_id=po["id"], item_id=item_id, qty=qty, rate=rate)
        self.event(
            po["created_at"], "po.sent", "purchase_order", po["id"], "agent", "stock", number=po["number"]
        )
        return po

    def _rfq(self, item_id, qty, d, chosen) -> None:
        r = self.r
        rfq = self.add("rfqs", item_id=item_id, qty=qty, created_at=ts(d, 15 * 60), status="closed")
        for p, sup in r.sample(self.sim.suppliers, k=min(3, len(self.sim.suppliers))):
            rate = chosen[1] if p["id"] == chosen[0] else round(chosen[1] * r.uniform(1.003, 1.03), 2)
            self.add(
                "supplier_quotes",
                rfq_id=rfq["id"],
                supplier_id=p["id"],
                item_id=item_id,
                rate=rate,
                delivery_days=sup.days,
                received_at=ts(d, 17 * 60 + r.randint(0, 120)),
                valid_until=d + timedelta(days=2),
            )
            self.s.add(
                "_quote_prices",
                organisation_id=self.org,
                item_id=item_id,
                party_id=p["id"],
                source="supplier_quote",
                date=d,
                rate=rate,
                qty=None,
            )

    # --------------------------------------------------- inbox, approvals, scenarios

    def inbox_and_scenarios(
        self, profiles: list[dict], metrics: list[dict], promises: list[dict], forecast: list[dict]
    ) -> None:
        r, plan, sim = self.r, self.sim.plan, self.sim
        prof = {p["party_id"]: p for p in profiles}
        parties = {p["id"]: p for p in self.s.rows["parties"] if p["organisation_id"] == self.org}
        now = ts(self.today, 6 * 60 + 5)
        role_user = self.users

        def task(agent, kind, title, detail, etype, eid, amount, prio, role, status="open", created=now):
            t = self.add(
                "tasks",
                agent=agent,
                kind=kind,
                title=title,
                detail=detail,
                entity_type=etype,
                entity_id=eid,
                amount=amount,
                priority=prio,
                assignee_role=role,
                status=status,
                created_at=created,
                due_at=ts(self.today, 18 * 60) if status == "open" else None,
                done_at=None if status == "open" else (as_dt(created) + timedelta(hours=3)).isoformat(),
            )
            return t

        # Calls: the biggest overdue, weighted by how late.
        overdue = sorted(
            (p for p in profiles if p["overdue"] > 0),
            key=lambda p: -p["overdue"] * (1 + p["oldest_overdue_days"] / 30),
        )
        for p in overdue[:8]:
            task(
                "collect",
                "call_customer",
                f"Call {parties[p['party_id']]['name']}",
                f"{p['overdue']:.0f} overdue, oldest {p['oldest_overdue_days']} days. Grade {p['grade']}.",
                "party",
                p["party_id"],
                p["overdue"],
                1 if p["oldest_overdue_days"] > 30 else 2,
                "accounts",
            )
        for pr in promises:
            if pr["status"] == "missed" and pr["due_date"] >= self.today - timedelta(days=3):
                task(
                    "collect",
                    "missed_promise",
                    f"{parties[pr['party_id']]['name']} missed a promise",
                    f"Promised {pr['amount']:.0f} for {pr['due_date']}. Nothing received.",
                    "promise",
                    pr["id"],
                    pr["amount"],
                    1,
                    "accounts",
                )
        for q in self.quotes:
            if q["status"] == "draft":
                task(
                    "sales",
                    "review_quote",
                    f"Send {q['number']} to {parties[q['party_id']]['name']}",
                    f"Total {q['total']:.0f}, margin {q['margin_pct']:.1f}%",
                    "quote",
                    q["id"],
                    q["total"],
                    2,
                    "sales",
                )
        on_order = {
            ln["item_id"]
            for po in self.s.rows["purchase_orders"]
            if po["organisation_id"] == self.org and po["status"] == "sent"
            for ln in self.s.rows["po_lines"]
            if ln["po_id"] == po["id"]
        }
        for m in metrics:
            it = sim.item_by_id[m["item_id"]]
            if m["status"] == "reorder" and m["item_id"] not in on_order:
                task(
                    "stock",
                    "reorder",
                    f"Reorder {it.name}",
                    f"{m['days_left']} days left at {m['per_day']:.1f} {it.unit}/day",
                    "item",
                    m["item_id"],
                    m["stock_value"],
                    1,
                    "purchase",
                )
            if m["status"] == "idle":
                task(
                    "stock",
                    "idle_stock",
                    f"Clear idle {it.name}",
                    f"No sale for {m['idle_days']} days, {m['stock_value']:.0f} stuck",
                    "item",
                    m["item_id"],
                    m["stock_value"],
                    3,
                    "owner",
                )

        # Some of yesterday's work, already done.
        for _k in range(12):
            p = r.choice(profiles)
            task(
                "collect",
                "call_customer",
                f"Call {parties[p['party_id']]['name']}",
                "Done from the call list",
                "party",
                p["party_id"],
                p["outstanding"],
                2,
                "accounts",
                status="done",
                created=ts(next_working(self.today - timedelta(days=r.randint(1, 6))), 9 * 60 + 30),
            )

        owner = role_user["owner"]
        # Slipping customer.
        slip = prof[plan.slipping.party["id"]]
        task(
            "sales",
            "win_back",
            f"{parties[slip['party_id']]['name']} has stopped ordering",
            f"Last order {slip['last_order_on']}, usually every {slip['avg_order_gap_days']} days",
            "party",
            slip["party_id"],
            slip["sales_90d"],
            2,
            "sales",
        )
        self.scenarios.append(
            {
                "id": "slipping_customer",
                "agent": "sales",
                "title": "A regular customer has gone quiet",
                "situation": f"{parties[slip['party_id']]['name']} ordered every {slip['avg_order_gap_days']} days and has not ordered since {slip['last_order_on']}.",
                "expect": {
                    "party": parties[slip["party_id"]]["name"],
                    "trend": "down",
                    "action": "win_back_call",
                },
                "check_sql": f"select p.name, cp.trend, cp.last_order_on from kb.customer_profiles cp join kb.parties p on p.id=cp.party_id where cp.party_id={slip['party_id']}",
            }
        )

        # Grade drop -> suggest a lower credit limit, waits for the owner.
        gd = prof[plan.grade_drop.party["id"]]
        ap = self.add(
            "approvals",
            agent="score",
            action_type="change_credit_limit",
            title=f"Lower {parties[gd['party_id']]['name']}'s credit limit",
            reason=f"Moved from grade {gd['previous_grade']} to {gd['grade']}: oldest unpaid bill is {gd['oldest_overdue_days']} days overdue",
            amount=gd["suggested_credit_limit"],
            payload={"party_id": gd["party_id"], "new_limit": gd["suggested_credit_limit"]},
            requested_by=None,
            requested_at=ts(self.today, 6 * 60 + 2),
            status="waiting",
            decided_by=None,
            decided_at=None,
            graph_thread_id=f"score:{self.org}:{gd['party_id']}",
        )
        self.event(
            ap["requested_at"],
            "grade.changed",
            "party",
            gd["party_id"],
            "agent",
            "score",
            **{"from": gd["previous_grade"], "to": gd["grade"]},
        )
        self.event(
            ap["requested_at"],
            "approval.requested",
            "approval",
            ap["id"],
            "agent",
            "score",
            reason=ap["reason"],
        )
        self.scenarios.append(
            {
                "id": "grade_drop",
                "agent": "score",
                "title": "A good customer has started paying late",
                "situation": f"{parties[gd['party_id']]['name']} paid within about a week of the due date for months; bills from the last ~80 days are running over a month late (oldest now {gd['oldest_overdue_days']} days overdue).",
                "expect": {
                    "party": parties[gd["party_id"]]["name"],
                    "previous_grade": gd["previous_grade"],
                    "grade": gd["grade"],
                    "action": "propose_lower_limit",
                    "approval_waiting": True,
                },
                "check_sql": f"select p.name, cp.previous_grade, cp.grade, cp.avg_days_late from kb.customer_profiles cp join kb.parties p on p.id=cp.party_id where cp.party_id={gd['party_id']}",
            }
        )

        # Idle stock -> an offer below list price, waits for the owner.
        if plan.idle_item:
            iid = sim.item_rows[plan.idle_item.key]["id"]
            m = next(x for x in metrics if x["item_id"] == iid)
            buyers = sorted({parties[b]["name"] for b in plan.idle_buyers})
            ap2 = self.add(
                "approvals",
                agent="stock",
                action_type="send_offer",
                title=f"Offer {plan.idle_item.name} to {len(buyers)} past buyers",
                reason="Offer price is below your list price",
                amount=m["stock_value"],
                payload={"item_id": iid, "price": round(plan.idle_item.cost * 1.02, 2), "to": buyers},
                requested_by=None,
                requested_at=ts(self.today, 6 * 60 + 3),
                status="waiting",
                decided_by=None,
                decided_at=None,
                graph_thread_id=f"stock:{self.org}:idle:{iid}",
            )
            self.event(
                ap2["requested_at"],
                "approval.requested",
                "approval",
                ap2["id"],
                "agent",
                "stock",
                reason=ap2["reason"],
            )
            self.scenarios.append(
                {
                    "id": "idle_stock",
                    "agent": "stock",
                    "title": "Money stuck in stock nobody buys",
                    "situation": f"{plan.idle_item.name}: no sale for {m['idle_days']} days, {m['stock_value']:.0f} at cost.",
                    "expect": {
                        "item": plan.idle_item.name,
                        "status": "idle",
                        "past_buyers": buyers,
                        "action": "offer_to_past_buyers",
                    },
                    "check_sql": f"select i.name, m.status, m.idle_days from kb.item_metrics m join kb.items i on i.id=m.item_id where m.item_id={iid}",
                }
            )

        # Cash gap: the first week the bank balance goes below zero.
        bulk = plan.bulk_purchase
        short = next((f for f in forecast if f["closing_balance"] < 0), None)
        if short:
            task(
                "cash",
                "cash_gap",
                f"Cash runs short in the week of {short['week_start']:%d %b}",
                f"Balance falls to {short['closing_balance']:.0f}. {bulk['supplier']['name']} bill of "
                f"{bulk['bill']['amount']:.0f} falls due {bulk['bill']['due_date']}.",
                "cash_forecast",
                None,
                -short["closing_balance"],
                1,
                "owner",
            )
        self.scenarios.append(
            {
                "id": "cash_gap",
                "agent": "cash",
                "title": "Cash runs short three weeks out",
                "situation": f"A {bulk['bill']['amount']:.0f} bill to {bulk['supplier']['name']} (bulk buy) falls due {bulk['bill']['due_date']}; "
                f"the bank balance of {forecast[0]['opening_balance']:.0f} covers weeks 1-2 but not week 3.",
                "expect": {
                    "short_week_start": str(short["week_start"]) if short else None,
                    "short_week_number": forecast.index(short) + 1 if short else None,
                    "closing_balance": short["closing_balance"] if short else None,
                    "big_payment": bulk["supplier"]["name"],
                    "action": "ask_early_payment_or_move_supplier_payment",
                },
                "check_sql": f"select week_start, closing_balance from kb.cash_forecast where organisation_id={self.org} "
                f"and closing_balance < 0 order by week_start limit 1",
            }
        )

        # Duplicate ledger.
        dup = plan.duplicate_of
        task(
            "collect",
            "duplicate_ledger",
            f"Same customer twice in Tally? {dup['duplicate']['name']}",
            f"Same GSTIN and phone as {dup['original']['name']}. One bill is sitting on the second ledger.",
            "party",
            dup["duplicate"]["id"],
            None,
            2,
            "accounts",
        )
        self.scenarios.append(
            {
                "id": "duplicate_ledger",
                "agent": "collect",
                "title": "One customer, two ledgers",
                "situation": f"{dup['duplicate']['name']} and {dup['original']['name']} share a GSTIN and phone; a bill on the second one is going unchased.",
                "expect": {
                    "original": dup["original"]["name"],
                    "duplicate": dup["duplicate"]["name"],
                    "same_gstin": True,
                    "action": "flag_for_accounts",
                },
                "check_sql": f"select count(*) from kb.parties where organisation_id={self.org} and gstin='{dup['original']['gstin']}'",
            }
        )

        # A few decisions from the past week, so approvals has history.
        for _k in range(6):
            d = next_working(self.today - timedelta(days=r.randint(1, 7)))
            q = r.choice([x for x in self.quotes if x["status"] in ("won", "lost", "sent", "opened")])
            self.add(
                "approvals",
                agent="sales",
                action_type="send_quote",
                title=f"{q['number']} for {parties[q['party_id']]['name']}",
                reason="Discount above 1.5% on last rate",
                amount=q["total"],
                payload={"quote": q["number"]},
                requested_by=q["owner_id"],
                requested_at=ts(d, 11 * 60),
                status=r.choice(("approved", "approved", "approved", "rejected")),
                decided_by=owner["id"],
                decided_at=ts(d, 11 * 60 + r.randint(5, 90)),
                graph_thread_id=f"sales:{self.org}:{q['number']}",
            )

    # ----------------------------------------------------------------- memory

    def memory(self) -> None:
        r, sim, c = self.r, self.sim, self.c
        custs = sorted(sim.customers, key=lambda cu: -cu.weight)[:12]
        sups = [p for p, _ in sim.suppliers]
        users = {u["role"]: u for u in self.s.rows["users"] if u["organisation_id"] == self.org}

        def mem(
            scope_type, scope_id, kind, content, source, created_by, days_ago=None, valid_to=None, conf=0.8
        ):
            at = ts(self.today - timedelta(days=days_ago or r.randint(3, 50)), r.randint(9 * 60, 19 * 60))
            self.add(
                "memories",
                scope_type=scope_type,
                scope_id=scope_id,
                kind=kind,
                content=content,
                embedding=None,
                source=source,
                confidence=conf,
                valid_from=at,
                valid_to=valid_to,
                created_by=created_by,
            )

        a, b, cc, d, e = custs[0], custs[1], custs[2], custs[3], custs[4]
        it0, it1 = c.items[0], c.items[1]
        mem(
            "party",
            a.party["id"],
            "preference",
            f"{a.party['contact_name']} at {a.party['name']} wants rates before 11 am; after that they buy from whoever replied first.",
            "chat",
            "sales",
        )
        mem(
            "party",
            b.party["id"],
            "fact",
            f"{b.party['name']} pays only after their own client releases funds, usually around the 10th of the month.",
            "call note",
            "collect",
            conf=0.7,
        )
        mem(
            "party",
            b.party["id"],
            "fact",
            f"{b.party['name']} used to pay around the 5th.",
            "call note",
            "collect",
            days_ago=80,
            valid_to=ts(self.today - timedelta(days=30), 600),
        )
        mem(
            "party",
            cc.party["id"],
            "instruction",
            f"Do not give {cc.party['name']} more than 1% off the last rate; they always come back.",
            "owner",
            users["owner"]["name"],
            conf=1.0,
        )
        mem(
            "party",
            d.party["id"],
            "note",
            f"{d.party['name']} disputes freight on every bill. Quote freight as a separate line.",
            "email",
            "sales",
        )
        mem(
            "party",
            e.party["id"],
            "preference",
            f"Send {e.party['name']}'s statements to {e.party['contact_name']} in accounts, not the owner.",
            "chat",
            "collect",
        )
        mem(
            "org",
            None,
            "instruction",
            "Never send reminders on Sundays or before 9 am.",
            "owner",
            users["owner"]["name"],
            conf=1.0,
        )
        mem(
            "org",
            None,
            "preference",
            "Morning brief: cash first, then collections, then everything else.",
            "chat",
            users["owner"]["name"],
            conf=1.0,
        )
        mem(
            "org",
            None,
            "fact",
            f"Busy season is {('Jan to Mar' if c.trade != 'pharma' else 'Jul to Oct')}; keep two extra weeks of stock of fast items then.",
            "owner",
            users["owner"]["name"],
        )
        mem(
            "item",
            sim.item_rows[it0.key]["id"],
            "fact",
            f"When {it0.name} is short, most customers accept another brand at the same rate.",
            "chat",
            "sales",
        )
        mem(
            "item",
            sim.item_rows[it1.key]["id"],
            "note",
            f"{it1.name}: customers often type '{(it1.aliases or (it1.name,))[0]}'.",
            "learned",
            "sales",
        )
        mem(
            "party",
            sups[0]["id"],
            "fact",
            f"{sups[0]['name']} gives an extra 0.5% if paid within 7 days.",
            "call note",
            "cash",
        )
        mem(
            "party",
            sups[-1]["id"],
            "fact",
            f"{sups[-1]['name']} is cheapest but often late; only use when the item is not urgent.",
            "learned",
            "stock",
        )
        mem(
            "user",
            users["accounts"]["id"],
            "preference",
            f"{users['accounts']['name']} wants the call list sorted by area.",
            "chat",
            "collect",
        )

        seen: set[str] = set()
        for it in c.items:
            iid = sim.item_rows[it.key]["id"]
            for k, al in enumerate(it.aliases):
                if al.lower() in seen:
                    continue  # one word, one item: an ambiguous alias is asked about, not stored
                seen.add(al.lower())
                self.add(
                    "item_aliases",
                    item_id=iid,
                    alias=al.lower(),
                    source="learned" if k else "tally",
                    hits=r.randint(2, 140),
                )

        notes = [
            (
                f"Call with {a.party['contact_name']} ({a.party['name']})",
                f"Asked for {it0.name} rates daily before 11. Happy with last delivery. Next project in Hinjewadi starts in 3 weeks; expects 300+ {it0.unit}.",
            ),
            (
                f"{sups[0]['name']} price list",
                f"Rates valid this week. {it0.name}: list less 1.2%. {it1.name}: list less 0.8%. Extra 0.5% for payment within 7 days. Delivery 2-3 days from depot.",
            ),
        ]
        for title, text in notes:
            doc = self.add(
                "documents",
                kind="note" if "Call" in title else "pdf",
                title=title,
                party_id=None,
                received_at=ts(self.today - timedelta(days=r.randint(2, 20)), 12 * 60),
                storage_url=None,
                text=text,
            )
            self.add("document_chunks", document_id=doc["id"], chunk_no=1, content=text, embedding=None)

        for k, (role, agent, _title) in enumerate(
            (
                ("owner", "ask", "Who owes the most"),
                ("accounts", "collect", "Today's calls"),
                ("sales", "sales", "Quote follow-ups"),
            )
        ):
            u = users[role]
            self.add(
                "chat_threads",
                user_id=u["id"],
                agent=agent,
                langgraph_thread_id=f"{self.org}:{u['id']}:{agent}:{k}",
                created_at=ts(self.today - timedelta(days=k + 1), 9 * 60 + 15),
                last_message_at=ts(self.today - timedelta(days=k), 18 * 60),
            )

    def _email_document(self, enq, cu) -> None:
        text = f"From: {cu.party['email'] or cu.party['contact_name']}\nSubject: Enquiry\n\n{enq['raw_text']}\n\nRegards,\n{cu.party['contact_name']}\n{cu.party['name']}"
        doc = self.add(
            "documents",
            kind="email",
            title=f"Enquiry from {cu.party['name']}",
            party_id=cu.party["id"],
            received_at=enq["received_at"],
            storage_url=None,
            text=text,
        )
        self.add("document_chunks", document_id=doc["id"], chunk_no=1, content=text, embedding=None)

    # ------------------------------------------------------------ runs and sync

    def runs_and_sync(self) -> None:
        r = self.r
        max_alter = max(v["alter_id"] for v in self.vouchers)
        alter = max_alter - 600
        for k in range(3, -1, -1):
            d = self.today - timedelta(days=k)
            if not working_day(d):
                continue
            end = 20 * 60 if k else 9 * 60 + 30
            for minute in range(9 * 60, end, 15):
                alter = min(max_alter, alter + r.randint(0, 12))
                bad = r.random() < 0.02
                self.add(
                    "tally_sync_runs",
                    started_at=ts(d, minute),
                    finished_at=ts(d, minute + 1),
                    status="partial" if bad else "ok",
                    last_alter_id=alter,
                    objects_read=r.randint(0, 40),
                    error="Tally not responding (company closed on OFFICE-PC)" if bad else None,
                )
        plan = (
            ("brief", 8 * 60, "schedule"),
            ("collect", 9 * 60, "schedule"),
            ("stock", 10 * 60, "schedule"),
            ("score", 13 * 60, "event"),
            ("cash", 18 * 60, "schedule"),
            ("score", 19 * 60, "event"),
        )
        for k in range(7, -1, -1):
            d = self.today - timedelta(days=k)
            if not working_day(d):
                continue
            for agent, minute, trig in plan:
                if k == 0 and minute > 9 * 60 + 30:
                    continue
                calls = r.randint(1, 6) if agent in ("brief", "cash") else r.randint(0, 3)
                tin, tout = calls * r.randint(1500, 4000), calls * r.randint(150, 600)
                failed = r.random() < 0.015
                self.add(
                    "agent_runs",
                    agent=agent,
                    trigger_type=trig,
                    trigger_ref=f"{agent}@{minute // 60:02d}:00",
                    started_at=ts(d, minute),
                    finished_at=ts(d, minute + 1),
                    status="failed" if failed else "ok",
                    llm_calls=calls,
                    tokens_in=tin,
                    tokens_out=tout,
                    cost_inr=round((tin * 0.00025 + tout * 0.001), 2),
                    outcome={"summary": f"{agent} run"} if not failed else None,
                    error="LLM timeout after 3 retries" if failed else None,
                )

    # ------------------------------------------------------------------ events

    def tally_events(self) -> None:
        since = self.today - timedelta(days=30)
        for v in self.vouchers:
            if v["date"] >= since:
                self.event(
                    ts(v["date"], 17 * 60 + (v["alter_id"] % 180)),
                    "voucher.posted",
                    "voucher",
                    v["id"],
                    "tally_sync",
                    None,
                    type=v["voucher_type"],
                    number=v["number"],
                    amount=v["amount"],
                )

    CONSUMERS = {
        "voucher.posted": ("score", "stock", "cash", "brief", "collect"),
        "enquiry.received": ("sales",),
        "quote.created": ("brief",),
        "quote.sent": ("brief",),
        "quote.opened": ("sales",),
        "quote.won": ("sales", "stock", "brief"),
        "quote.lost": ("sales", "brief"),
        "quote.expired": ("sales",),
        "promise.made": ("collect", "cash"),
        "promise.kept": ("collect", "score", "cash"),
        "promise.part_kept": ("collect", "score", "cash"),
        "promise.missed": ("collect", "score", "cash", "brief"),
        "message.sent": (),
        "po.sent": ("cash",),
        "po.received": ("stock", "cash"),
        "supplier_quote.received": ("stock",),
        "grade.changed": ("sales", "collect", "brief"),
        "approval.requested": ("brief",),
    }

    def write_events(self) -> None:
        self.tally_events()
        self.events.sort(key=lambda e: e["occurred_at"])
        cutoff = as_dt(ts(self.today, 6 * 60))
        for e in self.events:
            row = self.add("events", **e)
            pending = as_dt(e["occurred_at"]) >= cutoff
            for consumer in self.CONSUMERS.get(e["type"], ()):
                if (
                    e["type"] == "voucher.posted"
                    and consumer == "collect"
                    and e["payload"].get("type") != "receipt"
                ):
                    continue
                self.s.add(
                    "event_deliveries",
                    event_id=row["id"],
                    consumer=consumer,
                    status="pending" if pending else "done",
                    attempts=0 if pending else 1,
                    processed_at=None if pending else e["occurred_at"],
                )
