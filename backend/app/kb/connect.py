"""Put a real desk on the agents: point it at its Tally and load the books.

    uv run python scripts/oprisa_connect.py <org-slug> --tally-url http://192.168.1.20:9000

What it does for one existing organisation:
  1. `kb_business` with source "tally_xml" and the connector address
     (or updates it, keeping everything already synced)
  2. a desk role for every active user who has none yet: the owner is
     "owner", everyone else "sales" until changed (`set_role`)
  3. the first sync - every master and voucher since AlterID 0 - then facts
     and one full agent cycle, so the Inbox fills from the real books

If Tally can't be reached the desk is still created; the failed sync is
recorded and every tick retries it (see jobs.tick_all). Nothing here touches
the mock data path, and nothing downstream of the sync knows the difference.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenancy import bind_session
from app.kb import facts, sync
from app.kb.models import KbBusiness, KbMember
from app.models import Organisation, User, UserRole

logger = get_logger(__name__)

DESK_ROLES = ("owner", "accounts", "sales", "purchase")


def connect_desk(
    db: Session,
    slug: str,
    tally_url: str,
    *,
    trade: str = "steel",
    city: str | None = None,
    language: str = "English",
    tally_version: str = "TallyPrime",
    run_agents: bool = True,
) -> dict:
    """`db` must be a super-admin session; it is bound to the desk on the way."""
    org = db.scalars(select(Organisation).where(Organisation.slug == slug)).first()
    if org is None:
        raise ValueError(f"No organisation with slug {slug!r}.")
    if not tally_url.startswith(("http://", "https://")):
        raise ValueError("The Tally connector address must start with http:// or https://")
    bind_session(db, org.id)

    biz = db.scalars(select(KbBusiness)).first()
    if biz is not None and biz.source == "mock":
        raise ValueError(
            "This desk runs on sample books. Re-create it as a real desk rather than mixing the two."
        )
    if biz is None:
        biz = KbBusiness(organisation_id=org.id, source="tally_xml")
        db.add(biz)
    biz.source_url = tally_url.rstrip("/")
    biz.trade, biz.city, biz.language, biz.tally_version = trade, city, language, tally_version
    biz.as_of = None  # real time
    db.flush()

    have = set(db.scalars(select(KbMember.user_id)))
    added = 0
    for u in db.scalars(select(User).where(User.organisation_id == org.id, User.is_active.is_(True))):
        if u.id not in have:
            role = "owner" if u.role == UserRole.OWNER else "sales"
            db.add(KbMember(organisation_id=org.id, user_id=u.id, desk_role=role))
            added += 1
    db.flush()

    run = sync.run_sync(db, refresh_facts=False)
    out = {
        "organisation": org.name,
        "members_added": added,
        "sync": run.status,
        "error": run.error,
        "objects": run.objects_read,
    }
    if run.status == "ok":
        facts.refresh(db, kpi_history=True)
        db.flush()
        if run_agents:
            from app.kb.jobs import first_run

            out["first_run"] = first_run(db)
    logger.info("Connected %s to %s: sync %s", org.name, biz.source_url, run.status)
    return out


def set_role(db: Session, slug: str, email: str, desk_role: str) -> None:
    """Change whose Inbox a person's tasks land in."""
    if desk_role not in DESK_ROLES:
        raise ValueError(f"Desk role must be one of {', '.join(DESK_ROLES)}.")
    org = db.scalars(select(Organisation).where(Organisation.slug == slug)).first()
    if org is None:
        raise ValueError(f"No organisation with slug {slug!r}.")
    bind_session(db, org.id)
    user = db.scalars(select(User).where(User.organisation_id == org.id, User.email == email)).first()
    if user is None:
        raise ValueError(f"No user {email} on {org.name}.")
    member = db.scalars(select(KbMember).where(KbMember.user_id == user.id)).first()
    if member is None:
        db.add(KbMember(organisation_id=org.id, user_id=user.id, desk_role=desk_role))
    else:
        member.desk_role = desk_role
    db.flush()
