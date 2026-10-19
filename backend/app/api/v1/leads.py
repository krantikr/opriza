"""Public lead capture: Request-access forms and live-demo sign-ups.

Unauthenticated by necessity: a prospect has no account. The `leads` table
carries no `organisation_id`, so it sits outside row-level security and an
unbound session can insert into it (see `app.models.system.Lead`).

Kept deliberately small. There is no read route here - the team reads leads
from the admin console on a bound session, never from this public surface.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import Lead

router = APIRouter(tags=["leads"])

Db = Annotated[Session, Depends(get_db)]


class LeadIn(BaseModel):
    """What the Request-access form sends.

    Only name, company and email are required; the rest helps us prepare for
    the first call. `website` is a honeypot - a real person never fills it, so
    anything in it is a bot and the request is quietly accepted and dropped.
    """

    name: str = Field(min_length=1, max_length=160)
    company: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field(min_length=4, max_length=40)
    monthly_enquiries: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=4000)
    #: Honeypot. Named to tempt bots that autofill every field.
    website: str | None = Field(default=None, max_length=400)

    @field_validator("name", "company", "phone")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip()


class LeadAck(BaseModel):
    received: bool


@router.post("/leads", response_model=LeadAck, status_code=status.HTTP_201_CREATED)
def create_lead(payload: LeadIn, request: Request, db: Db) -> LeadAck:
    """Record a design-partner request.

    Always answers the same way whether the row was stored or dropped as spam,
    so the honeypot gives nothing away.
    """
    # A filled honeypot is a bot. Accept the request so it learns nothing, but
    # store nothing.
    if payload.website:
        return LeadAck(received=True)

    lead = Lead(
        name=payload.name,
        company=payload.company,
        email=str(payload.email),
        phone=payload.phone,
        monthly_enquiries=payload.monthly_enquiries,
        note=payload.note,
        source="marketing_site",
        user_agent=(request.headers.get("user-agent") or "")[:400] or None,
    )
    db.add(lead)
    db.commit()
    return LeadAck(received=True)


class DemoLeadIn(BaseModel):
    """What the live demo sends when a visitor presses "Start my demo".

    Contact fields are required, as on the Request-access form. The business
    fields mirror the demo's details step and are stored together in
    `Lead.details`; each is optional so an older demo build still gets through.
    """

    name: str = Field(min_length=1, max_length=160)
    company: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field(min_length=6, max_length=40)
    city: str | None = Field(default=None, max_length=80)
    #: The trade picked, as the demo's id ('steel') and as shown ('Steel and metals').
    industry: str | None = Field(default=None, max_length=60)
    industry_label: str | None = Field(default=None, max_length=120)
    revenue: str | None = Field(default=None, max_length=40)
    team: str | None = Field(default=None, max_length=40)
    tally: str | None = Field(default=None, max_length=40)
    #: The problems ticked on the first step, as their on-screen labels.
    problems: list[str] = Field(default_factory=list, max_length=20)
    #: Honeypot, as on the Request-access form.
    website: str | None = Field(default=None, max_length=400)

    @field_validator("name", "company", "phone")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip()

    @field_validator("phone")
    @classmethod
    def _phone_has_digits(cls, v: str) -> str:
        if sum(ch.isdigit() for ch in v) < 6:
            raise ValueError("Enter a phone number with at least 6 digits.")
        return v

    @field_validator("problems")
    @classmethod
    def _short_labels(cls, v: list[str]) -> list[str]:
        return [p.strip()[:120] for p in v if p and p.strip()]


@router.post("/leads/demo", response_model=LeadAck, status_code=status.HTTP_201_CREATED)
def create_demo_lead(payload: DemoLeadIn, request: Request, db: Db) -> LeadAck:
    """Record a live-demo sign-up as a lead with source 'demo'.

    Append-only like every lead: a visitor who changes their details and starts
    again arrives as a new row (the demo only re-sends when something changed),
    and nothing here can edit an existing row.
    """
    if payload.website:
        return LeadAck(received=True)

    details = {
        key: value
        for key, value in {
            "city": payload.city,
            "industry": payload.industry,
            "industry_label": payload.industry_label,
            "revenue": payload.revenue,
            "team": payload.team,
            "tally": payload.tally,
            "problems": payload.problems,
        }.items()
        if value not in (None, "", [])
    }
    lead = Lead(
        name=payload.name,
        company=payload.company,
        email=str(payload.email),
        phone=payload.phone,
        source="demo",
        details=details or None,
        user_agent=(request.headers.get("user-agent") or "")[:400] or None,
    )
    db.add(lead)
    db.commit()
    return LeadAck(received=True)
