"""Collections: reminders, statements, today's calls, and every payment promise.

Daily at 9:00 it reminds customers whose bills fall due soon, sends overdue
customers a statement with a link to pick a payment date, finds promises that
were missed, builds the call list, and flags customers keyed twice in Tally.
A receipt arriving from Tally settles promises and clears calls.
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select

from app.kb import events, fmt
from app.kb.agents.base import Agent, already_messaged, send_message
from app.kb.models import (
    KbBill,
    KbCustomerProfile,
    KbMessage,
    KbParty,
    KbPromise,
    KbVoucher,
)
from app.kb.runtime import Ctx, Proposal, close_tasks, post, task

STATEMENTS_PER_DAY = 25


class CollectAgent(Agent):
    name = "collect"
    label = "Collections"
    jobs = {"collect_daily": (9, 0)}

    # ------------------------------------------------------------------ gather

    def gather(self, ctx: Ctx, case: dict) -> dict:
        db = ctx.db
        if "receipt" in case:
            v = db.get(KbVoucher, case["receipt"])
            promises = db.scalars(
                select(KbPromise)
                .where(KbPromise.party_id == v.party_id, KbPromise.status.in_(("open", "missed")))
                .order_by(KbPromise.due_date)
            ).all()
            prof = db.scalars(
                select(KbCustomerProfile).where(KbCustomerProfile.party_id == v.party_id)
            ).first()
            return {
                "voucher": {
                    "id": v.id,
                    "party_id": v.party_id,
                    "amount": float(v.amount),
                    "date": v.date,
                    "type": v.voucher_type,
                    "number": v.number,
                },
                "promises": [
                    {
                        "id": p.id,
                        "amount": float(p.amount),
                        "due": p.due_date,
                        "made": p.made_on,
                        "status": p.status,
                    }
                    for p in promises
                ],
                "overdue_left": float(prof.overdue) if prof else 0.0,
            }
        if (
            case.get("job") != "collect_daily"
            and "statement_for" not in case
            and "remind_parties" not in case
        ):
            return {}
        today = ctx.today
        parties = {p.id: p for p in db.scalars(select(KbParty).where(KbParty.kind == "customer"))}
        profiles = {p.party_id: p for p in db.scalars(select(KbCustomerProfile))}
        bills = [
            b
            for b in db.scalars(
                select(KbBill).where(KbBill.direction == "receivable", KbBill.pending_amount > 1)
            )
        ]
        promises = db.scalars(select(KbPromise).where(KbPromise.status == "open")).all()
        receipts = defaultdict(list)
        for v in db.scalars(
            select(KbVoucher).where(
                KbVoucher.voucher_type == "receipt", KbVoucher.date >= today - timedelta(days=60)
            )
        ):
            receipts[v.party_id].append((v.date, float(v.amount)))
        last_statement = dict(
            db.execute(
                select(KbMessage.party_id, func.max(KbMessage.created_at))
                .where(KbMessage.purpose == "statement")
                .group_by(KbMessage.party_id)
            ).all()
        )
        return {
            "today": today,
            "bills": [
                {
                    "id": b.id,
                    "party_id": b.party_id,
                    "ref": b.bill_ref,
                    "due": b.due_date,
                    "pending": float(b.pending_amount),
                }
                for b in bills
            ],
            "profiles": {
                str(pid): {
                    "grade": p.grade,
                    "overdue": float(p.overdue),
                    "outstanding": float(p.outstanding),
                    "oldest": p.oldest_overdue_days,
                    "pay_day": p.usual_pay_day,
                    "avg_late": float(p.avg_days_late),
                }
                for pid, p in profiles.items()
            },
            "promises": [
                {
                    "id": p.id,
                    "party_id": p.party_id,
                    "amount": float(p.amount),
                    "due": p.due_date,
                    "made": p.made_on,
                }
                for p in promises
            ],
            "paid_since": {
                str(p.id): sum(a for d, a in receipts[p.party_id] if d >= p.made_on) for p in promises
            },
            "last_statement": {str(pid): d.date() for pid, d in last_statement.items() if pid},
            "gstin": [
                {"party_id": p.id, "gstin": p.gstin, "name": p.name, "phone": p.phone}
                for p in parties.values()
                if p.gstin
            ],
            "names": {str(pid): p.name for pid, p in parties.items()},
        }

    # ------------------------------------------------------------------ decide

    def decide(self, ctx: Ctx, case: dict, data: dict) -> list[Proposal]:
        if "receipt" in case:
            return self._decide_receipt(ctx, data)
        if "promise_made" in case:
            return [
                {
                    "kind": "note_promise",
                    "title": "Promise made",
                    "payload": {"party_id": case["promise_made"]},
                }
            ]
        if "statement_for" in case:
            return [
                {
                    "kind": "send_statements",
                    "title": "Send a statement",
                    "payload": {"party_ids": [case["statement_for"]]},
                }
            ]
        if "remind_parties" in case:
            ids = set(case["remind_parties"])
            bills = [b["id"] for b in data.get("bills", []) if b["party_id"] in ids]
            return (
                [
                    {
                        "kind": "send_reminders",
                        "title": f"Remind {len(ids)} customers",
                        "payload": {"bill_ids": bills, "include_overdue": True},
                    }
                ]
                if bills
                else []
            )
        if not data:
            return []
        today: date = data["today"]
        out: list[Proposal] = []

        # Promises that came and went with nothing (or too little) received.
        for p in data["promises"]:
            if p["due"] < today:
                paid = data["paid_since"].get(str(p["id"]), 0)
                status = "part_kept" if paid >= 0.5 * p["amount"] else "missed"
                out.append(
                    {
                        "kind": "close_promise",
                        "title": f"Promise from {data['names'].get(str(p['party_id']))} {status.replace('_', ' ')}",
                        "payload": {"promise_id": p["id"], "status": status, "paid": paid},
                        "entity_type": "promise",
                        "entity_id": p["id"],
                    }
                )

        # Reminders for bills falling due within the window, once per bill.
        window = int(ctx.rule("remind_days_before_due"))
        due_soon = [
            b
            for b in data["bills"]
            if today <= b["due"] <= today + timedelta(days=window)
            and not already_messaged(ctx, "reminder", "bill", b["id"])
        ]
        if due_soon:
            out.append(
                {
                    "kind": "send_reminders",
                    "title": f"Remind {len({b['party_id'] for b in due_soon})} customers before due",
                    "payload": {"bill_ids": [b["id"] for b in due_soon]},
                }
            )

        # Statements for overdue customers, at most every N days each.
        every = int(ctx.rule("statement_every_days"))
        overdue = sorted(
            (pid for pid, p in data["profiles"].items() if p["overdue"] > 1),
            key=lambda pid: -data["profiles"][pid]["overdue"],
        )  # str ids
        due_statement = [
            pid
            for pid in overdue
            if (data["last_statement"].get(pid) or date(1900, 1, 1)) <= today - timedelta(days=every)
        ]
        if due_statement:
            out.append(
                {
                    "kind": "send_statements",
                    "title": f"Statements to {min(len(due_statement), STATEMENTS_PER_DAY)} overdue customers",
                    "payload": {"party_ids": [int(x) for x in due_statement[:STATEMENTS_PER_DAY]]},
                }
            )

        # Today's calls: the biggest overdue, weighted by how late.
        size = int(ctx.rule("call_list_size"))
        ranked = sorted(
            overdue,
            key=lambda pid: -data["profiles"][pid]["overdue"] * (1 + data["profiles"][pid]["oldest"] / 30),
        )
        if ranked:
            out.append(
                {
                    "kind": "call_list",
                    "title": "Today's call list",
                    "payload": {"party_ids": [int(x) for x in ranked[:size]]},
                }
            )

        # The same customer keyed twice: same GSTIN on two ledgers.
        by_gstin = defaultdict(list)
        for p in data["gstin"]:
            by_gstin[p["gstin"]].append(p)
        groups = [g for g in by_gstin.values() if len(g) > 1]
        if groups:
            out.append(
                {
                    "kind": "flag_duplicates",
                    "title": "Customers keyed twice in Tally",
                    "payload": {"groups": [[x["party_id"] for x in g] for g in groups]},
                }
            )
        return out

    def _decide_receipt(self, ctx: Ctx, data: dict) -> list[Proposal]:
        v = data["voucher"]
        out: list[Proposal] = [
            {"kind": "note_receipt", "title": "Receipt", "payload": {"voucher_id": v["id"]}}
        ]
        left = v["amount"]
        for p in data["promises"]:
            if left <= 0:
                break
            status = "kept" if left >= 0.98 * p["amount"] else "part_kept"
            out.append(
                {
                    "kind": "close_promise",
                    "title": f"Promise {status.replace('_', ' ')}",
                    "payload": {"promise_id": p["id"], "status": status, "paid": min(left, p["amount"])},
                    "entity_type": "promise",
                    "entity_id": p["id"],
                }
            )
            left -= p["amount"]
        return out

    # --------------------------------------------------------------------- act

    def do_close_promise(self, ctx: Ctx, pl: dict) -> dict:
        p = ctx.db.get(KbPromise, pl["promise_id"])
        if p is None or p.status not in ("open", "missed"):
            return {}
        p.status = pl["status"]
        p.settled_amount = pl.get("paid") or 0
        party = ctx.db.get(KbParty, p.party_id)
        events.publish(
            ctx.db,
            f"promise.{p.status}",
            "promise",
            p.id,
            source="agent",
            actor=self.name,
            party_id=p.party_id,
            amount=float(p.amount),
        )
        if p.status == "missed":
            task(
                ctx,
                kind="missed_promise",
                title=f"{party.name} missed a promise",
                detail=f"Promised {fmt.inr(p.amount)} for {fmt.day(p.due_date)}. Nothing received.",
                entity_type="promise",
                entity_id=p.id,
                amount=float(p.amount),
                priority=1,
                role="accounts",
                dedupe=f"missed:{p.id}",
                why=[
                    f"Promise made {fmt.day(p.made_on)} for {fmt.day(p.due_date)}",
                    "No receipt in Tally since then",
                ],
            )
            post(
                ctx,
                card={
                    "kind": "alert",
                    "tone": "bad",
                    "title": f"{party.name} missed a promise",
                    "body": f"They promised {fmt.inr(p.amount)} for {fmt.day(p.due_date)} and nothing has come in. "
                    "It's at the top of today's calls.",
                },
                actions=[
                    {"id": "go-call", "label": "Call now", "primary": True, "data": {"party_id": party.id}}
                ],
                ref={"party_id": party.id},
            )
        else:
            close_tasks(ctx, kind="missed_promise", entity_type="promise", entity_id=p.id)
        return {"promise": p.id, "status": p.status}

    def do_send_reminders(self, ctx: Ctx, pl: dict) -> dict:
        sent = 0
        bills = [ctx.db.get(KbBill, bid) for bid in pl.get("bill_ids", [])]
        for b in bills:
            if b is None or float(b.pending_amount) <= 1:
                continue
            party = ctx.db.get(KbParty, b.party_id)
            send_message(
                ctx,
                party,
                "reminder",
                {
                    "bill": b.bill_ref,
                    "amount": fmt.inr(b.pending_amount, short=False),
                    "due": fmt.day(b.due_date),
                },
                entity_type="bill",
                entity_id=b.id,
                link_purpose="statement",
                link_entity=("party", party.id),
            )
            sent += 1
        if sent:
            post(
                ctx,
                text=f"Sent **{sent} payment reminder{'s' if sent != 1 else ''}** for bills falling due in the next "
                f"{int(ctx.rule('remind_days_before_due'))} days.",
                status="Sent by Collections",
            )
        return {"reminders": sent}

    def do_send_statements(self, ctx: Ctx, pl: dict) -> dict:
        sent = 0
        for pid in pl.get("party_ids", []):
            party = ctx.db.get(KbParty, pid)
            prof = ctx.db.scalars(select(KbCustomerProfile).where(KbCustomerProfile.party_id == pid)).first()
            open_bills = (
                ctx.db.scalar(
                    select(func.count())
                    .select_from(KbBill)
                    .where(
                        KbBill.party_id == pid, KbBill.direction == "receivable", KbBill.pending_amount > 1
                    )
                )
                or 0
            )
            if party is None or prof is None or float(prof.outstanding) <= 1:
                continue
            send_message(
                ctx,
                party,
                "statement",
                {
                    "amount": fmt.inr(prof.outstanding, short=False),
                    "bills": open_bills,
                    "oldest": prof.oldest_overdue_days,
                },
                entity_type="party",
                entity_id=pid,
                link_purpose="statement",
            )
            sent += 1
        if sent:
            post(
                ctx,
                text=f"Sent **{sent} statement{'s' if sent != 1 else ''}** to overdue customers, each with a link to pick a payment date.",
                status="Sent by Collections",
            )
        return {"statements": sent}

    def do_call_list(self, ctx: Ctx, pl: dict) -> dict:
        rows = []
        total = 0.0
        for pid in pl.get("party_ids", []):
            party = ctx.db.get(KbParty, pid)
            prof = ctx.db.scalars(select(KbCustomerProfile).where(KbCustomerProfile.party_id == pid)).first()
            if not party or not prof:
                continue
            total += float(prof.overdue)
            task(
                ctx,
                kind="call_customer",
                title=f"Call {party.name}",
                detail=f"{fmt.inr(prof.overdue)} overdue, oldest {prof.oldest_overdue_days} days. Grade {prof.grade}.",
                entity_type="party",
                entity_id=pid,
                amount=float(prof.overdue),
                priority=1 if prof.oldest_overdue_days > 30 else 2,
                role="accounts",
                dedupe=f"call:{pid}",
                why=list(prof.reasons or []),
            )
            rows.append(
                {
                    "name": party.name,
                    "amount": float(prof.overdue),
                    "tag": f"{prof.oldest_overdue_days} d",
                    "tone": "bad" if prof.oldest_overdue_days > 30 else "warn",
                    "hint": f"Grade {prof.grade} · usually pays in {prof.usual_pay_day} days",
                }
            )
        if rows:
            post(
                ctx,
                text="Here's today's call list, biggest and latest first.",
                card={"kind": "queue", "total": total, "count": len(rows), "rows": rows[:8]},
                actions=[{"id": "go-collect", "label": "Open Collections", "primary": True}],
            )
        return {"calls": len(rows)}

    def do_flag_duplicates(self, ctx: Ctx, pl: dict) -> dict:
        n = 0
        for group in pl.get("groups", []):
            parties = [ctx.db.get(KbParty, pid) for pid in group]
            parties = [p for p in parties if p]
            if len(parties) < 2:
                continue
            original = min(parties, key=lambda p: p.since or date(2100, 1, 1))
            dup = [p for p in parties if p.id != original.id]
            pending = (
                ctx.db.scalar(
                    select(func.coalesce(func.sum(KbBill.pending_amount), 0)).where(
                        KbBill.party_id.in_([p.id for p in dup]), KbBill.direction == "receivable"
                    )
                )
                or 0
            )
            for d in dup:
                if task(
                    ctx,
                    kind="duplicate_ledger",
                    title=f"Same customer twice in Tally? {d.name}",
                    detail=f"Same GSTIN and phone as {original.name}. {fmt.inr(pending)} is sitting on the second ledger.",
                    entity_type="party",
                    entity_id=d.id,
                    amount=float(pending),
                    priority=2,
                    role="accounts",
                    dedupe=f"dup:{original.gstin}",
                    why=[f"GSTIN {original.gstin} on both ledgers"],
                ):
                    n += 1
        return {"duplicates": n}

    def do_note_receipt(self, ctx: Ctx, pl: dict) -> dict:
        v = ctx.db.get(KbVoucher, pl["voucher_id"])
        party = ctx.db.get(KbParty, v.party_id) if v and v.party_id else None
        if not party:
            return {}
        prof = ctx.db.scalars(select(KbCustomerProfile).where(KbCustomerProfile.party_id == party.id)).first()
        if prof is not None and float(prof.overdue) <= 1:
            close_tasks(ctx, kind="call_customer", entity_type="party", entity_id=party.id)
        post(
            ctx,
            text=f"**{fmt.inr(v.amount)}** received from {party.name} ({v.number})."
            + (
                f" Still overdue: {fmt.inr(prof.overdue)}."
                if prof and float(prof.overdue) > 1
                else " Nothing overdue now."
            ),
        )
        return {"receipt": v.id}

    def do_note_promise(self, ctx: Ctx, pl: dict) -> dict:
        party = ctx.db.get(KbParty, pl["party_id"])
        p = ctx.db.scalars(
            select(KbPromise)
            .where(KbPromise.party_id == pl["party_id"], KbPromise.status == "open")
            .order_by(KbPromise.id.desc())
        ).first()
        if not party or not p:
            return {}
        close_tasks(ctx, kind="call_customer", entity_type="party", entity_id=party.id)
        post(
            ctx,
            text=f"{party.name} promised **{fmt.inr(p.amount)}** for {fmt.day(p.due_date)}. "
            "I took them off today's calls and will check on the day.",
        )
        return {"promise": p.id}

    # ------------------------------------------------------------------ events

    def on_event(self, run, event) -> None:
        p = event.payload or {}
        if (
            event.type == "voucher.posted"
            and p.get("type") in ("receipt", "credit_note")
            and p.get("party_id")
        ):
            run({"receipt": event.entity_id}, f"voucher {p.get('number')}")
        elif event.type == "handoff.requested" and p.get("action") == "statement":
            run({"statement_for": int(p["party_id"])}, "handoff from Ask")
        elif event.type == "promise.made" and p.get("party_id"):
            run({"promise_made": int(p["party_id"])}, "promise made")

    def on_chat_action(self, db, message, action: dict, user_id: int | None) -> str | None:
        return None
