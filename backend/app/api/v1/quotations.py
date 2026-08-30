"""Quotation listing, detail and the four review actions."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import TenantDb, current_user, get_quotation
from app.api.serializers import quotation_detail_out, quotation_out
from app.core.db import utcnow
from app.core.logging import get_logger
from app.models import (
    PRICING_FROZEN_STATUSES,
    NotSentReason,
    PriorityProduct,
    QuotationLineItem,
    QuotationPricing,
    QuotationRequest,
    QuotationStatus,
    User,
)
from app.schemas.common import ActionResult, Page
from app.schemas.pricing import OverrideIn, PricingOptionIn, PricingOut
from app.schemas.quotations import (
    StageIn,
    ApproveIn,
    DraftUpdateIn,
    FollowUpIn,
    NotSentReasonIn,
    PastOrdersOut,
    QuotationDetailOut,
    QuotationDetailsIn,
    QuotationOut,
    RejectIn,
    ThreadMessageOut,
    ThreadOut,
)
from app.services import audit
from app.services.pricing.engine import active_rule_set
from app.services.pricing.service import PricingService
from app.services.quotations.approval import ApprovalError, ApprovalService
from app.services.quotations.draft_figures import refresh_draft_figures
from app.services.quotations.drafting import DraftingService
from app.services.quotations.followup import FollowUpError, FollowUpService
from app.services.quotations.past_orders import PastOrdersService

logger = get_logger(__name__)
router = APIRouter(prefix="/quotations", tags=["quotations"])


def _loaded(query):
    """Eager-load the relationships every quotation response touches."""
    return query.options(
        selectinload(QuotationRequest.line_items).selectinload(
            QuotationLineItem.matched_stock_item
        ),
        selectinload(QuotationRequest.drafts),
        selectinload(QuotationRequest.customer),
        selectinload(QuotationRequest.email),
        selectinload(QuotationRequest.follow_ups),
        selectinload(QuotationRequest.replies),
    )


def _priority_products(db) -> set[tuple[str, str]]:
    return {(p.grade, p.make) for p in db.scalars(select(PriorityProduct))}


@router.get("/{quotation_id}/thread", response_model=ThreadOut)
def quotation_thread(
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
) -> ThreadOut:
    """The whole conversation with this customer, oldest message first.

    A read-model over the same rows the pipeline uses, so the thread and the
    mailbox can never disagree about where a conversation stands.
    """
    from dataclasses import asdict

    from app.services.threads import build_thread, thread_state

    messages = build_thread(db, quotation)
    return ThreadOut(
        quotation_id=quotation.id,
        quotation_number=quotation.quotation_number,
        # The conversation's state, not the first message's - a reply that
        # needs answering lives on its own row.
        state=thread_state(db, quotation),
        status=quotation.status.value,
        customer_name=quotation.customer_name_raw,
        customer_email=quotation.customer_email,
        messages=[ThreadMessageOut(**asdict(m)) for m in messages],
    )


@router.get("", response_model=Page[QuotationOut])
def list_quotations(
    db: TenantDb,
    status_filter: QuotationStatus | None = Query(default=None, alias="status"),
    customer_id: int | None = None,
    search: str | None = Query(default=None, description="Match quotation number or customer"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[QuotationOut]:
    query = select(QuotationRequest)
    count_query = select(func.count()).select_from(QuotationRequest)

    if status_filter:
        query = query.where(QuotationRequest.status == status_filter)
        count_query = count_query.where(QuotationRequest.status == status_filter)
    if customer_id:
        query = query.where(QuotationRequest.customer_id == customer_id)
        count_query = count_query.where(QuotationRequest.customer_id == customer_id)
    if search:
        pattern = f"%{search.strip()}%"
        condition = (
            QuotationRequest.quotation_number.ilike(pattern)
            | QuotationRequest.customer_name_raw.ilike(pattern)
            | QuotationRequest.customer_company_raw.ilike(pattern)
            | QuotationRequest.customer_email.ilike(pattern)
        )
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        _loaded(query).order_by(QuotationRequest.created_at.desc()).limit(limit).offset(offset)
    ).all()

    pairs = _priority_products(db)
    return Page(
        items=[quotation_out(q, pairs) for q in rows], total=total, limit=limit, offset=offset
    )


@router.get("/export", response_model=None, tags=["quotations"])
def export_quotations(
    db: TenantDb,
    status_filter: QuotationStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    stage: str | None = Query(default=None),
    days: int | None = Query(default=None, ge=1),
) -> Response:
    """The quotation list as a real .xlsx workbook.

    Registered *before* `/{quotation_id}` because FastAPI matches in order and
    a dynamic segment would otherwise swallow the literal path and try to read
    "export" as an integer id.

    A real workbook rather than a CSV: traders open these in Excel, and a CSV
    of Indian-format rupee figures loses its number typing on the way in. Every
    column that holds a number is written as a number so the file can be summed
    and sorted without being cleaned up first.
    """
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    query = select(QuotationRequest)
    if status_filter:
        query = query.where(QuotationRequest.status == status_filter)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            QuotationRequest.quotation_number.ilike(pattern)
            | QuotationRequest.customer_name_raw.ilike(pattern)
            | QuotationRequest.customer_company_raw.ilike(pattern)
            | QuotationRequest.customer_email.ilike(pattern)
        )
    if days:
        query = query.where(
            QuotationRequest.created_at >= utcnow() - timedelta(days=days)
        )

    rows = db.scalars(
        _loaded(query).order_by(QuotationRequest.created_at.desc())
    ).all()

    if stage:
        from app.services.quotations.stages import stage_of

        rows = [q for q in rows if stage_of(q) == stage]

    headers = [
        "Quotation",
        "Customer",
        "Contact",
        "Email",
        "Material",
        "Lines",
        "Value (INR)",
        "Status",
        "Delivery to",
        "Raised",
        "Sent",
    ]

    book = Workbook()
    sheet = book.active
    sheet.title = "Quotations"
    sheet.append(headers)

    head_fill = PatternFill("solid", fgColor="0F172A")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center")

    for quotation in rows:
        out = quotation_out(quotation)
        sheet.append(
            [
                out.quotation_number,
                out.customer_company or out.customer_name or "",
                out.customer_name or "",
                out.customer_email or "",
                out.headline_product or "",
                out.line_count,
                # Written as a number, not a formatted string, so the column
                # sums in Excel without being cleaned up first.
                float(out.total_suggested_value) if out.total_suggested_value else None,
                out.status,
                out.delivery_location or "",
                _naive(quotation.created_at),
                _naive(quotation.sent_at),
            ]
        )

    for column in range(1, len(headers) + 1):
        letter = get_column_letter(column)
        width = max(
            len(str(sheet.cell(row=r, column=column).value or ""))
            for r in range(1, sheet.max_row + 1)
        )
        sheet.column_dimensions[letter].width = min(max(width + 2, 10), 42)

    for row in sheet.iter_rows(min_row=2, min_col=7, max_col=7):
        for cell in row:
            cell.number_format = "#,##0.00"
    for row in sheet.iter_rows(min_row=2, min_col=10, max_col=11):
        for cell in row:
            cell.number_format = "dd-mmm-yyyy hh:mm"

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{sheet.max_row}"

    buffer = BytesIO()
    book.save(buffer)
    stamp = utcnow().strftime("%Y-%m-%d")

    return Response(
        content=buffer.getvalue(),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="quotations-{stamp}.xlsx"'
        },
    )


def _naive(value):
    """Excel has no concept of an offset, and openpyxl refuses tz-aware values."""
    return value.replace(tzinfo=None) if value is not None else None


@router.get("/{quotation_id}/past-orders", response_model=PastOrdersOut)
def quotation_past_orders(
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
) -> PastOrdersOut:
    """What this customer has bought and been quoted before.

    The question a trader asks before sending a rate - "is this what they
    normally pay?" - answered from the same invoice table the pricing
    calculator anchors on, so the tab shows the evidence behind the figure
    rather than a second opinion assembled differently.
    """
    from dataclasses import asdict

    result = PastOrdersService(db).for_quotation(quotation)
    data = asdict(result)
    return PastOrdersOut(**data)


@router.get("/{quotation_id}/attachment", response_model=None, tags=["quotations"])
def quotation_attachment(
    db: TenantDb,
    fmt: str = Query("html", pattern="^(html|pdf)$"),
    quotation: QuotationRequest = Depends(get_quotation),
) -> Response:
    """The document that goes out attached to the quotation email.

    Served as HTML by default so a reviewer can open it in a tab and read
    exactly what the customer will receive - it is the *same* markup the PDF is
    rendered from, not a second rendering that could disagree with it. `fmt=pdf`
    returns the real file, which is what the reviewer is checking.
    """
    from app.services.quotations import pdf as quotation_pdf
    from app.services.quotations.table import build_rows

    # A row exists as soon as a line does, priced or not. The attachment needs a
    # *rate* on at least one line: a quotation document that quotes nothing is
    # not a quotation, and sending one would look like an error to the customer.
    # Deliberately not `row.priced`, which additionally requires a line amount
    # and so a quantity - quoting a rate against an unstated tonnage is normal.
    rows = build_rows(quotation)
    if not any(row.rate is not None for row in rows):
        raise HTTPException(
            status_code=404,
            detail="This quotation has no priced lines, so there is nothing to attach.",
        )

    if fmt == "pdf":
        document = quotation_pdf.build(quotation, rows)
        if document is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "The PDF renderer is unavailable on this host. The HTML preview "
                    "shows the same document."
                ),
            )
        return Response(
            content=document,
            media_type="application/pdf",
            headers={
                "Content-Disposition":
                    f'inline; filename="{quotation_pdf.filename(quotation)}"'
            },
        )

    return Response(
        content=quotation_pdf.build_html(quotation, rows),
        media_type="text/html; charset=utf-8",
    )


@router.get("/{quotation_id}", response_model=QuotationDetailOut)
def get_quotation_detail(
    quotation_id: int, db: TenantDb
) -> QuotationDetailOut:
    quotation = db.scalars(
        _loaded(select(QuotationRequest)).where(QuotationRequest.id == quotation_id)
    ).first()
    if quotation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Quotation {quotation_id} not found")
    return quotation_detail_out(quotation, _priority_products(db))


@router.put("/{quotation_id}/draft", response_model=ActionResult)
def update_draft(
    payload: DraftUpdateIn,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    user: User | None = Depends(current_user),
) -> ActionResult:
    """Save a reviewer's edits. Does not send."""
    try:
        ApprovalService(db).edit_draft(
            quotation,
            subject=payload.subject,
            body=payload.body,
            user_id=user.id if user else None,
            comments=payload.comments,
        )
    except ApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    return ActionResult(
        detail="Draft saved.", quotation_id=quotation.id, status=quotation.status.value
    )


@router.post("/{quotation_id}/regenerate", response_model=ActionResult)
def regenerate_draft(
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    user: User | None = Depends(current_user),
) -> ActionResult:
    """Ask for a fresh draft from the same verified figures.

    Regeneration rewrites the prose only. It does not re-run matching or
    pricing, so a reviewer cannot shake a different price out of the system by
    pressing the button again.
    """
    # Regeneration touches prose, not figures - but the stored draft is the
    # record of what the customer was actually sent, so it is frozen for the
    # same reason the price is.
    _require_unsent(quotation)
    service = ApprovalService(db)
    service.record_regeneration(quotation, user_id=user.id if user else None)

    result = DraftingService(db).generate(quotation, user_id=user.id if user else None)
    if result.error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Draft generation failed: {result.error}")

    return ActionResult(
        detail=f"Draft v{result.draft.version} generated.",
        quotation_id=quotation.id,
        status=quotation.status.value,
        warnings=result.review_notes,
    )


@router.post("/{quotation_id}/approve", response_model=ActionResult)
def approve_quotation(
    payload: ApproveIn,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    user: User | None = Depends(current_user),
) -> ActionResult:
    """Record the approval and send the email. The only path that sends."""
    try:
        result = ApprovalService(db).approve_and_send(
            quotation,
            user_id=user.id if user else None,
            subject=payload.subject,
            body=payload.body,
            comments=payload.comments,
        )
    except ApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if not result.sent:
        # The approval is recorded; the send is what failed. Say which.
        return ActionResult(
            ok=False,
            detail=f"Approved, but sending failed: {result.send.error if result.send else 'unknown error'}",
            quotation_id=quotation.id,
            status=quotation.status.value,
            warnings=[
                "The approval is recorded. Retry sending once the problem is resolved.",
                *result.warnings,
            ],
        )

    return ActionResult(
        detail=f"{quotation.quotation_number} sent to {quotation.customer_email}.",
        quotation_id=quotation.id,
        status=quotation.status.value,
        # A price in the wording that the calculator does not hold. The mail
        # has gone; naming the figure is what lets the desk follow it up.
        warnings=result.warnings,
    )


@router.post("/{quotation_id}/follow-up", response_model=ActionResult)
def send_follow_up(
    payload: FollowUpIn,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    user: User | None = Depends(current_user),
) -> ActionResult:
    """Send a nudge on a quotation that has already gone out. Repeatable."""
    try:
        result = FollowUpService(db).send(
            quotation,
            user_id=user.id if user else None,
            subject=payload.subject,
            body=payload.body,
        )
    except FollowUpError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if not result.sent:
        return ActionResult(
            ok=False,
            detail=f"Follow-up failed: {result.send.error}",
            quotation_id=quotation.id,
            status=quotation.status.value,
        )

    return ActionResult(
        detail=f"Follow-up sent to {quotation.customer_email}.",
        quotation_id=quotation.id,
        status=quotation.status.value,
    )


@router.post("/{quotation_id}/reject", response_model=ActionResult)
def reject_quotation(
    payload: RejectIn,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    user: User | None = Depends(current_user),
) -> ActionResult:
    try:
        ApprovalService(db).reject(
            quotation, reason=payload.reason, user_id=user.id if user else None
        )
    except ApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    return ActionResult(
        detail=f"{quotation.quotation_number} rejected.",
        quotation_id=quotation.id,
        status=quotation.status.value,
    )


# --- Pricing calculator ----------------------------------------------------


@router.get("/pricing/locations", response_model=list[str])
def list_pricing_locations(db: TenantDb) -> list[str]:
    """Every warehouse a quotation could be priced from - whatever locations
    have ever appeared in a stock import, whether or not this specific
    material happens to be there right now.

    Registered before `/{quotation_id}/...`, matching the convention already
    used for `/export` above: a literal path declared after a parameterised
    one risks FastAPI trying to read "pricing" as a quotation id first.
    """
    return PricingService(db).known_locations()


@router.get("/{quotation_id}/pricing", response_model=list[PricingOut])
def get_pricing(
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
) -> list[PricingOut]:
    """The stored cost build-up for every line, as the calculator renders it."""
    live = active_rule_set(db)
    rows = []
    for item in quotation.line_items:
        if item.pricing is None:
            continue
        out = PricingOut.model_validate(item.pricing)
        # A row priced against a rule set that is no longer the live one is a
        # snapshot, not a verdict. Saying so lets the screen offer a recompute
        # instead of repeating a warning that has since been resolved.
        out.rules_stale = bool(live and item.pricing.rule_set_id != live.id)
        rows.append(out)
    return rows


def _require_unsent(quotation: QuotationRequest) -> None:
    """Refuse to rewrite the figures of a quotation already with the customer.

    A sent quotation is a commitment, and the stored build-up is the record of
    what was actually offered. Re-pricing it would overwrite that record with a
    number the customer never saw - and the trader would have no way to tell
    what they had promised. Re-quoting at a new price is a new quotation.
    """
    if quotation.status in PRICING_FROZEN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{quotation.quotation_number} is {quotation.status.value}. "
                "Its figures are the record of what was quoted and cannot be changed."
            ),
        )


@router.post("/{quotation_id}/lines/{line_id}/pricing/override", response_model=PricingOut)
def override_component(
    line_id: int,
    payload: OverrideIn,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    user: User | None = Depends(current_user),
) -> QuotationPricing:
    """Substitute one component's figure for this quotation only.

    The calculated value is kept beside the override, so the breakdown still
    explains itself. Changing a figure marks any existing draft stale rather
    than letting text written against the old number go out unchanged.
    """
    _require_unsent(quotation)
    item = next((i for i in quotation.line_items if i.id == line_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Line item not found")

    result = PricingService(db).set_override(
        item,
        component_code=payload.component_code,
        amount=payload.amount,
        user_id=user.id if user else None,
        reason=payload.reason,
        despatch_location=payload.despatch_location,
    )

    audit.record(
        db,
        entity_type="quotation_request",
        entity_id=quotation.id,
        action="PRICING_OVERRIDDEN",
        user_id=user.id if user else None,
        details={
            "line_no": item.line_no,
            "component": payload.component_code,
            "amount": str(payload.amount),
            "reason": payload.reason,
            "despatch_location": payload.despatch_location,
        },
    )
    # An overridden component moves the quoted rate, and the drafted reply
    # carries that rate as text. Refreshing it keeps the document and the
    # calculator from disagreeing while the draft still sits in review - but
    # only when the changed option is the one actually selected; editing a
    # comparison option nobody has chosen yet must not touch what the
    # customer is being shown.
    if result.record.is_selected:
        refresh_draft_figures(db, quotation)
    db.commit()
    return result.record


@router.delete("/{quotation_id}/lines/{line_id}/pricing/override/{component_code}", response_model=PricingOut)
def clear_component_override(
    line_id: int,
    component_code: str,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    despatch_location: str | None = None,
) -> QuotationPricing:
    """Put a component back to what the rules say."""
    _require_unsent(quotation)
    item = next((i for i in quotation.line_items if i.id == line_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Line item not found")
    result = PricingService(db).clear_override(
        item, component_code, despatch_location=despatch_location
    )
    if result.record.is_selected:
        refresh_draft_figures(db, quotation)
    db.commit()
    return result.record


@router.get("/{quotation_id}/lines/{line_id}/pricing/options", response_model=list[PricingOut])
def list_pricing_options(
    line_id: int,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
) -> list[QuotationPricing]:
    """Every price this line has been given, one per despatch location
    compared - almost always just one, the line's original build-up."""
    item = next((i for i in quotation.line_items if i.id == line_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Line item not found")
    return item.pricing_options


@router.post(
    "/{quotation_id}/lines/{line_id}/pricing/options",
    response_model=PricingOut,
    status_code=status.HTTP_201_CREATED,
)
def add_pricing_option(
    line_id: int,
    payload: PricingOptionIn,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
) -> QuotationPricing:
    """Add a price to compare from another warehouse, or a hand-priced
    "Other" location with no stock behind it."""
    _require_unsent(quotation)
    item = next((i for i in quotation.line_items if i.id == line_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Line item not found")

    if any(o.despatch_location == payload.despatch_location for o in item.pricing_options):
        raise HTTPException(
            status_code=422,
            detail=f"This line already has an option for {payload.despatch_location}.",
        )

    service = PricingService(db)
    if payload.manual:
        record = service.add_manual_option(item, payload.despatch_location or "Other")
    else:
        record = service.price_line(
            item, quotation=quotation, despatch_location=payload.despatch_location
        ).record
    db.commit()
    return record


@router.post(
    "/{quotation_id}/lines/{line_id}/pricing/options/{pricing_id}/select",
    response_model=PricingOut,
)
def select_pricing_option(
    line_id: int,
    pricing_id: int,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    user: User | None = Depends(current_user),
) -> QuotationPricing:
    """Make one option the line's selected price - what the draft, the PDF
    and every report will read from now on."""
    _require_unsent(quotation)
    item = next((i for i in quotation.line_items if i.id == line_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Line item not found")

    try:
        record = PricingService(db).select_option(item, pricing_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    audit.record(
        db,
        entity_type="quotation_request",
        entity_id=quotation.id,
        action="PRICING_OPTION_SELECTED",
        user_id=user.id if user else None,
        details={"line_no": item.line_no, "despatch_location": record.despatch_location},
    )
    # The selected option changed, so what the draft quotes changed with it.
    refresh_draft_figures(db, quotation)
    db.commit()
    return record


@router.delete("/{quotation_id}/lines/{line_id}/pricing/options/{pricing_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_pricing_option(
    line_id: int,
    pricing_id: int,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
) -> None:
    """Drop one comparison option. Never the selected one - pick a
    different option first, so the line is never left with no price."""
    _require_unsent(quotation)
    item = next((i for i in quotation.line_items if i.id == line_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Line item not found")

    record = next((o for o in item.pricing_options if o.id == pricing_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="Pricing option not found")
    if record.is_selected:
        raise HTTPException(
            status_code=422,
            detail="This is the selected price - choose a different option before removing it.",
        )

    item.pricing_options.remove(record)
    db.commit()


@router.post("/{quotation_id}/pricing/recalculate", response_model=list[PricingOut])
def recalculate(
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    keep_overrides: bool = True,
) -> list[QuotationPricing]:
    """Re-run the current rules over every line.

    Used after publishing new rules, or when stock has moved. Overrides are
    kept by default: recomputing must not silently discard a figure a human
    deliberately set.
    """
    _require_unsent(quotation)
    service = PricingService(db)
    records = [
        service.price_line(item, quotation=quotation, keep_overrides=keep_overrides).record
        for item in quotation.line_items
    ]
    refresh_draft_figures(db, quotation)
    db.commit()
    return records


@router.put("/{quotation_id}/details", response_model=ActionResult)
def update_details(
    payload: QuotationDetailsIn,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    user: User | None = Depends(current_user),
) -> ActionResult:
    """Record terms the enquiry left unstated, and re-price against them.

    Re-pricing is the point: a delivery location brings freight into the
    build-up, and payment terms drive the financing line. Saving the fields
    without recomputing would leave a quote that contradicts its own inputs.
    """
    changed: dict[str, str | None] = {}
    for field_name in ("delivery_location", "required_delivery_date", "payment_terms"):
        value = getattr(payload, field_name)
        cleaned = value.strip() if isinstance(value, str) else value
        cleaned = cleaned or None
        if getattr(quotation, field_name) != cleaned:
            changed[field_name] = cleaned
            setattr(quotation, field_name, cleaned)

    if not changed:
        return ActionResult(detail="No changes.", quotation_id=quotation.id)

    # Anything still outstanding stays outstanding; anything supplied is
    # removed from the missing list so the banner reflects reality.
    supplied = {
        "delivery_location": "delivery location",
        "required_delivery_date": "required delivery date",
        "payment_terms": "payment terms",
    }
    remaining = [
        note
        for note in (quotation.missing_information or [])
        if not any(
            phrase in note.lower()
            for key, phrase in supplied.items()
            if changed.get(key)
        )
    ]
    quotation.missing_information = remaining or None
    db.flush()

    service = PricingService(db)
    for item in quotation.line_items:
        service.price_line(item, quotation=quotation)

    # The terms that were just supplied are usually the reason the lines could
    # not be priced at all, so the draft written before them shows an empty
    # Rate column. Re-splicing its table here means the reply the reviewer is
    # looking at carries the figures the calculator now holds, without costing
    # a regeneration or rewriting a sentence they may have edited.
    refreshed = refresh_draft_figures(db, quotation)

    audit.record(
        db,
        entity_type="quotation_request",
        entity_id=quotation.id,
        action="DETAILS_UPDATED",
        user_id=user.id if user else None,
        details={k: str(v) for k, v in changed.items()},
    )
    db.commit()

    detail = f"Updated {', '.join(changed)} and re-priced every line."
    if refreshed is not None:
        detail += " The drafted reply now shows the new figures."

    return ActionResult(
        detail=detail,
        quotation_id=quotation.id,
        status=quotation.status.value,
    )


@router.post("/{quotation_id}/stage", response_model=ActionResult)
def set_stage(
    payload: StageIn,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    user: User | None = Depends(current_user),
) -> ActionResult:
    """Move a quotation to a working stage by hand.

    Every stage is settable, deliberately. A deal is agreed on the phone as
    often as by email, a customer says "we'll take it" to a salesman in a
    corridor, and a board that cannot be corrected is one that stops being
    trusted and then stops being used.

    What this changes is the *status* - where the quotation sits on the board.
    It does not touch the draft, the approval record, or the sent message id,
    so the account of what was actually said to the customer survives a
    trader dragging a card, and the audit log records who moved it.
    """
    from app.services.quotations.stages import LABELS, STATUS_FOR_STAGE

    target = STATUS_FOR_STAGE.get(payload.stage)
    if target is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{payload.stage} is not a stage. Expected one of: "
            + ", ".join(STATUS_FOR_STAGE),
        )

    previous = quotation.status
    if previous is target and payload.stage != "delivery_pending":
        return ActionResult(
            detail=f"Already in {LABELS.get(payload.stage, payload.stage)}.",
            quotation_id=quotation.id,
            status=quotation.status.value,
        )

    quotation.status = target

    # The dates that define a stage move with it, or the board and the
    # timestamps disagree about the same quotation.
    if payload.stage == "delivery_pending":
        # Back from payment: the goods have not gone after all.
        quotation.despatched_at = None
        quotation.paid_at = None
    elif payload.stage == "payment_pending":
        quotation.despatched_at = quotation.despatched_at or utcnow()
        quotation.paid_at = None
    elif payload.stage in ("completed", "won"):
        quotation.despatched_at = quotation.despatched_at or utcnow()
        quotation.paid_at = quotation.paid_at or utcnow()

    audit.record(
        db,
        entity_type="quotation_request",
        entity_id=quotation.id,
        action="STAGE_CHANGED",
        user_id=user.id if user else None,
        details={
            "quotation_number": quotation.quotation_number,
            "stage": payload.stage,
            "from_status": previous.value,
            "to_status": target.value,
            "reason": payload.reason,
        },
    )
    db.commit()

    return ActionResult(
        detail=f"{quotation.quotation_number} moved to {LABELS.get(payload.stage, payload.stage)}.",
        quotation_id=quotation.id,
        status=quotation.status.value,
    )


@router.post("/{quotation_id}/not-sent-reason", response_model=ActionResult)
def set_not_sent_reason(
    payload: NotSentReasonIn,
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
) -> ActionResult:
    """Record why a quotation still sitting in "received" hasn't gone out.

    Separate from `set_stage`: the reason can be set, changed, or cleared
    (pass `not_sent_reason: null`) without the quotation itself moving.
    """
    if payload.not_sent_reason is not None:
        try:
            quotation.not_sent_reason = NotSentReason(payload.not_sent_reason)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{payload.not_sent_reason} is not a reason. Expected one of: "
                + ", ".join(r.value for r in NotSentReason),
            ) from exc
    else:
        quotation.not_sent_reason = None
    quotation.not_sent_note = payload.not_sent_note
    db.commit()

    return ActionResult(
        detail="Reason updated.",
        quotation_id=quotation.id,
        status=quotation.status.value,
    )


@router.post("/{quotation_id}/despatched", response_model=ActionResult)
def mark_despatched(
    db: TenantDb,
    quotation: QuotationRequest = Depends(get_quotation),
    user: User | None = Depends(current_user),
) -> ActionResult:
    """Record that the goods have gone out.

    An accepted quotation sits in the Delivery queue until this happens,
    because until the material ships the customer is still owed something.
    """
    if quotation.status is not QuotationStatus.CUSTOMER_ACCEPTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{quotation.quotation_number} is {quotation.status.value}, not accepted. "
                "Only an accepted quotation can be despatched."
            ),
        )
    if quotation.despatched_at is not None:
        return ActionResult(
            detail="Already recorded as despatched.",
            quotation_id=quotation.id,
            status=quotation.status.value,
        )

    quotation.despatched_at = utcnow()
    audit.record(
        db,
        entity_type="quotation_request",
        entity_id=quotation.id,
        action="DESPATCHED",
        user_id=user.id if user else None,
        details={"quotation_number": quotation.quotation_number},
    )
    db.commit()

    return ActionResult(
        detail=f"{quotation.quotation_number} marked despatched.",
        quotation_id=quotation.id,
        status=quotation.status.value,
    )
