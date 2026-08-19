"""Dashboard metrics, audit trail and system status."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.rules import get_rules
from app.models import (
    Approval,
    ApprovalAction,
    AuditLog,
    Customer,
    Email,
    ProcessingStatus,
    QuotationLineItem,
    QuotationRequest,
    QuotationStatus,
    StockAvailability,
    StockItem,
)
from app.schemas.common import Page
from app.schemas.dashboard import (
    ActivityItem,
    ApprovalMetrics,
    DashboardMetrics,
    EmailMetrics,
    QuotationMetrics,
    SystemStatus,
)
from app.schemas.quotations import AuditLogOut
from app.services.email.factory import get_email_source
from app.services.telemetry import usage_summary
from app.services.trends import TrendService

router = APIRouter(tags=["dashboard"])


def _counts_by(db: Session, column) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {(value.value if hasattr(value, "value") else str(value)): count for value, count in rows if value}


def _distinct_spec_count(db: Session) -> int:
    rows = db.execute(
        select(
            StockItem.product_type, StockItem.grade, StockItem.thickness_mm,
            StockItem.width_mm, StockItem.length_mm,
        ).distinct()
    ).all()
    return len(rows)


@router.get("/dashboard/metrics", response_model=DashboardMetrics)
def dashboard_metrics(db: Session = Depends(get_db)) -> DashboardMetrics:
    # --- Emails -----------------------------------------------------------
    email_status = _counts_by(db, Email.processing_status)
    email_category = _counts_by(db, Email.category)
    avg_ms = db.scalar(select(func.avg(Email.processing_ms)).where(Email.processing_ms.isnot(None)))

    emails = EmailMetrics(
        total=db.scalar(select(func.count()).select_from(Email)) or 0,
        pending=email_status.get(ProcessingStatus.PENDING.value, 0),
        processed=email_status.get(ProcessingStatus.PROCESSED.value, 0),
        skipped=email_status.get(ProcessingStatus.SKIPPED.value, 0),
        failed=email_status.get(ProcessingStatus.FAILED.value, 0),
        quotation_requests=email_category.get("QUOTATION_REQUEST", 0),
        by_category=email_category,
        avg_processing_ms=round(float(avg_ms), 1) if avg_ms else None,
    )

    # --- Quotations -------------------------------------------------------
    quotation_status = _counts_by(db, QuotationRequest.status)
    # Suggested rate x tonnage for replies still awaiting approval - indicative
    # only, since suggested_rate is always a cost-plus suggestion.
    suggested_value = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    StockAvailability.suggested_rate
                    * func.coalesce(QuotationLineItem.quantity_mt, StockAvailability.available_qty_mt)
                ),
                0,
            )
        )
        .select_from(StockAvailability)
        .join(QuotationLineItem, StockAvailability.quotation_line_item_id == QuotationLineItem.id)
        .join(QuotationRequest, QuotationLineItem.quotation_request_id == QuotationRequest.id)
        .where(
            QuotationRequest.status.in_([QuotationStatus.READY_FOR_REVIEW, QuotationStatus.EDITED])
        )
    )

    replied = (
        db.scalar(
            select(func.count(func.distinct(Email.replied_to_quotation_id))).where(
                Email.replied_to_quotation_id.isnot(None)
            )
        )
        or 0
    )

    quotations = QuotationMetrics(
        total=db.scalar(select(func.count()).select_from(QuotationRequest)) or 0,
        pending_approval=quotation_status.get(QuotationStatus.READY_FOR_REVIEW.value, 0)
        + quotation_status.get(QuotationStatus.EDITED.value, 0),
        needs_information=quotation_status.get(QuotationStatus.NEEDS_INFORMATION.value, 0),
        approved=quotation_status.get(QuotationStatus.APPROVED.value, 0),
        sent=quotation_status.get(QuotationStatus.SENT.value, 0),
        rejected=quotation_status.get(QuotationStatus.REJECTED.value, 0),
        failed=quotation_status.get(QuotationStatus.FAILED.value, 0),
        replied=replied,
        by_status=quotation_status,
        by_confidence=_counts_by(db, QuotationRequest.confidence),
        total_suggested_value=Decimal(str(suggested_value or 0)),
    )

    # --- Approvals (section 22 quality signals) ---------------------------
    action_counts = _counts_by(db, Approval.action)
    decisions = (
        action_counts.get(ApprovalAction.APPROVE.value, 0)
        + action_counts.get(ApprovalAction.REJECT.value, 0)
    )
    approved = action_counts.get(ApprovalAction.APPROVE.value, 0)
    edited = (
        db.scalar(
            select(func.count()).select_from(Approval).where(Approval.was_edited.is_(True))
        )
        or 0
    )

    approvals = ApprovalMetrics(
        decisions=decisions,
        approved=approved,
        rejected=action_counts.get(ApprovalAction.REJECT.value, 0),
        edited=edited,
        approval_rate=round(approved / decisions, 3) if decisions else None,
        edit_rate=round(edited / approved, 3) if approved else None,
    )

    # --- Recent activity --------------------------------------------------
    recent = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(15)).all()
    activity = [
        ActivityItem(
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            action=entry.action,
            detail=(entry.details or {}).get("quotation_number")
            or (entry.details or {}).get("subject")
            or (entry.details or {}).get("category"),
            at=entry.created_at,
        )
        for entry in recent
    ]

    return DashboardMetrics(
        emails=emails,
        quotations=quotations,
        approvals=approvals,
        llm=usage_summary(db),
        recent_activity=activity,
        generated_at=datetime.now(UTC),
    )


@router.get("/audit-logs", response_model=Page[AuditLogOut])
def list_audit_logs(
    db: Session = Depends(get_db),
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Page[AuditLogOut]:
    query = select(AuditLog)
    count_query = select(func.count()).select_from(AuditLog)

    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
        count_query = count_query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
        count_query = count_query.where(AuditLog.entity_id == entity_id)

    total = db.scalar(count_query) or 0
    rows = db.scalars(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return Page(
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/system/status", response_model=SystemStatus, tags=["system"])
def system_status(db: Session = Depends(get_db)) -> SystemStatus:
    """What the system is configured to do, and whether it can do it.

    Surfaced in the UI so the state of the Gmail connection and the LLM key is
    visible, rather than being discovered when a poll silently returns nothing.
    """
    source = get_email_source()
    rules = get_rules()

    return SystemStatus(
        app_name=settings.app_name,
        environment=settings.app_env,
        database=settings.sqlalchemy_url.split("///")[-1],
        email_source=source.describe(),
        email_source_available=source.is_available(),
        llm_configured=settings.llm_configured,
        llm_models={
            "classify": settings.llm_model_classify,
            "extract": settings.llm_model_extract,
            "draft": settings.llm_model_draft,
        },
        auto_send_enabled=settings.auto_send_enabled,
        rules_version=rules.version,
        stock_lots=db.scalar(select(func.count()).select_from(StockItem)) or 0,
        stock_specs=_distinct_spec_count(db),
        customers=db.scalar(select(func.count()).select_from(Customer)) or 0,
    )


@router.get("/dashboard/trends", tags=["dashboard"])
def dashboard_trends(
    days: int = Query(30, ge=7, le=365), db: Session = Depends(get_db)
) -> dict:
    """A daily series plus the same window immediately preceding it.

    The comparison is like for like - 30 days against 30 days - because
    measuring a partial period against a whole one either flatters or damns
    the desk for no reason.
    """
    return TrendService(db).build(days).to_dict()


@router.get("/system/rules", tags=["system"])
def business_rules() -> dict:
    """The matching and suggested-pricing rules currently in force."""
    return get_rules().model_dump()


# Referenced by the line-item count in metrics; kept explicit for clarity.
_ = QuotationLineItem
