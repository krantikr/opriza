"""What people do in the app, as one service layer.

Every change a person makes goes through here and ends the same way an
agent's change does: rows written, an event published, and the agents that
care given the event straight away (`jobs.dispatch_events`), so the screen
the person is looking at already shows what the agents did about it.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.kb import clock, events, jobs, links, runtime
from app.kb.agents import AGENTS
from app.kb.models import (
    KbApproval,
    KbChatMessage,
    KbEnquiry,
    KbItem,
    KbParty,
    KbPromise,
    KbQuote,
    KbQuoteLine,
    KbShareLink,
    KbSupplierQuote,
    KbTask,
)
from app.kb.sources.base import TallyBatch, TBillRef, TVoucher


class ActionError(ValueError):
    """Something the person asked for that cannot be done (shown as a 400)."""


def _org(db: Session) -> int:
    return db.info["organisation_id"]


# ---------------------------------------------------------------- enquiries


def new_enquiry(db: Session, *, party_id: int | None, text: str, channel: str, user_id: int | None) -> dict:
    if not text.strip():
        raise ActionError("Paste the enquiry text.")
    if party_id is not None and db.get(KbParty, party_id) is None:
        raise ActionError("Unknown customer.")
    party = db.get(KbParty, party_id) if party_id else None
    enq = KbEnquiry(
        organisation_id=_org(db),
        party_id=party_id,
        channel=channel,
        raw_text=text.strip(),
        received_at=clock.now(db),
        status="new",
        assigned_to=user_id if party is None else (party.salesperson_id or user_id),
    )
    db.add(enq)
    db.flush()
    events.publish(
        db, "enquiry.received", "enquiry", enq.id, source="user", actor=str(user_id or ""), channel=channel
    )
    jobs.dispatch_events(db)
    quote = db.scalars(select(KbQuote).where(KbQuote.enquiry_id == enq.id)).first()
    approval = db.scalars(
        select(KbApproval).where(
            KbApproval.action_type == "send_quote",
            KbApproval.entity_type == "enquiry",
            KbApproval.entity_id == enq.id,
        )
    ).first()
    return {
        "enquiry_id": enq.id,
        "status": enq.status,
        "quote": quote.number if quote else None,
        "quote_id": quote.id if quote else None,
        "approval_id": approval.id if approval else None,
        "approval_reason": approval.reason if approval else None,
    }


# ------------------------------------------------------------------ quotes


def edit_quote(db: Session, quote_id: int, rates: dict[int, float], *, user_id: int | None) -> dict:
    """A salesperson changes rates on a draft; the Sales agent's gate decides if it can go."""
    q = db.get(KbQuote, quote_id)
    if q is None:
        raise ActionError("Quote not found.")
    if q.status not in ("draft", "pending_approval"):
        raise ActionError("Only a draft quote can be changed.")
    from app.kb.agents.sales import pricing

    subtotal = tax = margin_num = 0.0
    for ln in db.scalars(select(KbQuoteLine).where(KbQuoteLine.quote_id == q.id)):
        if ln.id in rates:
            if rates[ln.id] <= 0:
                raise ActionError("Rates must be positive.")
            ln.rate = round(float(rates[ln.id]), 2)
        item = db.get(KbItem, ln.item_id)
        cost = pricing(db, q.party_id, ln.item_id, clock.today(db))["cost"]
        ln.margin_pct = round((float(ln.rate) - cost) / float(ln.rate) * 100, 2)
        amt = float(ln.qty) * float(ln.rate)
        subtotal += amt
        tax += amt * float(item.gst_rate) / 100
        margin_num += amt - float(ln.qty) * cost
    q.subtotal, q.tax = round(subtotal, 2), round(tax, 2)
    q.total = round(subtotal + tax + float(q.freight), 2)
    q.margin_pct = round(margin_num / subtotal * 100, 2) if subtotal else 0
    q.status = "draft"
    for a in db.scalars(
        select(KbApproval).where(KbApproval.status == "waiting", KbApproval.action_type == "send_quote")
    ):
        if (a.payload or {}).get("quote_id") == q.id:
            a.status = "expired"
    db.flush()
    return submit_quote(db, quote_id, user_id=user_id)


def submit_quote(db: Session, quote_id: int, *, user_id: int | None) -> dict:
    q = db.get(KbQuote, quote_id)
    if q is None or q.status not in ("draft", "pending_approval"):
        raise ActionError("This quote has already gone out.")
    q.status = "pending_approval"
    out = runtime.run_case(
        db,
        "sales",
        {"quote_id": q.id, "review": True},
        trigger="manual",
        ref=f"review {q.number}",
        user_id=user_id,
    )
    jobs.dispatch_events(db)
    db.refresh(q)
    if q.status == "pending_approval" and not out["approvals"]:
        q.status = "sent" if q.sent_at else q.status
    return {"quote": q.number, "status": q.status, "approvals": out["approvals"]}


def mark_quote(db: Session, quote_id: int, outcome: str, reason: str | None, user_id: int | None) -> dict:
    q = db.get(KbQuote, quote_id)
    if q is None:
        raise ActionError("Quote not found.")
    if outcome not in ("won", "lost"):
        raise ActionError("Outcome is won or lost.")
    q.status = outcome
    q.decided_at = clock.now(db)
    q.lost_reason = reason if outcome == "lost" else None
    events.publish(
        db, f"quote.{outcome}", "quote", q.id, source="user", actor=str(user_id or ""), number=q.number
    )
    jobs.dispatch_events(db)
    return {"quote": q.number, "status": q.status}


# ------------------------------------------------------------- collections


def remind(db: Session, party_ids: list[int], user_id: int | None) -> dict:
    out = runtime.run_case(
        db, "collect", {"remind_parties": party_ids}, trigger="manual", ref="reminders", user_id=user_id
    )
    return {"results": out["results"]}


def statement(db: Session, party_id: int, user_id: int | None) -> dict:
    out = runtime.run_case(
        db, "collect", {"statement_for": party_id}, trigger="manual", ref="statement", user_id=user_id
    )
    return {"results": out["results"]}


def log_promise(
    db: Session, party_id: int, amount: float, due: date, source: str, user_id: int | None
) -> dict:
    if amount <= 0:
        raise ActionError("Amount must be positive.")
    if due < clock.today(db):
        raise ActionError("The promise date is in the past.")
    if db.get(KbParty, party_id) is None:
        raise ActionError("Unknown customer.")
    p = KbPromise(
        organisation_id=_org(db),
        party_id=party_id,
        amount=amount,
        made_on=clock.today(db),
        due_date=due,
        source=source,
        status="open",
    )
    db.add(p)
    db.flush()
    events.publish(
        db,
        "promise.made",
        "promise",
        p.id,
        source="user",
        actor=str(user_id or ""),
        party_id=party_id,
        amount=amount,
        due=due,
    )
    jobs.dispatch_events(db)
    return {"promise_id": p.id}


# ----------------------------------------------------------------- inbox


def update_task(db: Session, task_id: int, status: str) -> dict:
    t = db.get(KbTask, task_id)
    if t is None:
        raise ActionError("Task not found.")
    if status not in ("open", "done", "dismissed", "snoozed"):
        raise ActionError("Unknown status.")
    t.status = status
    t.done_at = clock.now(db) if status in ("done", "dismissed") else None
    db.flush()
    return {"id": t.id, "status": t.status}


def decide(
    db: Session,
    approval_id: int,
    approve: bool,
    user_id: int | None,
    note: str | None = None,
    payload: dict | None = None,
) -> dict:
    a = db.get(KbApproval, approval_id)
    if a is None:
        raise ActionError("Approval not found.")
    if a.status != "waiting":
        raise ActionError(f"Already {a.status}.")
    out = runtime.decide_approval(db, a, approve, user_id, payload=payload, note=note)
    jobs.dispatch_events(db)
    return {
        "id": a.id,
        "status": a.status,
        "resumed": bool(out.get("resumed")),
        "result": out.get("result"),
        "error": out.get("error"),
    }


# ------------------------------------------------------------------- chat


def chat_send(db: Session, thread: str, text: str, user_id: int | None) -> dict:
    if not text.strip():
        raise ActionError("Type a question.")
    now = clock.now(db)
    db.add(
        KbChatMessage(
            organisation_id=_org(db),
            thread=thread,
            sender="me",
            user_id=user_id,
            at=now,
            text=text.strip(),
            read=True,
        )
    )
    db.flush()
    out = runtime.run_case(
        db,
        "ask",
        {"question": text.strip(), "thread": thread},
        trigger="chat",
        ref=text.strip()[:100],
        user_id=user_id,
    )
    jobs.dispatch_events(db)
    return {"status": out["status"], "results": out["results"]}


def chat_action(db: Session, message_id: int, action_id: str, user_id: int | None, can_approve: bool) -> dict:
    m = db.get(KbChatMessage, message_id)
    if m is None:
        raise ActionError("Message not found.")
    ref = m.ref or {}
    label = next(
        (a["label"] for a in (m.actions or []) + (m.chips or []) if a.get("id") == action_id), action_id
    )
    if action_id in ("approve", "reject") and ref.get("approval_id"):
        if not can_approve:
            raise ActionError("Only the owner can approve this.")
        m.chosen = label
        out = decide(db, ref["approval_id"], action_id == "approve", user_id)
        return {"ok": True, **out}
    agent = AGENTS.get(m.thread)
    reply = agent.on_chat_action(db, m, {"id": action_id}, user_id) if agent else None
    if reply:
        m.chosen = label
        db.add(
            KbChatMessage(
                organisation_id=_org(db), thread=m.thread, sender="agent", at=clock.now(db), text=reply
            )
        )
    db.flush()
    return {"ok": True}


def mark_read(db: Session, thread: str) -> None:
    for m in db.scalars(
        select(KbChatMessage).where(KbChatMessage.thread == thread, KbChatMessage.read.is_(False))
    ):
        m.read = True
    db.flush()


# ------------------------------------------------------------------ links


def link_view(db: Session, link: KbShareLink) -> dict:
    """What the customer or supplier sees. `db` is bound to the link's desk."""
    from app.kb import fmt
    from app.kb.models import KbBill, KbCustomerProfile, KbPoLine, KbPurchaseOrder, KbRfq
    from app.models import Organisation

    now = clock.now(db)
    party = db.get(KbParty, link.party_id)
    org = db.get(Organisation, link.organisation_id)
    first_open = link.first_opened_at is None
    if first_open:
        link.first_opened_at = now
    base = {
        "purpose": link.purpose,
        "company": org.name if org else "",
        "party": party.name,
        "contact": (party.contact_name or "").split(" ")[0],
        "expired": link.expires_at < now,
        "responded": link.responded_at is not None,
        "response": link.response,
    }
    if link.purpose == "quote":
        q = db.get(KbQuote, link.entity_id)
        if q.opened_at is None:
            q.opened_at = now
            if q.status == "sent":
                q.status = "opened"
            events.publish(db, "quote.opened", "quote", q.id, source="link", number=q.number)
        lines = db.execute(
            select(KbQuoteLine, KbItem)
            .join(KbItem, KbItem.id == KbQuoteLine.item_id)
            .where(KbQuoteLine.quote_id == q.id)
        ).all()
        base |= {
            "quote": {
                "number": q.number,
                "status": q.status,
                "valid_until": q.valid_until,
                "total": float(q.total),
                "subtotal": float(q.subtotal),
                "tax": float(q.tax),
                "freight": float(q.freight),
                "lines": [
                    {"item": i.name, "qty": float(ln.qty), "unit": i.unit, "rate": float(ln.rate)}
                    for ln, i in lines
                ],
                "credit_days": party.credit_days,
            }
        }
    elif link.purpose in ("statement", "early_pay"):
        bills = db.scalars(
            select(KbBill)
            .where(KbBill.party_id == party.id, KbBill.direction == "receivable", KbBill.pending_amount > 1)
            .order_by(KbBill.due_date)
        ).all()
        prof = db.scalars(select(KbCustomerProfile).where(KbCustomerProfile.party_id == party.id)).first()
        base |= {
            "statement": {
                "total": round(sum(float(b.pending_amount) for b in bills), 2),
                "overdue": float(prof.overdue) if prof else 0.0,
                "bills": [
                    {
                        "ref": b.bill_ref,
                        "date": b.bill_date,
                        "due": b.due_date,
                        "amount": float(b.pending_amount),
                        "days_late": max(0, (clock.today(db) - b.due_date).days),
                    }
                    for b in bills
                ],
                "dates": [clock.today(db) + timedelta(days=d) for d in (1, 3, 5, 7, 10, 14)],
            }
        }
    elif link.purpose == "rfq":
        rfq = db.get(KbRfq, link.entity_id)
        item = db.get(KbItem, rfq.item_id)
        base |= {
            "rfq": {
                "item": item.name,
                "unit": item.unit,
                "qty": float(rfq.qty),
                "status": rfq.status,
                "city": clock.business(db).city,
            }
        }
    elif link.purpose == "offer":
        item = db.get(KbItem, link.entity_id)
        from app.kb.models import KbItemMetric

        m = db.scalars(select(KbItemMetric).where(KbItemMetric.item_id == item.id)).first()
        ap = db.scalars(
            select(KbApproval)
            .where(KbApproval.action_type == "send_offer", KbApproval.status == "approved")
            .order_by(KbApproval.id.desc())
        ).first()
        price = (ap.payload or {}).get("price") if ap else float(item.standard_rate)
        base |= {
            "offer": {
                "item": item.name,
                "unit": item.unit,
                "price": price,
                "list": float(item.standard_rate),
                "available": float(m.stock_qty) if m else None,
            }
        }
    elif link.purpose == "po":
        po = db.get(KbPurchaseOrder, link.entity_id)
        lines = db.execute(
            select(KbPoLine, KbItem)
            .join(KbItem, KbItem.id == KbPoLine.item_id)
            .where(KbPoLine.po_id == po.id)
        ).all()
        base |= {
            "po": {
                "number": po.number,
                "status": po.status,
                "total": float(po.total),
                "lines": [
                    {"item": i.name, "qty": float(ln.qty), "unit": i.unit, "rate": float(ln.rate)}
                    for ln, i in lines
                ],
            }
        }
    base["amount_words"] = fmt.inr(
        base.get("quote", {}).get("total") or base.get("statement", {}).get("total") or 0
    )
    db.flush()
    if first_open:
        jobs.dispatch_events(db)
    return base


def link_respond(db: Session, link: KbShareLink, body: dict) -> dict:
    now = clock.now(db)
    if link.expires_at < now:
        raise ActionError("This link has expired. Please ask us for a new one.")
    party = db.get(KbParty, link.party_id)
    action = body.get("action")
    result: dict = {}
    if link.purpose == "quote":
        q = db.get(KbQuote, link.entity_id)
        if q.status in ("won", "lost", "expired"):
            raise ActionError(f"This quote is already {q.status}.")
        if action == "accept":
            q.status, q.decided_at = "won", now
            events.publish(db, "quote.won", "quote", q.id, source="link", number=q.number)
        elif action == "decline":
            q.status, q.decided_at = "lost", now
            q.lost_reason = (body.get("reason") or "Declined on the link")[:200]
            events.publish(db, "quote.lost", "quote", q.id, source="link", number=q.number)
        elif action == "change":
            q.status = "negotiating"
            db.add(
                KbTask(
                    organisation_id=_org(db),
                    agent="sales",
                    kind="quote_change",
                    title=f"{party.name} wants a change to {q.number}",
                    detail=(body.get("note") or "")[:500],
                    entity_type="quote",
                    entity_id=q.id,
                    amount=float(q.total),
                    priority=1,
                    assignee_role="sales",
                    status="open",
                    created_at=now,
                )
            )
        else:
            raise ActionError("Unknown action.")
        result = {"status": q.status}
    elif link.purpose in ("statement", "early_pay"):
        if action != "promise":
            raise ActionError("Pick a date to pay.")
        due = date.fromisoformat(str(body.get("date")))
        if due < clock.today(db):
            raise ActionError("Pick a date from today on.")
        amount = float(body.get("amount") or 0)
        if amount <= 0:
            raise ActionError("Enter the amount you will pay.")
        p = KbPromise(
            organisation_id=_org(db),
            party_id=party.id,
            amount=amount,
            made_on=clock.today(db),
            due_date=due,
            source="link",
            status="open",
        )
        db.add(p)
        db.flush()
        events.publish(
            db,
            "early_pay.promised" if link.purpose == "early_pay" else "promise.made",
            "promise",
            p.id,
            source="link",
            party_id=party.id,
            amount=amount,
            due=due,
        )
        if link.purpose == "early_pay":
            events.publish(
                db, "promise.made", "promise", p.id, source="link", party_id=party.id, amount=amount, due=due
            )
        result = {"promise_id": p.id, "due": due, "amount": amount}
    elif link.purpose == "rfq":
        rate = float(body.get("rate") or 0)
        days = int(body.get("days") or 3)
        if rate <= 0:
            raise ActionError("Enter your rate.")
        from app.kb.models import KbRfq

        rfq = db.get(KbRfq, link.entity_id)
        sq = KbSupplierQuote(
            organisation_id=_org(db),
            rfq_id=rfq.id,
            supplier_id=party.id,
            item_id=rfq.item_id,
            rate=rate,
            delivery_days=days,
            received_at=now,
            valid_until=clock.today(db) + timedelta(days=2),
        )
        db.add(sq)
        db.flush()
        events.publish(
            db,
            "supplier_quote.received",
            "supplier_quote",
            sq.id,
            source="link",
            supplier_id=party.id,
            item_id=rfq.item_id,
            rate=rate,
        )
        result = {"rate": rate}
    elif link.purpose == "offer":
        qty = float(body.get("qty") or 0)
        if qty <= 0:
            raise ActionError("How much would you like?")
        item = db.get(KbItem, link.entity_id)
        db.add(
            KbTask(
                organisation_id=_org(db),
                agent="stock",
                kind="offer_accepted",
                title=f"{party.name} wants {qty:g} {item.unit} of {item.name}",
                detail="Reserved from the offer link.",
                entity_type="item",
                entity_id=item.id,
                priority=1,
                assignee_role="sales",
                status="open",
                created_at=now,
            )
        )
        events.publish(db, "offer.accepted", "item", item.id, source="link", party_id=party.id, qty=qty)
        result = {"qty": qty}
    elif link.purpose == "po":
        result = {"confirmed": True}
    else:
        raise ActionError("Unknown link.")
    link.responded_at = now
    link.response = {
        "action": action,
        **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in result.items()},
    }
    db.flush()
    jobs.dispatch_events(db)
    return result


# --------------------------------------------------------- mock desk tools


def simulate(db: Session, kind: str, body: dict) -> dict:
    """For desks on mock data: pretend Tally or a customer did something.

    Uses the same paths a live desk does: a receipt arrives as a Tally batch
    through `sync.apply_batch`, an enquiry as a new enquiry, a supplier rate
    through the RFQ link. Refused on a live desk.
    """
    from app.kb import facts, sync

    biz = clock.business(db)
    if biz.source != "mock":
        raise ActionError("Simulation is only for desks on mock data.")
    if kind == "receipt":
        party = db.get(KbParty, int(body["party_id"]))
        from app.kb.models import KbBill

        bills = db.scalars(
            select(KbBill)
            .where(KbBill.party_id == party.id, KbBill.direction == "receivable", KbBill.pending_amount > 1)
            .order_by(KbBill.due_date)
        ).all()
        amount = float(body.get("amount") or sum(float(b.pending_amount) for b in bills[:1]))
        if amount <= 0 or not bills:
            raise ActionError("Nothing to receive from this customer.")
        left, refs = amount, []
        for b in bills:
            if left <= 0:
                break
            take = min(left, float(b.pending_amount))
            refs.append(TBillRef(ref=b.bill_ref, kind="agst", amount=round(take, 2)))
            left -= take
        biz.last_alter_id = (biz.last_alter_id or 0) + 1
        v = TVoucher(
            guid=f"sim-receipt-{biz.last_alter_id}",
            alter_id=biz.last_alter_id,
            vtype="receipt",
            number=f"SIM/R/{biz.last_alter_id}",
            date=clock.today(db),
            party_guid=party.tally_guid,
            amount=round(amount, 2),
            narration="Simulated receipt",
            bills=refs,
        )
        sync.apply_batch(db, TallyBatch(vouchers=[v], max_alter_id=biz.last_alter_id))
        biz.bank_balance = float(biz.bank_balance or 0) + amount
        facts.refresh(db)
        jobs.dispatch_events(db)
        return {"receipt": v.number, "amount": amount}
    if kind == "enquiry":
        return new_enquiry(
            db,
            party_id=int(body["party_id"]),
            text=body["text"],
            channel=body.get("channel", "email"),
            user_id=None,
        )
    if kind == "advance":
        hours = float(body.get("hours") or 24)
        clock.advance(db, hours)
        result = jobs.tick(db)
        return {"now": clock.now(db), **result}
    if kind == "supplier_rate":
        rfq_link = db.scalars(
            select(KbShareLink)
            .where(KbShareLink.purpose == "rfq", KbShareLink.responded_at.is_(None))
            .order_by(KbShareLink.id.desc())
        ).first()
        if rfq_link is None:
            raise ActionError("No open rate request.")
        return link_respond(db, rfq_link, {"rate": body.get("rate"), "days": body.get("days", 3)})
    raise ActionError("Unknown simulation.")


def link_for(db: Session, purpose: str, entity_type: str, entity_id: int) -> str:
    """A fresh customer link for an entity (used by "copy link" in the app)."""
    party_id = None
    if entity_type == "quote":
        party_id = db.get(KbQuote, entity_id).party_id
    elif entity_type == "party":
        party_id = entity_id
    if party_id is None:
        raise ActionError("Cannot make a link for that.")
    _, url = links.create(db, purpose, party_id, entity_type, entity_id)
    return url
