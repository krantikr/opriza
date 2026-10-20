"""Load the sample businesses onto Oprisa desks (development and demos).

    uv run alembic upgrade head
    uv run python scripts/rls.py apply
    uv run python scripts/oprisa_seed.py                  # all three
    uv run python scripts/oprisa_seed.py shree-balaji-steels

Each desk gets its team as sign-in users (password: oprisa-demo-1), twelve
months of books through the mock Tally source, a month of history, and one
full agent cycle, so the Inbox, Approvals and chat are produced by the agents
themselves. Re-running a desk rebuilds it from scratch.
"""

from __future__ import annotations

import sys
import time

from app.core.db import SessionLocal
from app.core.tenancy import bind_session
from app.kb.seed import SAMPLE_PASSWORD, email_for, seed_business
from app.kb.sources.mock import MockTallySource, mock_businesses


def main(argv: list[str]) -> int:
    keys = argv or [b["key"] for b in mock_businesses()]
    for key in keys:
        started = time.time()
        db = SessionLocal()
        try:
            bind_session(db, None, super_admin=True)
            org = seed_business(db, key)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        team = MockTallySource(key).team()
        print(f"\n{org.name}  (desk {org.id}, {time.time() - started:.0f}s)")
        for person in team:
            print(f"  {person['role']:<9} {email_for(person['name'], key):<45} {SAMPLE_PASSWORD}")
    print("\nSign in at /sign-in and open /app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
