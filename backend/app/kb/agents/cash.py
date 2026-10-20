"""Cash: see a short week coming while there's time to act.

The facts layer keeps a four-week forecast from today's bank balance, open
bills, each customer's payment habit and the usual outgoings. Daily (and when
promises or POs change the picture) this agent finds the first week the
balance drops below the owner's minimum, names what causes it, and proposes
the two levers an owner actually has: ask good customers to pay early, and
move a supplier payment. Asking customers for money is the owner's call, so
it always waits for approval.
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.kb import fmt
from app.kb.agents.base import Agent, send_message
from app.kb.models import KbApproval, KbBill, KbCashWeek, KbCustomerProfile, KbParty
from app.kb.runtime import Ctx, Proposal, post, task


class CashAgent(Agent):
    name = "cash"
    label = "Cash"
    jobs = {"cash_daily": (18, 0)}

    def gather(self, ctx: Ctx, case: dict) -> dict:
        db = ctx.db
        weeks = db.scalars(
            select(KbCashWeek).where(KbCashWeek.scenario == "base").order_by(KbCashWeek.week_start)
        ).all()
        if not weeks:
            return {}
        floor = float(ctx.rule("min_balance"))
        ahead = int(ctx.rule("alert_weeks_ahead"))
        short = next((w for w in weeks if float(w.closing_balance) < floor), None)
        out = {
            "weeks": [
                {
                    "start": w.week_start,
                    "opening": float(w.opening_balance),
                    "in": float(w.inflow),
                    "out": float(w.outflow),
                    "closing": float(w.closing_balance),
                    "detail": w.detail,
                }
                for w in weeks
            ],
            "floor": floor,
        }
        if short is None or weeks.index(short) >= max(ahead, 1) + 1:
            return out | {"short": None}
        k = weeks.index(short)
        shortfall = floor - float(short.closing_balance)
        # Who could pay early: A/B customers whose money is expected after the short week.
        later: dict[str, float] = {}
        for w in weeks[k + 1 :]:
            for pid, amt in (w.detail or {}).get("in_parties", {}).items():
                later[pid] = later.get(pid, 0) + amt
        grades = {str(p.party_id): p.grade for p in db.scalars(select(KbCustomerProfile))}
        early = sorted(
            ((int(pid), amt) for pid, amt in later.items() if grades.get(pid) in ("A", "B")),
            key=lambda x: -x[1],
        )
        picks, total = [], 0.0
        for pid, amt in early:
            if total >= shortfall * 1.2 or len(picks) >= 6:
                break
            picks.append({"party_id": pid, "amount": round(amt, 2), "name": db.get(KbParty, pid).name})
            total += amt
        # The biggest supplier payment in the short week, and whether it can move a week.
        big = db.scalars(
            select(KbBill)
            .where(
                KbBill.direction == "payable",
                KbBill.pending_amount > 1,
                KbBill.due_date >= short.week_start,
                KbBill.due_date < short.week_start + timedelta(days=7),
            )
            .order_by(KbBill.pending_amount.desc())
        ).first()
        delay = None
        if big is not None:
            delay = {
                "bill_id": big.id,
                "party_id": big.party_id,
                "name": db.get(KbParty, big.party_id).name,
                "amount": float(big.pending_amount),
                "due": big.due_date,
                "new_date": big.due_date + timedelta(days=7),
                "ref": big.bill_ref,
            }
        waiting = db.scalars(
            select(KbApproval).where(KbApproval.agent == "cash", KbApproval.status == "waiting")
        ).first()
        return out | {
            "short": {
                "week": k + 1,
                "start": short.week_start,
                "closing": float(short.closing_balance),
                "shortfall": round(shortfall, 2),
            },
            "early": picks,
            "early_total": round(total, 2),
            "delay": delay,
            "already_asked": waiting is not None,
        }

    def decide(self, ctx: Ctx, case: dict, data: dict) -> list[Proposal]:
        if not data or not data.get("short"):
            return (
                [{"kind": "all_clear", "title": "Cash fine", "payload": {}}]
                if case.get("job") and data
                else []
            )
        s = data["short"]
        if case.get("job") == "cash_recheck" and data["already_asked"]:
            return []
        out: list[Proposal] = [
            {
                "kind": "cash_alert",
                "title": f"Cash short in the week of {fmt.day(s['start'])}",
                "payload": {
                    "short": s,
                    "weeks": data["weeks"],
                    "delay": data["delay"],
                    "early_total": data["early_total"],
                },
            }
        ]
        if not data["already_asked"] and (data["early"] or data["delay"]):
            out.append(
                {
                    "kind": "ask_early_payment",
                    "title": f"Ask {len(data['early'])} customers to pay early"
                    + (f" and move {data['delay']['name']}'s payment" if data["delay"] else ""),
                    "amount": s["shortfall"],
                    "entity_type": "cash_forecast",
                    "entity_id": s["week"],
                    "payload": {
                        "week_start": s["start"],
                        "shortfall": s["shortfall"],
                        "early": data["early"],
                        "delay": data["delay"],
                    },
                }
            )
        return out

    def needs_approval(self, ctx: Ctx, p: Proposal) -> str | None:
        if p["kind"] == "ask_early_payment":
            pl = p["payload"]
            return (
                f"Week of {fmt.day(pl['week_start'])} goes {fmt.inr(pl['shortfall'])} short. "
                "Asking customers to pay early is your call."
            )
        return None

    def do_all_clear(self, ctx: Ctx, pl: dict) -> dict:
        return {}

    def do_cash_alert(self, ctx: Ctx, pl: dict) -> dict:
        s = pl["short"]
        delay = pl.get("delay")
        why = [f"Closing balance {fmt.inr(s['closing'])} in week {s['week']}"]
        if delay:
            why.append(f"{delay['name']} bill of {fmt.inr(delay['amount'])} due {fmt.day(delay['due'])}")
        task(
            ctx,
            kind="cash_gap",
            title=f"Cash runs short in the week of {fmt.day(s['start'])}",
            detail=f"Balance falls to {fmt.inr(s['closing'])}."
            + (
                f" {delay['name']} bill of {fmt.inr(delay['amount'])} falls due {fmt.day(delay['due'])}."
                if delay
                else ""
            ),
            entity_type="cash_forecast",
            entity_id=s["week"],
            amount=s["shortfall"],
            priority=1,
            role="owner",
            dedupe=f"cashgap:{s['start']}",
            why=why,
        )
        post(
            ctx,
            text=f"Heads up: in the week of **{fmt.day(s['start'])}** the bank goes to **{fmt.inr(s['closing'])}**."
            + (
                f" The big one is {delay['name']}'s {fmt.inr(delay['amount'])} bill due {fmt.day(delay['due'])}."
                if delay
                else ""
            ),
            card={
                "kind": "cashweeks",
                "weeks": [
                    {"label": fmt.day(w["start"]), "inflow": w["in"], "outflow": w["out"]}
                    for w in pl["weeks"]
                ],
            },
        )
        return {"short_week": s["start"]}

    def on_approval_requested(self, ctx: Ctx, p: Proposal, approval) -> None:
        pl = p["payload"]
        rows = [
            {
                "name": e["name"],
                "amount": e["amount"],
                "tag": "pay early",
                "tone": "info",
                "hint": "Grade A/B, money expected after the short week",
            }
            for e in pl["early"]
        ]
        if pl.get("delay"):
            d = pl["delay"]
            rows.append(
                {
                    "name": d["name"],
                    "amount": d["amount"],
                    "tag": "move 1 week",
                    "tone": "warn",
                    "hint": f"Bill {d['ref']} due {fmt.day(d['due'])} → {fmt.day(d['new_date'])}",
                }
            )
        post(
            ctx,
            text=f"Two ways to cover the {fmt.inr(pl['shortfall'])} gap. Shall I go ahead?",
            card={
                "kind": "queue",
                "total": sum(e["amount"] for e in pl["early"]),
                "count": len(rows),
                "rows": rows,
            },
            actions=[
                {"id": "approve", "label": "Yes, send the requests", "primary": True},
                {"id": "reject", "label": "I'll handle it"},
            ],
            ref={"approval_id": approval.id},
        )

    def do_ask_early_payment(self, ctx: Ctx, pl: dict) -> dict:
        sent = 0
        by = fmt.day(ctx.today + timedelta(days=5))
        for e in pl.get("early", []):
            party = ctx.db.get(KbParty, e["party_id"])
            send_message(
                ctx,
                party,
                "early_payment",
                {"amount": fmt.inr(e["amount"], short=False), "by": by},
                entity_type="party",
                entity_id=party.id,
                link_purpose="early_pay",
            )
            sent += 1
        d = pl.get("delay")
        if d:
            sup = ctx.db.get(KbParty, d["party_id"])
            send_message(
                ctx,
                sup,
                "payment_delay",
                {
                    "bill": d["ref"],
                    "amount": fmt.inr(d["amount"], short=False),
                    "due": fmt.day(d["due"]),
                    "new_date": fmt.day(d["new_date"]),
                },
                entity_type="bill",
                entity_id=d["bill_id"],
            )
        post(
            ctx,
            text=f"Sent early-payment requests to {sent} customers"
            + (f" and asked {d['name']} to take payment a week later." if d else "."),
        )
        return {"early_requests": sent, "delay_asked": bool(d)}

    def on_event(self, run, event) -> None:
        if event.type in ("promise.missed", "po.sent", "early_pay.promised"):
            run({"job": "cash_recheck"}, event.type)
