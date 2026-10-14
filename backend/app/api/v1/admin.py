"""The platform operator's console: onboard desks, suspend them, look in.

Every route here requires `SuperAdmin`, which returns **404** rather than 403
for anybody else. A trader probing these paths learns nothing about whether an
admin surface exists at all.

The operator onboards a desk and issues an invitation; they never set a
customer's password and have no route that signs them in as one. Support
access, if it is ever needed, should be an explicit and audited impersonation
feature rather than a side effect of being able to write to the users table.
"""

from __future__ import annotations

from typing import Annotated

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import SuperAdmin, get_db
from app.core.config import settings
from app.core.tenancy import bind_session
from app.models import (
    Lead,
    Mailbox,
    Organisation,
    OrgStatus,
    QuotationRequest,
    User,
    UserRole,
)
from app.schemas.auth import (
    CreateOrganisationIn,
    InviteIn,
    InviteOut,
    MailboxOut,
    OrganisationDetailOut,
    OrganisationSummaryOut,
    UserOut,
)
from app.services import auth as auth_service
from app.services.auth import AuthError

router = APIRouter(prefix="/admin", tags=["admin"])

Db = Annotated[Session, Depends(get_db)]


def _super_admin_db(db: Session) -> Session:
    """Bind the session to the cross-organisation sentinel.

    Needed because the policies compare against an explicit value: without
    this the console would correctly see nothing at all.
    """
    bind_session(db, None, super_admin=True)
    return db


@router.get("/organisations", response_model=list[OrganisationSummaryOut])
def list_organisations(admin: SuperAdmin, db: Db) -> list[OrganisationSummaryOut]:
    """Every desk, with the counts that show whether one is actually working."""
    _super_admin_db(db)

    users = dict(
        db.execute(
            select(User.organisation_id, func.count(User.id)).group_by(User.organisation_id)
        ).all()
    )
    mailboxes = dict(
        db.execute(
            select(Mailbox.organisation_id, func.count(Mailbox.id)).group_by(
                Mailbox.organisation_id
            )
        ).all()
    )
    quotations = dict(
        db.execute(
            select(
                QuotationRequest.organisation_id, func.count(QuotationRequest.id)
            ).group_by(QuotationRequest.organisation_id)
        ).all()
    )

    out: list[OrganisationSummaryOut] = []
    for org in db.scalars(select(Organisation).order_by(Organisation.name)):
        summary = OrganisationSummaryOut.model_validate(org)
        summary.user_count = users.get(org.id, 0)
        summary.mailbox_count = mailboxes.get(org.id, 0)
        summary.quotation_count = quotations.get(org.id, 0)
        summary.created_at = org.created_at
        out.append(summary)
    return out


@router.post(
    "/organisations",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_organisation(
    payload: CreateOrganisationIn, admin: SuperAdmin, db: Db
) -> InviteOut:
    """Onboard a trading desk and invite its owner.

    Returns the invitation, including the one-time link. Nothing is usable by
    the desk until its owner follows that link and chooses a password.
    """
    _super_admin_db(db)
    try:
        _, invite, token = auth_service.create_organisation(
            db,
            name=payload.name,
            owner_email=payload.owner_email,
            timezone=payload.timezone,
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    base = settings.cors_origins.split(",")[0].strip().rstrip("/")
    out = InviteOut.model_validate(invite)
    out.invite_url = f"{base}/accept-invite?token={token}"
    return out


@router.post("/organisations/{organisation_id}/suspend", response_model=OrganisationSummaryOut)
def suspend(organisation_id: int, admin: SuperAdmin, db: Db) -> OrganisationSummaryOut:
    """Stop a desk signing in and stop crawling its mail. Data is retained.

    Non-payment should not destroy a customer's records - suspension is
    reversible, deletion is not, and the two are deliberately separate.
    """
    _super_admin_db(db)
    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    organisation.status = OrgStatus.SUSPENDED
    # Every live session ends immediately rather than lasting until its token
    # expires, which for a suspension is the whole point.
    for person in db.scalars(select(User).where(User.organisation_id == organisation_id)):
        person.token_version += 1
    db.commit()
    db.refresh(organisation)
    return OrganisationSummaryOut.model_validate(organisation)


@router.post("/organisations/{organisation_id}/reactivate", response_model=OrganisationSummaryOut)
def reactivate(organisation_id: int, admin: SuperAdmin, db: Db) -> OrganisationSummaryOut:
    _super_admin_db(db)
    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    organisation.status = OrgStatus.ACTIVE
    db.commit()
    db.refresh(organisation)
    return OrganisationSummaryOut.model_validate(organisation)


@router.get("/overview")
def platform_overview(admin: SuperAdmin, db: Db) -> dict[str, object]:
    """The numbers an operator checks first thing.

    Chosen to answer "is the platform healthy" rather than to look busy:
    desks that signed up but never connected a mailbox are stalled
    onboardings, and mailboxes in error are customers whose mail has silently
    stopped arriving.
    """
    from datetime import timedelta

    from app.core.db import utcnow
    from app.models import Email, MailboxStatus

    _super_admin_db(db)
    week_ago = utcnow() - timedelta(days=7)

    desks = db.scalar(select(func.count()).select_from(Organisation)) or 0
    active = (
        db.scalar(
            select(func.count())
            .select_from(Organisation)
            .where(Organisation.status == OrgStatus.ACTIVE)
        )
        or 0
    )
    with_mailbox = (
        db.scalar(select(func.count(func.distinct(Mailbox.organisation_id)))) or 0
    )
    broken = (
        db.scalar(
            select(func.count())
            .select_from(Mailbox)
            .where(Mailbox.status.in_([MailboxStatus.ERROR, MailboxStatus.NEEDS_RECONNECT]))
        )
        or 0
    )

    return {
        "desks": desks,
        "active_desks": active,
        "suspended_desks": desks - active,
        # The gap that matters: signed up, never connected anything.
        "desks_without_mailbox": desks - with_mailbox,
        "mailboxes_needing_attention": broken,
        "people": db.scalar(select(func.count()).select_from(User)) or 0,
        "quotations": db.scalar(select(func.count()).select_from(QuotationRequest)) or 0,
        "emails_this_week": db.scalar(
            select(func.count()).select_from(Email).where(Email.received_at >= week_ago)
        )
        or 0,
    }


@router.get("/organisations/{organisation_id}", response_model=OrganisationDetailOut)
def organisation_detail(
    organisation_id: int, admin: SuperAdmin, db: Db
) -> OrganisationDetailOut:
    """One desk in full, for answering a support question about it."""
    from app.models import Email, MailboxStatus

    _super_admin_db(db)
    org = db.get(Organisation, organisation_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    detail = OrganisationDetailOut.model_validate(org)
    detail.created_at = org.created_at
    detail.users = [
        UserOut.model_validate(u)
        for u in db.scalars(
            select(User).where(User.organisation_id == organisation_id).order_by(User.name)
        )
    ]
    detail.mailboxes = [
        MailboxOut.model_validate(m)
        for m in db.scalars(select(Mailbox).where(Mailbox.organisation_id == organisation_id))
    ]
    detail.user_count = len(detail.users)
    detail.mailbox_count = len(detail.mailboxes)
    detail.quotation_count = (
        db.scalar(
            select(func.count())
            .select_from(QuotationRequest)
            .where(QuotationRequest.organisation_id == organisation_id)
        )
        or 0
    )
    detail.email_count = (
        db.scalar(
            select(func.count())
            .select_from(Email)
            .where(Email.organisation_id == organisation_id)
        )
        or 0
    )
    detail.needs_attention = any(
        m.status in (MailboxStatus.ERROR.value, MailboxStatus.NEEDS_RECONNECT.value)
        for m in detail.mailboxes
    )
    return detail


@router.post("/organisations/{organisation_id}/invite-owner", response_model=InviteOut)
def invite_another_owner(
    organisation_id: int, payload: InviteIn, admin: SuperAdmin, db: Db
) -> InviteOut:
    """Issue a fresh owner invitation for a desk.

    The recovery path when a desk's only owner has left or lost their
    password. Deliberately an *invitation* rather than a password reset: the
    operator still never learns a customer's credentials.
    """
    _super_admin_db(db)
    if db.get(Organisation, organisation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    try:
        invite, token = auth_service.invite_user(
            db,
            organisation_id=organisation_id,
            email=payload.email,
            role=UserRole.OWNER,
            invited_by_id=admin.id,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    base = settings.cors_origins.split(",")[0].strip().rstrip("/")
    out = InviteOut.model_validate(invite)
    out.invite_url = f"{base}/accept-invite?token={token}"
    return out


@router.delete("/organisations/{organisation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organisation(
    organisation_id: int, admin: SuperAdmin, db: Db, confirm: str = ""
) -> None:
    """Permanently remove a desk and everything belonging to it.

    Requires the desk's slug typed back as `confirm`. Suspension is the
    reversible action and should be the usual one; this exists for a customer
    who has asked to be deleted, and it cannot be undone.
    """
    _super_admin_db(db)
    org = db.get(Organisation, organisation_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if confirm != org.slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"To delete this desk permanently, confirm with its handle: {org.slug}",
        )
    # Cascades to every tenant table through the FK on organisation_id.
    db.delete(org)
    db.commit()


@router.get("/organisations/{organisation_id}/users", response_model=list[UserOut])
def organisation_users(organisation_id: int, admin: SuperAdmin, db: Db) -> list[UserOut]:
    """Who is on a desk, for answering a support question about access."""
    _super_admin_db(db)
    people = db.scalars(
        select(User).where(User.organisation_id == organisation_id).order_by(User.name)
    )
    return [UserOut.model_validate(p) for p in people]


__all__ = ["router"]


class LeadOut(BaseModel):
    """A design-partner request from the marketing site, for the admin list."""

    id: int
    created_at: datetime
    name: str
    company: str
    email: str
    phone: str
    monthly_enquiries: str | None
    note: str | None
    source: str
    status: str

    model_config = {"from_attributes": True}


#: The pipeline the operator moves a request through. Kept here (not an ORM
#: enum) so stages can change without a migration.
LEAD_STATUSES = ("new", "contacted", "qualified", "won", "lost")


class LeadStatusIn(BaseModel):
    status: str


@router.get("/leads", response_model=list[LeadOut])
def list_leads(admin: SuperAdmin, db: Db) -> list[LeadOut]:
    """Every incoming design-partner request, newest first.

    `leads` is a platform-level table (no organisation_id, no RLS), so this
    reads it directly on the super-admin session.
    """
    _super_admin_db(db)
    rows = db.scalars(select(Lead).order_by(Lead.created_at.desc())).all()
    return [LeadOut.model_validate(r) for r in rows]


@router.patch("/leads/{lead_id}", response_model=LeadOut)
def update_lead_status(lead_id: int, payload: LeadStatusIn, admin: SuperAdmin, db: Db) -> LeadOut:
    """Move a request to another pipeline stage."""
    if payload.status not in LEAD_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown status. Use one of: {', '.join(LEAD_STATUSES)}.",
        )
    _super_admin_db(db)
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such request.")
    lead.status = payload.status
    db.commit()
    db.refresh(lead)
    return LeadOut.model_validate(lead)
