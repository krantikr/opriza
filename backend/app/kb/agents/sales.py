"""Sales & Quote: every enquiry priced and sent in minutes, then followed up.

An enquiry (email, pasted WhatsApp text, phone note, chat) is read by the
brain, matched to items through the customer's own words (aliases), priced
from the customer's last rate and today's market, and sent as a secure link.
Code, not the model, sets every rate and checks it against the owner's rules:
margin floor, discount off the last rate, and the customer's credit limit.
Daily it nudges unopened quotes, expires stale ones, and flags regulars who
have stopped ordering.
"""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import func, select

from app.kb import events, fmt
from app.kb.agents.base import Agent, send_message
from app.kb.brain import CatalogEntry
from app.kb.models import (
    KbCustomerProfile,
    KbEnquiry,
    KbItem,
    KbItemAlias,
    KbItemMetric,
    KbParty,
    KbPricePoint,
    KbQuote,
    KbQuoteLine,
    KbTallyPosting,
)
from app.kb.runtime import Ctx, Proposal, close_tasks, post, task

WIN_BACK_PER_DAY = 5


def next_quote_number(db) -> str:
    nums = [int(m.group(1)) for n in db.scalars(select(KbQuote.number)) if (m := re.search(r"(\d+)$", n))]
    return f"Q-{(max(nums) + 1) if nums else 1001}"


def pricing(db, party_id: int | None, item_id: int, today) -> dict:
    """Last rate for this customer, today's market, and our cost, from the facts."""

    def latest(source: str, party: int | None = None, since_days: int | None = None):
        q = select(KbPricePoint).where(KbPricePoint.item_id == item_id, KbPricePoint.source == source)
        if party is not None:
            q = q.where(KbPricePoint.party_id == party)
        if since_days is not None:
            q = q.where(KbPricePoint.date >= today - timedelta(days=since_days))
        return db.scalars(q.order_by(KbPricePoint.date.desc(), KbPricePoint.id.desc()).limit(1)).first()

    item = db.get(KbItem, item_id)
    last = latest("sale", party_id) if party_id else None
    market_rows = db.scalars(
        select(KbPricePoint.rate).where(
            KbPricePoint.item_id == item_id,
            KbPricePoint.source == "sale",
            KbPricePoint.date >= today - timedelta(days=14),
        )
    ).all()
    market = sum(float(r) for r in market_rows) / len(market_rows) if market_rows else None
    buy = latest("purchase")
    cost = float(buy.rate) if buy else float(item.standard_cost)
    return {
        "last_rate": float(last.rate) if last else None,
        "last_date": last.date if last else None,
        "market": round(market, 2) if market else None,
        "cost": cost,
        "list": float(item.standard_rate),
    }


class SalesAgent(Agent):
    name = "sales"
    label = "Sales & Quote"
    jobs = {"sales_daily": (10, 0)}

    # ------------------------------------------------------------------ jobs

    def run_job(self, db, job: str) -> list[dict]:
        new = db.scalars(
            select(KbEnquiry.id).where(KbEnquiry.status == "new").order_by(KbEnquiry.received_at)
        ).all()
        return [{"enquiry_id": e} for e in new] + [{"job": job}]

    # ---------------------------------------------------------------- gather

    def gather(self, ctx: Ctx, case: dict) -> dict:
        db = ctx.db
        if "enquiry_id" in case:
            enq = db.get(KbEnquiry, case["enquiry_id"])
            party = db.get(KbParty, enq.party_id) if enq.party_id else None
            aliases: dict[int, list[str]] = {}
            for a in db.scalars(select(KbItemAlias)):
                aliases.setdefault(a.item_id, []).append(a.alias)
            items = db.scalars(select(KbItem)).all()
            sites = sorted({a for a in db.scalars(select(KbParty.area).where(KbParty.area.is_not(None)))})
            prof = (
                db.scalars(
                    select(KbCustomerProfile).where(KbCustomerProfile.party_id == enq.party_id)
                ).first()
                if party
                else None
            )
            return {
                "enquiry": {
                    "id": enq.id,
                    "text": enq.raw_text,
                    "status": enq.status,
                    "channel": enq.channel,
                    "party_id": enq.party_id,
                },
                "party": {
                    "id": party.id,
                    "name": party.name,
                    "credit_limit": float(party.credit_limit) if party.credit_limit else None,
                }
                if party
                else None,
                "profile": {"grade": prof.grade, "outstanding": float(prof.outstanding)} if prof else None,
                "catalog": [
                    {
                        "item_id": i.id,
                        "name": i.name,
                        "unit": i.unit,
                        "aliases": aliases.get(i.id, []),
                        "gst": float(i.gst_rate),
                    }
                    for i in items
                ],
                "sites": sites,
            }
        if "quote_id" in case:
            q = db.get(KbQuote, case["quote_id"])
            party = db.get(KbParty, q.party_id)
            prof = db.scalars(
                select(KbCustomerProfile).where(KbCustomerProfile.party_id == q.party_id)
            ).first()
            lines = db.scalars(select(KbQuoteLine).where(KbQuoteLine.quote_id == q.id)).all()
            return {
                "quote": {
                    "id": q.id,
                    "number": q.number,
                    "total": float(q.total),
                    "margin": float(q.margin_pct),
                    "status": q.status,
                },
                "lines": [
                    {
                        "item_id": ln.item_id,
                        "rate": float(ln.rate),
                        "last_rate": float(ln.last_rate) if ln.last_rate else None,
                        "margin": float(ln.margin_pct),
                    }
                    for ln in lines
                ],
                "party": {
                    "id": party.id,
                    "name": party.name,
                    "credit_limit": float(party.credit_limit) if party.credit_limit else None,
                },
                "profile": {"grade": prof.grade, "outstanding": float(prof.outstanding)} if prof else None,
            }
        if case.get("job") == "sales_daily":
            hours = float(ctx.rule("nudge_after_hours"))
            cutoff = ctx.now - timedelta(hours=hours)
            cold = db.scalars(
                select(KbQuote).where(
                    KbQuote.status == "sent",
                    KbQuote.opened_at.is_(None),
                    KbQuote.nudged_at.is_(None),
                    KbQuote.sent_at <= cutoff,
                )
            ).all()
            stale = db.scalars(
                select(KbQuote).where(
                    KbQuote.status.in_(("sent", "opened", "negotiating")), KbQuote.valid_until < ctx.today
                )
            ).all()
            slipping = db.scalars(
                select(KbCustomerProfile)
                .where(KbCustomerProfile.trend == "down", KbCustomerProfile.last_order_on.is_not(None))
                .order_by(KbCustomerProfile.sales_12m.desc())
            ).all()
            return {
                "cold": [
                    {
                        "id": q.id,
                        "number": q.number,
                        "total": float(q.total),
                        "sent_at": q.sent_at,
                        "party_id": q.party_id,
                    }
                    for q in cold
                    if q.valid_until is None or q.valid_until >= ctx.today
                ],
                "stale": [q.id for q in stale],
                "slipping": [
                    {
                        "party_id": p.party_id,
                        "last": p.last_order_on,
                        "gap": p.avg_order_gap_days,
                        "sales_12m": float(p.sales_12m),
                        "sales_90d": float(p.sales_90d),
                    }
                    for p in slipping
                    if (ctx.today - p.last_order_on).days >= 21
                ][:WIN_BACK_PER_DAY],
            }
        if "quote_won" in case or "quote_opened" in case:
            return {}
        return {}

    # ---------------------------------------------------------------- decide

    def decide(self, ctx: Ctx, case: dict, data: dict) -> list[Proposal]:
        if "enquiry_id" in case:
            return self._price_enquiry(ctx, data)
        if "quote_id" in case:
            q = data["quote"]
            return [
                {
                    "kind": "send_quote",
                    "title": f"{q['number']} for {data['party']['name']}",
                    "amount": q["total"],
                    "entity_type": "quote",
                    "entity_id": q["id"],
                    "payload": {
                        "quote_id": q["id"],
                        "margin": q["margin"],
                        "max_discount": max((self._discount(ln) for ln in data["lines"]), default=0.0),
                        "total": q["total"],
                        "party_id": data["party"]["id"],
                        "credit_limit": data["party"]["credit_limit"],
                        "outstanding": (data["profile"] or {}).get("outstanding", 0.0),
                        "priced_by": "person",
                    },
                }
            ]
        if "quote_won" in case:
            return [{"kind": "record_win", "title": "Quote won", "payload": {"quote_id": case["quote_won"]}}]
        if "quote_opened" in case:
            return [
                {
                    "kind": "note_opened",
                    "title": "Quote opened",
                    "payload": {"quote_id": case["quote_opened"]},
                }
            ]
        if case.get("job") == "sales_daily":
            out: list[Proposal] = []
            if data["cold"]:
                out.append(
                    {
                        "kind": "send_nudges",
                        "title": f"Nudge {len(data['cold'])} unopened quotes",
                        "payload": {"quote_ids": [q["id"] for q in data["cold"]]},
                    }
                )
            if data["stale"]:
                out.append(
                    {
                        "kind": "expire_quotes",
                        "title": "Expire old quotes",
                        "payload": {"quote_ids": data["stale"]},
                    }
                )
            for s in data["slipping"]:
                out.append(
                    {
                        "kind": "win_back",
                        "title": "Win-back call",
                        "payload": s,
                        "entity_type": "party",
                        "entity_id": s["party_id"],
                    }
                )
            return out
        return []

    @staticmethod
    def _discount(line: dict) -> float:
        if not line.get("last_rate"):
            return 0.0
        return round((line["last_rate"] - line["rate"]) / line["last_rate"] * 100, 2)

    def _price_enquiry(self, ctx: Ctx, data: dict) -> list[Proposal]:
        enq = data["enquiry"]
        if enq["status"] != "new":
            return []
        if data["party"] is None:
            return [
                {
                    "kind": "needs_review",
                    "title": "Enquiry from an unknown sender",
                    "payload": {
                        "enquiry_id": enq["id"],
                        "why": "I couldn't match the sender to a customer in Tally.",
                    },
                }
            ]
        catalog = [
            CatalogEntry(item_id=c["item_id"], name=c["name"], unit=c["unit"], aliases=c["aliases"])
            for c in data["catalog"]
        ]
        parsed = ctx.brain.parse_enquiry(enq["text"], catalog, data["sites"])
        lines = [ln for ln in parsed.lines if ln.item_id]
        if not lines:
            return [
                {
                    "kind": "needs_review",
                    "title": "Enquiry I couldn't read",
                    "payload": {
                        "enquiry_id": enq["id"],
                        "why": "No item or quantity I could match to your stock list.",
                    },
                }
            ]
        floor = float(ctx.rule("margin_floor_pct"))
        gst = {c["item_id"]: c["gst"] for c in data["catalog"]}
        priced = []
        for ln in lines:
            p = pricing(ctx.db, data["party"]["id"], ln.item_id, ctx.today)
            recent_last = (
                p["last_rate"] if p["last_date"] and (ctx.today - p["last_date"]).days <= 45 else None
            )
            rate = recent_last or p["market"] or p["list"]
            # Follow the market when it has moved since their last purchase.
            if recent_last and p["market"] and abs(p["market"] - recent_last) / recent_last > 0.02:
                rate = round((recent_last + p["market"]) / 2, 2)
            minimum = round(p["cost"] / (1 - (floor + 0.5) / 100), 2)
            note = None
            if rate < minimum:
                rate, note = minimum, "raised to keep your margin floor"
            margin = round((rate - p["cost"]) / rate * 100, 2)
            priced.append(
                {
                    "item_id": ln.item_id,
                    "said_as": ln.said_as,
                    "qty": ln.qty,
                    "rate": round(rate, 2),
                    "last_rate": p["last_rate"],
                    "market": p["market"],
                    "cost": p["cost"],
                    "margin": margin,
                    "gst": gst.get(ln.item_id, 18.0),
                    "note": note,
                }
            )
        subtotal = sum(x["qty"] * x["rate"] for x in priced)
        tax = sum(x["qty"] * x["rate"] * x["gst"] / 100 for x in priced)
        freight = round(subtotal * 0.004, 2) if clock_trade(ctx) != "pharma" else 0.0
        total = round(subtotal + tax + freight, 2)
        margin = (
            round(sum(x["qty"] * (x["rate"] - x["cost"]) for x in priced) / subtotal * 100, 2)
            if subtotal
            else 0
        )
        return [
            {
                "kind": "send_quote",
                "title": f"Quote for {data['party']['name']}",
                "amount": total,
                "entity_type": "enquiry",
                "entity_id": enq["id"],
                "payload": {
                    "enquiry_id": enq["id"],
                    "party_id": data["party"]["id"],
                    "lines": priced,
                    "subtotal": round(subtotal, 2),
                    "tax": round(tax, 2),
                    "freight": freight,
                    "total": total,
                    "margin": margin,
                    "max_discount": max((self._discount(x) for x in priced), default=0.0),
                    "credit_limit": data["party"]["credit_limit"],
                    "outstanding": (data["profile"] or {}).get("outstanding", 0.0),
                    "site": parsed.site,
                    "needed_by": parsed.needed_by,
                    "notes": parsed.notes,
                    "priced_by": "agent",
                },
            }
        ]

    # ------------------------------------------------------------------ gate

    def needs_approval(self, ctx: Ctx, p: Proposal) -> str | None:
        if p["kind"] != "send_quote":
            return None
        pl = p["payload"]
        floor = float(ctx.rule("margin_floor_pct"))
        if pl["margin"] < floor:
            return f"Margin {pl['margin']:.1f}% is below your {floor:.1f}% floor"
        max_disc = float(ctx.rule("max_discount_pct"))
        if pl.get("max_discount", 0) > max_disc:
            return (
                f"{pl['max_discount']:.1f}% below this customer's last rate (your limit is {max_disc:.1f}%)"
            )
        limit = pl.get("credit_limit")
        if ctx.rule("check_credit_limit") and limit and pl.get("outstanding", 0) + pl["total"] > limit:
            return (
                f"Would take {fmt.inr(pl.get('outstanding', 0) + pl['total'])} on credit against a "
                f"{fmt.inr(limit)} limit"
            )
        if not ctx.rule("auto_send_in_band"):
            return "You asked to approve every quote before it goes out"
        return None

    def on_approval_requested(self, ctx: Ctx, p: Proposal, approval) -> None:
        pl = p.get("payload") or {}
        if pl.get("enquiry_id"):
            enq = ctx.db.get(KbEnquiry, pl["enquiry_id"])
            if enq is not None:
                enq.status = "waiting"  # priced; the quote waits for the owner
        elif pl.get("quote_id"):
            q = ctx.db.get(KbQuote, pl["quote_id"])
            if q is not None:
                q.status = "pending_approval"
        super().on_approval_requested(ctx, p, approval)

    def on_rejected(self, ctx: Ctx, p: Proposal, approval) -> None:
        pl = p.get("payload") or {}
        if pl.get("quote_id"):
            q = ctx.db.get(KbQuote, pl["quote_id"])
            if q:
                q.status = "draft"
                task(
                    ctx,
                    kind="review_quote",
                    title=f"Re-price {q.number}",
                    role="sales",
                    detail="You turned it down at this price. Change the rate and send again.",
                    entity_type="quote",
                    entity_id=q.id,
                    amount=float(q.total),
                    dedupe=f"reprice:{q.id}",
                )
        elif pl.get("enquiry_id"):
            enq = ctx.db.get(KbEnquiry, pl["enquiry_id"])
            if enq:
                enq.status = "needs_review"
                task(
                    ctx,
                    kind="review_enquiry",
                    title="Price this enquiry yourself",
                    role="sales",
                    detail=enq.raw_text[:200],
                    entity_type="enquiry",
                    entity_id=enq.id,
                    dedupe=f"enq:{enq.id}",
                )
        post(ctx, text=f"Okay, I held back: {p['title']}. It's in the sales team's Inbox to re-price.")

    # ------------------------------------------------------------------- act

    def do_send_quote(self, ctx: Ctx, pl: dict) -> dict:
        db = ctx.db
        if pl.get("quote_id"):
            q = db.get(KbQuote, pl["quote_id"])
        else:
            enq = db.get(KbEnquiry, pl["enquiry_id"])
            party = db.get(KbParty, pl["party_id"])
            q = KbQuote(
                organisation_id=ctx.org,
                number=next_quote_number(db),
                party_id=party.id,
                enquiry_id=enq.id,
                status="draft",
                created_at=ctx.now,
                valid_until=ctx.today + timedelta(days=3),
                subtotal=pl["subtotal"],
                freight=pl["freight"],
                tax=pl["tax"],
                total=pl["total"],
                margin_pct=pl["margin"],
                owner_id=enq.assigned_to or party.salesperson_id,
            )
            db.add(q)
            db.flush()
            for ln in pl["lines"]:
                db.add(
                    KbQuoteLine(
                        organisation_id=ctx.org,
                        quote_id=q.id,
                        item_id=ln["item_id"],
                        qty=ln["qty"],
                        rate=ln["rate"],
                        last_rate=ln["last_rate"],
                        margin_pct=ln["margin"],
                    )
                )
                self._learn_alias(ctx, ln)
            enq.status = "quoted"
            events.publish(
                db,
                "quote.created",
                "quote",
                q.id,
                source="agent",
                actor=self.name,
                number=q.number,
                total=float(q.total),
            )
        party = db.get(KbParty, q.party_id)
        lines = db.scalars(select(KbQuoteLine).where(KbQuoteLine.quote_id == q.id)).all()
        items = {
            i.id: i for i in db.scalars(select(KbItem).where(KbItem.id.in_([ln.item_id for ln in lines])))
        }
        summary = ", ".join(
            f"{fmt.qty(float(ln.qty), items[ln.item_id].unit)} {items[ln.item_id].name}" for ln in lines
        )
        send_message(
            ctx,
            party,
            "quote",
            {
                "quote_no": q.number,
                "items": summary,
                "total": fmt.inr(q.total, short=False),
                "valid": fmt.day(q.valid_until),
            },
            entity_type="quote",
            entity_id=q.id,
            link_purpose="quote",
        )
        q.status = "sent"
        q.sent_at = ctx.now
        events.publish(db, "quote.sent", "quote", q.id, source="agent", actor=self.name, number=q.number)
        close_tasks(ctx, entity_type="quote", entity_id=q.id)
        prof = db.scalars(select(KbCustomerProfile).where(KbCustomerProfile.party_id == party.id)).first()
        post(
            ctx,
            text=f"Quoted **{party.name}** within minutes of their enquiry."
            if pl.get("enquiry_id")
            else None,
            card={
                "kind": "quote",
                "no": q.number,
                "customer": party.name,
                "grade": prof.grade if prof else "B",
                "lines": [
                    {
                        "name": items[ln.item_id].name,
                        "qty": float(ln.qty),
                        "unit": items[ln.item_id].unit,
                        "rate": float(ln.rate),
                    }
                    for ln in lines
                ],
                "freight": float(q.freight),
                "margin": float(q.margin_pct),
                "inBand": True,
                "status": "sent",
                "lastRate": float(lines[0].last_rate) if lines and lines[0].last_rate else None,
                "terms": f"Valid till {fmt.day(q.valid_until)} · {party.credit_days} days credit",
            },
            actions=[{"id": "view-quote", "label": "Open quote", "data": {"quote_id": q.id}}],
            ref={"quote_id": q.id},
        )
        return {"quote": q.number, "total": float(q.total)}

    def _learn_alias(self, ctx: Ctx, ln: dict) -> None:
        said = (ln.get("said_as") or "").strip().lower()
        item = ctx.db.get(KbItem, ln["item_id"])
        if (
            not said
            or not item
            or said == item.name.lower()
            or len(said) > 60
            or re.search(r"\d+\s*(mt|bags?|box)", said)
        ):
            return
        row = ctx.db.scalars(select(KbItemAlias).where(KbItemAlias.alias == said)).first()
        if row is None:
            ctx.db.add(
                KbItemAlias(organisation_id=ctx.org, item_id=item.id, alias=said, source="learned", hits=1)
            )
        elif row.item_id == item.id:
            row.hits += 1

    def do_needs_review(self, ctx: Ctx, pl: dict) -> dict:
        enq = ctx.db.get(KbEnquiry, pl["enquiry_id"])
        enq.status = "needs_review"
        party = ctx.db.get(KbParty, enq.party_id) if enq.party_id else None
        task(
            ctx,
            kind="review_enquiry",
            title=f"Look at an enquiry from {party.name if party else 'a new sender'}",
            role="sales",
            detail=f"{pl['why']} “{enq.raw_text[:160]}”",
            entity_type="enquiry",
            entity_id=enq.id,
            priority=1,
            dedupe=f"enq:{enq.id}",
        )
        return {"review": enq.id}

    def do_send_nudges(self, ctx: Ctx, pl: dict) -> dict:
        n = 0
        rows = []
        for qid in pl.get("quote_ids", []):
            q = ctx.db.get(KbQuote, qid)
            if not q or q.status != "sent" or q.opened_at is not None:
                continue
            party = ctx.db.get(KbParty, q.party_id)
            send_message(
                ctx,
                party,
                "nudge",
                {
                    "quote_no": q.number,
                    "total": fmt.inr(q.total, short=False),
                    "valid": fmt.day(q.valid_until),
                },
                entity_type="quote",
                entity_id=q.id,
                link_purpose="quote",
            )
            q.nudged_at = ctx.now
            n += 1
            rows.append(
                {
                    "name": party.name,
                    "amount": float(q.total),
                    "tag": q.number,
                    "tone": "warn",
                    "hint": f"Sent {fmt.day(q.sent_at)}, not opened",
                }
            )
        if n:
            post(
                ctx,
                text=f"Nudged **{n} quotes** nobody has opened yet.",
                card={"kind": "queue", "total": sum(r["amount"] for r in rows), "count": n, "rows": rows[:6]},
            )
        return {"nudged": n}

    def do_expire_quotes(self, ctx: Ctx, pl: dict) -> dict:
        n = 0
        for qid in pl.get("quote_ids", []):
            q = ctx.db.get(KbQuote, qid)
            if q and q.status in ("sent", "opened", "negotiating"):
                q.status = "expired"
                q.decided_at = ctx.now
                events.publish(ctx.db, "quote.expired", "quote", q.id, source="agent", actor=self.name)
                n += 1
        return {"expired": n}

    def do_win_back(self, ctx: Ctx, pl: dict) -> dict:
        party = ctx.db.get(KbParty, pl["party_id"])
        gap = pl.get("gap")
        task(
            ctx,
            kind="win_back",
            title=f"{party.name} has stopped ordering",
            detail=f"Last order {fmt.day(pl['last'])}"
            + (f", usually every {gap:.0f} days" if gap else "")
            + f". Bought {fmt.inr(pl['sales_12m'])} in the last year.",
            entity_type="party",
            entity_id=party.id,
            amount=pl["sales_12m"],
            priority=2,
            role="sales",
            dedupe=f"winback:{party.id}",
            why=[f"No order since {fmt.day(pl['last'])}"],
        )
        post(
            ctx,
            card={
                "kind": "alert",
                "tone": "warn",
                "title": f"{party.name} has gone quiet",
                "body": f"No order since {fmt.day(pl['last'])}"
                + (f" (usually every {gap:.0f} days)" if gap else "")
                + ". Worth a call this week.",
            },
            actions=[{"id": "go-customer", "label": "Open customer", "data": {"party_id": party.id}}],
        )
        return {"win_back": party.id}

    def do_record_win(self, ctx: Ctx, pl: dict) -> dict:
        q = ctx.db.get(KbQuote, pl["quote_id"])
        party = ctx.db.get(KbParty, q.party_id)
        ctx.db.add(
            KbTallyPosting(
                organisation_id=ctx.org,
                kind="sales_order",
                entity_type="quote",
                entity_id=q.id,
                payload={"quote": q.number, "party": party.name, "total": float(q.total)},
                created_at=ctx.now,
            )
        )
        minutes = int((q.decided_at - q.created_at).total_seconds() // 60) if q.decided_at else 0
        post(
            ctx,
            card={
                "kind": "won",
                "customer": party.name,
                "amount": float(q.total),
                "quoteNo": q.number,
                "minutes": minutes,
                "posted": True,
            },
            text=f"**{party.name}** accepted {q.number}. The sales order is queued for Tally.",
        )
        return {"won": q.number}

    def do_note_opened(self, ctx: Ctx, pl: dict) -> dict:
        q = ctx.db.get(KbQuote, pl["quote_id"])
        party = ctx.db.get(KbParty, q.party_id)
        post(ctx, text=f"{party.name} just opened {q.number} ({fmt.inr(q.total)}). A good moment to call.")
        return {"opened": q.number}

    # ---------------------------------------------------------------- events

    def on_event(self, run, event) -> None:
        p = event.payload or {}
        if event.type == "enquiry.received":
            run({"enquiry_id": event.entity_id}, f"enquiry {event.entity_id}")
        elif event.type == "quote.won":
            run({"quote_won": event.entity_id}, f"quote {p.get('number')}")
        elif event.type == "quote.opened":
            run({"quote_opened": event.entity_id}, f"quote {p.get('number')}")


def clock_trade(ctx: Ctx) -> str:
    from app.kb import clock

    return clock.business(ctx.db).trade


def unquoted_count(db) -> int:
    return db.scalar(select(func.count()).select_from(KbEnquiry).where(KbEnquiry.status == "new")) or 0


def stock_of(db, item_id: int) -> float:
    m = db.scalars(select(KbItemMetric).where(KbItemMetric.item_id == item_id)).first()
    return float(m.stock_qty) if m else 0.0
