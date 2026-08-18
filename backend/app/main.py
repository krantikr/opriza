"""FastAPI application entry point.

    uv run uvicorn app.main:app --reload

The optional background poller is off by default. Ingesting a real mailbox on a
timer is a decision to make deliberately, not something that should start
happening because someone ran the server.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.db import Base, engine, session_scope
from app.core.logging import configure_logging, get_logger
from app.core.rules import get_rules
from app.models import Email  # noqa: F401 - registers the ORM metadata
from app.services.email.factory import get_email_source
from app.services.email.ingestion import EmailIngestionService
from app.workflows.quotation import process_pending_emails

logger = get_logger(__name__)
_scheduler: BackgroundScheduler | None = None


def poll_cycle() -> None:
    """One scheduled ingest-and-process pass."""
    db = session_scope()
    try:
        source = get_email_source()
        if not source.is_available():
            logger.warning("Poll skipped: %s is not available.", source.describe())
            return
        EmailIngestionService(db, source).ingest(limit=settings.gmail_max_results)
        if settings.llm_configured:
            process_pending_emails(db, limit=settings.gmail_max_results)
        else:
            logger.warning("Poll ingested only: OPENROUTER_API_KEY is not set.")
    except Exception:  # noqa: BLE001 - a failed poll must not kill the scheduler
        logger.exception("Scheduled poll failed")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    configure_logging()

    # Create any missing tables so a fresh checkout can boot. Seeding and
    # imports stay in scripts/init_db.py, which is explicit about what it does.
    Base.metadata.create_all(bind=engine)

    rules = get_rules()
    logger.info("%s starting (%s)", settings.app_name, settings.app_env)
    logger.info("Database        : %s", settings.sqlalchemy_url)
    logger.info("Email source    : %s", get_email_source().describe())
    logger.info("LLM configured  : %s", settings.llm_configured)
    logger.info("Business rules  : v%s", rules.version)
    if not settings.llm_configured:
        logger.warning("OPENROUTER_API_KEY is not set - the AI steps will refuse to run.")

    if settings.polling_enabled:
        _scheduler = BackgroundScheduler(timezone="UTC")
        _scheduler.add_job(
            poll_cycle,
            "interval",
            seconds=settings.polling_interval_seconds,
            id="email_poll",
            max_instances=1,  # never let two polls overlap on one SQLite file
            coalesce=True,
        )
        _scheduler.start()
        logger.info("Poller started (every %ss)", settings.polling_interval_seconds)
    else:
        logger.info("Poller disabled. Use POST /api/v1/pipeline/run to trigger a cycle.")

    yield

    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Poller stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "AI-assisted quotation workflow for steel trading. "
        "Language models read and write; deterministic services price; a human approves."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}
