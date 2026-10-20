"""Events: how the agents connect without calling each other.

`publish` writes one row in `kb_events` inside the caller's transaction, so an
event exists exactly when the change it describes was committed, plus one
`kb_event_deliveries` row per subscribed agent. `dispatch` hands pending
deliveries to the agents' handlers, each in its own savepoint, so one failing
handler is retried later without undoing the others.

Adding an agent means adding it to SUBSCRIPTIONS, not rewiring the others.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.kb import clock
from app.kb.models import KbEvent, KbEventDelivery

logger = get_logger(__name__)

#: Event type -> the agents that react to it.
SUBSCRIPTIONS: dict[str, tuple[str, ...]] = {
    "voucher.posted": ("score", "stock", "cash", "collect", "sales"),
    "enquiry.received": ("sales",),
    "quote.created": ("brief",),
    "quote.sent": ("brief",),
    "quote.opened": ("sales",),
    "quote.won": ("sales", "stock", "brief"),
    "quote.lost": ("sales", "brief"),
    "quote.expired": ("sales",),
    "promise.made": ("collect", "cash"),
    "promise.kept": ("collect", "score", "cash"),
    "promise.part_kept": ("collect", "score", "cash"),
    "promise.missed": ("collect", "score", "cash", "brief"),
    "supplier_quote.received": ("stock",),
    "po.sent": ("cash",),
    "po.received": ("stock", "cash"),
    "grade.changed": ("sales", "collect", "brief"),
    "approval.requested": ("brief",),
    "approval.decided": ("brief",),
    "offer.accepted": ("sales", "stock"),
    "early_pay.promised": ("cash", "collect"),
    "handoff.requested": ("sales", "collect", "stock", "cash"),
}

#: Some voucher types only matter to some agents.
VOUCHER_FILTER = {
    "collect": {"receipt", "credit_note", "sales"},
    "sales": {"sales"},
    "stock": {"sales", "purchase"},
    "score": {"receipt", "credit_note"},
}


def publish(
    db: Session,
    type_: str,
    entity_type: str,
    entity_id: int,
    *,
    source: str,
    actor: str | None = None,
    at: datetime | None = None,
    **payload,
) -> KbEvent:
    event = KbEvent(
        occurred_at=at or clock.now(db),
        type=type_,
        entity_type=entity_type,
        entity_id=entity_id,
        source=source,
        actor=actor,
        payload=_jsonable(payload),
    )
    db.add(event)
    db.flush()
    for consumer in SUBSCRIPTIONS.get(type_, ()):
        if consumer == actor:
            continue  # an agent already did its part when it published
        only = VOUCHER_FILTER.get(consumer)
        if type_ == "voucher.posted" and only and payload.get("type") not in only:
            continue
        if type_ == "handoff.requested" and payload.get("to") != consumer:
            continue
        db.add(KbEventDelivery(event_id=event.id, consumer=consumer))
    db.flush()
    return event


Handler = Callable[[Session, KbEvent], None]


def dispatch(db: Session, handlers: dict[str, Handler], *, limit: int = 500, max_attempts: int = 3) -> int:
    """Run pending deliveries in event order. Returns how many were handled."""
    rows = db.execute(
        select(KbEventDelivery, KbEvent)
        .join(KbEvent, KbEvent.id == KbEventDelivery.event_id)
        .where(KbEventDelivery.status == "pending")
        .order_by(KbEvent.occurred_at, KbEvent.id)
        .limit(limit)
        .with_for_update(of=KbEventDelivery, skip_locked=True)
    ).all()
    done = 0
    for delivery, event in rows:
        handler = handlers.get(delivery.consumer)
        delivery.attempts += 1
        if handler is None:
            delivery.status = "skipped"
            continue
        try:
            with db.begin_nested():
                handler(db, event)
            delivery.status = "done"
            delivery.processed_at = clock.now(db)
            done += 1
        except Exception as exc:  # noqa: BLE001 - one bad handler must not stop the rest
            logger.exception("Agent %s failed on event %s #%s", delivery.consumer, event.type, event.id)
            delivery.error = str(exc)[:2000]
            delivery.status = "failed" if delivery.attempts >= max_attempts else "pending"
        db.flush()
    return done


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
