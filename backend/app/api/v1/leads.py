"""Public design-partner requests from the marketing site.

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
