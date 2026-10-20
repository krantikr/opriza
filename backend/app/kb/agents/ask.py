"""Ask Oprisa: answers from the books, in chat.

Every answer comes from a read-only tool over the knowledge base, so the
figures are exact and the rows behind them can be shown. The brain picks the
tool (an LLM with structured output, or the keyword router below) and phrases
the answer; it never computes a number. Asking it to *do* something hands the
request to the agent that owns it, so that agent's rules still apply.
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

import calendar
import difflib
import re
from datetime import date, timedelta

from sqlalchemy import func, or_, select

from app.kb import clock, events, fmt
from app.kb.agents.base import Agent
from app.kb.brain import ToolCall, ToolSpec
from app.kb.models import (
    KbApproval,
    KbBill,
    KbCashWeek,
    KbCustomerProfile,
    KbDocument,
    KbDocumentChunk,
    KbItem,
    KbItemAlias,
    KbItemMetric,
    KbMemory,
    KbParty,
    KbPricePoint,
    KbPromise,
    KbQuote,
    KbTask,
    KbVoucher,
)
from app.kb.runtime import Ctx, Proposal, post

TOOLS: list[ToolSpec] = [
    ToolSpec(
        "top_debtors",
        "Customers who owe the most (outstanding), with overdue amounts.",
        {"n": "how many, default 5"},
    ),
    ToolSpec("overdue_total", "Total overdue right now and how many customers."),
    ToolSpec(
        "sales_period",
        "Sales before tax between two dates.",
        {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD, exclusive"},
    ),
    ToolSpec(
        "running_out",
        "Items that will run out within N days at the current selling rate.",
        {"days": "default 7"},
    ),
    ToolSpec(
        "payables_due",
        "What we must pay suppliers in the next N days (including overdue).",
        {"days": "default 7"},
    ),
    ToolSpec(
        "last_rate", "The rate a customer paid for an item last time.", {"customer": "name", "item": "name"}
    ),
    ToolSpec("grade_count", "How many customers are in a grade (A, B, C, D).", {"grade": "A|B|C|D"}),
    ToolSpec(
        "customer", "Everything about one customer: grade, dues, buying, reasons.", {"customer": "name"}
    ),
    ToolSpec("cash_position", "Bank balance today and the next four weeks."),
    ToolSpec("open_quotes", "Quotes sent and not yet won or lost."),
    ToolSpec("stock_of", "Stock and days left for one item.", {"item": "name"}),
    ToolSpec("idle_stock", "Stock that hasn't sold for a long time, and what it's worth."),
    ToolSpec("stopped_buying", "Regular customers who have stopped ordering."),
    ToolSpec("promises_due", "Payment promises due in the next N days.", {"days": "default 7"}),
    ToolSpec("top_customers", "Biggest customers by sales in the last 12 months.", {"n": "default 5"}),
    ToolSpec("search_notes", "Search remembered notes, emails and documents.", {"text": "words to find"}),
    ToolSpec("what_needs_me", "What is waiting for the owner today: approvals and urgent tasks."),
    ToolSpec(
        "send_statement",
        "ACTION: ask the Collections agent to send a customer their statement.",
        {"customer": "name"},
    ),
    ToolSpec(
        "remember",
        "ACTION: remember a note or preference for later.",
        {"text": "the note", "customer": "optional name"},
    ),
    ToolSpec("help", "When nothing else fits: say what I can answer."),
]
TOOL_NAMES = {t.name for t in TOOLS}
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {
    m.lower(): i for i, m in enumerate(calendar.month_abbr) if m
}


# ---------------------------------------------------------------------------
# Finding names in a question
# ---------------------------------------------------------------------------


def find_party(db, text: str, kind: str | None = None) -> KbParty | None:
    q = select(KbParty)
    if kind:
        q = q.where(KbParty.kind == kind)
    parties = db.scalars(q).all()
    low = text.lower()
    hits = [p for p in parties if p.name.lower() in low]
    if hits:
        return max(hits, key=lambda p: len(p.name))
    # "Om Sai" for "Om Sai Structures": the first words of a name, when only one party starts that way.
    words = re.findall(r"[a-z0-9&.]+", low)
    text_words = " " + " ".join(words) + " "
    for n in (3, 2):
        starts: dict[str, list[KbParty]] = {}
        for p in parties:
            head = " ".join(re.findall(r"[a-z0-9&.]+", p.name.lower())[:n])
            if len(head) >= 5 and len(head.split()) == n:
                starts.setdefault(head, []).append(p)
        found = [ps[0] for head, ps in starts.items() if f" {head} " in text_words and len(ps) == 1]
        if len(found) == 1:
            return found[0]
    names = {p.name.lower(): p for p in parties}
    for n in (4, 3, 2):
        for i in range(len(words) - n + 1):
            frag = " ".join(words[i : i + n])
            m = difflib.get_close_matches(frag, names, n=1, cutoff=0.86)
            if m:
                return names[m[0]]
    return None


def find_item(db, text: str) -> KbItem | None:
    low = text.lower()
    items = db.scalars(select(KbItem)).all()
    hits = [i for i in items if i.name.lower() in low]
    if hits:
        return max(hits, key=lambda i: len(i.name))
    best = None
    for a in db.scalars(select(KbItemAlias)):
        if re.search(rf"(?<![\w]){re.escape(a.alias)}(?![\w])", low) and (
            best is None or len(a.alias) > len(best.alias)
        ):
            best = a
    return db.get(KbItem, best.item_id) if best else None


def month_range(today: date, text: str) -> tuple[date, date, str] | None:
    low = text.lower()
    first = today.replace(day=1)
    if "last month" in low or "previous month" in low:
        start = (first - timedelta(days=1)).replace(day=1)
        return start, first, f"{start:%B}"
    if "this month" in low or "month to date" in low or "mtd" in low:
        return first, today + timedelta(days=1), f"{today:%B} so far"
    if "yesterday" in low:
        y = today - timedelta(days=1)
        return y, today, "yesterday"
    if "this week" in low:
        start = today - timedelta(days=today.weekday())
        return start, today + timedelta(days=1), "this week"
    if "last week" in low:
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=7), "last week"
    if "this year" in low or "financial year" in low or "fy" in low.split():
        fy = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
        return fy, today + timedelta(days=1), "this financial year"
    for word in re.findall(r"[a-z]+", low):
        if word in MONTHS:
            m = MONTHS[word]
            year = today.year if m <= today.month else today.year - 1
            start = date(year, m, 1)
            end = date(year + (m == 12), m % 12 + 1, 1)
            return start, end, f"{start:%B %Y}"
    return None


# ---------------------------------------------------------------------------
# The tools: read-only, exact
# ---------------------------------------------------------------------------


def t_top_debtors(db, args) -> dict:
    n = int(args.get("n") or 5)
    rows = db.execute(
        select(KbCustomerProfile, KbParty)
        .join(KbParty, KbParty.id == KbCustomerProfile.party_id)
        .order_by(KbCustomerProfile.outstanding.desc())
        .limit(n)
    ).all()
    if not rows:
        return {"answer": "Nobody owes you anything right now."}
    top, party = rows[0]
    return {
        "answer": f"**{party.name}** owes the most: {fmt.inr(top.outstanding)}"
        + (
            f", of which {fmt.inr(top.overdue)} is overdue."
            if float(top.overdue) > 1
            else ", none of it overdue."
        ),
        "party": party.name,
        "party_id": party.id,
        "amount": float(top.outstanding),
        "card": {
            "kind": "table",
            "title": "Who owes the most",
            "cols": ["Customer", "Owes", "Overdue", "Grade"],
            "align": ["l", "r", "r", "l"],
            "rows": [[p.name, fmt.inr(pr.outstanding), fmt.inr(pr.overdue), pr.grade] for pr, p in rows],
        },
    }


def t_overdue_total(db, args) -> dict:
    total, count = db.execute(
        select(
            func.coalesce(func.sum(KbCustomerProfile.overdue), 0),
            func.count().filter(KbCustomerProfile.overdue > 1),
        )
    ).one()
    return {
        "answer": f"**{fmt.inr(total)}** is overdue across {count} customers.",
        "amount": round(float(total), 2),
        "count": int(count),
    }


def t_sales_period(db, args) -> dict:
    start, end = date.fromisoformat(args["start"]), date.fromisoformat(args["end"])
    label = args.get("label") or f"{fmt.day(start)} to {fmt.day(end - timedelta(days=1))}"
    total, n = db.execute(
        select(func.coalesce(func.sum(KbVoucher.amount - KbVoucher.tax_amount), 0), func.count()).where(
            KbVoucher.voucher_type == "sales", KbVoucher.date >= start, KbVoucher.date < end
        )
    ).one()
    return {
        "answer": f"Sales {label}: **{fmt.inr(total)}** before tax, across {n} invoices.",
        "amount": round(float(total), 2),
        "invoices": int(n),
        "start": start,
        "end": end,
    }


def t_running_out(db, args) -> dict:
    days = float(args.get("days") or 7)
    rows = db.execute(
        select(KbItemMetric, KbItem)
        .join(KbItem, KbItem.id == KbItemMetric.item_id)
        .where(KbItemMetric.days_left < days)
        .order_by(KbItemMetric.days_left)
    ).all()
    if not rows:
        return {"answer": f"Nothing runs out in the next {days:.0f} days.", "items": []}
    names = [i.name for _, i in rows]
    return {
        "answer": f"{len(rows)} item{'s' if len(rows) > 1 else ''} will run out within {days:.0f} days: "
        + ", ".join(f"**{i.name}** ({m.days_left} days)" for m, i in rows)
        + ".",
        "items": names,
        "card": {
            "kind": "table",
            "title": "Running out",
            "cols": ["Item", "Stock", "Per day", "Days left"],
            "align": ["l", "r", "r", "r"],
            "rows": [
                [
                    i.name,
                    fmt.qty(float(m.stock_qty), i.unit),
                    fmt.qty(float(m.per_day), i.unit),
                    f"{m.days_left}",
                ]
                for m, i in rows
            ],
        },
    }


def t_payables_due(db, args) -> dict:
    days = int(args.get("days") or 7)
    until = clock.today(db) + timedelta(days=days)
    rows = db.execute(
        select(KbBill, KbParty)
        .join(KbParty, KbParty.id == KbBill.party_id)
        .where(KbBill.direction == "payable", KbBill.pending_amount > 1, KbBill.due_date < until)
        .order_by(KbBill.due_date)
    ).all()
    total = round(sum(float(b.pending_amount) for b, _ in rows), 2)
    return {
        "answer": f"You have **{fmt.inr(total)}** to pay suppliers in the next {days} days"
        + (f" ({len(rows)} bills)." if rows else "."),
        "amount": total,
        "card": {
            "kind": "table",
            "title": "Supplier bills due",
            "cols": ["Supplier", "Bill", "Due", "Amount"],
            "align": ["l", "l", "l", "r"],
            "rows": [
                [p.name, b.bill_ref, fmt.day(b.due_date), fmt.inr(b.pending_amount)] for b, p in rows[:10]
            ],
        }
        if rows
        else None,
    }


def t_last_rate(db, args) -> dict:
    party = find_party(db, args.get("customer", ""))
    item = find_item(db, args.get("item", ""))
    if not party or not item:
        return {"answer": "Tell me the customer and the item, e.g. “last rate for Om Sai on TMT 12mm”."}
    pp = db.scalars(
        select(KbPricePoint)
        .where(
            KbPricePoint.party_id == party.id, KbPricePoint.item_id == item.id, KbPricePoint.source == "sale"
        )
        .order_by(KbPricePoint.date.desc(), KbPricePoint.id.desc())
        .limit(1)
    ).first()
    if pp is None:
        return {"answer": f"{party.name} hasn't bought {item.name} in the last year."}
    return {
        "answer": f"{party.name} last paid **{fmt.rate(pp.rate)}/{item.unit}** for {item.name} on {fmt.day(pp.date)}.",
        "rate": float(pp.rate),
        "date": pp.date,
        "party": party.name,
        "item": item.name,
    }


def t_grade_count(db, args) -> dict:
    g = (args.get("grade") or "D").upper()[:1]
    n = (
        db.scalar(
            select(func.count())
            .select_from(KbCustomerProfile)
            .where(KbCustomerProfile.grade == g, KbCustomerProfile.sales_12m > 0)
        )
        or 0
    )
    rows = db.execute(
        select(KbCustomerProfile, KbParty)
        .join(KbParty, KbParty.id == KbCustomerProfile.party_id)
        .where(KbCustomerProfile.grade == g, KbCustomerProfile.sales_12m > 0)
        .order_by(KbCustomerProfile.outstanding.desc())
        .limit(8)
    ).all()
    return {
        "answer": f"**{n} customers** are grade {g}.",
        "count": int(n),
        "card": {
            "kind": "table",
            "title": f"Grade {g}",
            "cols": ["Customer", "Owes", "Days late"],
            "align": ["l", "r", "r"],
            "rows": [[p.name, fmt.inr(pr.outstanding), f"{pr.avg_days_late:.0f}"] for pr, p in rows],
        }
        if rows
        else None,
    }


def t_customer(db, args) -> dict:
    party = find_party(db, args.get("customer", ""), "customer")
    if not party:
        return {"answer": "I couldn't find that customer. Try their name as it is in Tally."}
    pr = db.scalars(select(KbCustomerProfile).where(KbCustomerProfile.party_id == party.id)).first()
    if pr is None:
        return {"answer": f"{party.name} has no history yet."}
    return {
        "answer": f"**{party.name}** is grade {pr.grade}. They owe {fmt.inr(pr.outstanding)} "
        f"({fmt.inr(pr.overdue)} overdue) and bought {fmt.inr(pr.sales_12m)} in the last year. "
        + " ".join(f"{r}." for r in (pr.reasons or [])[:2]),
        "party": party.name,
        "party_id": party.id,
        "grade": pr.grade,
        "card": {
            "kind": "kpis",
            "title": party.name,
            "kpis": [
                {"label": "Grade", "value": pr.grade},
                {"label": "Owes", "value": fmt.inr(pr.outstanding)},
                {
                    "label": "Overdue",
                    "value": fmt.inr(pr.overdue),
                    "tone": "bad" if float(pr.overdue) > 1 else "good",
                },
                {"label": "Sales 12 m", "value": fmt.inr(pr.sales_12m)},
            ],
        },
    }


def t_cash_position(db, args) -> dict:
    weeks = db.scalars(select(KbCashWeek).order_by(KbCashWeek.week_start)).all()
    if not weeks:
        return {"answer": "No cash forecast yet; it appears after the first Tally sync."}
    short = next((w for w in weeks if float(w.closing_balance) < 0), None)
    text = f"Bank today: **{fmt.inr(weeks[0].opening_balance)}**. "
    text += (
        f"It goes to {fmt.inr(short.closing_balance)} in the week of {fmt.day(short.week_start)}."
        if short
        else f"It stays positive for {len(weeks)} weeks, ending at {fmt.inr(weeks[-1].closing_balance)}."
    )
    return {
        "answer": text,
        "bank": float(weeks[0].opening_balance),
        "card": {
            "kind": "cashweeks",
            "weeks": [
                {"label": fmt.day(w.week_start), "inflow": float(w.inflow), "outflow": float(w.outflow)}
                for w in weeks
            ],
        },
    }


def t_open_quotes(db, args) -> dict:
    rows = db.execute(
        select(KbQuote, KbParty)
        .join(KbParty, KbParty.id == KbQuote.party_id)
        .where(KbQuote.status.in_(("sent", "opened", "negotiating", "pending_approval")))
        .order_by(KbQuote.total.desc())
    ).all()
    total = sum(float(q.total) for q, _ in rows)
    return {
        "answer": f"**{len(rows)} quotes** are open, worth {fmt.inr(total)}.",
        "count": len(rows),
        "amount": round(total, 2),
        "card": {
            "kind": "table",
            "title": "Open quotes",
            "cols": ["Quote", "Customer", "Status", "Value"],
            "align": ["l", "l", "l", "r"],
            "rows": [[q.number, p.name, q.status.replace("_", " "), fmt.inr(q.total)] for q, p in rows[:10]],
        },
    }


def t_stock_of(db, args) -> dict:
    item = find_item(db, args.get("item", ""))
    if not item:
        return {"answer": "Which item? Use the name from your stock list."}
    m = db.scalars(select(KbItemMetric).where(KbItemMetric.item_id == item.id)).first()
    if m is None:
        return {"answer": f"No stock figures for {item.name} yet."}
    left = (
        f", about {m.days_left} days at {fmt.qty(float(m.per_day), item.unit)} a day"
        if m.days_left is not None
        else ", and none sold recently"
    )
    return {
        "answer": f"**{fmt.qty(float(m.stock_qty), item.unit)}** of {item.name} in stock{left}.",
        "item": item.name,
        "stock": float(m.stock_qty),
        "days_left": m.days_left,
    }


def t_idle_stock(db, args) -> dict:
    rows = db.execute(
        select(KbItemMetric, KbItem)
        .join(KbItem, KbItem.id == KbItemMetric.item_id)
        .where(KbItemMetric.status == "idle")
        .order_by(KbItemMetric.stock_value.desc())
    ).all()
    total = sum(float(m.stock_value) for m, _ in rows)
    if not rows:
        return {"answer": "No idle stock right now.", "amount": 0}
    return {
        "answer": f"**{fmt.inr(total)}** is sitting in stock that hasn't sold: "
        + ", ".join(f"{i.name} ({m.idle_days} days)" for m, i in rows)
        + ".",
        "amount": round(total, 2),
    }


def t_stopped_buying(db, args) -> dict:
    rows = db.execute(
        select(KbCustomerProfile, KbParty)
        .join(KbParty, KbParty.id == KbCustomerProfile.party_id)
        .where(KbCustomerProfile.trend == "down")
        .order_by(KbCustomerProfile.sales_12m.desc())
        .limit(6)
    ).all()
    if not rows:
        return {"answer": "No regular customer has stopped ordering."}
    return {
        "answer": "These regulars have slowed down or stopped: "
        + ", ".join(f"**{p.name}** (last order {fmt.day(pr.last_order_on)})" for pr, p in rows)
        + ".",
        "parties": [p.name for _, p in rows],
    }


def t_promises_due(db, args) -> dict:
    days = int(args.get("days") or 7)
    today = clock.today(db)
    rows = db.execute(
        select(KbPromise, KbParty)
        .join(KbParty, KbParty.id == KbPromise.party_id)
        .where(KbPromise.status == "open", KbPromise.due_date < today + timedelta(days=days))
        .order_by(KbPromise.due_date)
    ).all()
    total = sum(float(p.amount) for p, _ in rows)
    if not rows:
        return {"answer": f"No promises due in the next {days} days.", "amount": 0}
    return {
        "answer": f"{len(rows)} promises worth **{fmt.inr(total)}** are due in the next {days} days.",
        "amount": round(total, 2),
        "card": {
            "kind": "table",
            "title": "Promises due",
            "cols": ["Customer", "Due", "Amount"],
            "align": ["l", "l", "r"],
            "rows": [[p.name, fmt.day(pr.due_date), fmt.inr(pr.amount)] for pr, p in rows],
        },
    }


def t_top_customers(db, args) -> dict:
    n = int(args.get("n") or 5)
    rows = db.execute(
        select(KbCustomerProfile, KbParty)
        .join(KbParty, KbParty.id == KbCustomerProfile.party_id)
        .order_by(KbCustomerProfile.sales_12m.desc())
        .limit(n)
    ).all()
    return {
        "answer": f"Your biggest customer is **{rows[0][1].name}** with {fmt.inr(rows[0][0].sales_12m)} in the last 12 months."
        if rows
        else "No sales yet.",
        "card": {
            "kind": "bars",
            "title": "Top customers, last 12 months",
            "highlight": 0,
            "bars": [
                {"label": p.name, "value": float(pr.sales_12m), "display": fmt.inr(pr.sales_12m)}
                for pr, p in rows
            ],
        },
    }


def t_search_notes(db, args) -> dict:
    words = [
        w
        for w in re.findall(r"[a-zA-Z0-9]{3,}", args.get("text", ""))
        if w.lower()
        not in {"what", "did", "the", "about", "notes", "said", "say", "any", "have", "from", "for", "with"}
    ]
    if not words:
        return {"answer": "What should I look for?"}
    party = find_party(db, args.get("text", ""))
    if party is not None:
        mems = db.scalars(
            select(KbMemory)
            .where(KbMemory.valid_to.is_(None), KbMemory.scope_type == "party", KbMemory.scope_id == party.id)
            .limit(5)
        ).all()
        chunks = db.execute(
            select(KbDocumentChunk, KbDocument)
            .join(KbDocument, KbDocument.id == KbDocumentChunk.document_id)
            .where(KbDocument.party_id == party.id)
            .order_by(KbDocument.received_at.desc())
            .limit(3)
        ).all()
    else:
        like = [f"%{w}%" for w in words[:5]]
        mems = db.scalars(
            select(KbMemory)
            .where(KbMemory.valid_to.is_(None), or_(*[KbMemory.content.ilike(x) for x in like]))
            .limit(5)
        ).all()
        chunks = db.execute(
            select(KbDocumentChunk, KbDocument)
            .join(KbDocument, KbDocument.id == KbDocumentChunk.document_id)
            .where(or_(*[KbDocumentChunk.content.ilike(x) for x in like]))
            .limit(3)
        ).all()
    if not mems and not chunks:
        return {"answer": "I didn't find anything about that in your notes or documents."}
    parts = [f"• {m.content}" for m in mems] + [
        f"• {d.title} ({fmt.day(d.received_at)}): " + " ".join(c.content.split("\n\n", 1)[-1].split())[:200]
        for c, d in chunks
    ]
    return {"answer": "Here's what I have:\n" + "\n".join(parts)}


def t_what_needs_me(db, args) -> dict:
    approvals = db.scalars(
        select(KbApproval).where(KbApproval.status == "waiting").order_by(KbApproval.requested_at)
    ).all()
    urgent = db.scalars(
        select(KbTask)
        .where(KbTask.status == "open", KbTask.priority == 1)
        .order_by(KbTask.amount.desc().nulls_last())
        .limit(5)
    ).all()
    lines = [f"• Approve: {a.title} ({a.reason})" for a in approvals[:5]] + [f"• {t.title}" for t in urgent]
    return {
        "answer": f"**{len(approvals)} approvals** and {len(urgent)} urgent tasks:\n" + "\n".join(lines)
        if lines
        else "Nothing urgent. The agents have today covered.",
        "approvals": len(approvals),
    }


def t_send_statement(db, args) -> dict:
    party = find_party(db, args.get("customer", ""), "customer")
    if not party:
        return {"answer": "Which customer should get the statement?"}
    events.publish(
        db,
        "handoff.requested",
        "party",
        party.id,
        source="user",
        actor="ask",
        to="collect",
        action="statement",
        party_id=party.id,
    )
    return {
        "answer": f"Asked the Collections agent to send **{party.name}** their statement. It follows your message rules.",
        "handoff": "collect",
        "party": party.name,
    }


def t_remember(db, args) -> dict:
    text = (args.get("text") or "").strip()
    if not text:
        return {"answer": "What should I remember?"}
    party = find_party(db, args.get("customer") or text)
    db.add(
        KbMemory(
            organisation_id=db.info["organisation_id"],
            scope_type="party" if party else "org",
            scope_id=party.id if party else None,
            kind="note",
            content=text,
            source="chat",
            confidence=1.0,
            valid_from=clock.now(db),
            created_by="owner",
        )
    )
    db.flush()
    return {"answer": "Noted. I'll keep that in mind" + (f" for {party.name}." if party else ".")}


def t_help(db, args) -> dict:
    return {
        "answer": "I answer from your Tally data. Try: “Who owes me the most?”, “Sales last month”, "
        "“What will run out this week?”, “Cash position”, “Last rate for <customer> on <item>”, "
        "or “Send <customer> a statement”."
    }


IMPL = {name[2:]: fn for name, fn in globals().items() if name.startswith("t_")}


# ---------------------------------------------------------------------------
# The keyword router (rules brain)
# ---------------------------------------------------------------------------


def rule_route(db, question: str) -> ToolCall:
    q = question.lower()
    today = clock.today(db)
    days = 30 if "month" in q else 7
    if m := re.search(r"next (\d+) days", q):
        days = int(m.group(1))
    if re.search(r"\b(remember|note that|keep in mind)\b", q):
        text = re.sub(
            r"^.*?\b(remember( that)?|note that|keep in mind( that)?)\b[:,]?\s*", "", question, flags=re.I
        )
        return ToolCall(tool="remember", args={"text": text})
    if re.search(r"\bsend\b.*\bstatement\b|\bstatement\b.*\bsend\b", q):
        return ToolCall(tool="send_statement", args={"customer": question})
    if re.search(r"\b(rate|price)\b", q) and re.search(r"\b(last|paid|pay)\b", q):
        return ToolCall(tool="last_rate", args={"customer": question, "item": question})
    if re.search(r"\bgrade\s*([abcd])\b", q):
        return ToolCall(
            tool="grade_count", args={"grade": re.search(r"\bgrade\s*([abcd])\b", q).group(1).upper()}
        )
    if re.search(r"\b(run out|running out|out of stock|reorder|finish)\b", q):
        return ToolCall(tool="running_out", args={"days": str(days)})
    if re.search(r"\b(supplier|payable|pay suppliers|have to pay|we owe|i owe)\b", q):
        return ToolCall(tool="payables_due", args={"days": str(days)})
    if re.search(r"\b(owe|owes|owing|debtor|debtors)\b", q):
        return ToolCall(tool="top_debtors", args={"n": "5"})
    if "overdue" in q:
        return ToolCall(tool="overdue_total", args={})
    if re.search(r"\b(sales|sold|revenue|turnover)\b", q) and (rng := month_range(today, q)):
        return ToolCall(
            tool="sales_period",
            args={"start": rng[0].isoformat(), "end": rng[1].isoformat(), "label": rng[2]},
        )
    if re.search(r"\b(cash|bank|balance|payroll|salar)", q):
        return ToolCall(tool="cash_position", args={})
    if re.search(r"\bquotes?\b", q):
        return ToolCall(tool="open_quotes", args={})
    if re.search(r"\b(idle|not moving|dead stock|slow moving|stuck)\b", q):
        return ToolCall(tool="idle_stock", args={})
    if re.search(r"\b(stopped|not ordering|gone quiet|quiet|lost customers|slipping)\b", q):
        return ToolCall(tool="stopped_buying", args={})
    if "promise" in q:
        return ToolCall(tool="promises_due", args={"days": str(days)})
    if re.search(r"\b(top|best|biggest)\b.*\bcustomers?\b", q):
        return ToolCall(tool="top_customers", args={"n": "5"})
    if re.search(r"\b(need me|needs me|to do|todo|what should i|today)\b", q):
        return ToolCall(tool="what_needs_me", args={})
    if re.search(r"\b(note|notes|said|mentioned|email|document)\b", q):
        return ToolCall(tool="search_notes", args={"text": question})
    if find_item(db, q) and re.search(r"\b(stock|how much|how many|left)\b", q):
        return ToolCall(tool="stock_of", args={"item": question})
    if find_party(db, q, "customer"):
        return ToolCall(tool="customer", args={"customer": question})
    if find_item(db, q):
        return ToolCall(tool="stock_of", args={"item": question})
    if re.search(r"\b(sales|sold)\b", q):
        start = today.replace(day=1)
        return ToolCall(
            tool="sales_period",
            args={
                "start": start.isoformat(),
                "end": (today + timedelta(days=1)).isoformat(),
                "label": f"{today:%B} so far",
            },
        )
    return (
        ToolCall(tool="search_notes", args={"text": question})
        if len(q.split()) > 2
        else ToolCall(tool="help", args={})
    )


def answer(db, question: str, brain) -> dict:
    """Plan, run the tool, phrase the answer. Used by the agent and the tests."""
    call = brain.plan_answer(
        question, TOOLS, {"rule_route": lambda qq: rule_route(db, qq), "today": clock.today(db)}
    )
    tool = call.tool if call.tool in IMPL else "help"
    args = dict(call.args)
    # The LLM may leave names out of the args; the question always has them.
    for key in ("customer", "item", "text"):
        if key in {a for t in TOOLS if t.name == tool for a in t.args} and not args.get(key):
            args[key] = question
    try:
        result = IMPL[tool](db, args)
    except (ValueError, KeyError):
        tool, result = "help", t_help(db, {})
    text = brain.phrase_answer(question, tool, result)
    return {"tool": tool, "args": args, "result": result, "text": text}


class AskAgent(Agent):
    name = "ask"
    label = "Ask Oprisa"

    def decide(self, ctx: Ctx, case: dict, data: dict) -> list[Proposal]:
        return [
            {
                "kind": "answer",
                "title": "Answer",
                "payload": {"question": case["question"], "thread": case.get("thread", "ask")},
            }
        ]

    def do_answer(self, ctx: Ctx, pl: dict) -> dict:
        out = answer(ctx.db, pl["question"], ctx.brain)
        card = out["result"].get("card")
        post(ctx, thread=pl.get("thread", "ask"), text=out["text"], card=card)
        return {
            "tool": out["tool"],
            "answer": out["text"],
            "result": {k: v for k, v in out["result"].items() if k not in ("card", "answer")},
        }
