"""Cross-cutting system tables: users, audit trail, LLM telemetry, imports."""

from datetime import datetime

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import ImportEntity, ImportStatus, RecordStatus, UserRole
from app.models.mixins import CreatedAtMixin, TimestampMixin, enum_col


class User(Base, TimestampMixin):
    """Actors in the system.

    The MVP ships with a single seeded user and no login screen. The table and
    its foreign keys exist anyway so approvals and audit entries carry a real
    identity from the first row written.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        enum_col(UserRole), default=UserRole.ADMIN, nullable=False
    )
    status: Mapped[RecordStatus] = mapped_column(
        enum_col(RecordStatus), default=RecordStatus.ACTIVE, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email}>"


class AuditLog(Base, CreatedAtMixin):
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


class LLMCall(Base, CreatedAtMixin):
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


class ImportBatch(Base, CreatedAtMixin):
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
