"""Shared route dependencies: who is calling, and which desk they belong to.

Every authenticated route depends on `current_user`, and every tenant-scoped
route depends on `tenant_db` rather than on `get_db` directly. That difference
is the whole safety property: `tenant_db` binds the session to the caller's
organisation before any handler runs, so a handler that forgets to filter gets
an empty result instead of another desk's data.

The organisation is taken from the signed token and from nowhere else. It is
never read from a header, a query parameter, or a body, because those are
things a caller can set to somebody else's id.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.security import TokenError, read_token
from app.core.tenancy import bind_session
from app.models import OrgStatus, QuotationRequest, User, UserRole

#: `auto_error=False` so a missing header produces our own 401 with a message
#: a person can act on, rather than FastAPI's bare "Not authenticated".
_bearer = HTTPBearer(auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Please sign in to continue.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """The signed-in user, or 401.

    Four things are checked, and all four have caused real incidents in
    systems that skipped them: the signature, that the account still exists
    and is active, that the token's version still matches the user's (so a
    password change or deactivation invalidates tokens already issued), and
    that the organisation has not been suspended.
    """
    if credentials is None:
        raise _UNAUTHENTICATED

    try:
        payload = read_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Loading the user needs to see across organisations, because the session
    # is not bound yet - this lookup is what determines the binding.
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED

    if payload.get("ver") != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This session is no longer valid. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    organisation = user.organisation
    if organisation is not None and organisation.status is OrgStatus.SUSPENDED:
        raise _unauthorised(
            "This account is suspended. Please contact your administrator."
        )

    return user


CurrentUser = Annotated[User, Depends(current_user)]


def tenant_db(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Generator[Session, None, None]:
    """A session bound to the caller's organisation for the whole request.

    This is the dependency that makes row-level security take effect. A route
    that takes `get_db` instead is unscoped, which is why `test_tenancy.py`
    fails the build if any business route does so.
    """
    if user.is_super_admin:
        # The console legitimately reads across desks. Explicit and separate
        # from the tenant path so it can never be reached by accident.
        bind_session(db, None, super_admin=True)
    else:
        bind_session(db, user.organisation_id)
    yield db


TenantDb = Annotated[Session, Depends(tenant_db)]


def require_admin(user: CurrentUser) -> User:
    """Owner of the desk, or the super admin. For team and settings changes."""
    if not user.can_administer:
        raise _unauthorised(
            "Only the account owner can change this. Ask them to make the change."
        )
    return user


def require_member(user: CurrentUser) -> User:
    """Anyone who may change trading data. Excludes VIEWER."""
    if user.role is UserRole.VIEWER and not user.is_super_admin:
        raise _unauthorised("Your account has read-only access.")
    return user


def require_super_admin(user: CurrentUser) -> User:
    """The platform operator. Onboards desks; never trades inside one."""
    if not user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]
MemberUser = Annotated[User, Depends(require_member)]
SuperAdmin = Annotated[User, Depends(require_super_admin)]


def get_quotation(quotation_id: int, db: TenantDb) -> QuotationRequest:
    """One quotation belonging to the caller's desk.

    Another desk's id yields 404 rather than 403: row-level security means the
    row is genuinely not visible here, and saying "forbidden" would confirm it
    exists to someone who should not know that.
    """
    quotation = db.get(QuotationRequest, quotation_id)
    if quotation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Quotation {quotation_id} not found"
        )
    return quotation


def open_scoped_session(organisation_id: int) -> Session:
    """A bound session for background work that has no request behind it.

    The poller and the scheduler iterate over organisations, so they cannot
    take the binding from a token. Callers are responsible for closing it;
    `app.core.tenancy.as_organisation` is the safer wrapper where a block
    will do.
    """
    db = SessionLocal()
    bind_session(db, organisation_id)
    return db


__all__ = [
    "AdminUser",
    "CurrentUser",
    "MemberUser",
    "SuperAdmin",
    "TenantDb",
    "current_user",
    "get_db",
    "get_quotation",
    "open_scoped_session",
    "require_admin",
    "require_member",
    "require_super_admin",
    "tenant_db",
]
