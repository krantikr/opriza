"""Notifications, follow-up rules, stock movement, customer management, reports.

The follow-up endpoints are worth reading carefully: `POST /follow-ups/{id}/send`
is the only route that mails a customer, and it delegates to `FollowUpService`,
which refuses anything that is not already `SENT`. The scheduler can mark a
nudge due; nothing here lets it deliver one on its own.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, TenantDb, current_user
from app.core.config import settings
from app.core.db import utcnow
from app.models import (
    Customer,
    CustomerNote,
    CustomerTier,
    FollowUpRule,
    FollowUpSchedule,
    FollowUpStatus,
    Notification,
    NotificationChannel,
    NotificationRule,
    PushDevice,
    QuotationRequest,
    QuotationStatus,
    RecordStatus,
    StockItem,
    StockMovement,
    StockMovementKind,
    User,
)
from app.schemas.common import ActionResult, Page
from app.schemas.ops import (
    BalanceOut,
    ChaseBoardOut,
    ChaseRowOut,
    ChaseSendIn,
    CustomerIn,
    CustomerNoteIn,
    CustomerNoteOut,
    FollowUpRuleIn,
    FollowUpRuleOut,
    FollowUpScheduleOut,
    MarkLostIn,
    NotificationOut,
    NotificationRuleIn,
    NotificationRuleOut,
    PriorityIn,
    PushDeviceIn,
    PushDeviceOut,
    PushStatusOut,
    SnoozeIn,
    StockImportOut,
    StockMovementIn,
    StockMovementOut,
    TimelineEntry,
)
from app.services import html_report, periods
from app.services.chase import ChaseService
from app.services.desk import DeskService
from app.services.ingestion.excel_importer import ImportFailed, StockImporter
from app.services.insights import InsightService
from app.services.notifications import NotificationService
from app.services.notifications.channels import get_channel
from app.services.quotations.followup import FollowUpError, FollowUpService
from app.services.quotations.followup_rules import FollowUpScheduler
from app.services.reports import DateRange, ReportService
from app.services.stock.movements import StockMovementService
from app.services.stock.resync import StockResyncService
from app.services.workbook import WorkbookBuilder

router = APIRouter()


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@router.get("/notifications", response_model=Page[NotificationOut], tags=["notifications"])
def list_notifications(
    db: TenantDb,
    unread_only: bool = False,
    limit: int = Query(50,
    ge=1,
    le=200),
    offset: int = Query(0,
    ge=0),
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
def unread_count(db: TenantDb) -> dict[str, int]:
    return {"unread": NotificationService(db).unread_count()}


@router.post("/notifications/{notification_id}/read", tags=["notifications"])
def mark_read(notification_id: int, db: TenantDb) -> dict[str, bool]:
    row = NotificationService(db).mark_read(notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/notifications/read-all", tags=["notifications"])
def mark_all_read(db: TenantDb) -> dict[str, int]:
    return {"marked": NotificationService(db).mark_all_read()}


@router.get("/notification-rules", response_model=list[NotificationRuleOut], tags=["notifications"])
def list_notification_rules(db: TenantDb) -> list[NotificationRule]:
    return list(db.scalars(select(NotificationRule).order_by(NotificationRule.id)))


@router.post(
    "/notification-rules",
    response_model=NotificationRuleOut,
    status_code=status.HTTP_201_CREATED,
    tags=["notifications"],
)
def create_notification_rule(
    payload: NotificationRuleIn, db: TenantDb
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
    rule_id: int, payload: NotificationRuleIn, db: TenantDb
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
def delete_notification_rule(rule_id: int, db: TenantDb) -> None:
    rule = db.get(NotificationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()


# ---------------------------------------------------------------------------
# Follow-up rules and queue
# ---------------------------------------------------------------------------


@router.get("/follow-up-rules", response_model=list[FollowUpRuleOut], tags=["follow-ups"])
def list_follow_up_rules(db: TenantDb) -> list[FollowUpRule]:
    return list(db.scalars(select(FollowUpRule).order_by(FollowUpRule.id)))


@router.post(
    "/follow-up-rules",
    response_model=FollowUpRuleOut,
    status_code=status.HTTP_201_CREATED,
    tags=["follow-ups"],
)
def create_follow_up_rule(payload: FollowUpRuleIn, db: TenantDb) -> FollowUpRule:
    rule = FollowUpRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/follow-up-rules/{rule_id}", response_model=FollowUpRuleOut, tags=["follow-ups"])
def update_follow_up_rule(
    rule_id: int, payload: FollowUpRuleIn, db: TenantDb
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
def delete_follow_up_rule(rule_id: int, db: TenantDb) -> None:
    rule = db.get(FollowUpRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()


@router.get("/follow-ups/queue", response_model=list[FollowUpScheduleOut], tags=["follow-ups"])
def follow_up_queue(db: TenantDb) -> list[FollowUpSchedule]:
    """Nudges a rule says are owed, waiting for a human to send them."""
    return list(
        db.scalars(
            select(FollowUpSchedule)
            .where(FollowUpSchedule.status == FollowUpStatus.DUE)
            .order_by(FollowUpSchedule.due_at)
        )
    )


@router.post("/follow-ups/run", tags=["follow-ups"])
def run_scheduler(db: TenantDb) -> dict[str, int]:
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
    db: TenantDb,
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
    schedule_id: int, db: TenantDb
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
# Push devices
#
# Push is the only channel that reaches a trader with the site closed. The
# in-app bell needs the dashboard open and the browser Notification API needs
# the tab alive, so neither covers the case this exists for.
# ---------------------------------------------------------------------------


@router.get("/push/status", response_model=PushStatusOut, tags=["notifications"])
def push_status(db: TenantDb, user: User | None = Depends(current_user)) -> PushStatusOut:
    """Whether push can work, and how many devices this person has registered.

    `configured` is about the desk's Firebase setup rather than the browser's
    permission, so the UI can say "ask your administrator" instead of
    prompting for a permission that could never deliver anything.
    """
    count = 0
    if user is not None:
        count = int(
            db.scalar(
                select(func.count())
                .select_from(PushDevice)
                .where(PushDevice.user_id == user.id, PushDevice.is_active.is_(True))
            )
            or 0
        )
    return PushStatusOut(configured=settings.fcm_configured, devices=count)


@router.post("/push/devices", response_model=PushDeviceOut, tags=["notifications"])
def register_push_device(
    payload: PushDeviceIn,
    db: TenantDb,
    user: User | None = Depends(current_user),
) -> PushDevice:
    """Register or refresh this browser's push token.

    Idempotent on the token, because the frontend calls it on every load:
    Firebase rotates tokens on its own schedule, and a device that registered
    once and never again would quietly stop receiving anything. A token that
    was previously retired is revived here - the person has clearly just
    granted permission again.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to register a device.")

    device = db.scalar(select(PushDevice).where(PushDevice.token == payload.token))
    if device is None:
        device = PushDevice(user_id=user.id, token=payload.token)
        db.add(device)

    device.user_id = user.id
    device.label = payload.label or device.label
    device.user_agent = payload.user_agent or device.user_agent
    device.is_active = True
    device.disabled_reason = None
    device.last_seen_at = utcnow()
    db.commit()
    db.refresh(device)
    return device


@router.get("/push/devices", response_model=list[PushDeviceOut], tags=["notifications"])
def list_push_devices(db: TenantDb, user: User | None = Depends(current_user)) -> list[PushDevice]:
    """This person's registered devices, so they can see and revoke them."""
    if user is None:
        return []
    return list(
        db.scalars(
            select(PushDevice)
            .where(PushDevice.user_id == user.id)
            .order_by(PushDevice.last_seen_at.desc().nullslast())
        )
    )


@router.delete(
    "/push/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["notifications"],
)
def revoke_push_device(
    device_id: int, db: TenantDb, user: User | None = Depends(current_user)
) -> None:
    """Turn a device off. Row-level security already scopes this to the desk;
    the user check stops one colleague revoking another's phone."""
    device = db.get(PushDevice, device_id)
    if device is None or (user is not None and device.user_id != user.id):
        raise HTTPException(status_code=404, detail="Device not found")
    device.is_active = False
    device.disabled_reason = "Turned off by the user."
    db.commit()


@router.post("/push/test", response_model=ActionResult, tags=["notifications"])
def send_test_push(db: TenantDb, user: User | None = Depends(current_user)) -> ActionResult:
    """Send a push to this person's own devices.

    The only honest way to confirm the whole chain - Firebase project, service
    account, service worker, OS permission - is actually working end to end.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in first.")

    devices = list(
        db.scalars(
            select(PushDevice).where(
                PushDevice.user_id == user.id, PushDevice.is_active.is_(True)
            )
        )
    )
    if not devices:
        return ActionResult(ok=False, detail="No devices registered on this account yet.")

    channel = get_channel(NotificationChannel.PUSH)
    sent = 0
    retired = 0
    errors: list[str] = []
    for device in devices:
        outcome = channel.send(
            destination=device.token,
            title="Steel Desk",
            body="Push notifications are working.",
            link="/",
        )
        if outcome.sent:
            sent += 1
            device.last_seen_at = utcnow()
        elif outcome.error:
            errors.append(outcome.error)
            # A token Firebase has retired stays in the list for ever
            # otherwise, and one browser that re-registered a few times then
            # reads as several devices - so "Sent to 1 of 3" looks like a
            # failure when every live device was actually reached. Retiring
            # it here is the same rule the notification service already
            # applies; only this endpoint was missing it.
            if getattr(channel, "is_dead_token", None) and channel.is_dead_token(outcome.error):
                device.is_active = False
                device.disabled_reason = "Firebase no longer recognises this device."
                retired += 1

    db.commit()
    reached = f"Sent to {sent} of {len(devices)} device(s)."
    if retired:
        reached += f" Removed {retired} device(s) Firebase no longer recognises."
    return ActionResult(
        ok=sent > 0,
        detail=(
            reached
            if sent
            else (errors[0] if errors else "Delivery failed.")
        ),
    )


# ---------------------------------------------------------------------------
# Chase board
#
# `/queue` above is the scheduler's view: nudges a rule has already decided are
# due. The board below is the trader's view: every open quotation, bucketed by
# whose turn it is and ranked by money at risk. Both exist because they answer
# different questions, and the queue is what the scheduler acts on.
# ---------------------------------------------------------------------------


@router.get("/follow-ups/board", response_model=ChaseBoardOut, tags=["follow-ups"])
def chase_board(db: TenantDb) -> ChaseBoardOut:
    """Every open quotation, ranked by what it costs to keep ignoring it."""
    service = ChaseService(db)
    rows = service.board()
    counts = service.counts(rows)

    return ChaseBoardOut(
        rows=[ChaseRowOut(**_row_dict(r)) for r in rows],
        counts=counts,
        value_awaiting_you=sum(r.value for r in rows if r.turn.value == "YOURS"),
        quiet_over_a_week=sum(
            1 for r in rows if r.days_waiting >= 7 and r.turn.value != "SNOOZED"
        ),
    )


def _row_dict(row) -> dict:
    """`ChaseRow` is a slotted dataclass, so `asdict` is the honest conversion."""
    from dataclasses import asdict

    data = asdict(row)
    data["turn"] = row.turn.value
    return data


@router.post("/follow-ups/quotation/{quotation_id}/send", response_model=ActionResult, tags=["follow-ups"])
def send_chase(
    quotation_id: int,
    payload: ChaseSendIn,
    db: TenantDb,
    user: User | None = Depends(current_user),
) -> ActionResult:
    """Send the follow-up the trader just read and edited in the drawer.

    Distinct from `/follow-ups/{schedule_id}/send`, which mails whatever the
    scheduler drafted days ago. Here the text arrives from the screen, so what
    the trader saw under the thread is exactly what goes out. It still routes
    through `FollowUpService.send`, which remains the only function that mails
    a customer and still refuses anything that is not `SENT`.
    """
    quotation = db.get(QuotationRequest, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found")

    try:
        result = FollowUpService(db).send(
            quotation,
            user_id=user.id if user else None,
            subject=payload.subject,
            body=payload.body,
        )
    except FollowUpError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # A nudge the scheduler was still holding for this quotation is now
    # redundant: the trader has just chased by hand. Leaving it DUE would show
    # the same row as outstanding tomorrow morning.
    if payload.schedule_id is not None:
        schedule = db.get(FollowUpSchedule, payload.schedule_id)
        if schedule is not None and schedule.status is FollowUpStatus.DUE:
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


@router.post("/follow-ups/quotation/{quotation_id}/snooze", response_model=ActionResult, tags=["follow-ups"])
def snooze_quotation(quotation_id: int, payload: SnoozeIn, db: TenantDb) -> ActionResult:
    """Park a quotation until a date the trader chose.

    "He said call after Diwali." Without this the row sits on the chase list
    with nothing anybody can do about it, and a list full of rows you cannot
    act on is a list you stop reading.
    """
    quotation = db.get(QuotationRequest, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if payload.until <= date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Pick a date in the future - snoozing until today changes nothing.",
        )

    quotation.snoozed_until = payload.until
    if payload.note:
        quotation.review_notes = _with_note(quotation.review_notes, payload.note)

    # The scheduler must not chase something deliberately parked.
    FollowUpScheduler(db).cancel_for(quotation, "Snoozed by a reviewer.")
    db.commit()

    return ActionResult(
        detail=f"Parked until {payload.until:%-d %b}.",
        quotation_id=quotation.id,
        status=quotation.status.value,
    )


@router.post("/follow-ups/quotation/{quotation_id}/lost", response_model=ActionResult, tags=["follow-ups"])
def mark_lost(quotation_id: int, payload: MarkLostIn, db: TenantDb) -> ActionResult:
    """Record that a quotation did not convert, and why.

    The reason is the point. One tap keeps it cheap enough that the data
    actually accumulates, and only then can a report answer "how many did we
    lose purely on price".
    """
    quotation = db.get(QuotationRequest, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found")

    quotation.lost_reason = payload.reason
    quotation.lost_note = payload.note
    quotation.status = QuotationStatus.CUSTOMER_DECLINED
    FollowUpScheduler(db).cancel_for(quotation, f"Marked lost: {payload.reason.value}.")
    db.commit()

    return ActionResult(
        detail="Marked lost.",
        quotation_id=quotation.id,
        status=quotation.status.value,
    )


@router.post("/follow-ups/quotation/{quotation_id}/wake", response_model=ActionResult, tags=["follow-ups"])
def wake_quotation(quotation_id: int, db: TenantDb) -> ActionResult:
    """Bring a snoozed quotation back onto the board now."""
    quotation = db.get(QuotationRequest, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found")
    quotation.snoozed_until = None
    db.commit()
    return ActionResult(detail="Back on the board.", quotation_id=quotation.id)


def _with_note(existing: str | None, note: str) -> str:
    return f"{existing}\n{note}" if existing else note


# ---------------------------------------------------------------------------
# Stock movement
# ---------------------------------------------------------------------------


@router.get("/stock/movements", response_model=list[StockMovementOut], tags=["stock"])
def list_movements(db: TenantDb, limit: int = Query(100, ge=1, le=500)) -> list[StockMovement]:
    return StockMovementService(db).history(limit=limit)


@router.post(
    "/stock/movements",
    response_model=StockMovementOut,
    status_code=status.HTTP_201_CREATED,
    tags=["stock"],
)
def create_movement(
    payload: StockMovementIn,
    db: TenantDb,
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
def list_holds(db: TenantDb) -> list[StockMovement]:
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
def lift_hold(movement_id: int, db: TenantDb) -> dict[str, bool]:
    """Release a hold, putting the tonnage back on offer."""
    lifted = StockMovementService(db).lift_hold(movement_id)
    if not lifted:
        raise HTTPException(status_code=404, detail="No open hold with that id")
    return {"ok": True}


@router.get("/stock/{stock_item_id}/balance", response_model=BalanceOut, tags=["stock"])
def stock_balance(stock_item_id: int, db: TenantDb) -> BalanceOut:
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


MAX_STOCK_UPLOAD_BYTES = 20 * 1024 * 1024
STOCK_UPLOAD_SUFFIXES = {".xlsx", ".xlsm", ".xls"}


@router.post("/stock/import", response_model=StockImportOut, tags=["stock"])
async def import_stock(
    db: TenantDb,
    user: CurrentUser,
    file: UploadFile = File(...),  # noqa: B008 - FastAPI's declaration style
) -> StockImportOut:
    """Replace the stock list from an uploaded spreadsheet.

    The file is a full point-in-time snapshot, so it replaces what is held
    rather than merging into it - two imports of the same file leave one copy
    of each lot, not two. The swap and the insert share one transaction, so a
    file that fails half way through leaves the previous stock untouched.

    The upload is written to a temporary file because the importer reads via
    pandas, which needs a real path; it is removed on every exit path.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in STOCK_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload an Excel file (.xlsx, .xlsm or .xls).",
        )

    payload = await file.read()
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="That file is empty."
        )
    # Bounded before anything touches the database: an oversized upload is
    # rejected as a bad request, never as a timeout half way through a replace.
    if len(payload) > MAX_STOCK_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="That file is larger than 20 MB.",
        )

    tmp = Path(tempfile.mkdtemp()) / (Path(file.filename or "stock.xlsx").name)
    try:
        tmp.write_bytes(payload)
        try:
            result = StockImporter(db, imported_by=user.email).run(tmp)
        except ImportFailed as exc:
            # The importer raises this for a file it cannot read or one missing
            # required columns. Nothing was replaced, so this is a plain 400
            # naming the problem rather than a server error.
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except Exception:
            # Anything else leaves the session mid-transaction, and the replace
            # must not be half-applied. Rolling back here is what guarantees
            # the desk still has the stock it started with; the error is then
            # re-raised so it is logged rather than quietly swallowed.
            db.rollback()
            raise
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)

    # The import replaced the stock table, which detached every quotation line
    # matched against it. Re-match and re-price the open book so a desk is not
    # left with quotations pointing at lots that no longer exist, quoting costs
    # the business no longer pays. Sent quotations are deliberately untouched.
    resync = StockResyncService(db).resync_open_quotations()

    return StockImportOut(
        quotations_repriced=resync.quotations_repriced,
        drafts_to_rewrite=resync.drafts_flagged,
        status=result.status.value,
        source_file=result.source_file,
        rows_total=result.rows_total,
        rows_imported=result.rows_imported,
        rows_failed=result.rows_failed,
        rows_skipped=result.rows_skipped,
        errors=result.errors,
        batch_id=result.batch_id,
    )


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------


@router.post(
    "/customers", response_model=dict, status_code=status.HTTP_201_CREATED, tags=["customers"]
)
def create_customer(payload: CustomerIn, db: TenantDb) -> dict:
    data = payload.model_dump()
    data["tier"] = CustomerTier(data["tier"])
    customer = Customer(**data, status=RecordStatus.ACTIVE)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return {"id": customer.id, "name": customer.name}


@router.put("/customers/{customer_id}", response_model=dict, tags=["customers"])
def update_customer(
    customer_id: int, payload: CustomerIn, db: TenantDb
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
def verify_customer(customer_id: int, db: TenantDb) -> dict:
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


@router.post("/customers/{customer_id}/priority", response_model=dict, tags=["customers"])
def set_customer_priority(customer_id: int, payload: PriorityIn, db: TenantDb) -> dict:
    """Flag or unflag a customer as priority, from the Customers or
    Quotations list row - a toggle, unlike `verify`, which only ever moves
    one way."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer.is_priority = payload.is_priority
    db.commit()
    return {"id": customer.id, "is_priority": customer.is_priority}


@router.get(
    "/customers/{customer_id}/notes", response_model=list[CustomerNoteOut], tags=["customers"]
)
def list_customer_notes(customer_id: int, db: TenantDb) -> list[CustomerNote]:
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
    db: TenantDb,
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
def customer_timeline(customer_id: int, db: TenantDb) -> list[TimelineEntry]:
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
def insights(db: TenantDb, days: int = Query(30, ge=7, le=365)) -> dict:
    """Headline metrics against the preceding window, plus what needs a person."""
    return InsightService(db).build(days).to_dict()


@router.get("/reports/funnel", tags=["reports"])
def funnel_report(
    db: TenantDb,
    days: int = Query(30,
    ge=1,
    le=730),
    start: date | None = None,
    end: date | None = None,
) -> dict:
    period = _period(days, start, end)
    stages = ReportService(db).funnel(period)
    return {
        "period": period.label(),
        "stages": [
            {
                "stage": s.stage,
                "count": s.count,
                "note": s.note,
                "tonnes": float(s.tonnes),
                "value": float(s.value),
                "unquantified": s.unquantified,
            }
            for s in stages
        ],
    }


def _named_period(period: str, start: date | None, end: date | None):
    """A named window, or an explicit range when both dates are given."""
    if start and end:
        return periods.custom(start, end)
    return periods.resolve(period)


@router.get("/reports/periods", tags=["reports"])
def report_periods() -> dict:
    """The named windows offered in the picker, resolved against today."""
    return {
        "choices": [
            {
                "key": key,
                "label": label,
                "range": periods.resolve(key).current.label(),
            }
            for key, label in periods.CHOICES
        ]
    }


@router.get("/reports/desk", tags=["reports"])
def desk_report(
    db: TenantDb,
    period: str = Query("this-month"),
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """The trading view of a period: what was earned, lost, and left standing."""
    return DeskService(db).build(_named_period(period, start, end)).to_dict()


@router.get("/reports/pack", tags=["reports"], response_model=None)
def report_pack(
    db: TenantDb,
    period: str = Query("this-month"),
    start: date | None = None,
    end: date | None = None,
) -> Response:
    """The whole period as one workbook - a summary sheet plus every table.

    Built server-side rather than in the browser so the file that reaches an
    accountant carries the same figures the page showed, formatted as numbers.
    """
    window = _named_period(period, start, end)
    desk = DeskService(db).build(window)
    service = ReportService(db)
    span = window.current

    builder = WorkbookBuilder(f"Trading report - {window.label}")
    builder.write_summary(desk)
    builder.add_rows("Won & lost by customer", desk.customers)
    builder.add_rows("Product margins", desk.products)
    builder.add_rows("Why we lost", desk.lost_reasons)
    builder.add_rows("Stock ageing", desk.stock.get("oldest", []))
    builder.add_rows("Quiet customers", desk.quiet_customers)
    builder.add_report("Quotation detail", service.win_loss(span))
    builder.add_report("Margin by line", service.margin(span))

    slug = window.label.lower().replace(" ", "-")
    return Response(
        content=builder.to_bytes(),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="trading-report-{slug}.xlsx"'
        },
    )


@router.get("/reports/document", tags=["reports"], response_model=None)
def report_document(
    db: TenantDb,
    user: CurrentUser,
    period: str = Query("this-month"),
    start: date | None = None,
    end: date | None = None,
    download: bool = True,
) -> Response:
    """The period report as one self-contained HTML file.

    The workbook is for somebody who wants to sum a column; this is for somebody
    who wants to read the report. Rendered server-side from the same figures the
    page shows, with its stylesheet inlined, so the file survives being emailed
    or archived and prints to the same pages.
    """
    window = _named_period(period, start, end)
    desk = DeskService(db).build(window)
    service = ReportService(db)
    span = window.current

    organisation = user.organisation.name if user.organisation else "Trading desk"
    html = html_report.build(
        desk,
        organisation=organisation,
        registers={
            "Quotation register": service.win_loss(span),
            "Margin by line": service.margin(span),
        },
    )

    slug = window.label.lower().replace(" ", "-")
    disposition = "attachment" if download else "inline"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'{disposition}; filename="trading-report-{slug}.html"'
        },
    )


@router.get("/reports/{name}", tags=["reports"], response_model=None)
def report(
    name: str,
    db: TenantDb,
    days: int = Query(30,
    ge=1,
    le=730),
    period_key: str | None = Query(None, alias="period"),
    start: date | None = None,
    end: date | None = None,
    fmt: str = Query("json",
    pattern="^(json|csv)$"),
) -> Response | dict:
    """One of: win-loss, margin, stock-ageing, customers, products.

    Accepts either a named period ("last-month") or a rolling day count, so a
    CSV pulled from the page covers exactly the window the page was showing.
    """
    period = (
        _named_period(period_key, start, end).current
        if period_key
        else _period(days, start, end)
    )
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
