"""Create the database schema, seed the default user, and import master data.

    uv run python scripts/init_db.py                              # create + import
    uv run python scripts/init_db.py --reset                      # drop everything first
    uv run python scripts/init_db.py --no-import                  # schema and user only
    uv run python scripts/init_db.py --stock-file "data/Stock List Aug-2026.xlsx"
    uv run python scripts/init_db.py --data-dir ...                # customers.xlsx from elsewhere

There is no fixed stock filename - the client's export is dated per month -
so it is passed explicitly with `--stock-file` rather than discovered by
convention.

The MVP deliberately has no migration tool. With SQLite, `--reset` is the
honest workflow; Alembic goes in at the PostgreSQL transition, where
versioned migrations start earning their keep.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.db import Base, engine, session_scope
from app.core.logging import get_logger
from app.core.paths import SAMPLE_DIR
from app.models import User, UserRole  # noqa: F401 - registers all tables
from app.services.ingestion.excel_importer import ImportFailed, import_directory
from app.services.pricing.defaults import seed_pricing_defaults

logger = get_logger("init_db")

DEFAULT_USER_EMAIL = "owner@localhost"
DEFAULT_USER_NAME = "Business Owner"


def create_schema(reset: bool) -> None:
    if reset:
        logger.warning("Dropping all tables in %s", settings.sqlalchemy_url)
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    logger.info("Schema ready (%d tables)", len(Base.metadata.tables))


def seed_default_user() -> None:
    """Ensure the single MVP user exists.

    There is no login in the MVP, but approvals and audit rows still need a real
    identity to point at, so it is created here rather than left null.
    """
    with session_scope() as db:
        existing = db.scalar(select(User).where(User.email == DEFAULT_USER_EMAIL))
        if existing:
            logger.info("Default user already present (id=%s)", existing.id)
            return
        user = User(name=DEFAULT_USER_NAME, email=DEFAULT_USER_EMAIL, role=UserRole.ADMIN)
        db.add(user)
        db.commit()
        logger.info("Seeded default user %s (id=%s)", user.email, user.id)


def seed_defaults() -> None:
    """Publish a starting rule set and the operational rules a desk needs.

    Idempotent, so this is safe on every run. A new installation opens on a
    calculator it recognises rather than an empty table it has to design.
    """
    from app.core.db import session_scope
    from app.models import FollowUpRule, NotificationChannel, NotificationKind, NotificationRule

    db = session_scope()
    try:
        rule_set = seed_pricing_defaults(db)
        logger.info("Pricing rules: v%s active", rule_set.version)

        if db.query(NotificationRule).count() == 0:
            db.add(
                NotificationRule(
                    label="Quotation ready - dashboard",
                    kind=NotificationKind.QUOTATION_READY,
                    channel=NotificationChannel.IN_APP,
                )
            )
            logger.info("Seeded the default notification rule")

        if db.query(FollowUpRule).count() == 0:
            from app.models import FollowUpTrigger

            db.add(
                FollowUpRule(
                    label="Confirm within 24 hours",
                    trigger=FollowUpTrigger.ELAPSED,
                    first_after_hours=24,
                    interval_days=5,
                    max_attempts=2,
                    stop_after_days=30,
                    auto_send=False,
                )
            )
            db.add(
                FollowUpRule(
                    label="Follow up on the customer's own date",
                    trigger=FollowUpTrigger.PROMISED_DATE,
                    remind_before_hours=0,
                    max_attempts=2,
                    stop_after_days=60,
                    auto_send=False,
                )
            )
            logger.info("Seeded two follow-up rules (both queue for approval)")
        db.commit()
    finally:
        db.close()


def import_master_data(data_dir: Path, stock_file: Path | None) -> bool:
    if not data_dir.exists():
        logger.error("Data directory not found: %s", data_dir)
        return False

    with session_scope() as db:
        try:
            results = import_directory(db, data_dir, stock_file=stock_file)
        except ImportFailed as exc:
            logger.error("Import aborted: %s", exc)
            return False

    if not results:
        logger.warning(
            "Nothing imported - no customers.xlsx in %s and no --stock-file given", data_dir
        )
        return False

    print("\nImport summary")
    print("-" * 78)
    for result in results:
        print("  " + result.summary())
        for error in result.errors[:5]:
            print(f"      row {error['row']}: {error['error']}")
        if len(result.errors) > 5:
            print(f"      ... and {len(result.errors) - 5} more errors")
    print("-" * 78)
    return all(r.rows_failed == 0 for r in results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop all tables before creating")
    parser.add_argument("--no-import", action="store_true", help="skip master data import")
    parser.add_argument("--data-dir", type=Path, default=SAMPLE_DIR, help="folder holding customers.xlsx")
    parser.add_argument(
        "--stock-file", type=Path, default=None, help="path to the client's stock list .xlsx"
    )
    args = parser.parse_args()

    logger.info("Database: %s", settings.sqlalchemy_url)
    create_schema(reset=args.reset)
    seed_default_user()
    seed_defaults()

    if args.no_import:
        logger.info("Skipping master data import (--no-import)")
        return 0

    clean = import_master_data(args.data_dir, args.stock_file)
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
