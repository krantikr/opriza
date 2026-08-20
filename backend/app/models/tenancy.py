"""Organisations, their people, and the invitations that create them.

Steel Desk is one deployment serving many trading desks who compete with each
other. Two of them seeing each other's customer lists or pricing is the worst
failure this system can have - worse than being down, because nobody notices.

So isolation is enforced in three places, deliberately overlapping:

1. **Postgres row-level security.** Every tenant table carries
   `organisation_id` and a policy keyed on `app.org_id`. A query that forgets
   to filter returns *nothing* rather than another desk's rows. See
   `app.core.tenancy` for how the setting is applied per request.
2. **The application session**, which sets that variable from the caller's
   token and never from anything a request body can influence.
3. **Tests** that ask, as one desk, for another desk's rows and require an
   empty answer.

The database is the one that actually holds. The other two are how mistakes
get caught early, but RLS is what makes a missed `WHERE` clause a bug rather
than a breach.
"""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import (
    InviteStatus,
    MailboxStatus,
    OrgStatus,
    UserRole,
)
from app.models.mixins import TimestampMixin, enum_col


class Organisation(Base, TimestampMixin):
    """One trading desk. The unit of isolation for every other table.

    Deliberately *not* carrying an `organisation_id` of its own: it is the
    tenant, so it is scoped by id, and the super admin is the only actor who
    sees more than one row.
    """

    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Stable, human-readable handle used in logs and the admin console, where
    #: a numeric id makes an incident harder to read than it needs to be.
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    status: Mapped[OrgStatus] = mapped_column(
        enum_col(OrgStatus), default=OrgStatus.ACTIVE, nullable=False, index=True
    )

    # --- Identity used on outgoing quotations ---------------------------
    # Previously read from .env, which cannot work once one process serves
    # several desks: every trader would sign off as the same company.
    company_email: Mapped[str | None] = mapped_column(String(255))
    company_phone: Mapped[str | None] = mapped_column(String(40))
    company_signatory: Mapped[str | None] = mapped_column(String(120))

    # --- Mail crawl window ----------------------------------------------
    # A desk's working day is local to that desk. Storing an IANA zone rather
    # than an offset keeps this correct across DST without anyone editing it.
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Kolkata", nullable=False)
    #: Start of the active window, in the organisation's own timezone.
    crawl_active_from: Mapped[time] = mapped_column(default=time(8, 0), nullable=False)
    #: End of the active window. May be earlier than `crawl_active_from`, which
    #: means the window crosses midnight - see `is_active_at`.
    crawl_active_to: Mapped[time] = mapped_column(default=time(22, 0), nullable=False)
    #: How often to poll inside the window, and outside it.
    crawl_active_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    crawl_quiet_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    crawl_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list[User]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )
    mailboxes: Mapped[list[Mailbox]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )
    invites: Mapped[list[Invite]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Organisation {self.slug}>"


class User(Base, TimestampMixin):
    """A person who signs in. Belongs to exactly one organisation.

    The super admin is the single exception: `organisation_id` is null and
    `is_super_admin` is set. They onboard desks and never appear inside one,
    so no trader can be an accidental super admin by editing their own row.
    """

    __tablename__ = "app_users"
    __table_args__ = (
        # Email is unique per organisation, not globally: the same person may
        # legitimately work for two desks, and one desk's sign-up must not be
        # able to probe whether an address exists elsewhere.
        UniqueConstraint("organisation_id", "email", name="uq_user_org_email"),
        Index("ix_app_users_email", "email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Argon2id. Null for a user who has been invited but not yet set one.
    password_hash: Mapped[str | None] = mapped_column(String(255))

    role: Mapped[UserRole] = mapped_column(
        enum_col(UserRole), default=UserRole.MEMBER, nullable=False
    )
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column()
    #: Bumped to invalidate every issued token for this user at once - used by
    #: password change and by an owner deactivating someone.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    organisation: Mapped[Organisation | None] = relationship(back_populates="users")

    @property
    def can_administer(self) -> bool:
        """Whether this user may change org settings, billing and team."""
        return self.is_super_admin or self.role is UserRole.OWNER

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email} org={self.organisation_id}>"


class Mailbox(Base, TimestampMixin):
    """A connected enquiry mailbox belonging to one organisation.

    Replaces the single credential file path in `.env`, which could only ever
    describe one desk's mailbox. Refresh tokens are encrypted at rest by
    `app.core.crypto` - a database backup should not be a set of live Gmail
    credentials for every customer.
    """

    __tablename__ = "mailboxes"
    __table_args__ = (
        UniqueConstraint("organisation_id", "email_address", name="uq_mailbox_org_address"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(String(20), default="GMAIL", nullable=False)
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)

    #: Encrypted OAuth refresh token. Never logged, never serialised outward.
    refresh_token_enc: Mapped[str | None] = mapped_column(String(2000))
    token_expires_at: Mapped[datetime | None] = mapped_column()

    status: Mapped[MailboxStatus] = mapped_column(
        enum_col(MailboxStatus), default=MailboxStatus.DISCONNECTED, nullable=False
    )
    #: Why the last poll failed, in words a trader can act on. Kept because a
    #: silently disconnected mailbox looks exactly like a quiet week.
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_polled_at: Mapped[datetime | None] = mapped_column()
    #: Gmail's own cursor, so a reconnect does not re-ingest the whole inbox.
    history_id: Mapped[str | None] = mapped_column(String(60))

    organisation: Mapped[Organisation] = relationship(back_populates="mailboxes")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Mailbox {self.email_address} org={self.organisation_id}>"


class Invite(Base, TimestampMixin):
    """A pending invitation to join an organisation.

    Only the hash of the token is stored. An invite link is a credential until
    it is used, and a leaked database should not hand out working ones.
    """

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[UserRole] = mapped_column(
        enum_col(UserRole), default=UserRole.MEMBER, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[InviteStatus] = mapped_column(
        enum_col(InviteStatus), default=InviteStatus.PENDING, nullable=False, index=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column()
    invited_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )

    organisation: Mapped[Organisation] = relationship(back_populates="invites")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Invite {self.email} org={self.organisation_id} {self.status}>"


__all__ = ["Invite", "Mailbox", "Organisation", "User"]
