"""The business clock.

A live desk runs on real time. A desk on mock data runs on the data's own
"today" (19 Oct 2026, 10:30 am), frozen, so the planted situations stay true
however long ago the data was loaded; `advance()` moves it forward on purpose.
Every agent asks this module what time it is, never `datetime.now()`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.kb.models import KbBusiness

IST = ZoneInfo("Asia/Kolkata")


def business(db: Session) -> KbBusiness:
    """The bound desk's business row (created on first use)."""
    biz = db.scalars(select(KbBusiness)).first()
    if biz is None:
        biz = KbBusiness()
        db.add(biz)
        db.flush()
    return biz


def now(db: Session) -> datetime:
    biz = business(db)
    return biz.as_of.astimezone(IST) if biz.as_of else utcnow().astimezone(IST)


def today(db: Session) -> date:
    return now(db).date()


def advance(db: Session, hours: float) -> datetime:
    """Move a frozen clock forward (mock desks only)."""
    biz = business(db)
    if biz.as_of is None:
        raise ValueError("This desk runs on real time; its clock cannot be moved.")
    biz.as_of = biz.as_of + timedelta(hours=hours)
    db.flush()
    return biz.as_of


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST)
