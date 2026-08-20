"""Create the super admin, so there is somebody who can onboard the first desk.

Idempotent: running it twice does not create a second operator or reset an
existing password.

    uv run python scripts/seed_platform.py

The credentials come from `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD`. The
defaults are development-only and the script says so loudly, because a
platform operator account with a known password is the one credential worth
being noisy about.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.core.tenancy import bind_session
from app.models import User, UserRole
from app.services.auth import normalise_email


def main() -> int:
    db = SessionLocal()
    try:
        # The operator belongs to no organisation, so this runs on the
        # cross-tenant sentinel rather than scoped to a desk.
        bind_session(db, None, super_admin=True)

        address = normalise_email(settings.super_admin_email)
        existing = db.scalars(select(User).where(User.email == address)).first()
        if existing is not None:
            print(f"Super admin already exists: {address}")
            return 0

        db.add(
            User(
                organisation_id=None,
                name="Platform Operator",
                email=address,
                password_hash=hash_password(settings.super_admin_password),
                role=UserRole.OWNER,
                is_super_admin=True,
            )
        )
        db.commit()

        print(f"Created super admin: {address}")
        if settings.super_admin_password == "change-me-now":
            print(
                "\n  WARNING: this account uses the default password.\n"
                "  Set SUPER_ADMIN_PASSWORD and change it before this is\n"
                "  reachable from anywhere but your own machine.\n"
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
