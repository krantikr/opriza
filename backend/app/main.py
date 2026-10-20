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
from app.core.db import session_scope
from app.core.logging import configure_logging, get_logger
from app.core.rules import get_rules
from app.core.tenancy import assert_rls_enforced
from app.models import Email  # noqa: F401 - registers the ORM metadata
from app.services.email.factory import get_email_source
from app.services.poller import poll_all_organisations

logger = get_logger(__name__)
_scheduler: BackgroundScheduler | None = None


def poll_cycle() -> None:
    """One scheduled tick across every active organisation.

    The tick is frequent; whether a given desk is actually checked is decided
    per organisation from its own crawl window. See `app.services.poller`.
    """
    try:
        poll_all_organisations()
    except Exception:  # noqa: BLE001 - a failed poll must not kill the scheduler
        logger.exception("Scheduled poll failed")


def agents_cycle() -> None:
    """Run due agent jobs and pending events for every Oprisa desk."""
    try:
        from app.kb.jobs import tick_all

        tick_all()
    except Exception:  # noqa: BLE001 - a failed tick must not kill the scheduler
        logger.exception("Scheduled agent tick failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    configure_logging()

    # Schema changes go through Alembic now ("uv run alembic upgrade head").
    # `create_all` is deliberately gone: it silently diverges from the
    # migration history, which is how five sessions of hand-written ALTER
    # TABLE happened in the first place.
    # Refuse to serve traffic if the database connection can bypass row-level
    # security - see app.core.tenancy for why this is fatal, not a warning.
    db = session_scope()
    try:
        assert_rls_enforced(db)
    finally:
        db.close()

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
            seconds=settings.poll_tick_seconds,
            id="email_poll",
            max_instances=1,  # never let two polls overlap on one SQLite file
            coalesce=True,
        )
        _scheduler.start()
        logger.info(
            "Poller started: ticking every %ss, each desk checked on its own "
            "crawl window.",
            settings.poll_tick_seconds,
        )
    else:
        logger.info("Poller disabled. Use POST /api/v1/pipeline/run to trigger a cycle.")

    from app.kb.brain import brain_mode
    from app.kb.jobs import scheduler_enabled

    logger.info("Agent brain     : %s", brain_mode())
    if scheduler_enabled():
        if _scheduler is None:
            _scheduler = BackgroundScheduler(timezone="UTC")
            _scheduler.start()
        _scheduler.add_job(
            agents_cycle, "interval", minutes=5, id="agents_tick", max_instances=1, coalesce=True
        )
        logger.info("Agent scheduler on: due jobs and events every 5 minutes.")
    else:
        logger.info("Agent scheduler off (AGENTS_SCHEDULER=on to enable; or run scripts/agents_tick.py).")

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
