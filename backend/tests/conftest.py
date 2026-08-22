"""Shared test fixtures.

Tests run against PostgreSQL, not SQLite. That is a requirement rather than a
preference: tenant isolation is enforced by row-level security, and a suite on
a database with no such feature would pass while proving nothing about the
property the product depends on most.

Each test gets a schema created fresh with its policies applied, and every
session is bound to a default organisation so ordinary tests need not think
about tenancy at all. `test_tenancy.py` is where the binding is manipulated
deliberately.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base, get_db
from app.core.tenancy import bind_session
from app.main import app
from app.models import (
    ConfidenceLevel,
    Customer,
    CustomerTier,
    Email,
    EmailCategory,
    EmailSourceType,
    MatchStatus,
    Organisation,
    ProcessingStatus,
    QuantityUnit,
    QuotationLineItem,
    QuotationRequest,
    QuotationStatus,
    StockAvailability,
    StockItem,
    User,
    UserRole,
)
from app.services.email.sender import LocalFileSender

#: The suite's own database. Separate from development data so a test run
#: cannot destroy work in progress.
TEST_DATABASE_URL = (
    "postgresql+psycopg://steeldesk_app:steeldesk_dev@localhost:5432/steeldesk_test"
)


@pytest.fixture(scope="session")
def engine():
    """One engine and one schema for the run; tables are truncated per test.

    Creating 31 tables and 30 policies per test would dominate the runtime.
    """
    from scripts.rls import LOGIN_TABLES, login_policy_sql, policy_sql, tenant_tables

    engine = create_engine(TEST_DATABASE_URL, future=True)

    # Dropping the schema rather than the tables: `drop_all` needs a
    # dependency sort, and `emails` and `quotation_requests` reference each
    # other, so no such order exists. The schema does not care.
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        for table in tenant_tables():
            builder = login_policy_sql if table in LOGIN_TABLES else policy_sql
            for statement in builder(table):
                conn.execute(text(statement))

    yield engine
    engine.dispose()


@pytest.fixture()
def default_org(engine) -> int:
    """The organisation every ordinary test's data belongs to.

    Created with the super-admin binding, because an organisation row has no
    `organisation_id` of its own to be scoped by.
    """
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        bind_session(session, None, super_admin=True)
        # One statement for every table: `sorted_tables` cannot order these,
        # because `emails` and `quotation_requests` reference each other, and
        # TRUNCATE ... CASCADE does not care about order anyway.
        names = ", ".join(f'"{t}"' for t in Base.metadata.tables)
        session.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
        org = Organisation(slug="test-desk", name="Test Desk")
        session.add(org)
        session.commit()
        return org.id
    finally:
        session.close()


@pytest.fixture()
def db(engine, default_org) -> Generator[Session, None, None]:
    """A session bound to the default organisation.

    Bound by default so that the several hundred tests written before
    multi-tenancy keep testing what they were written to test, rather than
    each needing to learn about organisations.
    """
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    bind_session(session, default_org)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def platform_db(engine, default_org) -> Generator[Session, None, None]:
    """A session bound as the platform operator, for cross-desk work.

    Onboarding an organisation is deliberately impossible from a desk-scoped
    session, so the tests that do it need this rather than `db`.
    """
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    bind_session(session, None, super_admin=True)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def two_desks(engine, default_org):
    """Two organisations, each with one customer, for the isolation tests."""
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        bind_session(session, None, super_admin=True)
        alpha = Organisation(slug="alpha", name="Alpha Steel")
        beta = Organisation(slug="beta", name="Beta Metals")
        session.add_all([alpha, beta])
        session.commit()

        for org, label in ((alpha, "Alpha"), (beta, "Beta")):
            bind_session(session, org.id)
            session.add(
                Customer(
                    organisation_id=org.id,
                    name=f"{label} customer",
                    email=f"{label.lower()}@example.com",
                )
            )
            session.commit()

        session.expunge_all()
        return alpha, beta
    finally:
        session.close()


@pytest.fixture()
def default_user(db: Session, default_org: int) -> User:
    user = User(
        organisation_id=default_org,
        name="Test Owner",
        email="owner@example.com",
        role=UserRole.OWNER,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def plate(db: Session) -> StockItem:
    """IS 2062 E250 plate, 10 x 1500 x 6000 - the reference lot."""
    lot = StockItem(
        product_type="Plate",
        grade="E250",
        thickness_mm=10.0,
        width_mm=1500.0,
        length_mm=6000.0,
        location="NAGPUR",
        nop=40.0,
        qty_kg=Decimal("28260.000"),
        balance_nop=40.0,
        balance_qty_kg=Decimal("28260.000"),
        landed_cost_per_kg=56.5,
        ageing_days=7,
        stock_date=date.today() - timedelta(days=7),
    )
    db.add(lot)
    db.commit()
    return lot


@pytest.fixture()
def wide_plate(db: Session) -> StockItem:
    """Same grade and thickness, different width - the ambiguity case."""
    lot = StockItem(
        product_type="Plate",
        grade="E250",
        thickness_mm=10.0,
        width_mm=2000.0,
        length_mm=6300.0,
        location="788",
        nop=25.0,
        qty_kg=Decimal("24727.500"),
        balance_nop=25.0,
        balance_qty_kg=Decimal("24727.500"),
        landed_cost_per_kg=56.5,
        ageing_days=9,
        stock_date=date.today() - timedelta(days=9),
    )
    db.add(lot)
    db.commit()
    return lot


@pytest.fixture()
def customer(db: Session) -> Customer:
    record = Customer(
        customer_code="CUST-001",
        name="Rajesh Kumar",
        email="rajesh@abcindustries.co.in",
        company="ABC Industries Pvt Ltd",
        default_delivery_location="Patna",
        tier=CustomerTier.A,
        # Imported master data is trusted; only rows built from an email
        # signature stay unverified. HIGH confidence requires this.
        is_verified=True,
    )
    db.add(record)
    db.commit()
    return record


# NOTE: the `comparable_sales` and `priced_quotation` fixtures were removed with
# the pricing engine they described (PriceMaster / SalesTransaction /
# PricingRecommendation). Suggested pricing is now derived from landed cost on
# the stock lots themselves - see `stock_pricing` in business_rules.yaml.


@pytest.fixture()
def quoted_quotation(db: Session, plate: StockItem, customer: Customer) -> QuotationRequest:
    """A quotation that has been through matching and the stock check.

    Built directly rather than by running the workflow, so the drafting and
    API tests exercise their own subject rather than re-testing the pipeline.
    Figures mirror what `StockAvailabilityService` actually produces for the
    `plate` lot: 28.26 MT on hand, landed cost 56.5/kg -> 56,500.00/MT, plus
    the configured 8% markup, rounded to the nearest 50 -> 61,000.00/MT.
    """
    email = Email(
        message_id="local:quoted-fixture-1",
        thread_id="local-thread:quoted",
        # `reply_to` threads on this, not on the internal message_id.
        rfc822_message_id="<enquiry-1@sample.local>",
        source=EmailSourceType.LOCAL,
        sender_email=customer.email,
        sender_name=customer.name,
        subject="Enquiry - IS 2062 E250 Plate 10mm",
        body_text="Please quote 20 MT of 10mm plate delivered to Patna.",
        received_at=datetime.now(UTC),
        processing_status=ProcessingStatus.PROCESSED,
        category=EmailCategory.QUOTATION_REQUEST,
    )
    db.add(email)
    db.flush()

    quotation = QuotationRequest(
        quotation_number="Q-000001",
        email_id=email.id,
        customer_id=customer.id,
        customer_name_raw=customer.name,
        customer_company_raw=customer.company,
        customer_email=customer.email,
        status=QuotationStatus.READY_FOR_REVIEW,
        confidence=ConfidenceLevel.HIGH,
        delivery_location="Patna",
    )
    db.add(quotation)
    db.flush()

    item = QuotationLineItem(
        quotation_request_id=quotation.id,
        line_no=1,
        raw_text="IS 2062 E250 Plate 10 x 1500 x 6000 mm",
        product_type="Plate",
        grade="E250",
        thickness_mm=10.0,
        width_mm=1500.0,
        length_mm=6000.0,
        quantity=Decimal("20"),
        quantity_unit=QuantityUnit.MT,
        quantity_mt=Decimal("20"),
        matched_stock_item_id=plate.id,
        match_status=MatchStatus.MATCH_FOUND,
        match_score=100.0,
    )
    db.add(item)
    db.flush()

    db.add(
        StockAvailability(
            quotation_line_item_id=item.id,
            available_qty_mt=Decimal("28.260"),
            available_nop=40.0,
            sufficient=True,
            locations=[{"location": "NAGPUR", "balance_qty_mt": 28.26}],
            ageing_min_days=7,
            ageing_max_days=7,
            lot_count=1,
            suggested_rate=Decimal("61000.00"),
            currency="INR",
            unit=QuantityUnit.MT,
            rules_version="1.0",
            confidence=ConfidenceLevel.HIGH,
            requires_manual_review=False,
            breakdown=[
                {
                    "id": "stock_lookup",
                    "label": "Stock lookup",
                    "reason": "1 stock lot(s) matched. Balance on hand: 28.26 MT (40 pcs).",
                    "applied": True,
                },
                {
                    "id": "suggested_rate",
                    "label": "Suggested rate",
                    "reason": (
                        "Weighted-average landed cost INR 56,500.00/MT plus 8% markup: "
                        "INR 61,000.00/MT (indicative - subject to confirmation, not an "
                        "approved price)."
                    ),
                    "applied": True,
                },
            ],
            explanation=(
                "1 stock lot(s) matched. Balance on hand: 28.26 MT (40 pcs).\n"
                "Weighted-average landed cost INR 56,500.00/MT plus 8% markup: "
                "INR 61,000.00/MT (indicative - subject to confirmation, not an "
                "approved price)."
            ),
            stock_as_of=date.today(),
        )
    )
    db.commit()
    db.refresh(quotation)
    return quotation


# ---------------------------------------------------------------------------
# API client
#
# Shared rather than per-module: several suites now drive routes, and each
# rebuilding this would risk them drifting apart on how auth is set up.
# ---------------------------------------------------------------------------


@pytest.fixture()
def sent_dir(tmp_path, monkeypatch) -> Path:
    """Redirect outbound mail to a temporary folder."""
    outbox = tmp_path / "sent"
    monkeypatch.setattr(
        "app.services.quotations.approval.get_sender", lambda: LocalFileSender(outbox)
    )
    return outbox


@pytest.fixture()
def client(db, default_user, sent_dir) -> TestClient:
    """An authenticated client for the default desk.

    The session is overridden, but authentication is *not* faked: the client
    signs in with a real token, so these tests exercise the same dependency
    chain a browser does. Stubbing `current_user` instead would leave every
    route's auth untested.
    """
    from app.api.deps import tenant_db
    from app.core.security import issue_token

    app.dependency_overrides[get_db] = lambda: db
    # `tenant_db` is overridden because the test session is already bound by
    # the `db` fixture; re-binding it inside a TestClient request would open a
    # second transaction on the same session.
    app.dependency_overrides[tenant_db] = lambda: db

    token = issue_token(
        user_id=default_user.id,
        organisation_id=default_user.organisation_id,
        role=default_user.role.value,
        is_super_admin=False,
        token_version=default_user.token_version,
    )
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client
    app.dependency_overrides.clear()
