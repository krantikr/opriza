"""Tenant isolation: the property the whole product depends on.

Steel Desk serves trading desks that compete with each other. One of them
seeing another's customers, pricing or enquiries is the worst thing this
system can do, and it is silent when it happens - nobody reports data they
were not supposed to receive.

These tests are adversarial on purpose. Rather than checking that a scoped
query returns scoped results, they sign in as one desk and *try* to reach
another's data, by id, by unfiltered query, and by writing under a borrowed
organisation id. Every one of them must come back empty or refused.

The structural tests at the bottom are the ones that keep this true over
time: they fail the build when a new table or a new route is added without
the scoping the rest of the system assumes.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from sqlalchemy import select, text

from app.core.db import Base
from app.core.security import issue_token, read_token
from app.core.tenancy import SUPER_ADMIN, bind_session
from app.models import Customer, StockItem
from scripts.rls import LOGIN_TABLES, UNSCOPED, tenant_tables

pytestmark = pytest.mark.usefixtures("two_desks")


# --- Reading another desk's data -------------------------------------------


def test_an_unfiltered_query_returns_only_the_bound_desk(db, two_desks):
    """The guarantee: a forgotten WHERE clause is empty, not a leak."""
    alpha, beta = two_desks

    bind_session(db, alpha.id)
    names = db.scalars(select(Customer.name)).all()
    assert names == ["Alpha customer"]
    db.commit()

    bind_session(db, beta.id)
    assert db.scalars(select(Customer.name)).all() == ["Beta customer"]
    db.commit()


def test_asking_for_another_desks_row_by_id_returns_nothing(db, two_desks):
    """Even naming the id explicitly does not reach across."""
    alpha, beta = two_desks

    bind_session(db, beta.id)
    beta_customer_id = db.scalars(select(Customer.id)).one()
    db.commit()

    bind_session(db, alpha.id)
    assert db.get(Customer, beta_customer_id) is None
    db.commit()


def test_filtering_by_another_desks_id_returns_nothing(db, two_desks):
    """The obvious attack - just ask for the other organisation - is refused."""
    alpha, beta = two_desks

    bind_session(db, alpha.id)
    found = db.scalars(
        select(Customer).where(Customer.organisation_id == beta.id)
    ).all()
    assert found == []
    db.commit()


# --- Writing as another desk -----------------------------------------------


def test_writing_under_another_desks_id_is_refused(db, two_desks):
    """`WITH CHECK` stops a desk labelling a row as somebody else's.

    Without it a desk could insert rows into a competitor's account - data it
    could not then see, but which would appear in their interface as if they
    had entered it.
    """
    alpha, beta = two_desks

    bind_session(db, alpha.id)
    db.add(
        Customer(
            organisation_id=beta.id,
            name="Smuggled",
            email="smuggled@example.com",
        )
    )
    with pytest.raises(Exception):  # noqa: B017 - the DBAPI error type is not the point
        db.commit()
    db.rollback()


def test_a_new_row_is_stamped_with_the_bound_desk(db, two_desks):
    """A handler that forgets `organisation_id` still writes to the right desk."""
    alpha, _ = two_desks

    bind_session(db, alpha.id)
    item = StockItem(product_type="PLATE", grade="E250", location="Mumbai")
    db.add(item)
    db.commit()

    assert item.organisation_id == alpha.id


# --- The unbound and super-admin cases --------------------------------------


def test_an_unbound_session_sees_no_business_data(db, two_desks):
    """Forgetting to bind fails closed.

    The dangerous alternative would be for an unbound session to see
    everything, which turns one missed dependency into a full leak.
    """
    db.execute(text("SELECT set_config('app.org_id', '', true)"))
    assert db.scalars(select(Customer)).all() == []
    db.commit()


def test_the_super_admin_sees_every_desk(db, two_desks):
    """The console is meant to cross desks, and does so explicitly."""
    bind_session(db, None, super_admin=True)
    names = sorted(db.scalars(select(Customer.name)).all())
    assert names == ["Alpha customer", "Beta customer"]
    db.commit()


def test_the_super_admin_sentinel_is_not_the_empty_value(db):
    """Being unscoped must never be mistaken for being the operator."""
    assert SUPER_ADMIN not in ("", None)


# --- Tokens ----------------------------------------------------------------


def test_the_organisation_comes_from_the_signed_token(db, two_desks):
    """A caller cannot choose which desk they are, because the server signed it."""
    alpha, _ = two_desks
    token = issue_token(
        user_id=1, organisation_id=alpha.id, role="OWNER",
        is_super_admin=False, token_version=0,
    )
    assert read_token(token)["org"] == alpha.id


def test_a_tampered_token_is_rejected(db, two_desks):
    """Editing the payload invalidates the signature."""
    from app.core.security import TokenError

    alpha, beta = two_desks
    token = issue_token(
        user_id=1, organisation_id=alpha.id, role="OWNER",
        is_super_admin=False, token_version=0,
    )
    header, payload, signature = token.split(".")
    forged = f"{header}.{payload[:-4]}AAAA.{signature}"

    with pytest.raises(TokenError):
        read_token(forged)


# --- Structural: what keeps this true as the code changes -------------------


def test_every_business_table_carries_an_organisation_id():
    """A new table without tenancy is a leak waiting to be written to."""
    missing = [
        name
        for name, table in Base.metadata.tables.items()
        if name not in UNSCOPED and "organisation_id" not in table.columns
    ]
    assert missing == [], (
        f"These tables hold data but have no organisation_id: {missing}. "
        "Add TenantMixin, or add the table to UNSCOPED in scripts/rls.py "
        "with a reason."
    )


def test_every_tenant_table_has_an_enforced_policy(db):
    """The column alone isolates nothing - the policy is what enforces it."""
    protected = set(
        db.execute(
            text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' "
                "AND c.relrowsecurity AND c.relforcerowsecurity"
            )
        ).scalars()
    )
    missing = sorted(set(tenant_tables()) - protected)
    assert missing == [], (
        f"These tables have organisation_id but no enforced RLS policy: "
        f"{missing}. Run: uv run python scripts/rls.py apply"
    )


def test_business_routes_take_a_bound_session():
    """A handler on `get_db` is unscoped, and would see every desk's data.

    Checked structurally rather than by exercising every endpoint, because the
    failure is silent: such a route works perfectly in a single-tenant test
    and leaks in production.
    """
    routes = pathlib.Path(__file__).resolve().parents[1] / "app/api/v1"
    # `auth` and `admin` legitimately run before a tenant is known, or across
    # tenants; `leads` is the public marketing-site capture, which has no tenant
    # and whose table has no RLS. Every other router serves one desk.
    # `links` is the public customer-link surface: it binds to the link's own
    # desk (found by token hash) before reading anything, see api/v1/links.py.
    allowed = {"auth.py", "admin.py", "leads.py", "links.py", "router.py", "__init__.py"}

    offenders: list[str] = []
    for path in sorted(routes.glob("*.py")):
        if path.name in allowed:
            continue
        source = path.read_text()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef):
                continue
            args = node.args.args + node.args.kwonlyargs
            annotations = {ast.unparse(a.annotation) for a in args if a.annotation}
            if any("get_db" in a for a in annotations):
                offenders.append(f"{path.name}:{node.name}")

    assert offenders == [], (
        f"These handlers use an unscoped session: {offenders}. "
        "Use TenantDb so row-level security applies."
    )


def test_login_tables_are_documented_as_deliberate():
    """The relaxed-read tables are a considered exception, not an oversight."""
    assert LOGIN_TABLES == {"app_users", "invites"}, (
        "LOGIN_TABLES widens read access before a tenant is known. Adding a "
        "table here needs a reason recorded in scripts/rls.py."
    )


# --- Quotation references ---------------------------------------------------


def test_each_desk_numbers_its_own_quotations_from_one(db, two_desks):
    """A new customer's first quotation is number 1, not the platform total.

    Numbering from a shared row id would start a desk at whatever everyone
    else had reached, and would tell them how much business the other desks
    on the platform are writing.
    """
    from app.core.tenancy import bind_session
    from app.services.quotations.assembly import next_quotation_number

    alpha, beta = two_desks

    bind_session(db, alpha.id)
    assert next_quotation_number(db, alpha.id) == "AL-000001"
    db.commit()

    bind_session(db, beta.id)
    assert next_quotation_number(db, beta.id) == "BE-000001"
    db.commit()


def test_the_prefix_comes_from_the_desks_name(db, two_desks):
    """"KK Traders" numbers its quotations KK-000001."""
    from app.models import Organisation
    from app.services.quotations.assembly import quotation_prefix

    assert quotation_prefix(Organisation(slug="kk", name="KK Traders")) == "KK"
    assert quotation_prefix(Organisation(slug="a", name="Alpha Steel")) == "AL"
    # Digits and punctuation are skipped rather than producing "7 " as a prefix.
    assert quotation_prefix(Organisation(slug="s", name="7 Steel")) == "ST"
    # A name with no letters still has to yield a usable reference.
    assert quotation_prefix(Organisation(slug="x", name="123")) == "Q"


def test_numbering_continues_from_the_desks_own_highest(db, two_desks):
    """Sequential within a desk, and unaffected by any other desk's activity."""
    from app.core.tenancy import bind_session
    from app.models import Email, EmailSourceType, ProcessingStatus, QuotationRequest
    from app.services.quotations.assembly import next_quotation_number

    alpha, beta = two_desks

    def _quotation(org_id: int, number: str) -> None:
        email = Email(
            organisation_id=org_id,
            message_id=f"local:{number}",
            source=EmailSourceType.LOCAL,
            processing_status=ProcessingStatus.PROCESSED,
        )
        db.add(email)
        db.flush()
        db.add(
            QuotationRequest(
                organisation_id=org_id, email_id=email.id, quotation_number=number
            )
        )
        db.commit()

    bind_session(db, alpha.id)
    _quotation(alpha.id, "AL-000001")
    _quotation(alpha.id, "AL-000002")
    assert next_quotation_number(db, alpha.id) == "AL-000003"
    db.commit()

    # Beta is untouched by Alpha writing two quotations.
    bind_session(db, beta.id)
    assert next_quotation_number(db, beta.id) == "BE-000001"
    db.commit()
