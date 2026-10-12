"""Generate and apply PostgreSQL row-level security policies.

Policies are derived from the models rather than written by hand: every table
carrying `organisation_id` gets one, so adding a table cannot leave a gap that
nobody notices until two desks can read each other.

Run after any migration that adds a table:

    uv run python scripts/rls.py apply

`check` reports tables that have the column but no policy, and is what the
test suite calls so the gap fails a build rather than reaching production.
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from app.core.db import Base, SessionLocal, engine
from app.core.tenancy import ORG_SETTING, SUPER_ADMIN
from app.models import *  # noqa: F401,F403 - registers every table

#: The tenant itself. Scoped by id at the application layer; the super admin
#: is the only caller who ever lists more than one.
#:
#: `leads` is platform-level on purpose: a design-partner request from the
#: marketing site arrives before any tenant exists, so the table carries no
#: organisation_id and takes no RLS policy. The public `/api/v1/leads` route
#: relies on exactly that to insert on an unbound session.
UNSCOPED = {"organisations", "alembic_version", "leads"}

#: Tables that must be readable *before* a tenant is known, because reading
#: them is how the tenant gets determined. Sign-in has to find a user by email
#: across organisations, and accepting an invitation has to find an invite by
#: token, both without any binding in place.
#:
#: They are not left unprotected. They get a policy that permits reading an
#: unbound session but still confines writes to the caller's own desk, so a
#: bound request cannot create or modify a user in another organisation.
#: The confidentiality that matters - who is on a desk - is enforced at the
#: route layer, where `/team` runs on a bound session.
LOGIN_TABLES = {"app_users", "invites"}


def tenant_tables() -> list[str]:
    """Every table carrying `organisation_id`, from the models themselves."""
    return sorted(
        name
        for name, table in Base.metadata.tables.items()
        if "organisation_id" in table.columns and name not in UNSCOPED
    )


def login_policy_sql(table: str) -> list[str]:
    """Policy for a table that sign-in must read before binding.

    Reads are permitted when nothing is bound (the sign-in path); once a
    session *is* bound, the ordinary tenant rule applies. Writes always
    require the row to belong to the caller's organisation, so the relaxed
    read cannot be turned into a way to add a user to somebody else's desk.
    """
    unbound = f"current_setting('{ORG_SETTING}', true) IS NULL " \
              f"OR current_setting('{ORG_SETTING}', true) = ''"
    tenant = (
        f"current_setting('{ORG_SETTING}', true) = '{SUPER_ADMIN}'"
        f" OR organisation_id::text = current_setting('{ORG_SETTING}', true)"
    )
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        f"DROP POLICY IF EXISTS tenant_isolation ON {table};",
        f"DROP POLICY IF EXISTS tenant_read ON {table};",
        f"DROP POLICY IF EXISTS tenant_write ON {table};",
        f"CREATE POLICY tenant_read ON {table} FOR SELECT USING (({unbound}) OR ({tenant}));",
        f"CREATE POLICY tenant_write ON {table} "
        f"USING (({unbound}) OR ({tenant})) WITH CHECK (({unbound}) OR ({tenant}));",
    ]


def policy_sql(table: str) -> list[str]:
    """The statements that isolate one table.

    `USING` governs which rows are visible; `WITH CHECK` governs which may be
    written. Both are needed - without `WITH CHECK`, a desk could insert a row
    labelled with another desk's id and hand itself data it cannot then see.

    The super-admin branch compares against an explicit sentinel rather than
    treating an unset variable as permission, so a request that never got
    scoped sees nothing instead of everything.
    """
    # The comparison is made on *text*, not on int. PostgreSQL may evaluate
    # both sides of the OR regardless of order, so casting the setting to int
    # fails outright when it holds the super-admin sentinel rather than an id.
    # Casting the column to text instead keeps one predicate that is valid for
    # both cases, and the index on organisation_id is still usable via the
    # equality on the setting.
    predicate = (
        f"(current_setting('{ORG_SETTING}', true) = '{SUPER_ADMIN}'"
        f" OR organisation_id::text = current_setting('{ORG_SETTING}', true))"
    )
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        # FORCE applies the policy to the table's owner too. Without it the
        # owning role is exempt, which is exactly the role the app connects as.
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        f"DROP POLICY IF EXISTS tenant_isolation ON {table};",
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING {predicate} WITH CHECK {predicate};",
    ]


def apply() -> int:
    tables = tenant_tables()
    with engine.begin() as conn:
        for table in tables:
            builder = login_policy_sql if table in LOGIN_TABLES else policy_sql
            for statement in builder(table):
                conn.execute(text(statement))
    print(f"Row-level security applied to {len(tables)} tables.")
    return 0


def check() -> int:
    """Report any tenant table without an active policy."""
    expected = set(tenant_tables())
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relrowsecurity AND c.relforcerowsecurity"
            )
        ).scalars()
        protected = set(rows)

    unprotected = sorted(expected - protected)
    if unprotected:
        print("Tables with organisation_id but no enforced policy:")
        for name in unprotected:
            print(f"  - {name}")
        return 1
    print(f"All {len(expected)} tenant tables are protected.")
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(apply() if command == "apply" else check())
