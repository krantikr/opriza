"""Binding a database session to exactly one organisation.

This is the load-bearing piece of the multi-tenant design. Everything else -
the `organisation_id` columns, the scoped queries, the role checks - is a
convenience on top of what happens here.

**How it works.** PostgreSQL row-level security policies on every tenant table
compare `organisation_id` against `current_setting('app.org_id')`. This module
is the only place that sets it, from the caller's verified token and never
from anything a request body can reach. A query that forgets its `WHERE`
clause returns nothing instead of another desk's rows.

**Why transaction-local.** `set_config(..., true)` is scoped to the current
transaction, so a pooled connection handed to the next request cannot inherit
the previous caller's organisation - the failure that turns connection pooling
into a cross-tenant data leak. It is used in preference to `SET LOCAL` because
only the function form accepts a bind parameter; `SET LOCAL` would require
interpolating the id into SQL text.

**Why the app role must not be superuser.** PostgreSQL exempts superusers and
any role with BYPASSRLS from every policy. Connecting as one silently disables
tenant isolation while every test still passes. `assert_rls_enforced` checks
this at startup and refuses to boot rather than serve traffic unprotected.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

logger = get_logger(__name__)

#: Session variable the policies read. Namespaced so it cannot collide with a
#: PostgreSQL setting of its own.
ORG_SETTING = "app.org_id"

#: Set by the super admin path to mean "every organisation". A distinct
#: sentinel rather than a null, so that *forgetting* to scope (which leaves
#: the setting empty) can never be mistaken for *choosing* not to.
SUPER_ADMIN = "__super_admin__"


#: `set_config(key, value, is_local => true)`. The function form is used
#: rather than `SET LOCAL` because only it accepts bind parameters, keeping the
#: organisation id out of SQL text entirely.
_SET_ORG = text("SELECT set_config(:key, :value, true)")


class TenantNotSet(RuntimeError):
    """A query ran on a session nobody bound to an organisation.

    Raised rather than defaulting to something, because both plausible
    defaults are wrong: defaulting to no rows hides bugs until a trader
    reports missing data, and defaulting to all rows is the breach.
    """


def _stamp_new_rows(session: Session, flush_context, instances) -> None:  # noqa: ARG001
    """Fill in `organisation_id` on new rows from the session's binding.

    Without this, every insert site in the application has to remember to set
    the column, and the one that forgets fails at the database with an
    RLS violation - safe, but only discovered at runtime.

    Stamping it from the session's own binding makes the common case correct
    by construction: a row is owned by whichever desk the request belongs to,
    and an explicit value is left alone so the super admin and the seeding
    script can still write deliberately.
    """
    org_id = session.info.get("organisation_id")
    if org_id is None:
        return
    for obj in session.new:
        if hasattr(obj, "organisation_id") and getattr(obj, "organisation_id", None) is None:
            obj.organisation_id = org_id


def _rebind_on_begin(session: Session, transaction, connection) -> None:  # noqa: ARG001
    """Re-apply the binding whenever a new transaction begins.

    The binding is transaction-local, which is what stops it leaking between
    pooled requests. The corollary is that `commit()` discards it, so any
    read afterwards - `db.refresh(obj)` in a create handler, most commonly -
    runs unbound and sees nothing, and SQLAlchemy reports the row it just
    wrote as missing.

    `after_begin` is the correct hook rather than `after_commit`: a committed
    session cannot emit SQL, and the setting has to exist on the *new*
    transaction anyway. It is issued on the connection for the same reason.

    The guarantee is unchanged - a connection nobody bound is still unbound,
    because `session.info` is empty until `bind_session` fills it.
    """
    org_id = session.info.get("organisation_id")
    if org_id is not None:
        connection.execute(_SET_ORG, {"key": ORG_SETTING, "value": str(org_id)})
    elif session.info.get("super_admin"):
        connection.execute(_SET_ORG, {"key": ORG_SETTING, "value": SUPER_ADMIN})


event.listen(Session, "before_flush", _stamp_new_rows)
event.listen(Session, "after_begin", _rebind_on_begin)


def bind_session(db: Session, organisation_id: int | None, *, super_admin: bool = False) -> None:
    """Scope every subsequent query on `db` to one organisation.

    Transaction-local, so it is released when the request's transaction ends
    and cannot leak to the next caller of a pooled connection.
    """
    if super_admin:
        # The super admin console reads across desks. Policies check for this
        # sentinel explicitly; it is never inferred from a missing value.
        db.execute(_SET_ORG, {"key": ORG_SETTING, "value": SUPER_ADMIN})
        # No stamping for the operator: they write on behalf of a named desk
        # and must say which, rather than having one inferred.
        db.info["organisation_id"] = None
        db.info["super_admin"] = True
        return

    if organisation_id is None:
        raise TenantNotSet(
            "A tenant-scoped session was opened without an organisation. "
            "Every request must resolve to one desk, or to the super admin."
        )

    db.execute(_SET_ORG, {"key": ORG_SETTING, "value": str(organisation_id)})
    # Read back by the before_flush hook above, so new rows land on this desk
    # without every call site repeating it.
    db.info["organisation_id"] = organisation_id
    db.info["super_admin"] = False


@contextmanager
def as_organisation(db: Session, organisation_id: int) -> Iterator[Session]:
    """Run a block against one organisation, restoring nothing afterwards.

    For background work - the poller, the follow-up scheduler - which loops
    over desks rather than serving one caller. Each iteration gets its own
    transaction so the binding cannot bleed into the next organisation.
    """
    try:
        bind_session(db, organisation_id)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def current_organisation(db: Session) -> int | None:
    """Which organisation this session is bound to, for diagnostics."""
    value = db.execute(text(f"SELECT current_setting('{ORG_SETTING}', true)")).scalar()
    if not value or value == SUPER_ADMIN:
        return None
    return int(value)


def assert_rls_enforced(db: Session) -> None:
    """Refuse to serve traffic if the connection can bypass tenant isolation.

    Checked at startup because the failure is invisible: as a superuser every
    query works, every test passes, and every desk sees every other desk. A
    loud refusal to boot is the only safe response.
    """
    row = db.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one_or_none()
    if row is None:
        return
    is_super, bypasses = row
    if is_super or bypasses:
        raise RuntimeError(
            "The database user can bypass row-level security, so tenant "
            "isolation is not in force. Connect as a NOSUPERUSER NOBYPASSRLS "
            "role (see scripts/rls.py) before serving traffic."
        )


__all__ = [
    "ORG_SETTING",
    "SUPER_ADMIN",
    "TenantNotSet",
    "as_organisation",
    "assert_rls_enforced",
    "bind_session",
    "current_organisation",
]
