"""Database engine, session factory and declarative base.

SQLite is the MVP store. Two things matter for correctness here:

1. WAL journal mode, so the background email poller can write while the API
   serves reads without lock contention.
2. No SQLite-specific SQL anywhere in the codebase - every query goes through
   SQLAlchemy - so moving to PostgreSQL later is a URL change plus a migration.
"""

from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp used for every audit-relevant column."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base with a portable timezone-aware datetime default."""

    type_annotation_map = {datetime: DateTime(timezone=True)}


_connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

engine: Engine = create_engine(
    settings.sqlalchemy_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    """Enable WAL + foreign keys on every SQLite connection."""
    if not settings.is_sqlite:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session_scope() -> Session:
    """Session for background jobs and scripts. Caller is responsible for close."""
    return SessionLocal()
