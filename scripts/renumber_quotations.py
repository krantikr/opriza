"""Renumber existing quotations per organisation.

Before this, references came from a shared row id, so the second desk onboarded
started at Q-000014 - continuing the first desk's count, and telling them how
much business somebody else had written.

This gives each desk its own series from 1, prefixed with its initials:

    Alpha Steel Traders   Q-000001..Q-000013  ->  AL-000001..AL-000013
    KK Traders            Q-000014..Q-000017  ->  KK-000001..KK-000004

Order is preserved: the oldest quotation on a desk keeps being its first.

    uv run python scripts/renumber_quotations.py          # show the plan
    uv run python scripts/renumber_quotations.py --apply  # write it

A quotation number appears in sent email, so renumbering after a desk has been
trading is a real change - a customer holding Q-000014 will not find it under
that name. Printing the plan first, and requiring --apply, is deliberate.
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.tenancy import bind_session
from app.models import Organisation, QuotationRequest
from app.services.quotations.assembly import quotation_prefix


def main(apply: bool) -> int:
    db = SessionLocal()
    try:
        bind_session(db, None, super_admin=True)
        organisations = list(db.scalars(select(Organisation).order_by(Organisation.id)))

        total = 0
        for org in organisations:
            prefix = quotation_prefix(org)
            quotations = list(
                db.scalars(
                    select(QuotationRequest)
                    .where(QuotationRequest.organisation_id == org.id)
                    # Oldest first, so the desk's first quotation stays its first.
                    .order_by(QuotationRequest.created_at, QuotationRequest.id)
                )
            )
            if not quotations:
                continue

            print(f"\n{org.name} ({prefix})")
            for index, quotation in enumerate(quotations, start=1):
                new_number = f"{prefix}-{index:06d}"
                if quotation.quotation_number == new_number:
                    continue
                print(f"  {quotation.quotation_number}  ->  {new_number}")
                if apply:
                    quotation.quotation_number = new_number
                total += 1

        if not apply:
            print(f"\n{total} would be renumbered. Re-run with --apply to write it.")
            return 0

        # Committed in one transaction: a half-renumbered desk would have two
        # quotations claiming the same reference.
        db.commit()
        print(f"\nRenumbered {total} quotations.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv))
