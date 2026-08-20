"""Sign-in, invitations, and onboarding a new desk.

Deliberately free of HTTP concepts so the rules are testable directly and so
the same logic serves the API, the seeding script, and any future CLI.
"""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.logging import get_logger
from app.core.security import (
    hash_password,
    issue_token,
    new_invite_token,
    verify_password,
)
from app.models import (
    Invite,
    InviteStatus,
    Organisation,
    OrgStatus,
    User,
    UserRole,
)

logger = get_logger(__name__)

#: How long an invitation stays usable. Long enough to survive a weekend,
#: short enough that a forwarded link does not stay live indefinitely.
INVITE_VALID_FOR = timedelta(days=7)

#: Minimum password length. Length beats composition rules for real-world
#: strength, so there is no "must contain a symbol" requirement to work around.
MIN_PASSWORD_LENGTH = 10


class AuthError(RuntimeError):
    """Sign-in or invitation failed, with a message safe to show a caller."""


def normalise_email(email: str) -> str:
    return email.strip().lower()


def slugify(name: str) -> str:
    """A short handle for an organisation, used in logs and the admin console."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:60] or "desk"


def unique_slug(db: Session, name: str) -> str:
    """`slugify`, with a numeric suffix if the handle is taken."""
    base = slugify(name)
    candidate = base
    n = 2
    while db.scalar(select(func.count()).select_from(Organisation).where(Organisation.slug == candidate)):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def check_password_strength(password: str) -> None:
    """Raise if a password is too weak to accept."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(
            f"Choose a password of at least {MIN_PASSWORD_LENGTH} characters."
        )


# --- Sign in ---------------------------------------------------------------


def authenticate(db: Session, email: str, password: str) -> tuple[User, str]:
    """Verify credentials and mint a token, or raise `AuthError`.

    One message covers every failure - unknown address, wrong password,
    deactivated account. Distinguishing them tells an attacker which addresses
    are real, and tells a legitimate user nothing they can act on that
    "check your details" does not.
    """
    address = normalise_email(email)

    # Sign-in necessarily crosses organisations: which desk the caller belongs
    # to is the *answer* here, so it cannot also be the filter.
    user = db.scalars(select(User).where(User.email == address)).first()

    # Verified even when there is no user, so a missing account and a wrong
    # password take the same time and cannot be told apart by timing.
    stored = user.password_hash if user else None
    if not verify_password(password, stored) or user is None or not user.is_active:
        raise AuthError("Those details did not match an account.")

    organisation = user.organisation
    if organisation is not None and organisation.status is OrgStatus.SUSPENDED:
        raise AuthError("This account is suspended. Please contact your administrator.")

    user.last_login_at = utcnow()
    db.commit()

    token = issue_token(
        user_id=user.id,
        organisation_id=user.organisation_id,
        role=user.role.value,
        is_super_admin=user.is_super_admin,
        token_version=user.token_version,
    )
    logger.info("Sign-in: %s (org=%s)", user.email, user.organisation_id)
    return user, token


def change_password(db: Session, user: User, current: str, replacement: str) -> None:
    """Change a password and invalidate every session it had issued."""
    if not verify_password(current, user.password_hash):
        raise AuthError("Your current password is not correct.")
    check_password_strength(replacement)

    user.password_hash = hash_password(replacement)
    # Anyone holding an older token - including whoever may have taken it - is
    # signed out by the change.
    user.token_version += 1
    db.commit()


# --- Onboarding a desk -----------------------------------------------------


def create_organisation(
    db: Session,
    *,
    name: str,
    owner_email: str,
    timezone: str = "Asia/Kolkata",
) -> tuple[Organisation, Invite, str]:
    """Onboard a trading desk and invite its first user as OWNER.

    The super admin never sets the owner's password: an invitation is issued
    and the owner chooses their own. That keeps the platform operator
    incapable of signing in as a customer.
    """
    address = normalise_email(owner_email)
    organisation = Organisation(
        slug=unique_slug(db, name),
        name=name.strip(),
        timezone=timezone,
        status=OrgStatus.ACTIVE,
    )
    db.add(organisation)
    db.flush()

    _seed_defaults(db, organisation.id)

    invite, token = invite_user(
        db, organisation_id=organisation.id, email=address, role=UserRole.OWNER
    )
    db.commit()
    logger.info("Onboarded organisation %s (owner %s)", organisation.slug, address)
    return organisation, invite, token


def _seed_defaults(db: Session, organisation_id: int) -> None:
    """Give a new desk the rules it needs to work on day one.

    Without a follow-up rule nothing is ever chased, and a trader would send
    their first quotation and see the Follow up tab stay empty forever with no
    indication why. Without a pricing rule set the Pricing screen has nothing
    to show and every enquiry prices as unquotable - the desk cannot do the one
    thing it exists to do. These are the rules the product is designed around;
    an owner can edit or disable them once they are in.

    Seeded without committing, so onboarding remains one transaction: a desk is
    never left half-configured by a failure part way through.
    """
    from app.models import FollowUpRule, FollowUpTrigger
    from app.services.pricing import seed_pricing_defaults

    # Pricing is seeded on its own idempotency check rather than the follow-up
    # one below, so a desk created before this was wired in still gets rules.
    seed_pricing_defaults(db, organisation_id=organisation_id, commit=False)

    existing = db.scalars(
        select(FollowUpRule).where(FollowUpRule.organisation_id == organisation_id)
    ).first()
    if existing is not None:
        return

    db.add_all(
        [
            FollowUpRule(
                organisation_id=organisation_id,
                label="Confirm within 24 hours",
                trigger=FollowUpTrigger.ELAPSED,
                first_after_hours=24,
                interval_days=3,
                max_attempts=2,
                is_active=True,
            ),
            FollowUpRule(
                organisation_id=organisation_id,
                label="Follow up on the customer's own date",
                trigger=FollowUpTrigger.PROMISED_DATE,
                first_after_hours=72,
                interval_days=5,
                max_attempts=2,
                is_active=True,
            ),
        ]
    )
    db.flush()


# --- Invitations -----------------------------------------------------------


def invite_user(
    db: Session,
    *,
    organisation_id: int,
    email: str,
    role: UserRole,
    invited_by_id: int | None = None,
) -> tuple[Invite, str]:
    """Invite somebody to a desk. Returns the invite and its plaintext token.

    The plaintext is returned once, for the link, and never stored.
    """
    address = normalise_email(email)

    existing = db.scalars(
        select(User).where(
            User.organisation_id == organisation_id, User.email == address
        )
    ).first()
    if existing is not None:
        raise AuthError(f"{address} is already on this team.")

    # Re-inviting supersedes any outstanding invitation rather than leaving
    # two live links for one address.
    for stale in db.scalars(
        select(Invite).where(
            Invite.organisation_id == organisation_id,
            Invite.email == address,
            Invite.status == InviteStatus.PENDING,
        )
    ):
        stale.status = InviteStatus.REVOKED

    token, token_hash = new_invite_token()
    invite = Invite(
        organisation_id=organisation_id,
        email=address,
        role=role,
        token_hash=token_hash,
        expires_at=utcnow() + INVITE_VALID_FOR,
        invited_by_id=invited_by_id,
    )
    db.add(invite)
    db.flush()
    db.commit()
    return invite, token


def accept_invite(
    db: Session, *, token: str, name: str, password: str
) -> tuple[User, str]:
    """Turn an invitation into an account, and sign the person in.

    Runs unauthenticated - the caller has only the link - so the token lookup
    must not be scoped to an organisation. It is safe because the token is 256
    bits of randomness and single-use.
    """
    from app.core.security import hash_invite_token

    check_password_strength(password)

    invite = db.scalars(
        select(Invite).where(Invite.token_hash == hash_invite_token(token))
    ).first()

    if invite is None or invite.status is not InviteStatus.PENDING:
        raise AuthError("This invitation is no longer valid. Ask for a new one.")
    if invite.expires_at < utcnow():
        invite.status = InviteStatus.EXPIRED
        db.commit()
        raise AuthError("This invitation has expired. Ask for a new one.")

    user = User(
        organisation_id=invite.organisation_id,
        name=name.strip(),
        email=invite.email,
        password_hash=hash_password(password),
        role=invite.role,
        is_active=True,
    )
    db.add(user)

    invite.status = InviteStatus.ACCEPTED
    invite.accepted_at = utcnow()
    db.flush()

    user.last_login_at = utcnow()
    db.commit()

    access = issue_token(
        user_id=user.id,
        organisation_id=user.organisation_id,
        role=user.role.value,
        is_super_admin=False,
        token_version=user.token_version,
    )
    logger.info("Invitation accepted: %s (org=%s)", user.email, user.organisation_id)
    return user, access


def deactivate_user(db: Session, user: User) -> None:
    """Remove someone's access without deleting what they did.

    Their approvals and audit rows must survive - "who agreed this price" has
    to keep an answer after somebody leaves.
    """
    user.is_active = False
    user.token_version += 1
    db.commit()


__all__ = [
    "AuthError",
    "accept_invite",
    "authenticate",
    "change_password",
    "check_password_strength",
    "create_organisation",
    "deactivate_user",
    "invite_user",
    "normalise_email",
    "slugify",
]
