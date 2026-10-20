"""Scheduling: when each agent runs, and handing events to the agents.

tick(db)        for one bound desk: run any daily job that is due, then
                dispatch pending events until the agents have settled.
tick_all()      every desk: sync from its source if due, then tick.
                Called by scripts/agents_tick.py (cron) or, with
                AGENTS_SCHEDULER=on, every few minutes inside the API.
first_run(db)   a newly loaded desk: run every job once for today.
"""

from __future__ import annotations

import os
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.core.tenancy import bind_session
from app.kb import clock, events
from app.kb.agents import AGENTS
from app.kb.models import KbBusiness, KbJobRun, KbQuote
from app.kb.runtime import run_case

logger = get_logger(__name__)

#: Order matters on a fresh desk: the brief goes last so it reports what the others did.
JOB_ORDER = [
    ("sales", "sales_daily"),
    ("collect", "collect_daily"),
    ("stock", "stock_daily"),
    ("score", "score_daily"),
    ("cash", "cash_daily"),
    ("brief", "brief_daily"),
]
SYNC_EVERY_MINUTES = 15


def _runner(db: Session, agent: str):
    def run(case: dict, ref: str | None = None):
        return run_case(db, agent, case, trigger="event", ref=ref)

    return run


def dispatch_events(db: Session, rounds: int = 6) -> int:
    handlers = {name: (lambda db_, ev, a=name: AGENTS[a].on_event(_runner(db_, a), ev)) for name in AGENTS}
    total = 0
    for _ in range(rounds):
        n = events.dispatch(db, handlers)
        total += n
        if n == 0:
            break
    return total


def run_job(
    db: Session, agent: str, job: str, *, trigger: str = "schedule", user_id: int | None = None
) -> list[dict]:
    results = []
    for case in AGENTS[agent].run_job(db, job):
        ref = job if case.get("job") else ", ".join(f"{k} {v}" for k, v in case.items())
        results.append(run_case(db, agent, case, trigger=trigger, ref=ref, user_id=user_id))
    row = db.scalars(select(KbJobRun).where(KbJobRun.job == job)).first()
    if row is None:
        row = KbJobRun(organisation_id=db.info["organisation_id"], job=job)
        db.add(row)
    row.last_run_on = clock.today(db)
    row.last_run_at = clock.now(db)
    db.flush()
    return results


def due_jobs(db: Session) -> list[tuple[str, str]]:
    now = clock.now(db)
    last = {r.job: r.last_run_on for r in db.scalars(select(KbJobRun))}
    out = []
    for agent, job in JOB_ORDER:
        hh, mm = AGENTS[agent].jobs[job]
        if (now.hour, now.minute) >= (hh, mm) and last.get(job) != now.date():
            out.append((agent, job))
    return out


def tick(db: Session) -> dict:
    ran = []
    dispatched = dispatch_events(db)
    for agent, job in due_jobs(db):
        run_job(db, agent, job)
        ran.append(job)
        dispatched += dispatch_events(db)
    return {"jobs": ran, "events": dispatched}


def first_run(db: Session) -> dict:
    """Bring a freshly loaded desk up to today."""
    # Quotes a salesperson priced but nobody has checked yet go through the
    # Sales agent's gate first, like any quote would.
    for q in db.scalars(select(KbQuote).where(KbQuote.status == "pending_approval")):
        run_case(db, "sales", {"quote_id": q.id, "review": True}, trigger="manual", ref=f"review {q.number}")
    ran = []
    for agent, job in JOB_ORDER:
        if agent == "brief":
            dispatch_events(db)
        run_job(db, agent, job, trigger="schedule")
        ran.append(job)
    dispatch_events(db)
    return {"jobs": ran}


def tick_all() -> list[dict]:
    """Every desk on the knowledge base: sync if due, then tick."""
    from app.kb import sync

    out = []
    admin = SessionLocal()
    try:
        bind_session(admin, None, super_admin=True)
        orgs = [(b.organisation_id, b.source, b.last_sync_at) for b in admin.scalars(select(KbBusiness))]
    finally:
        admin.close()
    for org_id, source, last_sync in orgs:
        db = SessionLocal()
        try:
            bind_session(db, org_id)
            now = clock.now(db)
            if source != "mock" and (
                last_sync is None or now - last_sync >= timedelta(minutes=SYNC_EVERY_MINUTES)
            ):
                sync.run_sync(db)
            result = tick(db)
            db.commit()
            out.append({"organisation_id": org_id, **result})
        except Exception:  # noqa: BLE001 - one desk failing must not stop the others
            db.rollback()
            logger.exception("Agent tick failed for organisation %s", org_id)
        finally:
            db.close()
    return out


def scheduler_enabled() -> bool:
    import ai.config  # noqa: F401 - loads .env

    return (os.getenv("AGENTS_SCHEDULER") or "off").strip().lower() in ("on", "1", "true", "yes")
