"""Audit trail helper.

Every meaningful state change goes through here. Kept as one tiny function so
there is no excuse not to call it, and so audit writes never become the reason
a business operation fails: a logging problem is swallowed and reported, not
propagated.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import AuditLog

logger = get_logger(__name__)


def record(
    db: Session,
    *,
    entity_type: str,
    action: str,
    entity_id: int | None = None,
    details: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> AuditLog | None:
    """Append an audit entry. Does not commit - it joins the caller's transaction."""
    try:
        entry = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            details=details,
            user_id=user_id,
        )
        db.add(entry)
        return entry
    except Exception as exc:  # noqa: BLE001 - auditing must never break the workflow
        logger.error("Failed to write audit entry %s/%s: %s", entity_type, action, exc)
        return None
