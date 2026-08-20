"""Sign-in, invitations, team, and the desk's own settings.

Split by who may call:

* `/auth/*` - unauthenticated. Sign in, accept an invitation.
* `/auth/me`, `/team/*`, `/organisation` - the signed-in desk.
* `/admin/*` (in `admin.py`) - the platform operator.

These routes take `get_db` rather than `tenant_db` where they must work before
a tenant is known - signing in is how the tenant gets determined. Every route
that touches business data uses `tenant_db`, and a test enforces that.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AdminUser, CurrentUser, TenantDb, get_db
from app.core.config import settings
from app.core.db import utcnow
from app.models import Invite, InviteStatus, Organisation, User, UserRole
from app.schemas.auth import (
    AcceptInviteIn,
    ChangePasswordIn,
    CrawlStatusOut,
    InviteIn,
    InviteOut,
    LoginIn,
    MailboxOut,
    OrganisationOut,
    OrganisationUpdateIn,
    SessionOut,
    UserOut,
)
from app.services import auth as auth_service
from app.services.auth import AuthError
from app.services.crawl_window import decide, local_now

router = APIRouter(tags=["auth"])

Db = Annotated[Session, Depends(get_db)]


def _session_out(user: User, token: str) -> SessionOut:
    return SessionOut(
        access_token=token,
        user=UserOut.model_validate(user),
        organisation=(
            OrganisationOut.model_validate(user.organisation)
            if user.organisation
            else None
        ),
    )


def _callback_uri(request: Request) -> str:
    """Where Google returns after consent.

    Derived from the running server rather than configured separately, so it
    cannot drift from what the browser actually reaches - and so the value
    shown in a setup error is exactly the one to register with Google.
    """
    return str(request.base_url).rstrip("/") + "/api/v1/organisation/mailbox/callback"


def _invite_url(token: str) -> str:
    """The link the invited person follows. Shown once and never stored."""
    base = settings.cors_origins.split(",")[0].strip().rstrip("/")
    return f"{base}/accept-invite?token={token}"


# --- Unauthenticated -------------------------------------------------------


@router.post("/auth/login", response_model=SessionOut)
def login(payload: LoginIn, db: Db) -> SessionOut:
    try:
        user, token = auth_service.authenticate(db, payload.email, payload.password)
    except AuthError as exc:
        # 401 with one message for every cause - see `authenticate`.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    return _session_out(user, token)


@router.post("/auth/accept-invite", response_model=SessionOut)
def accept_invite(payload: AcceptInviteIn, db: Db) -> SessionOut:
    """Set a password from an invitation link and sign in."""
    try:
        user, token = auth_service.accept_invite(
            db, token=payload.token, name=payload.name, password=payload.password
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _session_out(user, token)


# --- The signed-in user ----------------------------------------------------


@router.get("/auth/me", response_model=SessionOut)
def me(user: CurrentUser) -> SessionOut:
    """Who am I. Used on page load to restore a session.

    Returns the stored token's own bearer rather than minting a new one, so
    refreshing a page does not extend a session indefinitely.
    """
    return SessionOut(
        access_token="",
        user=UserOut.model_validate(user),
        organisation=(
            OrganisationOut.model_validate(user.organisation) if user.organisation else None
        ),
    )


@router.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: ChangePasswordIn, user: CurrentUser, db: Db) -> None:
    try:
        auth_service.change_password(
            db, user, payload.current_password, payload.new_password
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


# --- The team --------------------------------------------------------------


@router.get("/team", response_model=list[UserOut])
def list_team(user: CurrentUser, db: TenantDb) -> list[UserOut]:
    """Everyone on this desk. Scoped by RLS, not by this query's filter."""
    people = db.scalars(select(User).order_by(User.name))
    return [UserOut.model_validate(p) for p in people]


@router.post("/team/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(payload: InviteIn, admin: AdminUser, db: TenantDb) -> InviteOut:
    """Invite a colleague. Owner only."""
    try:
        role = UserRole(payload.role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{payload.role} is not a role. Choose OWNER, MEMBER or VIEWER.",
        ) from exc

    try:
        invite, token = auth_service.invite_user(
            db,
            organisation_id=admin.organisation_id,
            email=payload.email,
            role=role,
            invited_by_id=admin.id,
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    out = InviteOut.model_validate(invite)
    # The only moment the plaintext exists outside the invited person's inbox.
    out.invite_url = _invite_url(token)
    return out


@router.get("/team/invites", response_model=list[InviteOut])
def list_invites(admin: AdminUser, db: TenantDb) -> list[InviteOut]:
    invites = db.scalars(
        select(Invite)
        .where(Invite.status == InviteStatus.PENDING)
        .order_by(Invite.created_at.desc())
    )
    return [InviteOut.model_validate(i) for i in invites]


@router.delete("/team/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(invite_id: int, admin: AdminUser, db: TenantDb) -> None:
    invite = db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    invite.status = InviteStatus.REVOKED
    db.commit()


@router.post("/team/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate(user_id: int, admin: AdminUser, db: TenantDb) -> None:
    """Remove someone's access, keeping what they did.

    An owner cannot deactivate themselves: a desk with nobody able to
    administer it can only be recovered by the platform operator.
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account.",
        )
    person = db.get(User, user_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    auth_service.deactivate_user(db, person)


# --- The organisation ------------------------------------------------------


@router.get("/organisation", response_model=OrganisationOut)
def get_organisation(user: CurrentUser) -> OrganisationOut:
    if user.organisation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This account is not attached to an organisation.",
        )
    return OrganisationOut.model_validate(user.organisation)


@router.patch("/organisation", response_model=OrganisationOut)
def update_organisation(
    payload: OrganisationUpdateIn, admin: AdminUser, db: TenantDb
) -> OrganisationOut:
    """Change desk settings, including the mail crawl window. Owner only."""
    organisation = db.get(Organisation, admin.organisation_id)
    if organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if payload.timezone is not None:
        # Validated here rather than at poll time: a typo should be rejected
        # while somebody is looking at the form, not silently fall back to UTC
        # hours later in a background job.
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(payload.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{payload.timezone} is not a known timezone.",
            ) from exc

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(organisation, field, value)
    organisation.updated_at = utcnow()
    db.commit()
    db.refresh(organisation)
    return OrganisationOut.model_validate(organisation)


@router.get("/organisation/crawl-status", response_model=CrawlStatusOut)
def crawl_status(user: CurrentUser, db: TenantDb) -> CrawlStatusOut:
    """What the poller is doing right now, and why.

    Exists so "why has no mail arrived since 10pm" is answerable in the
    interface instead of by reading server logs.
    """
    from app.models import Mailbox

    organisation = user.organisation
    if organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    decision = decide(organisation)
    last = db.scalars(
        select(Mailbox.last_polled_at).order_by(Mailbox.last_polled_at.desc()).limit(1)
    ).first()

    return CrawlStatusOut(
        enabled=organisation.crawl_enabled,
        active_now=decision.active,
        interval_minutes=decision.interval_minutes,
        reason=decision.reason,
        local_time=local_now(organisation).strftime("%H:%M"),
        last_polled_at=last,
    )


# --- The enquiry mailbox ---------------------------------------------------


@router.get("/organisation/mailbox/connect-url")
def mailbox_connect_url(admin: AdminUser, request: Request) -> dict[str, str]:
    """Where to send the owner to approve access to their mailbox.

    The redirect must match what is registered with Google exactly, so it is
    derived from the running server rather than configured in a second place
    that can drift.
    """
    from app.services.mailbox import MailboxError, consent_url

    redirect = _callback_uri(request)
    try:
        return {"url": consent_url(admin.organisation_id, redirect), "redirect_uri": redirect}
    except MailboxError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get("/organisation/mailbox/setup")
def mailbox_setup(admin: AdminUser, request: Request) -> dict[str, object]:
    """Whether Google connection is usable, and what to fix if not.

    A GET the page can render from, rather than discovering the problem by
    making a request that fails. Owner-only because the answer names the
    deployment's own configuration.
    """
    from app.services.mailbox import MailboxError, check_redirect_registered

    redirect = _callback_uri(request)
    try:
        problem = check_redirect_registered(redirect)
    except MailboxError as exc:
        return {"ready": False, "redirect_uri": redirect, "problem": str(exc)}
    return {"ready": problem is None, "redirect_uri": redirect, "problem": problem}


@router.get("/organisation/mailbox/callback", include_in_schema=False)
def mailbox_callback(
    request: Request,
    db: Db,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Where Google returns after consent.

    Unauthenticated by necessity - the browser arrives from Google carrying no
    session header. The organisation comes from the signed `state`, which is
    why that signature matters: this URL is public.
    """
    from app.core.tenancy import bind_session
    from app.services.mailbox import MailboxError, complete_connection, read_state

    app_url = settings.cors_origins.split(",")[0].strip().rstrip("/")

    def back(message: str, ok: bool) -> RedirectResponse:
        from urllib.parse import quote

        flag = "connected" if ok else "error"
        return RedirectResponse(f"{app_url}/mail-schedule?{flag}={quote(message)}")

    if error or not code or not state:
        return back("Connection was cancelled.", ok=False)

    try:
        organisation_id = read_state(state)
        bind_session(db, organisation_id)
        redirect = _callback_uri(request)
        mailbox = complete_connection(
            db, organisation_id=organisation_id, code=code, redirect_uri=redirect
        )
    except MailboxError as exc:
        return back(str(exc), ok=False)

    return back(mailbox.email_address, ok=True)


@router.post("/organisation/mailbox/sample", response_model=MailboxOut)
def connect_sample_mailbox(admin: AdminUser, db: TenantDb) -> MailboxOut:
    """Attach the sample mailbox, to see the system work before connecting Gmail."""
    from app.services.mailbox import connect_local

    return MailboxOut.model_validate(connect_local(db, admin.organisation_id))


@router.delete("/organisation/mailbox/{mailbox_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_mailbox(mailbox_id: int, admin: AdminUser, db: TenantDb) -> None:
    """Stop reading a mailbox. Mail already received is kept."""
    from app.models import Mailbox
    from app.services.mailbox import disconnect

    mailbox = db.get(Mailbox, mailbox_id)
    if mailbox is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    disconnect(db, mailbox)


@router.post("/organisation/mailbox/check-now")
def check_mailbox_now(admin: AdminUser, db: TenantDb) -> dict[str, object]:
    """Run a poll immediately, rather than waiting for the schedule.

    Traders reach for this the moment they connect a mailbox, and telling them
    to wait ten minutes to find out whether it worked is a poor first
    impression.
    """
    from app.services.poller import poll_one_organisation

    result = poll_one_organisation(db, admin.organisation_id)
    return {
        "checked": result.checked,
        "ingested": result.ingested,
        "failures": result.failures,
    }


@router.get("/organisation/mailboxes", response_model=list[MailboxOut])
def list_mailboxes(user: CurrentUser, db: TenantDb) -> list[MailboxOut]:
    from app.models import Mailbox

    boxes = db.scalars(select(Mailbox).order_by(Mailbox.id))
    return [MailboxOut.model_validate(b) for b in boxes]


__all__ = ["router"]
