"""Shared test fixtures.

Tests run against a throwaway SQLite file rather than the development database,
and against a fixed set of stock lots so the availability assertions are stable.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base
from app.models import (
    ConfidenceLevel,
    Customer,
    CustomerTier,
    Email,
    EmailCategory,
    EmailSourceType,
    MatchStatus,
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


@pytest.fixture()
def db(tmp_path) -> Generator[Session, None, None]:
    """A fresh, isolated database per test."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def default_user(db: Session) -> User:
    user = User(name="Test Owner", email="owner@test.local", role=UserRole.ADMIN)
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
