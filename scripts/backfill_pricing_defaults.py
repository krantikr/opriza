"""Give every desk that has no pricing rule set the starting one.

Onboarding seeds pricing defaults, but desks created before that was wired in
have none - and a desk with no rule set cannot price anything: the Pricing
screen 404s and every enquiry comes back unquotable, with no way to fix it from
the UI because the editor needs a version to edit.

Idempotent: a desk that already has rules is left exactly as it is, so this is
safe to run repeatedly and safe to run against a database that is already fine.

    uv run python scripts/backfill_pricing_defaults.py
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.tenancy import bind_session
from app.models import Organisation, PricingRuleSet
from app.services.pricing import seed_pricing_defaults


def main() -> int:
    db = SessionLocal()
    try:
        # Reading across every desk at once is exactly what the super-admin
        # sentinel is for; the seeding below is still scoped per organisation.
        bind_session(db, None, super_admin=True)

        organisations = list(db.scalars(select(Organisation).order_by(Organisation.id)))
        if not organisations:
            print("No organisations found - nothing to backfill.")
            return 0

        seeded = 0
        for org in organisations:
            has_rules = db.scalar(
                select(PricingRuleSet.id)
                .where(PricingRuleSet.organisation_id == org.id)
                .limit(1)
            )
            if has_rules is not None:
                print(f"  {org.slug}: already has pricing rules, skipped")
                continue

            rule_set = seed_pricing_defaults(db, organisation_id=org.id, commit=False)
            db.commit()
            seeded += 1
            print(f"  {org.slug}: seeded pricing rules v{rule_set.version}")

        print(f"\nDone. {seeded} of {len(organisations)} desk(s) needed seeding.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
