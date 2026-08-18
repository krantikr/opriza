"""Inbound email listing and detail."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.serializers import email_detail_out, email_out
from app.core.db import get_db
from app.models import Email, EmailCategory, ProcessingStatus
from app.schemas.common import Page
from app.schemas.quotations import EmailDetailOut, EmailOut

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_model=Page[EmailOut])
def list_emails(
    db: Session = Depends(get_db),
    processing_status: ProcessingStatus | None = None,
    category: EmailCategory | None = None,
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
    if search:
        pattern = f"%{search.strip()}%"
        condition = Email.subject.ilike(pattern) | Email.sender_email.ilike(pattern)
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.options(selectinload(Email.quotation_request))
        .order_by(Email.received_at.desc(), Email.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

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
