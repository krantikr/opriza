"""Notifications, follow-up rules, stock movement, customer management, reports.

The follow-up endpoints are worth reading carefully: `POST /follow-ups/{id}/send`
is the only route that mails a customer, and it delegates to `FollowUpService`,
which refuses anything that is not already `SENT`. The scheduler can mark a
nudge due; nothing here lets it deliver one on its own.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db
from app.core.db import utcnow
from app.models import (
    Customer,
    CustomerNote,
    CustomerTier,
    FollowUpRule,
    FollowUpSchedule,
    FollowUpStatus,
    Notification,
    NotificationRule,
    QuotationRequest,
    RecordStatus,
    StockItem,
    StockMovement,
    StockMovementKind,
    User,
)
from app.schemas.common import ActionResult, Page
from app.schemas.ops import (
    BalanceOut,
    CustomerIn,
    CustomerNoteIn,
    CustomerNoteOut,
    FollowUpRuleIn,
    FollowUpRuleOut,
    FollowUpScheduleOut,
    NotificationOut,
    NotificationRuleIn,
    NotificationRuleOut,
    StockMovementIn,
    StockMovementOut,
    TimelineEntry,
)
from app.services.insights import InsightService
from app.services.notifications import NotificationService
from app.services.quotations.followup import FollowUpError, FollowUpService
from app.services.quotations.followup_rules import FollowUpScheduler
from app.services.reports import DateRange, ReportService
from app.services.stock.movements import StockMovementService

router = APIRouter()


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@router.get("/notifications", response_model=Page[NotificationOut], tags=["notifications"])
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Page[NotificationOut]:
    from sqlalchemy import func

    query = select(Notification)
    count_query = select(func.count()).select_from(Notification)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
        count_query = count_query.where(Notification.read_at.is_(None))

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page(
        items=[NotificationOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/notifications/unread-count", tags=["notifications"])
def unread_count(db: Session = Depends(get_db)) -> dict[str, int]:
    return {"unread": NotificationService(db).unread_count()}


@router.post("/notifications/{notification_id}/read", tags=["notifications"])
def mark_read(notification_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    row = NotificationService(db).mark_read(notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/notifications/read-all", tags=["notifications"])
def mark_all_read(db: Session = Depends(get_db)) -> dict[str, int]:
    return {"marked": NotificationService(db).mark_all_read()}


@router.get("/notification-rules", response_model=list[NotificationRuleOut], tags=["notifications"])
def list_notification_rules(db: Session = Depends(get_db)) -> list[NotificationRule]:
    return list(db.scalars(select(NotificationRule).order_by(NotificationRule.id)))


@router.post(
    "/notification-rules",
    response_model=NotificationRuleOut,
    status_code=status.HTTP_201_CREATED,
    tags=["notifications"],
)
def create_notification_rule(
    payload: NotificationRuleIn, db: Session = Depends(get_db)
) -> NotificationRule:
    rule = NotificationRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put(
    "/notification-rules/{rule_id}", response_model=NotificationRuleOut, tags=["notifications"]
)
def update_notification_rule(
    rule_id: int, payload: NotificationRuleIn, db: Session = Depends(get_db)
) -> NotificationRule:
    rule = db.get(NotificationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    for key, value in payload.model_dump().items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete(
    "/notification-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["notifications"],
)
def delete_notification_rule(rule_id: int, db: Session = Depends(get_db)) -> None:
    rule = db.get(NotificationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()


# ---------------------------------------------------------------------------
# Follow-up rules and queue
# ---------------------------------------------------------------------------


@router.get("/follow-up-rules", response_model=list[FollowUpRuleOut], tags=["follow-ups"])
def list_follow_up_rules(db: Session = Depends(get_db)) -> list[FollowUpRule]:
    return list(db.scalars(select(FollowUpRule).order_by(FollowUpRule.id)))


@router.post(
    "/follow-up-rules",
    response_model=FollowUpRuleOut,
    status_code=status.HTTP_201_CREATED,
    tags=["follow-ups"],
)
def create_follow_up_rule(payload: FollowUpRuleIn, db: Session = Depends(get_db)) -> FollowUpRule:
    rule = FollowUpRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/follow-up-rules/{rule_id}", response_model=FollowUpRuleOut, tags=["follow-ups"])
def update_follow_up_rule(
    rule_id: int, payload: FollowUpRuleIn, db: Session = Depends(get_db)
) -> FollowUpRule:
    rule = db.get(FollowUpRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    for key, value in payload.model_dump().items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete(
    "/follow-up-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["follow-ups"]
)
def delete_follow_up_rule(rule_id: int, db: Session = Depends(get_db)) -> None:
    rule = db.get(FollowUpRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()


@router.get("/follow-ups/queue", response_model=list[FollowUpScheduleOut], tags=["follow-ups"])
def follow_up_queue(db: Session = Depends(get_db)) -> list[FollowUpSchedule]:
    """Nudges a rule says are owed, waiting for a human to send them."""
    return list(
        db.scalars(
            select(FollowUpSchedule)
            .where(FollowUpSchedule.status == FollowUpStatus.DUE)
            .order_by(FollowUpSchedule.due_at)
        )
    )


@router.post("/follow-ups/run", tags=["follow-ups"])
def run_scheduler(db: Session = Depends(get_db)) -> dict[str, int]:
    """Evaluate the rules now rather than waiting for the timer."""
    result = FollowUpScheduler(db).run()
    return {
        "scheduled": len(result.scheduled),
        "due": len(result.due),
        "cancelled": len(result.cancelled),
        "marked_cold": result.marked_cold,
    }


@router.post("/follow-ups/{schedule_id}/send", response_model=ActionResult, tags=["follow-ups"])
def send_follow_up(
    schedule_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
) -> ActionResult:
    """Send a queued nudge. The human step the scheduler deliberately leaves."""
    schedule = db.get(FollowUpSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    if schedule.status is not FollowUpStatus.DUE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Follow-up is {schedule.status.value}, not DUE.",
        )

    quotation = schedule.quotation_request
    try:
        result = FollowUpService(db).send(
            quotation,
            user_id=user.id if user else None,
            subject=schedule.subject,
            body=schedule.body,
        )
    except FollowUpError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    schedule.status = FollowUpStatus.SENT
    schedule.follow_up_id = result.follow_up.id
    schedule.resolved_at = utcnow()
    db.commit()

    return ActionResult(
        ok=result.sent,
        detail="Follow-up sent." if result.sent else f"Send failed: {result.send.error}",
        quotation_id=quotation.id,
        status=quotation.status.value,
    )


@router.post("/follow-ups/{schedule_id}/skip", response_model=ActionResult, tags=["follow-ups"])
def skip_follow_up(
    schedule_id: int, db: Session = Depends(get_db)
) -> ActionResult:
    schedule = db.get(FollowUpSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    schedule.status = FollowUpStatus.SKIPPED
    schedule.resolved_at = utcnow()
    schedule.resolution_note = "Skipped by a reviewer."
    db.commit()
    return ActionResult(
        detail="Follow-up skipped.", quotation_id=schedule.quotation_request_id
    )


# ---------------------------------------------------------------------------
# Stock movement
# ---------------------------------------------------------------------------


@router.get("/stock/movements", response_model=list[StockMovementOut], tags=["stock"])
def list_movements(
    limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)
) -> list[StockMovement]:
    return StockMovementService(db).history(limit=limit)


@router.post(
    "/stock/movements",
    response_model=StockMovementOut,
    status_code=status.HTTP_201_CREATED,
    tags=["stock"],
)
def create_movement(
    payload: StockMovementIn,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
) -> StockMovement:
    lot = db.get(StockItem, payload.stock_item_id) if payload.stock_item_id else None
    if payload.stock_item_id and lot is None:
        raise HTTPException(status_code=404, detail="Stock item not found")

    return StockMovementService(db).record(
        kind=payload.kind,
        quantity_kg=payload.quantity_kg,
        stock_item=lot,
        nop=payload.nop,
        location=payload.location,
        rate_per_kg=payload.rate_per_kg,
        reference=payload.reference,
        note=payload.note,
        movement_date=payload.movement_date,
        user_id=user.id if user else None,
    )


@router.get("/stock/holds", response_model=list[StockMovementOut], tags=["stock"])
def list_holds(db: Session = Depends(get_db)) -> list[StockMovement]:
    """Open blocks and reservations - everything held back from quoting."""
    return list(
        db.scalars(
            select(StockMovement)
            .where(
                StockMovement.is_open.is_(True),
                StockMovement.kind.in_(
                    [StockMovementKind.BLOCK, StockMovementKind.RESERVATION]
                ),
            )
            .order_by(StockMovement.created_at.desc())
        )
    )


@router.post("/stock/holds/{movement_id}/lift", tags=["stock"])
def lift_hold(movement_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    """Release a hold, putting the tonnage back on offer."""
    lifted = StockMovementService(db).lift_hold(movement_id)
    if not lifted:
        raise HTTPException(status_code=404, detail="No open hold with that id")
    return {"ok": True}


@router.get("/stock/{stock_item_id}/balance", response_model=BalanceOut, tags=["stock"])
def stock_balance(stock_item_id: int, db: Session = Depends(get_db)) -> BalanceOut:
    """Imported balance plus movements - what is actually free to sell."""
    lot = db.get(StockItem, stock_item_id)
    if lot is None:
        raise HTTPException(status_code=404, detail="Stock item not found")
    balance = StockMovementService(db).balance_for_lots([lot])
    return BalanceOut(
        on_hand_mt=balance.on_hand_mt.quantize(Decimal("0.001")),
        available_mt=balance.available_mt.quantize(Decimal("0.001")),
        reserved_mt=(balance.reserved_kg / Decimal(1000)).quantize(Decimal("0.001")),
    )


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------


@router.post(
    "/customers", response_model=dict, status_code=status.HTTP_201_CREATED, tags=["customers"]
)
def create_customer(payload: CustomerIn, db: Session = Depends(get_db)) -> dict:
    data = payload.model_dump()
    data["tier"] = CustomerTier(data["tier"])
    customer = Customer(**data, status=RecordStatus.ACTIVE)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return {"id": customer.id, "name": customer.name}


@router.put("/customers/{customer_id}", response_model=dict, tags=["customers"])
def update_customer(
    customer_id: int, payload: CustomerIn, db: Session = Depends(get_db)
) -> dict:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    data = payload.model_dump()
    data["tier"] = CustomerTier(data["tier"])
    for key, value in data.items():
        setattr(customer, key, value)
    db.commit()
    return {"id": customer.id, "name": customer.name}


@router.post("/customers/{customer_id}/verify", response_model=dict, tags=["customers"])
def verify_customer(customer_id: int, db: Session = Depends(get_db)) -> dict:
    """Confirm a record built from an email signature.

    Until this happens the tier adjustment is withheld from pricing, so this
    is a commercial decision, not an administrative tidy-up.
    """
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer.is_verified = True
    db.commit()
    return {"id": customer.id, "is_verified": True}


@router.get(
    "/customers/{customer_id}/notes", response_model=list[CustomerNoteOut], tags=["customers"]
)
def list_customer_notes(customer_id: int, db: Session = Depends(get_db)) -> list[CustomerNote]:
    return list(
        db.scalars(
            select(CustomerNote)
            .where(
                CustomerNote.customer_id == customer_id,
                CustomerNote.status == RecordStatus.ACTIVE,
            )
            .order_by(CustomerNote.pinned.desc(), CustomerNote.created_at.desc())
        )
    )


@router.post(
    "/customers/{customer_id}/notes",
    response_model=CustomerNoteOut,
    status_code=status.HTTP_201_CREATED,
    tags=["customers"],
)
def add_customer_note(
    customer_id: int,
    payload: CustomerNoteIn,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
) -> CustomerNote:
    if db.get(Customer, customer_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    note = CustomerNote(
        customer_id=customer_id,
        user_id=user.id if user else None,
        body=payload.body,
        pinned=payload.pinned,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get(
    "/customers/{customer_id}/timeline", response_model=list[TimelineEntry], tags=["customers"]
)
def customer_timeline(customer_id: int, db: Session = Depends(get_db)) -> list[TimelineEntry]:
    """Every interaction with this customer, newest first."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    entries: list[TimelineEntry] = []

    for quotation in db.scalars(
        select(QuotationRequest).where(QuotationRequest.customer_id == customer_id)
    ):
        entries.append(
            TimelineEntry(
                at=quotation.created_at,
                kind="ENQUIRY",
                title=f"Enquiry {quotation.quotation_number}",
                detail=quotation.email.subject if quotation.email else None,
                link=f"/quotations/{quotation.id}",
            )
        )
        if quotation.sent_at:
            entries.append(
                TimelineEntry(
                    at=quotation.sent_at,
                    kind="QUOTED",
                    title=f"Quotation {quotation.quotation_number} sent",
                    link=f"/quotations/{quotation.id}",
                )
            )

    for note in db.scalars(
        select(CustomerNote).where(
            CustomerNote.customer_id == customer_id,
            CustomerNote.status == RecordStatus.ACTIVE,
        )
    ):
        entries.append(
            TimelineEntry(at=note.created_at, kind="NOTE", title="Note", detail=note.body)
        )

    entries.sort(key=lambda e: e.at, reverse=True)
    return entries


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def _period(days: int, start: date | None, end: date | None) -> DateRange:
    if start and end:
        return DateRange(start=start, end=end)
    return DateRange.last_days(days)


@router.get("/reports/insights", tags=["reports"])
def insights(
    days: int = Query(30, ge=7, le=365), db: Session = Depends(get_db)
) -> dict:
    """Headline metrics against the preceding window, plus what needs a person."""
    return InsightService(db).build(days).to_dict()


@router.get("/reports/funnel", tags=["reports"])
def funnel_report(
    days: int = Query(30, ge=1, le=730),
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    period = _period(days, start, end)
    stages = ReportService(db).funnel(period)
    return {
        "period": period.label(),
        "stages": [{"stage": s.stage, "count": s.count, "note": s.note} for s in stages],
    }


@router.get("/reports/{name}", tags=["reports"], response_model=None)
def report(
    name: str,
    days: int = Query(30, ge=1, le=730),
    start: date | None = None,
    end: date | None = None,
    fmt: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
) -> Response | dict:
    """One of: win-loss, margin, stock-ageing, customers, products."""
    period = _period(days, start, end)
    service = ReportService(db)

    builders = {
        "win-loss": lambda: service.win_loss(period),
        "margin": lambda: service.margin(period),
        "stock-ageing": lambda: service.stock_ageing(),
        "customers": lambda: service.customer_performance(period),
        "products": lambda: service.product_performance(period),
    }
    builder = builders.get(name)
    if builder is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown report '{name}'. Available: {', '.join(sorted(builders))}",
        )

    result = builder()
    if fmt == "csv":
        return Response(
            content=result.to_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
        )
    return {
        "title": result.title,
        "period": result.period,
        "rows": result.rows,
        "totals": result.totals,
    }
