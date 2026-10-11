"""Manual pipeline triggers.

Ingestion and processing normally run on the poller. These endpoints let the
dashboard drive them on demand, which is what the demo in section 31 uses:
send an email, press the button, watch it appear.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import TenantDb
from app.core.config import settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.services.email.factory import get_email_source
from app.services.email.ingestion import EmailIngestionService
from app.services.poller import poll_all_organisations
from app.workflows.quotation import process_pending_emails

logger = get_logger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class IngestResult(BaseModel):
    source: str
    fetched: int = 0
    created: int = 0
    duplicates: int = 0
    failed: int = 0
    errors: list[dict] = Field(default_factory=list)


class ProcessResult(BaseModel):
    processed: int = 0
    ready_for_review: int = 0
    needs_information: int = 0
    skipped: int = 0
    failed: int = 0
    quotation_ids: list[int] = Field(default_factory=list)


@router.post("/ingest", response_model=IngestResult)
def ingest(
    db: TenantDb,
    source: str | None = Query(default=None, pattern="^(local|gmail)$"),
    limit: int = Query(default=25, ge=1, le=100),
) -> IngestResult:
    """Fetch new mail. Safe to call repeatedly - duplicates are skipped."""
    email_source = get_email_source(source)
    report = EmailIngestionService(db, email_source).ingest(limit=limit)
    return IngestResult(
        source=report.source,
        fetched=report.fetched,
        created=report.created,
        duplicates=report.duplicates,
        failed=report.failed,
        errors=report.errors,
    )


@router.post("/process", response_model=ProcessResult)
def process(
    db: TenantDb,
    limit: int = Query(default=25, ge=1, le=100),
) -> ProcessResult:
    """Run the quotation workflow over every pending email."""
    if not settings.llm_configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "OPENROUTER_API_KEY is not set, so the AI steps cannot run. "
            "Add it to .env and restart.",
        )

    results = process_pending_emails(db, limit=limit)
    outcomes = [r.outcome for r in results]

    return ProcessResult(
        processed=len(results),
        ready_for_review=outcomes.count("READY_FOR_REVIEW"),
        needs_information=outcomes.count("NEEDS_INFORMATION"),
        skipped=outcomes.count("SKIPPED"),
        failed=outcomes.count("FAILED"),
        quotation_ids=[r.quotation_id for r in results if r.quotation_id],
    )


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def ingest_and_process(background: BackgroundTasks, limit: int = Query(default=25, ge=1, le=100)):
    """Ingest then process, in the background.

    Returns immediately: a full cycle over a real mailbox takes longer than a
    browser is willing to wait.
    """

    def _cycle() -> None:
        db = session_scope()
        try:
            EmailIngestionService(db, get_email_source()).ingest(limit=limit)
            if settings.llm_configured:
                process_pending_emails(db, limit=limit)
            else:
                logger.warning("Skipping processing: OPENROUTER_API_KEY is not set.")
        except Exception:  # noqa: BLE001 - background task must not crash the server
            logger.exception("Background pipeline run failed")
        finally:
            db.close()

    background.add_task(_cycle)
    return {"detail": "Pipeline run started."}


@router.post("/cron", status_code=status.HTTP_202_ACCEPTED)
def cron_tick(background: BackgroundTasks, x_cron_secret: str | None = Header(default=None)):
    """One poll tick across *every* active desk, driven by an external cron.

    This is the production replacement for the in-process scheduler. On a free
    host that spins down when idle, a `BackgroundScheduler` cannot be trusted to
    keep ticking, so an external cron (GitHub Actions, cron-job.org) calls this
    on a schedule. Each call also wakes a sleeping host as a side effect.

    Unlike `/run`, this is *not* tenant-scoped: it loops over all organisations
    via `poll_all_organisations`, each one checked only if its own crawl window
    says it is due. It is guarded by a shared secret rather than a user session,
    because no user sits behind a cron. The secret is compared in constant time.

    Returns 202 immediately: a full sweep over real mailboxes outlives any
    cron's request timeout, so the work runs in the background.
    """
    if not settings.cron_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CRON_SECRET is not set, so the cron trigger is disabled.",
        )
    if x_cron_secret is None or not hmac.compare_digest(x_cron_secret, settings.cron_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing cron secret.")

    def _tick() -> None:
        try:
            result = poll_all_organisations()
            logger.info("Cron poll tick: %s", result.summary())
        except Exception:  # noqa: BLE001 - background task must not crash the server
            logger.exception("Cron poll tick failed")

    background.add_task(_tick)
    return {"detail": "Poll tick started."}
