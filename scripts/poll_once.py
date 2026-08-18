"""Run a single ingestion cycle, and optionally the quotation workflow.

    uv run python scripts/poll_once.py                    # ingest only
    uv run python scripts/poll_once.py --process          # ingest, then process
    uv run python scripts/poll_once.py --source gmail --limit 50

Safe to run repeatedly: already-ingested messages are counted as duplicates and
skipped, which is exactly the behaviour a scheduled poller depends on.

`--process` requires OPENROUTER_API_KEY. Without it the AI stages cannot run and
the script says so rather than failing halfway through.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.models import Email, QuotationRequest
from app.services.email.factory import get_email_source
from app.services.email.ingestion import EmailIngestionService
from app.workflows.quotation import process_pending_emails

logger = get_logger("poll_once")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["local", "gmail"], help="override EMAIL_SOURCE")
    parser.add_argument("--limit", type=int, default=25, help="max messages to fetch")
    parser.add_argument(
        "--process", action="store_true", help="run the quotation workflow after ingesting"
    )
    args = parser.parse_args()

    source = get_email_source(args.source)
    print(f"Source: {source.describe()}\n")

    db = session_scope()
    try:
        report = EmailIngestionService(db, source).ingest(limit=args.limit)

        print("Ingestion")
        print(f"  fetched    {report.fetched}")
        print(f"  new        {report.created}")
        print(f"  duplicate  {report.duplicates}")
        print(f"  failed     {report.failed}")
        for error in report.errors[:10]:
            print(f"      {error}")

        if args.process:
            if not settings.llm_configured:
                print(
                    "\nSkipping processing: OPENROUTER_API_KEY is not set.\n"
                    "Add it to .env to enable classification, extraction and drafting."
                )
                return 1

            print("\nProcessing")
            results = process_pending_emails(db, limit=args.limit)
            outcomes: dict[str, int] = {}
            for result in results:
                outcomes[result.outcome] = outcomes.get(result.outcome, 0) + 1
            for outcome, count in sorted(outcomes.items()):
                print(f"  {outcome:20} {count}")
            for result in results:
                if result.quotation_number:
                    print(f"      {result.quotation_number}  {result.status}")

        print(f"\n  emails in database:     {db.scalar(select(func.count()).select_from(Email))}")
        print(
            f"  quotations in database: "
            f"{db.scalar(select(func.count()).select_from(QuotationRequest))}"
        )
    finally:
        db.close()

    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
