"""Inbound email listing and detail."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.serializers import email_detail_out, email_out
from app.core.db import get_db, utcnow
from app.models import Email, EmailCategory, ProcessingStatus
from app.schemas.common import Page
from app.schemas.quotations import EmailDetailOut, EmailOut
from app.services import audit
from app.services.pipeline_state import resolve_state

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_model=Page[EmailOut])
def list_emails(
    db: Session = Depends(get_db),
    processing_status: ProcessingStatus | None = None,
    category: EmailCategory | None = None,
    awaiting_us: bool | None = Query(
        default=None,
        description="Only mail that asked us something and has not been answered",
    ),
    state: str | None = Query(
        default=None,
        description="Pipeline stage: ENQUIRY, FOLLOW_UP, NEEDS_REPLY, DELIVERY, COMPLAINT, DONE",
    ),
    search: str | None = Query(default=None, description="Match subject or sender"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[EmailOut]:
    query = select(Email)
    count_query = select(func.count()).select_from(Email)

    if processing_status:
        query = query.where(Email.processing_status == processing_status)
        count_query = count_query.where(Email.processing_status == processing_status)
    if category:
        query = query.where(Email.category == category)
        count_query = count_query.where(Email.category == category)
    if awaiting_us:
        # A customer asked something and nobody has answered yet - the clearest
        # definition of "we owe them", and the reason the tab exists.
        condition = Email.awaiting_us.is_(True) & Email.answered_at.is_(None)
        query = query.where(condition)
        count_query = count_query.where(condition)
    if search:
        pattern = f"%{search.strip()}%"
        condition = Email.subject.ilike(pattern) | Email.sender_email.ilike(pattern)
        query = query.where(condition)
        count_query = count_query.where(condition)

    loaded = query.options(
        selectinload(Email.quotation_request),
        selectinload(Email.replied_to_quotation),
    ).order_by(Email.received_at.desc(), Email.id.desc())

    if state:
        # The stage is derived from the quotation, the follow-up queue and the
        # reply, so it cannot be a SQL predicate. Resolving in Python keeps one
        # definition of each stage rather than a second, drifting copy in SQL.
        wanted = state.upper()
        matching = [e for e in db.scalars(loaded) if resolve_state(e).value == wanted]
        total = len(matching)
        rows = matching[offset : offset + limit]
    else:
        total = db.scalar(count_query) or 0
        rows = list(db.scalars(loaded.limit(limit).offset(offset)))

    return Page(items=[email_out(e) for e in rows], total=total, limit=limit, offset=offset)


@router.get("/{email_id}", response_model=EmailDetailOut)
def get_email(email_id: int, db: Session = Depends(get_db)) -> EmailDetailOut:
    email = db.scalars(
        select(Email)
        .where(Email.id == email_id)
        .options(selectinload(Email.attachments), selectinload(Email.quotation_request))
    ).first()
    if email is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Email {email_id} not found")
    return email_detail_out(email)


@router.post("/{email_id}/answered", response_model=EmailDetailOut)
def mark_answered(email_id: int, db: Session = Depends(get_db)) -> EmailDetailOut:
    """Clear a message from "needs reply".

    Sending a quotation or a follow-up clears this automatically; this is for
    everything answered another way - a phone call, a colleague's reply - so
    the tab reflects what is genuinely outstanding rather than becoming a list
    people learn to ignore.
    """
    email = db.get(Email, email_id)
    if email is None:
        raise HTTPException(status_code=404, detail=f"Email {email_id} not found")

    email.answered_at = utcnow()
    audit.record(
        db,
        entity_type="email",
        entity_id=email.id,
        action="MARKED_ANSWERED",
        details={"subject": email.subject},
    )
    db.commit()
    return email_detail_out(email)


@router.post("/{email_id}/needs-reply", response_model=EmailDetailOut)
def mark_needs_reply(email_id: int, db: Session = Depends(get_db)) -> EmailDetailOut:
    """Put a message back into "needs reply" - the classifier missed one."""
    email = db.get(Email, email_id)
    if email is None:
        raise HTTPException(status_code=404, detail=f"Email {email_id} not found")

    email.awaiting_us = True
    email.answered_at = None
    db.commit()
    return email_detail_out(email)
