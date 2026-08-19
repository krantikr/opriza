"""Quotation listing, detail and the four review actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import current_user, get_quotation
from app.api.serializers import quotation_detail_out, quotation_out
from app.core.db import get_db
from app.core.logging import get_logger
from app.models import QuotationPricing, QuotationRequest, QuotationStatus, User
from app.schemas.common import ActionResult, Page
from app.schemas.pricing import OverrideIn, PricingOut
from app.schemas.quotations import (
    ApproveIn,
    DraftUpdateIn,
    FollowUpIn,
    QuotationDetailOut,
    QuotationOut,
    RejectIn,
)
from app.services import audit
from app.services.pricing.service import PricingService
from app.services.quotations.approval import ApprovalError, ApprovalService
from app.services.quotations.drafting import DraftingService
from app.services.quotations.followup import FollowUpError, FollowUpService

logger = get_logger(__name__)
router = APIRouter(prefix="/quotations", tags=["quotations"])


def _loaded(query):
    """Eager-load the relationships every quotation response touches."""
    return query.options(
        selectinload(QuotationRequest.line_items),
        selectinload(QuotationRequest.drafts),
        selectinload(QuotationRequest.customer),
        selectinload(QuotationRequest.email),
        selectinload(QuotationRequest.follow_ups),
        selectinload(QuotationRequest.replies),
    )


@router.get("", response_model=Page[QuotationOut])
def list_quotations(
    db: Session = Depends(get_db),
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

    return Page(items=[quotation_out(q) for q in rows], total=total, limit=limit, offset=offset)


@router.get("/{quotation_id}", response_model=QuotationDetailOut)
def get_quotation_detail(
    quotation_id: int, db: Session = Depends(get_db)
) -> QuotationDetailOut:
    quotation = db.scalars(
        _loaded(select(QuotationRequest)).where(QuotationRequest.id == quotation_id)
    ).first()
    if quotation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Quotation {quotation_id} not found")
    return quotation_detail_out(quotation)


@router.put("/{quotation_id}/draft", response_model=ActionResult)
def update_draft(
    payload: DraftUpdateIn,
    quotation: QuotationRequest = Depends(get_quotation),
    db: Session = Depends(get_db),
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
    quotation: QuotationRequest = Depends(get_quotation),
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
) -> ActionResult:
    """Ask for a fresh draft from the same verified figures.

    Regeneration rewrites the prose only. It does not re-run matching or
    pricing, so a reviewer cannot shake a different price out of the system by
    pressing the button again.
    """
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
    quotation: QuotationRequest = Depends(get_quotation),
    db: Session = Depends(get_db),
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
            warnings=["The approval is recorded. Retry sending once the problem is resolved."],
        )

    return ActionResult(
        detail=f"{quotation.quotation_number} sent to {quotation.customer_email}.",
        quotation_id=quotation.id,
        status=quotation.status.value,
    )


@router.post("/{quotation_id}/follow-up", response_model=ActionResult)
def send_follow_up(
    payload: FollowUpIn,
    quotation: QuotationRequest = Depends(get_quotation),
    db: Session = Depends(get_db),
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
    quotation: QuotationRequest = Depends(get_quotation),
    db: Session = Depends(get_db),
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


@router.get("/{quotation_id}/pricing", response_model=list[PricingOut])
def get_pricing(
    quotation: QuotationRequest = Depends(get_quotation),
) -> list[QuotationPricing]:
    """The stored cost build-up for every line, as the calculator renders it."""
    return [item.pricing for item in quotation.line_items if item.pricing is not None]


@router.post("/{quotation_id}/lines/{line_id}/pricing/override", response_model=PricingOut)
def override_component(
    line_id: int,
    payload: OverrideIn,
    quotation: QuotationRequest = Depends(get_quotation),
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
) -> QuotationPricing:
    """Substitute one component's figure for this quotation only.

    The calculated value is kept beside the override, so the breakdown still
    explains itself. Changing a figure marks any existing draft stale rather
    than letting text written against the old number go out unchanged.
    """
    item = next((i for i in quotation.line_items if i.id == line_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Line item not found")

    result = PricingService(db).set_override(
        item,
        component_code=payload.component_code,
        amount=payload.amount,
        user_id=user.id if user else None,
        reason=payload.reason,
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
        },
    )
    db.commit()
    return result.record


@router.delete("/{quotation_id}/lines/{line_id}/pricing/override/{component_code}", response_model=PricingOut)
def clear_component_override(
    line_id: int,
    component_code: str,
    quotation: QuotationRequest = Depends(get_quotation),
    db: Session = Depends(get_db),
) -> QuotationPricing:
    """Put a component back to what the rules say."""
    item = next((i for i in quotation.line_items if i.id == line_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Line item not found")
    result = PricingService(db).clear_override(item, component_code)
    db.commit()
    return result.record


@router.post("/{quotation_id}/pricing/recalculate", response_model=list[PricingOut])
def recalculate(
    quotation: QuotationRequest = Depends(get_quotation),
    db: Session = Depends(get_db),
    keep_overrides: bool = True,
) -> list[QuotationPricing]:
    """Re-run the current rules over every line.

    Used after publishing new rules, or when stock has moved. Overrides are
    kept by default: recomputing must not silently discard a figure a human
    deliberately set.
    """
    service = PricingService(db)
    records = [
        service.price_line(item, quotation=quotation, keep_overrides=keep_overrides).record
        for item in quotation.line_items
    ]
    db.commit()
    return records
