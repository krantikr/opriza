"""Request and response shapes for authentication and tenancy."""

from __future__ import annotations

from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginIn(BaseModel):
    # Deliberately a plain string, not EmailStr. Sign-in should compare what
    # was typed against what is stored; rejecting an address at the schema
    # tells an unauthenticated caller which addresses are well-formed enough
    # to exist, and locks out any account whose address the validator happens
    # to dislike.
    email: str
    password: str


class AcceptInviteIn(BaseModel):
    token: str
    name: str = Field(min_length=1, max_length=120)
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    is_super_admin: bool
    is_active: bool
    last_login_at: datetime | None = None


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    status: str
    timezone: str
    company_email: str | None = None
    company_phone: str | None = None
    company_signatory: str | None = None
    crawl_active_from: time
    crawl_active_to: time
    crawl_active_minutes: int
    crawl_quiet_minutes: int
    crawl_enabled: bool
    #: Null means the desk has not overridden the built-in wording. The editor
    #: shows the default in that case rather than an empty box, so what is on
    #: screen is always what would actually be sent.
    followup_subject_template: str | None = None
    followup_body_template: str | None = None


class PlaceholderOut(BaseModel):
    """One substitution a template may use, and what it means."""

    name: str
    description: str


class EmailTemplatesOut(BaseModel):
    """The desk's wording, the built-in default, and what may be used."""

    followup_subject_template: str | None = None
    followup_body_template: str | None = None
    default_followup_subject: str
    default_followup_body: str
    placeholders: list[PlaceholderOut]


class SessionOut(BaseModel):
    """What the frontend needs after a sign-in: the token and who you are."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut
    #: Null for the super admin, who belongs to no desk.
    organisation: OrganisationOut | None = None


class InviteIn(BaseModel):
    email: EmailStr
    role: str = "MEMBER"


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    status: str
    expires_at: datetime
    #: Only ever populated on the response that creates it. Stored hashed, so
    #: it can never be shown again - the owner must re-invite instead.
    invite_url: str | None = None


class OrganisationUpdateIn(BaseModel):
    """Settings a desk owner may change about their own organisation."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = None
    company_email: EmailStr | None = None
    company_phone: str | None = Field(default=None, max_length=40)
    company_signatory: str | None = Field(default=None, max_length=120)
    crawl_active_from: time | None = None
    crawl_active_to: time | None = None
    #: Floors exist to protect the Gmail API quota, which is per-project and
    #: therefore shared across every desk on the platform.
    crawl_active_minutes: int | None = Field(default=None, ge=5, le=1440)
    crawl_quiet_minutes: int | None = Field(default=None, ge=10, le=1440)
    crawl_enabled: bool | None = None
    #: Follow-up wording. An empty string clears the override and restores the
    #: built-in default - distinct from `None`, which means "leave unchanged",
    #: so a desk can undo an edit without being able to send a blank email.
    followup_subject_template: str | None = Field(default=None, max_length=500)
    followup_body_template: str | None = Field(default=None, max_length=8000)


class CrawlStatusOut(BaseModel):
    """What the poller will do next, in words a trader can read."""

    enabled: bool
    active_now: bool
    interval_minutes: int
    reason: str
    local_time: str
    last_polled_at: datetime | None = None
    #: Two things override this desk's schedule entirely, and neither is
    #: visible from it. Without them the page describes a cadence that is
    #: not running and gives no hint why - which is the one question the
    #: screen exists to answer.
    #:
    #: The server-wide poller switch (`POLLING_ENABLED`). Off means nothing
    #: is fetched on a timer for any desk, whatever this schedule says.
    poller_running: bool = True
    #: Whether this desk has a mailbox at all. A schedule with nothing to
    #: poll is a schedule that will never fetch anything.
    mailbox_connected: bool = False


class CreateOrganisationIn(BaseModel):
    """Super admin onboarding a new desk."""

    name: str = Field(min_length=1, max_length=200)
    owner_email: EmailStr
    timezone: str = "Asia/Kolkata"


class OrganisationSummaryOut(OrganisationOut):
    """A desk as the super admin sees it, with enough to spot a problem."""

    user_count: int = 0
    mailbox_count: int = 0
    quotation_count: int = 0
    created_at: datetime | None = None


class OrganisationDetailOut(OrganisationSummaryOut):
    """One desk in full, for the operator answering a support question."""

    email_count: int = 0
    users: list[UserOut] = Field(default_factory=list)
    mailboxes: list[MailboxOut] = Field(default_factory=list)
    #: True when a mailbox has stopped working - the desk may not have noticed.
    needs_attention: bool = False


class MailboxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    email_address: str
    status: str
    last_error: str | None = None
    last_polled_at: datetime | None = None


__all__ = [
    "AcceptInviteIn",
    "OrganisationDetailOut",
    "ChangePasswordIn",
    "CrawlStatusOut",
    "CreateOrganisationIn",
    "InviteIn",
    "InviteOut",
    "LoginIn",
    "MailboxOut",
    "OrganisationOut",
    "OrganisationSummaryOut",
    "OrganisationUpdateIn",
    "SessionOut",
    "UserOut",
]
