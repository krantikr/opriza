"""Shared test fixtures.

Tests run against a throwaway SQLite file rather than the development database,
and against a fixed set of stock lots so the availability assertions are stable.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base
from app.models import (
    Customer,
    CustomerTier,
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
    )
    db.add(record)
    db.commit()
    return record


# NOTE: the `comparable_sales` and `priced_quotation` fixtures were removed with
# the pricing engine they described (PriceMaster / SalesTransaction /
# PricingRecommendation). Suggested pricing is now derived from landed cost on
# the stock lots themselves - see `stock_pricing` in business_rules.yaml.
