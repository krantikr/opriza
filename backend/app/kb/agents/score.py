"""Customer Score: grades every customer from how they actually pay.

The grade itself is computed by the facts layer (code, with reasons). This
agent watches it: when a customer moves down, it tells Sales and Collections
(`grade.changed`) and proposes a credit limit that matches the new grade.
Lowering a limit always waits for the owner (by default); raising one for an
A customer can be allowed to go ahead alone.
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.kb import events, fmt
from app.kb.agents.base import Agent
from app.kb.models import KbApproval, KbCustomerProfile, KbEvent, KbParty, KbTallyPosting
from app.kb.runtime import Ctx, Proposal, post

ORDER = "ABCD"
PER_RUN = 5


class ScoreAgent(Agent):
    name = "score"
    label = "Customer Score"
    jobs = {"score_daily": (19, 0)}

    def gather(self, ctx: Ctx, case: dict) -> dict:
        db = ctx.db
        q = select(KbCustomerProfile, KbParty).join(KbParty, KbParty.id == KbCustomerProfile.party_id)
        if case.get("party_id"):
            q = q.where(KbCustomerProfile.party_id == case["party_id"])
        rows = db.execute(q).all()
        waiting = {
            (a.payload or {}).get("party_id")
            for a in db.scalars(
                select(KbApproval).where(
                    KbApproval.action_type == "change_credit_limit", KbApproval.status == "waiting"
                )
            )
        }
        recent = {
            (e.entity_id, (e.payload or {}).get("to"))
            for e in db.scalars(
                select(KbEvent).where(
                    KbEvent.type == "grade.changed", KbEvent.occurred_at >= ctx.now - timedelta(days=30)
                )
            )
        }
        out = []
        for prof, party in rows:
            if not prof.previous_grade or prof.previous_grade == prof.grade or float(prof.sales_12m) <= 0:
                continue
            if (party.id, prof.grade) in recent:
                continue
            out.append(
                {
                    "party_id": party.id,
                    "name": party.name,
                    "from": prof.previous_grade,
                    "to": prof.grade,
                    "limit": float(party.credit_limit) if party.credit_limit else None,
                    "suggested": float(prof.suggested_credit_limit) if prof.suggested_credit_limit else None,
                    "outstanding": float(prof.outstanding),
                    "reasons": list(prof.reasons or []),
                    "avg_late": float(prof.avg_days_late),
                    "oldest": prof.oldest_overdue_days,
                    "waiting": party.id in waiting,
                }
            )
        out.sort(key=lambda r: -r["outstanding"])
        return {"changes": out}

    def decide(self, ctx: Ctx, case: dict, data: dict) -> list[Proposal]:
        out: list[Proposal] = []
        worse = [c for c in data.get("changes", []) if ORDER.index(c["to"]) > ORDER.index(c["from"])]
        better = [c for c in data.get("changes", []) if ORDER.index(c["to"]) < ORDER.index(c["from"])]
        for c in (worse + better)[: PER_RUN * 3]:
            out.append(
                {
                    "kind": "note_grade",
                    "title": f"{c['name']}: {c['from']} → {c['to']}",
                    "payload": c,
                    "entity_type": "party",
                    "entity_id": c["party_id"],
                }
            )
        for c in worse[:PER_RUN]:
            if c["waiting"] or not c["limit"] or not c["suggested"] or c["suggested"] >= c["limit"] * 0.9:
                continue
            out.append(
                {
                    "kind": "change_credit_limit",
                    "title": f"Lower the credit limit for {c['name']}",
                    "amount": c["suggested"],
                    "entity_type": "party",
                    "entity_id": c["party_id"],
                    "payload": {
                        "party_id": c["party_id"],
                        "old_limit": c["limit"],
                        "new_limit": c["suggested"],
                        "from": c["from"],
                        "to": c["to"],
                        "oldest": c["oldest"],
                        "reasons": c["reasons"],
                    },
                }
            )
        for c in better[:PER_RUN]:
            if (
                c["to"] == "A"
                and c["limit"]
                and c["suggested"]
                and c["suggested"] > c["limit"] * 1.1
                and not c["waiting"]
            ):
                out.append(
                    {
                        "kind": "change_credit_limit",
                        "title": f"Raise the credit limit for {c['name']}",
                        "amount": c["suggested"],
                        "entity_type": "party",
                        "entity_id": c["party_id"],
                        "payload": {
                            "party_id": c["party_id"],
                            "old_limit": c["limit"],
                            "new_limit": c["suggested"],
                            "from": c["from"],
                            "to": c["to"],
                            "oldest": c["oldest"],
                            "reasons": c["reasons"],
                        },
                    }
                )
        return out

    def needs_approval(self, ctx: Ctx, p: Proposal) -> str | None:
        if p["kind"] != "change_credit_limit":
            return None
        pl = p["payload"]
        lowering = pl["new_limit"] < pl["old_limit"]
        if lowering and ctx.rule("ask_before_lowering_limit"):
            what = (
                f"oldest unpaid bill is {pl['oldest']} days overdue"
                if pl.get("oldest")
                else "paying later than before"
            )
            return f"Moved from grade {pl['from']} to {pl['to']}: {what}"
        if not lowering and not ctx.rule("raise_limit_alone"):
            return f"Moved up to grade {pl['to']}; a higher limit is your call"
        return None

    def on_approval_requested(self, ctx: Ctx, p: Proposal, approval) -> None:
        pl = p["payload"]
        party = ctx.db.get(KbParty, pl["party_id"])
        post(
            ctx,
            card={
                "kind": "score",
                "name": party.name,
                "grade": pl["to"],
                "from": pl["from"],
                "reasons": [{"up": False, "text": r} for r in pl["reasons"][:4]],
                "suggestion": f"Change the credit limit from {fmt.inr(pl['old_limit'])} to {fmt.inr(pl['new_limit'])}",
            },
            actions=[
                {"id": "approve", "label": "Change the limit", "primary": True},
                {"id": "reject", "label": "Keep it"},
            ],
            ref={"approval_id": approval.id},
        )

    def do_note_grade(self, ctx: Ctx, c: dict) -> dict:
        events.publish(
            ctx.db,
            "grade.changed",
            "party",
            c["party_id"],
            source="agent",
            actor=self.name,
            **{"from": c["from"], "to": c["to"]},
        )
        return {"party": c["party_id"], "from": c["from"], "to": c["to"]}

    def do_change_credit_limit(self, ctx: Ctx, pl: dict) -> dict:
        party = ctx.db.get(KbParty, pl["party_id"])
        party.credit_limit = pl["new_limit"]
        ctx.db.add(
            KbTallyPosting(
                organisation_id=ctx.org,
                kind="credit_limit",
                entity_type="party",
                entity_id=party.id,
                payload={"ledger": party.name, "credit_limit": pl["new_limit"]},
                created_at=ctx.now,
            )
        )
        post(
            ctx,
            text=f"{party.name}'s credit limit is now **{fmt.inr(pl['new_limit'])}** (was {fmt.inr(pl['old_limit'])}). "
            "Queued for Tally.",
        )
        return {"party": party.id, "limit": pl["new_limit"]}

    def on_event(self, run, event) -> None:
        p = event.payload or {}
        if event.type == "voucher.posted" and p.get("party_id"):
            run({"party_id": int(p["party_id"])}, f"payment {p.get('number')}")
        elif event.type in ("promise.missed", "promise.kept", "promise.part_kept") and p.get("party_id"):
            run({"party_id": int(p["party_id"])}, event.type)
