"""Business Manager: the 8 am brief.

One card in the app: cash first, then money to collect, then everything
else, each line with a tap to the screen that handles it. The numbers come
from the facts; the brain only writes the opening sentence.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.kb import fmt
from app.kb.agents.base import Agent
from app.kb.models import (
    KbApproval,
    KbCashWeek,
    KbCustomerProfile,
    KbEnquiry,
    KbItemMetric,
    KbKpi,
    KbQuote,
    KbTask,
)
from app.kb.runtime import Ctx, Proposal, post
from app.models import Organisation, User


class BriefAgent(Agent):
    name = "brief"
    label = "Business Manager"
    jobs = {"brief_daily": (8, 0)}

    def gather(self, ctx: Ctx, case: dict) -> dict:
        db = ctx.db
        weeks = db.scalars(select(KbCashWeek).order_by(KbCashWeek.week_start)).all()
        floor = float(ctx.rule("min_balance", "cash"))
        short = next((w for w in weeks if float(w.closing_balance) < floor), None)
        overdue = db.execute(
            select(
                func.coalesce(func.sum(KbCustomerProfile.overdue), 0),
                func.count().filter(KbCustomerProfile.overdue > 1),
            )
        ).one()
        # The last day the shop traded: on a Monday that's Saturday, not an empty Sunday.
        last = db.execute(
            select(KbKpi.day, KbKpi.value)
            .where(
                KbKpi.metric == "sales",
                KbKpi.day < ctx.today,
                KbKpi.day >= ctx.today - timedelta(days=7),
                KbKpi.value > 0,
            )
            .order_by(KbKpi.day.desc())
            .limit(1)
        ).first()
        yday, sales_y = (last[0], last[1]) if last else (ctx.today - timedelta(days=1), 0)
        # Average over trading days only, so holidays don't drag it down.
        avg = (
            db.scalar(
                select(func.avg(KbKpi.value)).where(
                    KbKpi.metric == "sales", KbKpi.day >= ctx.today - timedelta(days=29), KbKpi.value > 0
                )
            )
            or 0
        )
        open_quotes = db.execute(
            select(func.count(), func.coalesce(func.sum(KbQuote.total), 0)).where(
                KbQuote.status.in_(("sent", "opened", "negotiating"))
            )
        ).one()
        approvals = (
            db.scalar(select(func.count()).select_from(KbApproval).where(KbApproval.status == "waiting")) or 0
        )
        tasks = dict(
            db.execute(
                select(KbTask.assignee_role, func.count())
                .where(KbTask.status == "open")
                .group_by(KbTask.assignee_role)
            ).all()
        )
        reorder = (
            db.scalar(select(func.count()).select_from(KbItemMetric).where(KbItemMetric.status == "reorder"))
            or 0
        )
        idle = (
            db.scalar(
                select(func.coalesce(func.sum(KbItemMetric.stock_value), 0)).where(
                    KbItemMetric.status == "idle"
                )
            )
            or 0
        )
        new_enq = (
            db.scalar(
                select(func.count())
                .select_from(KbEnquiry)
                .where(KbEnquiry.status.in_(("new", "needs_review")))
            )
            or 0
        )
        owner = db.scalars(select(User).where(User.organisation_id == ctx.org)).first()
        org = db.get(Organisation, ctx.org)
        return {
            "owner": (owner.name.split()[0] if owner else ""),
            "company": org.name if org else "",
            "week1_in": float(weeks[0].inflow) if weeks else 0.0,
            "bank": float(weeks[0].opening_balance) if weeks else 0.0,
            "short": {
                "start": short.week_start,
                "closing": float(short.closing_balance),
                "by": floor - float(short.closing_balance),
            }
            if short
            else None,
            "weeks": len(weeks),
            "overdue": float(overdue[0]),
            "overdue_count": int(overdue[1]),
            "sales_y": float(sales_y),
            "sales_day": yday,
            "sales_avg": float(avg),
            "quotes": int(open_quotes[0]),
            "quotes_value": float(open_quotes[1]),
            "approvals": int(approvals),
            "tasks": tasks,
            "reorder": int(reorder),
            "idle": float(idle),
            "enquiries": int(new_enq),
        }

    def decide(self, ctx: Ctx, case: dict, data: dict) -> list[Proposal]:
        return [{"kind": "post_brief", "title": "Morning brief", "payload": data}] if data else []

    def do_post_brief(self, ctx: Ctx, d: dict) -> dict:
        facts = {
            "owner": d["owner"],
            "weeks": d["weeks"],
            "overdue": fmt.inr(d["overdue"]),
            "overdue_count": d["overdue_count"],
            "collect_this_week": fmt.inr(d["week1_in"]),
            "approvals": d["approvals"],
        }
        if d["short"]:
            facts["cash_short_week"] = fmt.day(d["short"]["start"])
            facts["cash_short_by"] = fmt.inr(d["short"]["by"])
        text = ctx.brain.headline("brief", facts)
        change = (d["sales_y"] - d["sales_avg"]) / d["sales_avg"] * 100 if d["sales_avg"] else 0
        kpis = [
            {
                "label": "Bank today",
                "value": fmt.inr(d["bank"]),
                "note": f"short in week of {fmt.day(d['short']['start'])}"
                if d["short"]
                else "fine for 4 weeks",
                "tone": "bad" if d["short"] else "good",
            },
            {
                "label": "Overdue",
                "value": fmt.inr(d["overdue"]),
                "note": f"{d['overdue_count']} customers",
                "tone": "warn",
            },
            {
                "label": "Sales yesterday"
                if str(d.get("sales_day") or "")[:10] in ("", str(ctx.today - timedelta(days=1)))
                else f"Sales on {fmt.day(d['sales_day'])}",
                "value": fmt.inr(d["sales_y"]),
                "note": f"{change:+.0f}% vs a usual day",
                "tone": "good" if change >= 0 else "warn",
            },
            {
                "label": "Open quotes",
                "value": fmt.inr(d["quotes_value"]),
                "note": f"{d['quotes']} quotes",
                "tone": "info",
            },
        ]
        todo = []
        if d["approvals"]:
            todo.append(
                {"text": f"{d['approvals']} approvals wait for you", "go": {"to": "tab", "tab": "approvals"}}
            )
        if d["short"]:
            todo.append(
                {
                    "text": f"Cash: week of {fmt.day(d['short']['start'])} needs {fmt.inr(d['short']['by'])}",
                    "go": {"to": "thread", "id": "cash"},
                }
            )
        if d["tasks"].get("accounts"):
            todo.append(
                {
                    "text": f"{d['tasks']['accounts']} calls and follow-ups for accounts",
                    "go": {"to": "thread", "id": "collect"},
                }
            )
        if d["enquiries"]:
            todo.append(
                {"text": f"{d['enquiries']} enquiries need a look", "go": {"to": "thread", "id": "sales"}}
            )
        if d["reorder"]:
            todo.append({"text": f"{d['reorder']} items to reorder", "go": {"to": "thread", "id": "stock"}})
        if d["idle"] > 0:
            todo.append(
                {"text": f"{fmt.inr(d['idle'])} sitting in idle stock", "go": {"to": "thread", "id": "stock"}}
            )
        post(ctx, text=text, card={"kind": "brief", "kpis": kpis, "todo": todo})
        return {"brief": True}
