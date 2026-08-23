"""Dashboard metric DTOs (spec section 18)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class EmailMetrics(BaseModel):
    total: int = 0
    pending: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    quotation_requests: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    avg_processing_ms: float | None = None


class QuotationMetrics(BaseModel):
    total: int = 0
    pending_approval: int = 0
    needs_information: int = 0
    approved: int = 0
    sent: int = 0
    rejected: int = 0
    failed: int = 0
    # Distinct quotations with at least one classified customer reply,
    # regardless of intent - a quotation can be "replied" while its status
    # stays SENT (a NEEDS_REVIEW reply does not move the status).
    replied: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_confidence: dict[str, int] = Field(default_factory=dict)
    # Suggested rate x tonnage across replies awaiting approval - indicative
    # only, never an approved figure.
    total_suggested_value: Decimal | None = None


class ApprovalMetrics(BaseModel):
    """Section 22's quality signals: how often a human had to intervene."""

    decisions: int = 0
    approved: int = 0
    rejected: int = 0
    edited: int = 0
    approval_rate: float | None = None
    edit_rate: float | None = None


class ActivityItem(BaseModel):
    entity_type: str
    entity_id: int | None = None
    action: str
    detail: str | None = None
    at: datetime


class DashboardMetrics(BaseModel):
    emails: EmailMetrics
    quotations: QuotationMetrics
    approvals: ApprovalMetrics
    llm: dict[str, Any] = Field(default_factory=dict)
    recent_activity: list[ActivityItem] = Field(default_factory=list)
    generated_at: datetime


class SystemStatus(BaseModel):
    app_name: str
    environment: str
    database: str
    email_source: str
    email_source_available: bool
    llm_configured: bool
    llm_models: dict[str, str]
    auto_send_enabled: bool
    rules_version: str
    # The published pricing rule set, which is what the desk actually prices
    # with. None until one exists - distinct from `rules_version` above, which
    # is the version of the static business-rules file.
    pricing_version: int | None = None
    stock_lots: int = 0
    stock_specs: int = 0
    customers: int = 0
    #: When this desk's mailbox was last checked, and how often it is checked
    #: right now. The cadence is time-banded, so "every 10 minutes" is only
    #: true inside working hours - the poller's own reason string is carried
    #: through rather than restated here, where it would drift.
    last_polled_at: datetime | None = None
    poll_reason: str | None = None
