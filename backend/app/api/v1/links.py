"""Public customer and supplier links: /api/v1/links/{token}.

Unauthenticated by necessity: the customer has no account. The token is the
credential; only its hash is stored. The link is looked up once on a
platform-wide binding, and then the session is bound to *that link's* desk
for everything else, so the rest of the request runs under row-level
security exactly like a signed-in one.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.tenancy import bind_session
from app.kb import actions, links
from app.kb.actions import ActionError

router = APIRouter(prefix="/links", tags=["links"])

Db = Annotated[Session, Depends(get_db)]


def _resolve(db: Session, token: str):
    if len(token) < 16 or len(token) > 64:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link is not valid.")
    bind_session(db, None, super_admin=True)
    link = links.find(db, token)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link is not valid.")
    bind_session(db, link.organisation_id)
    return link


@router.get("/{token}")
def view(token: str, db: Db) -> dict:
    link = _resolve(db, token)
    out = actions.link_view(db, link)
    db.commit()
    return out


@router.post("/{token}")
def respond(token: str, body: dict[str, Any], db: Db) -> dict:
    link = _resolve(db, token)
    try:
        out = actions.link_respond(db, link, body)
    except (ActionError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return {"ok": True, **out}
