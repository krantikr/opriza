"""Connect a real desk to its Tally and start the agents on it.

    uv run python scripts/oprisa_connect.py <org-slug> --tally-url http://192.168.1.20:9000 \
        [--trade steel] [--city Pune] [--language Hinglish] [--tally-version TallyPrime]

    uv run python scripts/oprisa_connect.py <org-slug> --role priya@firm.in purchase

See docs/agents/RUNBOOK.md.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.core.db import SessionLocal
from app.core.tenancy import bind_session
from app.kb.connect import DESK_ROLES, connect_desk, set_role


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--tally-url")
    ap.add_argument("--trade", default="steel")
    ap.add_argument("--city")
    ap.add_argument("--language", default="English", choices=("English", "Hinglish"))
    ap.add_argument("--tally-version", default="TallyPrime")
    ap.add_argument(
        "--no-agents", action="store_true", help="Sync and build facts, but don't run the agents yet"
    )
    ap.add_argument(
        "--role", nargs=2, metavar=("EMAIL", "DESK_ROLE"), help=f"Set a desk role: {', '.join(DESK_ROLES)}"
    )
    args = ap.parse_args(argv)
    if not args.tally_url and not args.role:
        ap.error("give --tally-url to connect, or --role to change a desk role")

    db = SessionLocal()
    try:
        bind_session(db, None, super_admin=True)
        if args.role:
            set_role(db, args.slug, args.role[0], args.role[1])
            print(f"{args.role[0]} is now {args.role[1]}.")
        if args.tally_url:
            bind_session(db, None, super_admin=True)
            out = connect_desk(
                db,
                args.slug,
                args.tally_url,
                trade=args.trade,
                city=args.city,
                language=args.language,
                tally_version=args.tally_version,
                run_agents=not args.no_agents,
            )
            print(json.dumps(out, indent=2, default=str))
            if out["sync"] != "ok":
                print("\nTally wasn't reachable; the desk is set up and every tick will retry the sync.")
        db.commit()
    except ValueError as exc:
        db.rollback()
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
