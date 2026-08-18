"""Persists LLM call telemetry (spec section 22).

Every call is recorded, including the failures - a model that starts refusing
to produce valid output shows up here as a failure rate rather than as a
mysterious rise in manual reviews.

The `ai` package produces `LLMUsage` and knows nothing about the database; this
is the one place the two meet.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai.schemas import LLMUsage
from app.core.logging import get_logger
from app.models import LLMCall

logger = get_logger(__name__)


def record_call(
    db: Session,
    usage: LLMUsage,
    *,
    email_id: int | None = None,
    quotation_request_id: int | None = None,
) -> LLMCall | None:
    """Store one usage record. Never raises - telemetry must not break work."""
    try:
        call = LLMCall(
            task=usage.task,
            model=usage.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=usage.latency_ms,
            generation_id=usage.generation_id,
            attempts=usage.attempts,
            strict_schema_used=usage.strict_schema_used,
            succeeded=usage.succeeded,
            error=usage.error,
            email_id=email_id,
            quotation_request_id=quotation_request_id,
        )
        db.add(call)
        db.flush()
        return call
    except Exception as exc:  # noqa: BLE001 - telemetry is never load-bearing
        logger.error("Could not record LLM telemetry for task %s: %s", usage.task, exc)
        return None


def record_failure(
    db: Session,
    *,
    task: str,
    model: str,
    error: str,
    email_id: int | None = None,
    quotation_request_id: int | None = None,
) -> LLMCall | None:
    """Record a call that failed before any usage figures were available."""
    return record_call(
        db,
        LLMUsage(model=model, task=task, succeeded=False, error=error[:2000]),
        email_id=email_id,
        quotation_request_id=quotation_request_id,
    )


def usage_summary(db: Session) -> dict[str, object]:
    """Aggregate token spend and reliability, for the dashboard."""
    totals = db.execute(
        select(
            func.count(LLMCall.id),
            func.coalesce(func.sum(LLMCall.total_tokens), 0),
            func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
            func.coalesce(func.avg(LLMCall.latency_ms), 0.0),
        )
    ).one()

    failures = db.scalar(
        select(func.count()).select_from(LLMCall).where(LLMCall.succeeded.is_(False))
    )

    by_task = [
        {
            "task": task,
            "calls": calls,
            "tokens": int(tokens),
            "cost_usd": round(float(cost), 6),
        }
        for task, calls, tokens, cost in db.execute(
            select(
                LLMCall.task,
                func.count(LLMCall.id),
                func.coalesce(func.sum(LLMCall.total_tokens), 0),
                func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
            ).group_by(LLMCall.task)
        ).all()
    ]

    return {
        "calls": totals[0],
        "total_tokens": int(totals[1]),
        "total_cost_usd": round(float(totals[2]), 6),
        "avg_latency_ms": round(float(totals[3]), 1),
        "failures": failures or 0,
        "by_task": by_task,
    }
