"""Shared route dependencies.

`current_user` returns the single seeded MVP user. There is no login in this
build, but the dependency exists so approvals and audit rows carry a real
identity now, and so adding authentication later means changing this one
function rather than every handler that records an action.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import QuotationRequest, User

__all__ = ["get_db", "current_user", "get_quotation", "DbSession"]


def current_user(db: Session = Depends(get_db)) -> User | None:
    """The acting user. Single seeded owner until authentication is added."""
    return db.scalars(select(User).order_by(User.id).limit(1)).first()


def get_quotation(quotation_id: int, db: Session = Depends(get_db)) -> QuotationRequest:
    quotation = db.get(QuotationRequest, quotation_id)
    if quotation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Quotation {quotation_id} not found"
        )
    return quotation


def db_session() -> Generator[Session, None, None]:
    yield from get_db()


DbSession = Depends(get_db)
