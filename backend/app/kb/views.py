"""Read models for the app's screens. Each returns plain dicts, ready as JSON.

Every number here comes from the knowledge base (facts or mirror); nothing is
computed differently for a screen than for an agent.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.kb import brain as brain_mod
from app.kb import channels, clock, fmt, rules
from app.kb.models import (
    KbAgentRun,
    KbApproval,
    KbBill,
    KbBusiness,
    KbCashWeek,
    KbChatMessage,
    KbCustomerProfile,
    KbEnquiry,
    KbEvent,
    KbItem,
    KbItemMetric,
    KbKpi,
    KbMember,
    KbMemory,
    KbMessage,
    KbParty,
    KbPoLine,
    KbPricePoint,
    KbPromise,
    KbPurchaseOrder,
    KbQuote,
    KbQuoteLine,
    KbRfq,
    KbShareLink,
    KbSupplierQuote,
    KbSyncRun,
    KbTallyPosting,
    KbTask,
    KbVoucher,
)
from app.kb.runtime import AGENT_LABELS
from app.models import Organisation, User

THREADS = ["ask", "brief", "sales", "collect", "stock", "cash", "score"]
THREAD_LOOK = {
    "ask": ("Ask Oprisa", "Questions about your business", "O", "#E8A33D", "#3A1A05"),
    "brief": ("Business Manager", "Your 8 am brief", "B", "#8A2420", "#FFFFFF"),
    "sales": ("Sales & Quote", "Enquiries, quotes, follow-ups", "S", "#1F6B4D", "#FFFFFF"),
    "collect": ("Collections", "Reminders, calls, promises", "C", "#6D1A17", "#FFFFFF"),
    "stock": ("Stock & Purchase", "Reorders, supplier rates, POs", "P", "#2F4F6F", "#FFFFFF"),
    "cash": ("Cash", "Next four weeks of money", "₹", "#5B4A1F", "#FFFFFF"),
    "score": ("Customer Score", "Who pays how", "G", "#4A3F6B", "#FFFFFF"),
}


def desk_role(db: Session, user: User) -> str:
    m = db.scalars(select(KbMember).where(KbMember.user_id == user.id)).first()
    if m:
        return m.desk_role
    return "owner" if user.can_administer else "sales"


def me(db: Session, user: User) -> dict:
    biz = db.scalars(select(KbBusiness)).first()
    org = db.get(Organisation, user.organisation_id) if user.organisation_id else None
    last_sync = db.scalars(select(KbSyncRun).order_by(KbSyncRun.id.desc())).first()
    team = [
        {"id": u.id, "name": u.name, "desk_role": m.desk_role}
        for m, u in db.execute(select(KbMember, User).join(User, User.id == KbMember.user_id)).all()
    ]
    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role.value,
            "desk_role": desk_role(db, user),
            "can_approve": bool(user.can_administer),
        },
        "organisation": {"id": org.id, "name": org.name, "slug": org.slug} if org else None,
        "business": None
        if biz is None
        else {
            "trade": biz.trade,
            "city": biz.city,
            "language": biz.language,
            "tally_version": biz.tally_version,
            "source": biz.source,
            "mock": biz.source == "mock",
            "as_of": biz.as_of,
            "now": clock.now(db),
            "last_sync_at": biz.last_sync_at,
            "last_sync_status": last_sync.status if last_sync else None,
            "last_sync_error": last_sync.error if last_sync else None,
            "bank_balance": float(biz.bank_balance or 0),
        },
        "brain": brain_mod.brain_mode(),
        "channel": channels.channel_mode(),
        "team": team,
    }


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------


def home(db: Session, role: str) -> dict:
    today = clock.today(db)
    weeks = db.scalars(select(KbCashWeek).order_by(KbCashWeek.week_start)).all()
    floor = float(rules.get(db, "cash", "min_balance"))
    short = next((w for w in weeks if float(w.closing_balance) < floor), None)
    open_q = db.execute(
        select(func.count(), func.coalesce(func.sum(KbQuote.total), 0)).where(
            KbQuote.status.in_(("sent", "opened", "negotiating"))
        )
    ).one()
    overdue = db.execute(
        select(
            func.coalesce(func.sum(KbCustomerProfile.overdue), 0),
            func.count().filter(KbCustomerProfile.overdue > 1),
        )
    ).one()
    receivable = db.scalar(select(func.coalesce(func.sum(KbCustomerProfile.outstanding), 0))) or 0
    idle = (
        db.scalar(
            select(func.coalesce(func.sum(KbItemMetric.stock_value), 0)).where(KbItemMetric.status == "idle")
        )
        or 0
    )
    stock_value = db.scalar(select(func.coalesce(func.sum(KbItemMetric.stock_value), 0))) or 0
    promised = (
        db.scalar(
            select(func.coalesce(func.sum(KbPromise.amount), 0)).where(
                KbPromise.status == "open", KbPromise.due_date <= today + timedelta(days=7)
            )
        )
        or 0
    )
    sales = _series(db, "sales", today, 30)
    collections = _series(db, "collections", today, 30)
    s7 = sum(v for _, v in sales[-7:])
    p7 = sum(v for _, v in sales[-14:-7])
    mtd = (
        db.scalar(
            select(func.coalesce(func.sum(KbVoucher.amount - KbVoucher.tax_amount), 0)).where(
                KbVoucher.voucher_type == "sales", KbVoucher.date >= today.replace(day=1)
            )
        )
        or 0
    )
    sales_12m = db.scalar(select(func.coalesce(func.sum(KbCustomerProfile.sales_12m), 0))) or 0
    dso = round(float(receivable) / (float(sales_12m) * 1.18 / 365), 1) if sales_12m else None
    payables7 = (
        db.scalar(
            select(func.coalesce(func.sum(KbBill.pending_amount), 0)).where(
                KbBill.direction == "payable",
                KbBill.pending_amount > 1,
                KbBill.due_date < today + timedelta(days=7),
            )
        )
        or 0
    )
    brief = db.scalars(
        select(KbChatMessage).where(KbChatMessage.thread == "brief").order_by(KbChatMessage.id.desc())
    ).first()
    return {
        "today": today,
        "now": clock.now(db),
        "money_waiting": {
            "open_quotes": float(open_q[1]),
            "open_quote_count": int(open_q[0]),
            "overdue": float(overdue[0]),
            "overdue_customers": int(overdue[1]),
            "idle_stock": float(idle),
            "promised_this_week": float(promised),
        },
        "kpis": {
            "sales_7d": s7,
            "sales_7d_change": round((s7 - p7) / p7 * 100, 1) if p7 else None,
            "sales_mtd": float(mtd),
            "receivable": float(receivable),
            "dso": dso,
            "stock_value": float(stock_value),
            "payables_7d": float(payables7),
            "bank": float(weeks[0].opening_balance) if weeks else None,
        },
        "cash": {
            "weeks": [_week(w) for w in weeks],
            "short": _week(short) if short else None,
            "floor": floor,
        },
        "sales_series": [{"day": d, "value": v} for d, v in sales],
        "collections_series": [{"day": d, "value": v} for d, v in collections],
        "inbox": inbox(db, role, limit=8),
        "brief": _chat(brief) if brief else None,
        "approvals_waiting": db.scalar(
            select(func.count()).select_from(KbApproval).where(KbApproval.status == "waiting")
        ),
        "agents": agent_activity(db),
    }


def _series(db, metric, today, days) -> list[tuple]:
    rows = dict(
        db.execute(
            select(KbKpi.day, KbKpi.value).where(
                KbKpi.metric == metric, KbKpi.day >= today - timedelta(days=days)
            )
        ).all()
    )
    return [
        (today - timedelta(days=k), float(rows.get(today - timedelta(days=k), 0))) for k in range(days, 0, -1)
    ]


def _week(w: KbCashWeek) -> dict:
    return {
        "week_start": w.week_start,
        "opening": float(w.opening_balance),
        "inflow": float(w.inflow),
        "outflow": float(w.outflow),
        "closing": float(w.closing_balance),
        "in_top": (w.detail or {}).get("in", []),
        "out_top": (w.detail or {}).get("out", []),
    }


def agent_activity(db: Session) -> list[dict]:
    out = []
    today_start = clock.at(clock.today(db), 0)
    for agent in ("brief", "sales", "collect", "stock", "cash", "score", "ask"):
        last = db.scalars(
            select(KbAgentRun).where(KbAgentRun.agent == agent).order_by(KbAgentRun.id.desc())
        ).first()
        runs_today = (
            db.scalar(
                select(func.count())
                .select_from(KbAgentRun)
                .where(KbAgentRun.agent == agent, KbAgentRun.started_at >= today_start)
            )
            or 0
        )
        sent = (
            db.scalar(
                select(func.count())
                .select_from(KbMessage)
                .where(KbMessage.agent == agent, KbMessage.created_at >= today_start)
            )
            or 0
        )
        tasks = (
            db.scalar(
                select(func.count()).select_from(KbTask).where(KbTask.agent == agent, KbTask.status == "open")
            )
            or 0
        )
        waiting = (
            db.scalar(
                select(func.count())
                .select_from(KbApproval)
                .where(KbApproval.agent == agent, KbApproval.status == "waiting")
            )
            or 0
        )
        out.append(
            {
                "agent": agent,
                "label": AGENT_LABELS[agent],
                "last_run_at": last.started_at if last else None,
                "last_status": last.status if last else None,
                "runs_today": runs_today,
                "messages_today": sent,
                "open_tasks": tasks,
                "waiting": waiting,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Inbox and approvals
# ---------------------------------------------------------------------------


def inbox(db: Session, role: str | None, *, status: str = "open", limit: int = 200) -> list[dict]:
    q = select(KbTask).where(KbTask.status == status)
    if role and role != "owner":
        q = q.where(KbTask.assignee_role == role)
    rows = db.scalars(
        q.order_by(KbTask.priority, KbTask.amount.desc().nulls_last(), KbTask.id).limit(limit)
    ).all()
    return [
        {
            "id": t.id,
            "agent": t.agent,
            "kind": t.kind,
            "title": t.title,
            "detail": t.detail,
            "entity_type": t.entity_type,
            "entity_id": t.entity_id,
            "amount": float(t.amount) if t.amount else None,
            "priority": t.priority,
            "role": t.assignee_role,
            "status": t.status,
            "created_at": t.created_at,
            "why": t.why or [],
        }
        for t in rows
    ]


def approvals(db: Session, status: str = "waiting") -> list[dict]:
    q = select(KbApproval)
    if status != "all":
        q = q.where(KbApproval.status == status)
    rows = db.scalars(q.order_by(KbApproval.requested_at.desc(), KbApproval.id.desc()).limit(100)).all()
    users = {u.id: u.name for u in db.scalars(select(User))}
    return [
        {
            "id": a.id,
            "agent": a.agent,
            "agent_label": AGENT_LABELS.get(a.agent, a.agent),
            "action": a.action_type,
            "title": a.title,
            "reason": a.reason,
            "amount": float(a.amount) if a.amount is not None else None,
            "status": a.status,
            "requested_at": a.requested_at,
            "requested_by": users.get(a.requested_by),
            "decided_at": a.decided_at,
            "decided_by": users.get(a.decided_by),
            "note": a.decision_note,
            "details": approval_details(db, a),
            "payload": a.payload,
        }
        for a in rows
    ]


def approval_details(db: Session, a: KbApproval) -> dict:
    """What exactly will happen on Approve, in words and rows."""
    p = a.payload or {}
    if a.action_type == "send_quote":
        if p.get("quote_id"):
            q = db.get(KbQuote, p["quote_id"])
            lines = db.execute(
                select(KbQuoteLine, KbItem)
                .join(KbItem, KbItem.id == KbQuoteLine.item_id)
                .where(KbQuoteLine.quote_id == q.id)
            ).all()
            party = db.get(KbParty, q.party_id)
            rows = [
                [
                    i.name,
                    fmt.qty(float(ln.qty), i.unit),
                    fmt.rate(float(ln.rate)),
                    fmt.rate(float(ln.last_rate)) if ln.last_rate else "—",
                    f"{ln.margin_pct:.1f}%",
                ]
                for ln, i in lines
            ]
            return {
                "party": party.name,
                "lines": rows,
                "cols": ["Item", "Qty", "Rate", "Last rate", "Margin"],
                "total": float(q.total),
                "margin": float(q.margin_pct),
                "quote": q.number,
            }
        party = db.get(KbParty, p["party_id"])
        items = {i.id: i for i in db.scalars(select(KbItem))}
        rows = [
            [
                items[ln["item_id"]].name,
                fmt.qty(ln["qty"], items[ln["item_id"]].unit),
                fmt.rate(ln["rate"]),
                fmt.rate(ln["last_rate"]) if ln.get("last_rate") else "—",
                f"{ln['margin']:.1f}%",
            ]
            for ln in p["lines"]
        ]
        return {
            "party": party.name,
            "lines": rows,
            "cols": ["Item", "Qty", "Rate", "Last rate", "Margin"],
            "total": p["total"],
            "margin": p["margin"],
        }
    if a.action_type == "place_po":
        item = db.get(KbItem, p["item_id"])
        names = {s.id: s.name for s in db.scalars(select(KbParty).where(KbParty.kind == "supplier"))}
        rows = [
            [
                names.get(q["supplier_id"], "?"),
                fmt.rate(q["rate"]),
                f"{q['days']} days",
                "Best" if q["supplier_id"] == p["supplier_id"] else "",
            ]
            for q in sorted(p.get("quotes", []), key=lambda x: x["rate"])
        ]
        return {
            "item": item.name,
            "supplier": names.get(p["supplier_id"]),
            "qty": fmt.qty(p["qty"], item.unit),
            "rate": p["rate"],
            "total": p["total"],
            "saving_pct": p.get("saving_pct"),
            "last_purchase_rate": p.get("last_purchase_rate"),
            "days_left": p.get("days_left"),
            "lines": rows,
            "cols": ["Supplier", "Rate", "Delivery", ""],
        }
    if a.action_type == "send_offer":
        item = db.get(KbItem, p["item_id"])
        buyers = [db.get(KbParty, pid).name for pid in p.get("to", []) if db.get(KbParty, pid)]
        return {
            "item": item.name,
            "price": p["price"],
            "list": p["list"],
            "cost": p.get("cost"),
            "qty": fmt.qty(p["qty"], item.unit),
            "value": p.get("value"),
            "buyers": buyers,
        }
    if a.action_type == "change_credit_limit":
        party = db.get(KbParty, p["party_id"])
        return {
            "party": party.name,
            "old_limit": p["old_limit"],
            "new_limit": p["new_limit"],
            "from": p["from"],
            "to": p["to"],
            "reasons": p.get("reasons", []),
        }
    if a.action_type == "ask_early_payment":
        rows = [[e["name"], fmt.inr(e["amount"]), "Ask to pay early"] for e in p.get("early", [])]
        if p.get("delay"):
            d = p["delay"]
            rows.append(
                [
                    d["name"],
                    fmt.inr(d["amount"]),
                    f"Pay {fmt.day(d['new_date'])} instead of {fmt.day(d['due'])}",
                ]
            )
        return {
            "week_start": p["week_start"],
            "shortfall": p["shortfall"],
            "lines": rows,
            "cols": ["Who", "Amount", "Ask"],
        }
    return {}


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


def sales(db: Session) -> dict:
    today = clock.today(db)
    parties = {p.id: p for p in db.scalars(select(KbParty))}
    enq = db.scalars(select(KbEnquiry).order_by(KbEnquiry.received_at.desc()).limit(60)).all()
    quotes = db.scalars(
        select(KbQuote)
        .where(KbQuote.created_at >= clock.at(today - timedelta(days=30), 0))
        .order_by(KbQuote.created_at.desc())
    ).all()
    month = [q for q in quotes if q.decided_at and q.status in ("won", "lost")]
    won = [q for q in month if q.status == "won"]
    return {
        "enquiries": [
            {
                "id": e.id,
                "party": parties[e.party_id].name if e.party_id else None,
                "party_id": e.party_id,
                "channel": e.channel,
                "text": e.raw_text,
                "received_at": e.received_at,
                "status": e.status,
                "quote": next(
                    (
                        {"id": q.id, "number": q.number, "status": q.status}
                        for q in quotes
                        if q.enquiry_id == e.id
                    ),
                    None,
                ),
            }
            for e in enq
        ],
        "quotes": [_quote_row(q, parties) for q in quotes],
        "stats": {
            "open_value": sum(
                float(q.total) for q in quotes if q.status in ("sent", "opened", "negotiating")
            ),
            "win_rate": round(len(won) / len(month) * 100) if month else None,
            "won_value": sum(float(q.total) for q in won),
            "quotes_30d": len(quotes),
            "avg_minutes_to_quote": _avg_minutes(db, quotes),
        },
    }


def _avg_minutes(db, quotes) -> int | None:
    mins = []
    for q in quotes:
        if q.enquiry_id and q.sent_at:
            e = db.get(KbEnquiry, q.enquiry_id)
            if e:
                mins.append((q.sent_at - e.received_at).total_seconds() / 60)
    return round(sum(mins) / len(mins)) if mins else None


def _quote_row(q: KbQuote, parties) -> dict:
    return {
        "id": q.id,
        "number": q.number,
        "party": parties[q.party_id].name,
        "party_id": q.party_id,
        "status": q.status,
        "total": float(q.total),
        "margin": float(q.margin_pct),
        "created_at": q.created_at,
        "sent_at": q.sent_at,
        "opened_at": q.opened_at,
        "decided_at": q.decided_at,
        "valid_until": q.valid_until,
        "nudged_at": q.nudged_at,
    }


def quote(db: Session, quote_id: int) -> dict | None:
    q = db.get(KbQuote, quote_id)
    if q is None:
        return None
    party = db.get(KbParty, q.party_id)
    lines = db.execute(
        select(KbQuoteLine, KbItem)
        .join(KbItem, KbItem.id == KbQuoteLine.item_id)
        .where(KbQuoteLine.quote_id == q.id)
    ).all()
    enq = db.get(KbEnquiry, q.enquiry_id) if q.enquiry_id else None
    msgs = db.scalars(
        select(KbMessage)
        .where(KbMessage.entity_type == "quote", KbMessage.entity_id == q.id)
        .order_by(KbMessage.created_at)
    ).all()
    evs = db.scalars(
        select(KbEvent)
        .where(KbEvent.entity_type == "quote", KbEvent.entity_id == q.id)
        .order_by(KbEvent.occurred_at)
    ).all()
    return {
        **_quote_row(q, {party.id: party}),
        "freight": float(q.freight),
        "tax": float(q.tax),
        "subtotal": float(q.subtotal),
        "lost_reason": q.lost_reason,
        "lines": [
            {
                "id": ln.id,
                "item_id": i.id,
                "item": i.name,
                "unit": i.unit,
                "qty": float(ln.qty),
                "rate": float(ln.rate),
                "last_rate": float(ln.last_rate) if ln.last_rate else None,
                "margin": float(ln.margin_pct),
            }
            for ln, i in lines
        ],
        "enquiry": {
            "text": enq.raw_text,
            "channel": enq.channel,
            "received_at": enq.received_at,
            "parsed": enq.parsed,
        }
        if enq
        else None,
        "messages": [_message(m) for m in msgs],
        "timeline": [{"at": e.occurred_at, "type": e.type, "source": e.source} for e in evs],
    }


def _message(m: KbMessage) -> dict:
    return {
        "id": m.id,
        "agent": m.agent,
        "purpose": m.purpose,
        "channel": m.channel,
        "to": m.to_address,
        "body": m.body,
        "status": m.status,
        "created_at": m.created_at,
        "error": m.error,
    }


# ---------------------------------------------------------------------------
# Collections and customers
# ---------------------------------------------------------------------------

BUCKETS = [
    ("current", "Not due", -10_000, 0),
    ("1-30", "1–30 days", 1, 30),
    ("31-60", "31–60 days", 31, 60),
    ("60+", "60+ days", 61, 10_000),
]


def collections(db: Session) -> dict:
    today = clock.today(db)
    parties = {p.id: p for p in db.scalars(select(KbParty).where(KbParty.kind == "customer"))}
    profiles = {p.party_id: p for p in db.scalars(select(KbCustomerProfile))}
    bills = db.scalars(
        select(KbBill).where(KbBill.direction == "receivable", KbBill.pending_amount > 1)
    ).all()
    buckets = {k: {"key": k, "label": label, "amount": 0.0, "count": 0} for k, label, _, _ in BUCKETS}
    per_party = defaultdict(
        lambda: {"amount": 0.0, "overdue": 0.0, "bills": 0, "oldest": 0, "bucket": "current"}
    )
    for b in bills:
        late = (today - b.due_date).days
        key = next(k for k, _, lo, hi in BUCKETS if lo <= late <= hi)
        buckets[key]["amount"] += float(b.pending_amount)
        buckets[key]["count"] += 1
        pp = per_party[b.party_id]
        pp["amount"] += float(b.pending_amount)
        pp["bills"] += 1
        if late > 0:
            pp["overdue"] += float(b.pending_amount)
            if late > pp["oldest"]:
                pp["oldest"], pp["bucket"] = late, key
    last_msg = dict(
        db.execute(
            select(KbMessage.party_id, func.max(KbMessage.created_at))
            .where(KbMessage.agent == "collect")
            .group_by(KbMessage.party_id)
        ).all()
    )
    promises = db.execute(
        select(KbPromise, KbParty)
        .join(KbParty, KbParty.id == KbPromise.party_id)
        .order_by(KbPromise.due_date.desc())
        .limit(80)
    ).all()
    dues = []
    for pid, pp in per_party.items():
        if pid not in parties:
            continue
        prof = profiles.get(pid)
        dues.append(
            {
                "party_id": pid,
                "name": parties[pid].name,
                "area": parties[pid].area,
                "grade": prof.grade if prof else None,
                "amount": round(pp["amount"], 2),
                "overdue": round(pp["overdue"], 2),
                "bills": pp["bills"],
                "oldest": pp["oldest"],
                "bucket": pp["bucket"],
                "pay_day": prof.usual_pay_day if prof else None,
                "last_message_at": last_msg.get(pid),
                "phone": parties[pid].phone,
            }
        )
    dues.sort(key=lambda d: -d["overdue"])
    return {
        "buckets": list(buckets.values()),
        "dues": dues,
        "promises": [
            {
                "id": pr.id,
                "party_id": p.id,
                "party": p.name,
                "amount": float(pr.amount),
                "made_on": pr.made_on,
                "due_date": pr.due_date,
                "status": pr.status,
                "source": pr.source,
                "settled": float(pr.settled_amount),
            }
            for pr, p in promises
        ],
        "calls": [t for t in inbox(db, None, limit=300) if t["kind"] in ("call_customer", "missed_promise")],
    }


def customers(db: Session, q: str | None = None, grade: str | None = None) -> list[dict]:
    stmt = select(KbCustomerProfile, KbParty).join(KbParty, KbParty.id == KbCustomerProfile.party_id)
    if q:
        stmt = stmt.where(KbParty.name.ilike(f"%{q}%"))
    if grade:
        stmt = stmt.where(KbCustomerProfile.grade == grade.upper())
    rows = db.execute(stmt.order_by(KbCustomerProfile.sales_12m.desc()).limit(500)).all()
    return [
        {
            "party_id": p.id,
            "name": p.name,
            "area": p.area,
            "contact": p.contact_name,
            "phone": p.phone,
            "grade": pr.grade,
            "previous_grade": pr.previous_grade,
            "outstanding": float(pr.outstanding),
            "overdue": float(pr.overdue),
            "sales_12m": float(pr.sales_12m),
            "trend": pr.trend,
            "last_order_on": pr.last_order_on,
            "credit_limit": float(p.credit_limit) if p.credit_limit else None,
            "avg_days_late": float(pr.avg_days_late),
        }
        for pr, p in rows
    ]


def customer(db: Session, party_id: int) -> dict | None:
    p = db.get(KbParty, party_id)
    if p is None:
        return None
    pr = db.scalars(select(KbCustomerProfile).where(KbCustomerProfile.party_id == party_id)).first()
    bills = db.scalars(
        select(KbBill).where(KbBill.party_id == party_id, KbBill.pending_amount > 1).order_by(KbBill.due_date)
    ).all()
    sales_v = db.scalars(
        select(KbVoucher)
        .where(KbVoucher.party_id == party_id, KbVoucher.voucher_type.in_(("sales", "receipt")))
        .order_by(KbVoucher.date.desc())
        .limit(20)
    ).all()
    quotes_ = db.scalars(
        select(KbQuote).where(KbQuote.party_id == party_id).order_by(KbQuote.created_at.desc()).limit(10)
    ).all()
    promises = db.scalars(
        select(KbPromise).where(KbPromise.party_id == party_id).order_by(KbPromise.due_date.desc()).limit(10)
    ).all()
    msgs = db.scalars(
        select(KbMessage)
        .where(KbMessage.party_id == party_id)
        .order_by(KbMessage.created_at.desc())
        .limit(10)
    ).all()
    mems = db.scalars(
        select(KbMemory)
        .where(KbMemory.scope_type == "party", KbMemory.scope_id == party_id)
        .order_by(KbMemory.valid_from.desc())
    ).all()
    today = clock.today(db)
    return {
        "party": {
            "id": p.id,
            "name": p.name,
            "kind": p.kind,
            "contact": p.contact_name,
            "phone": p.phone,
            "email": p.email,
            "gstin": p.gstin,
            "city": p.city,
            "area": p.area,
            "credit_days": p.credit_days,
            "credit_limit": float(p.credit_limit) if p.credit_limit else None,
            "since": p.since,
        },
        "profile": None
        if pr is None
        else {
            "grade": pr.grade,
            "previous_grade": pr.previous_grade,
            "avg_days_late": float(pr.avg_days_late),
            "usual_pay_day": pr.usual_pay_day,
            "sales_12m": float(pr.sales_12m),
            "sales_90d": float(pr.sales_90d),
            "outstanding": float(pr.outstanding),
            "overdue": float(pr.overdue),
            "oldest": pr.oldest_overdue_days,
            "last_order_on": pr.last_order_on,
            "gap": pr.avg_order_gap_days,
            "trend": pr.trend,
            "suggested_limit": float(pr.suggested_credit_limit) if pr.suggested_credit_limit else None,
            "reasons": pr.reasons or [],
            "promises_made": pr.promises_made,
            "promises_kept": pr.promises_kept,
        },
        "bills": [
            {
                "id": b.id,
                "ref": b.bill_ref,
                "date": b.bill_date,
                "due": b.due_date,
                "amount": float(b.amount),
                "pending": float(b.pending_amount),
                "days_late": max(0, (today - b.due_date).days),
                "direction": b.direction,
            }
            for b in bills
        ],
        "vouchers": [
            {"type": v.voucher_type, "number": v.number, "date": v.date, "amount": float(v.amount)}
            for v in sales_v
        ],
        "quotes": [
            {
                "id": q.id,
                "number": q.number,
                "status": q.status,
                "total": float(q.total),
                "created_at": q.created_at,
            }
            for q in quotes_
        ],
        "promises": [
            {"id": x.id, "amount": float(x.amount), "due_date": x.due_date, "status": x.status}
            for x in promises
        ],
        "messages": [_message(m) for m in msgs],
        "memories": [
            {
                "id": m.id,
                "kind": m.kind,
                "content": m.content,
                "valid_from": m.valid_from,
                "valid_to": m.valid_to,
                "source": m.source,
            }
            for m in mems
        ],
    }


# ---------------------------------------------------------------------------
# Stock and purchase
# ---------------------------------------------------------------------------


def stock(db: Session) -> dict:
    rows = db.execute(select(KbItemMetric, KbItem).join(KbItem, KbItem.id == KbItemMetric.item_id)).all()
    suppliers = {p.id: p.name for p in db.scalars(select(KbParty).where(KbParty.kind == "supplier"))}
    pos = db.scalars(select(KbPurchaseOrder).order_by(KbPurchaseOrder.created_at.desc()).limit(40)).all()
    po_out = []
    for po in pos:
        lines = db.execute(
            select(KbPoLine, KbItem)
            .join(KbItem, KbItem.id == KbPoLine.item_id)
            .where(KbPoLine.po_id == po.id)
        ).all()
        po_out.append(
            {
                "id": po.id,
                "number": po.number,
                "supplier": suppliers.get(po.supplier_id),
                "status": po.status,
                "created_at": po.created_at,
                "total": float(po.total),
                "lines": [
                    {"item": i.name, "qty": float(ln.qty), "unit": i.unit, "rate": float(ln.rate)}
                    for ln, i in lines
                ],
            }
        )
    rfqs = []
    for r in db.scalars(select(KbRfq).where(KbRfq.status == "open")):
        it = db.get(KbItem, r.item_id)
        qs = db.scalars(select(KbSupplierQuote).where(KbSupplierQuote.rfq_id == r.id)).all()
        rfqs.append(
            {
                "id": r.id,
                "item": it.name,
                "unit": it.unit,
                "qty": float(r.qty),
                "created_at": r.created_at,
                "quotes": [
                    {
                        "supplier": suppliers.get(q.supplier_id),
                        "rate": float(q.rate),
                        "days": q.delivery_days,
                        "received_at": q.received_at,
                    }
                    for q in sorted(qs, key=lambda x: x.rate)
                ],
            }
        )
    order = {"reorder": 0, "watch": 1, "idle": 2, "ok": 3}
    items = sorted(
        rows,
        key=lambda r: (order.get(r[0].status, 9), r[0].days_left if r[0].days_left is not None else 9999),
    )
    return {
        "items": [
            {
                "item_id": i.id,
                "name": i.name,
                "group": i.stock_group,
                "unit": i.unit,
                "status": m.status,
                "stock": float(m.stock_qty),
                "value": float(m.stock_value),
                "per_day": float(m.per_day),
                "days_left": m.days_left,
                "idle_days": m.idle_days,
                "last_sale_on": m.last_sale_on,
                "sold_28d": float(m.sold_28d),
                "reorder_qty": float(m.reorder_qty) if m.reorder_qty else None,
                "rate": float(i.standard_rate),
            }
            for m, i in items
        ],
        "purchase_orders": po_out,
        "rfqs": rfqs,
        "totals": {
            "value": sum(float(m.stock_value) for m, _ in rows),
            "idle": sum(float(m.stock_value) for m, _ in rows if m.status == "idle"),
            "reorder": sum(1 for m, _ in rows if m.status == "reorder"),
        },
    }


def item_detail(db: Session, item_id: int) -> dict | None:
    it = db.get(KbItem, item_id)
    if it is None:
        return None
    m = db.scalars(select(KbItemMetric).where(KbItemMetric.item_id == item_id)).first()
    since = clock.today(db) - timedelta(days=120)
    pts = db.scalars(
        select(KbPricePoint)
        .where(KbPricePoint.item_id == item_id, KbPricePoint.date >= since)
        .order_by(KbPricePoint.date)
    ).all()
    weekly = defaultdict(lambda: defaultdict(list))
    for p in pts:
        wk = p.date - timedelta(days=p.date.weekday())
        weekly[wk][p.source].append(float(p.rate))
    names = {p.id: p.name for p in db.scalars(select(KbParty))}
    from app.kb.models import KbItemAlias

    return {
        "item": {
            "id": it.id,
            "name": it.name,
            "unit": it.unit,
            "group": it.stock_group,
            "gst": float(it.gst_rate),
            "list": float(it.standard_rate),
            "aliases": [a.alias for a in db.scalars(select(KbItemAlias).where(KbItemAlias.item_id == it.id))],
        },
        "metrics": None
        if m is None
        else {
            "status": m.status,
            "stock": float(m.stock_qty),
            "value": float(m.stock_value),
            "per_day": float(m.per_day),
            "days_left": m.days_left,
            "idle_days": m.idle_days,
            "sold_7d": float(m.sold_7d),
            "sold_28d": float(m.sold_28d),
        },
        "prices": [
            {"week": wk, **{src: round(sum(v) / len(v), 2) for src, v in d.items()}}
            for wk, d in sorted(weekly.items())
        ],
        "supplier_quotes": [
            {
                "supplier": names.get(q.supplier_id),
                "rate": float(q.rate),
                "days": q.delivery_days,
                "received_at": q.received_at,
            }
            for q in db.scalars(
                select(KbSupplierQuote)
                .where(KbSupplierQuote.item_id == item_id)
                .order_by(KbSupplierQuote.received_at.desc())
                .limit(12)
            )
        ],
    }


# ---------------------------------------------------------------------------
# Cash, reports, agents, chat
# ---------------------------------------------------------------------------


def cash(db: Session) -> dict:
    today = clock.today(db)
    weeks = db.scalars(select(KbCashWeek).order_by(KbCashWeek.week_start)).all()
    parties = {p.id: p.name for p in db.scalars(select(KbParty))}
    payables = db.scalars(
        select(KbBill)
        .where(
            KbBill.direction == "payable",
            KbBill.pending_amount > 1,
            KbBill.due_date < today + timedelta(days=28),
        )
        .order_by(KbBill.due_date)
    ).all()
    biz = clock.business(db)
    return {
        "bank": float(biz.bank_balance or 0),
        "bank_at": biz.bank_balance_at,
        "floor": float(rules.get(db, "cash", "min_balance")),
        "weeks": [_week(w) for w in weeks],
        "payables": [
            {
                "id": b.id,
                "party": parties.get(b.party_id),
                "ref": b.bill_ref,
                "due": b.due_date,
                "amount": float(b.pending_amount),
            }
            for b in payables
        ],
    }


def reports(db: Session) -> dict:
    today = clock.today(db)
    grades = dict(
        db.execute(
            select(KbCustomerProfile.grade, func.count())
            .where(KbCustomerProfile.sales_12m > 0)
            .group_by(KbCustomerProfile.grade)
        ).all()
    )
    monthly = defaultdict(float)
    for v in db.scalars(
        select(KbVoucher).where(
            KbVoucher.voucher_type == "sales", KbVoucher.date >= today - timedelta(days=365)
        )
    ):
        monthly[v.date.replace(day=1)] += float(v.amount) - float(v.tax_amount)
    recv = _series(db, "receivable", today + timedelta(days=1), 90)
    over = _series(db, "overdue", today + timedelta(days=1), 90)
    top = db.execute(
        select(KbCustomerProfile, KbParty)
        .join(KbParty, KbParty.id == KbCustomerProfile.party_id)
        .order_by(KbCustomerProfile.sales_12m.desc())
        .limit(10)
    ).all()
    return {
        "grades": {g: grades.get(g, 0) for g in "ABCD"},
        "sales_by_month": [{"month": m, "value": round(v, 2)} for m, v in sorted(monthly.items())],
        "receivable": [{"day": d, "value": v} for d, v in recv],
        "overdue": [{"day": d, "value": v} for d, v in over],
        "top_customers": [
            {"name": p.name, "sales_12m": float(pr.sales_12m), "grade": pr.grade} for pr, p in top
        ],
    }


def agents(db: Session) -> dict:
    return {
        "agents": agent_activity(db),
        "rules": rules.all_rules(db),
        "runs": [
            {
                "id": r.id,
                "agent": r.agent,
                "trigger": r.trigger_type,
                "ref": r.trigger_ref,
                "status": r.status,
                "started_at": r.started_at,
                "brain": r.brain,
                "llm_calls": r.llm_calls,
                "tokens": r.tokens_in + r.tokens_out,
                "cost_usd": r.cost_usd,
                "error": r.error,
                "outcome": r.outcome,
            }
            for r in db.scalars(select(KbAgentRun).order_by(KbAgentRun.id.desc()).limit(60))
        ],
        "postings": [
            {"id": p.id, "kind": p.kind, "status": p.status, "payload": p.payload, "created_at": p.created_at}
            for p in db.scalars(select(KbTallyPosting).order_by(KbTallyPosting.id.desc()).limit(30))
        ],
        "brain": brain_mod.brain_mode(),
        "channel": channels.channel_mode(),
    }


def _chat(m: KbChatMessage) -> dict:
    now = m.at
    return {
        "id": str(m.id),
        "from": m.sender,
        "at": now.hour * 60 + now.minute,
        "ts": m.at,
        "text": m.text,
        "card": m.card,
        "actions": m.actions,
        "chips": m.chips,
        "chosen": m.chosen,
        "status": m.status,
        "ref": m.ref,
    }


def chat_threads(db: Session) -> list[dict]:
    out = []
    for t in THREADS:
        last = db.scalars(
            select(KbChatMessage).where(KbChatMessage.thread == t).order_by(KbChatMessage.id.desc())
        ).first()
        unread = (
            db.scalar(
                select(func.count())
                .select_from(KbChatMessage)
                .where(
                    KbChatMessage.thread == t, KbChatMessage.read.is_(False), KbChatMessage.sender == "agent"
                )
            )
            or 0
        )
        name, sub, letter, bg, fg = THREAD_LOOK[t]
        out.append(
            {
                "id": t,
                "name": name,
                "sub": sub,
                "letter": letter,
                "bg": bg,
                "fg": fg,
                "unread": unread,
                "last": _chat(last) if last else None,
            }
        )
    return out


def chat_messages(db: Session, thread: str, limit: int = 120) -> list[dict]:
    rows = db.scalars(
        select(KbChatMessage)
        .where(KbChatMessage.thread == thread)
        .order_by(KbChatMessage.id.desc())
        .limit(limit)
    ).all()
    return [_chat(m) for m in reversed(rows)]


def search(db: Session, q: str) -> dict:
    like = f"%{q}%"
    parties = db.scalars(select(KbParty).where(KbParty.name.ilike(like)).limit(8)).all()
    items = db.scalars(select(KbItem).where(KbItem.name.ilike(like)).limit(6)).all()
    quotes_ = db.scalars(select(KbQuote).where(KbQuote.number.ilike(like)).limit(5)).all()
    return {
        "parties": [{"id": p.id, "name": p.name, "kind": p.kind} for p in parties],
        "items": [{"id": i.id, "name": i.name} for i in items],
        "quotes": [{"id": q.id, "number": q.number} for q in quotes_],
    }


def outbox(db: Session, limit: int = 100) -> list[dict]:
    names = {p.id: p.name for p in db.scalars(select(KbParty))}
    rows = db.scalars(select(KbMessage).order_by(KbMessage.id.desc()).limit(limit)).all()
    return [{**_message(m), "party": names.get(m.party_id)} for m in rows]


def link_status(db: Session, entity_type: str, entity_id: int) -> list[dict]:
    return [
        {
            "purpose": s.purpose,
            "created_at": s.created_at,
            "opened": s.first_opened_at,
            "responded": s.responded_at,
            "response": s.response,
        }
        for s in db.scalars(
            select(KbShareLink).where(
                KbShareLink.entity_type == entity_type, KbShareLink.entity_id == entity_id
            )
        )
    ]
