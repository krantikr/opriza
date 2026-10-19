"""Cross-cutting system tables: audit trail, LLM telemetry, imports.

Users live in `app.models.tenancy` - identity is a tenancy concern now that
one deployment serves many desks.
"""

from datetime import datetime

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import ImportEntity, ImportStatus
from app.models.mixins import CreatedAtMixin, TenantMixin, enum_col


class AuditLog(Base, CreatedAtMixin, TenantMixin):
    """Append-only record of every meaningful state change.

    Written from the beginning rather than bolted on, because in a trading
    business the question "who agreed to this price, and when?" has to have an
    answer that does not depend on anyone's memory.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    details: Mapped[dict | None] = mapped_column(JSON)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuditLog {self.entity_type}#{self.entity_id} {self.action}>"


class LLMCall(Base, CreatedAtMixin, TenantMixin):
    """Per-call LLM telemetry (spec section 22).

    Recorded for every call including failures, so latency, token spend and
    failure rate are measurable per task. `generation_id` is OpenRouter's
    identifier, which permits exact cost reconciliation after the fact.
    """

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    task: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False, index=True)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    generation_id: Mapped[str | None] = mapped_column(String(120))
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    strict_schema_used: Mapped[bool] = mapped_column(default=False, nullable=False)
    succeeded: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text)

    email_id: Mapped[int | None] = mapped_column(Integer, index=True)
    quotation_request_id: Mapped[int | None] = mapped_column(Integer, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LLMCall {self.task} {self.model} {self.total_tokens}tok>"


class ImportBatch(Base, CreatedAtMixin, TenantMixin):
    """One Excel import run (spec section 30).

    Keeps the file name, a content hash, row counts and validation errors so an
    imported figure can always be traced back to its source file and version.
    """

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[ImportEntity] = mapped_column(enum_col(ImportEntity), nullable=False)
    source_file: Mapped[str] = mapped_column(String(400), nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[ImportStatus] = mapped_column(
        enum_col(ImportStatus), default=ImportStatus.PENDING, nullable=False
    )

    rows_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[list | None] = mapped_column(JSON)

    imported_by: Mapped[str | None] = mapped_column(String(120))
    completed_at: Mapped[datetime | None] = mapped_column()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ImportBatch {self.entity_type} {self.source_file} {self.status}>"


class Lead(Base, CreatedAtMixin):
    """A prospect from the public site: a Request-access form or a demo sign-up.

    Platform-level on purpose: a prospect is not a tenant yet, so this table
    carries no `organisation_id` and therefore no row-level-security policy -
    which is what lets the unauthenticated `/api/v1/leads` route insert into
    it. It is append-only (CreatedAtMixin, no updates); the team reads it from
    the admin console, never the trading desk.
    """

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    monthly_enquiries: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(Text)
    #: Where the request came from - 'marketing_site' for the Request-access
    #: form, 'demo' for a sign-up from the live demo - so we can tell them apart
    #: without guessing.
    source: Mapped[str] = mapped_column(String(60), default="marketing_site", nullable=False, index=True)
    #: What the prospect told us about their business, when the channel asks.
    #: The demo stores trade, city, yearly sales, team size, Tally version and
    #: the problems they picked; the contact form leaves it empty.
    details: Mapped[dict | None] = mapped_column(JSON)
    #: Pipeline status the operator moves it through in the admin console. Kept
    #: a plain string rather than an enum so new stages can be added without a
    #: migration; the API validates the allowed set.
    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False, index=True)
    #: Light abuse signal, never shown to the prospect.
    user_agent: Mapped[str | None] = mapped_column(String(400))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Lead {self.company} {self.email}>"
