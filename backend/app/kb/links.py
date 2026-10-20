"""Secure links customers and suppliers open without an account.

Only a hash of the token is stored, as with team invites: a database leak
does not hand anyone a working link. Links expire after 7 days (quotes) to
14 days (statements).
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.kb import clock
from app.kb.models import KbShareLink

LIFETIME = {"quote": 7, "statement": 14, "rfq": 3, "offer": 7, "early_pay": 10, "po": 7}


def public_base() -> str:
    import ai.config  # noqa: F401 - loads .env

    return (os.getenv("APP_PUBLIC_URL") or "http://localhost:5173").rstrip("/")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(
    db: Session, purpose: str, party_id: int, entity_type: str, entity_id: int
) -> tuple[KbShareLink, str]:
    """A new link; returns the row and the URL to send (the only time the token exists)."""
    token = secrets.token_urlsafe(18)
    now = clock.now(db)
    row = KbShareLink(
        organisation_id=db.info["organisation_id"],
        token_hash=hash_token(token),
        purpose=purpose,
        party_id=party_id,
        entity_type=entity_type,
        entity_id=entity_id,
        created_at=now,
        expires_at=now + timedelta(days=LIFETIME.get(purpose, 7)),
    )
    db.add(row)
    db.flush()
    return row, f"{public_base()}/l/{token}"


def find(db: Session, token: str) -> KbShareLink | None:
    """Look a link up from its token. Needs a session that can see every desk."""
    return db.scalars(select(KbShareLink).where(KbShareLink.token_hash == hash_token(token))).first()
