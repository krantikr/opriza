"""Customers, stock, and ad-hoc availability checks."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import TenantDb
from app.api.serializers import customer_out, stock_item_out
from app.models import Customer, StockItem
from app.schemas.catalog import CustomerOut, StockCheckRequest, StockItemOut, StockSummaryOut
from app.schemas.common import Page
from app.schemas.quotations import StockAvailabilityOut
from app.services.stock.availability import StockAvailabilityService

router = APIRouter(tags=["catalog"])


# --- Stock -------------------------------------------------------------


@router.get("/stock", response_model=Page[StockItemOut])
def list_stock(
    db: TenantDb,
    product_type: str | None = None,
    grade: str | None = None,
    location: str | None = None,
    search: str | None = Query(default=None, description="Match grade or make"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[StockItemOut]:
    query = select(StockItem)
    count_query = select(func.count()).select_from(StockItem)

    if product_type:
        query = query.where(func.lower(StockItem.product_type) == product_type.lower())
        count_query = count_query.where(func.lower(StockItem.product_type) == product_type.lower())
    if grade:
        query = query.where(func.lower(StockItem.grade) == grade.lower())
        count_query = count_query.where(func.lower(StockItem.grade) == grade.lower())
    if location:
        query = query.where(func.lower(StockItem.location) == location.lower())
        count_query = count_query.where(func.lower(StockItem.location) == location.lower())
    if search:
        pattern = f"%{search.strip()}%"
        condition = StockItem.grade.ilike(pattern) | StockItem.make.ilike(pattern)
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = db.scalar(count_query) or 0
    ordered = query.order_by(StockItem.grade, StockItem.thickness_mm)
    rows = db.scalars(ordered.limit(limit).offset(offset)).all()
    return Page(items=[stock_item_out(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/stock/summary", response_model=list[StockSummaryOut])
def stock_summary(db: TenantDb) -> list[StockSummaryOut]:
    """Lots grouped by distinct spec - what the Stock dashboard page shows."""
    rows = list(db.scalars(select(StockItem)))
    groups: dict[tuple, list[StockItem]] = {}
    for row in rows:
        key = (row.product_type, row.grade, row.thickness_mm, row.width_mm, row.length_mm)
        groups.setdefault(key, []).append(row)

    summaries: list[StockSummaryOut] = []
    for lots in groups.values():
        representative = min(lots, key=lambda r: r.ageing_days or 0)
        balance_kg = sum((lot.balance_qty_kg or Decimal(0)) for lot in lots)
        ageing_values = [lot.ageing_days for lot in lots if lot.ageing_days is not None]
        costs = [
            (lot.landed_cost_per_kg, float(lot.balance_qty_kg or 0))
            for lot in lots
            if lot.landed_cost_per_kg is not None and (lot.balance_qty_kg or 0) > 0
        ]
        avg_cost = (
            sum(cost * weight for cost, weight in costs) / sum(w for _, w in costs) if costs else None
        )
        summaries.append(
            StockSummaryOut(
                product_type=representative.product_type,
                grade=representative.grade,
                thickness_mm=representative.thickness_mm,
                width_mm=representative.width_mm,
                length_mm=representative.length_mm,
                display_name=representative.display_name,
                lot_count=len(lots),
                balance_qty_mt=(balance_kg / Decimal(1000)).quantize(Decimal("0.001")),
                balance_nop=sum((lot.balance_nop or 0) for lot in lots),
                locations=sorted({lot.location for lot in lots if lot.location}),
                ageing_min_days=min(ageing_values) if ageing_values else None,
                ageing_max_days=max(ageing_values) if ageing_values else None,
                avg_landed_cost_per_kg=avg_cost,
                # Oldest first: ageing is what decides which lot to move, so
                # that is the order a reviewer wants to read them in.
                lots=[
                    stock_item_out(lot)
                    for lot in sorted(lots, key=lambda r: -(r.ageing_days or 0))
                ],
            )
        )

    summaries.sort(key=lambda s: (s.grade or "", s.thickness_mm or 0))
    return summaries


@router.get("/stock/{stock_item_id}", response_model=StockItemOut)
def get_stock_item(stock_item_id: int, db: TenantDb) -> StockItemOut:
    item = db.get(StockItem, stock_item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Stock item {stock_item_id} not found")
    return stock_item_out(item)


@router.post("/stock/check", response_model=StockAvailabilityOut, tags=["stock"])
def check_stock(payload: StockCheckRequest, db: TenantDb) -> StockAvailabilityOut:
    """Check availability for one stock spec directly.

    Runs the same service the workflow uses, so a figure checked here is the
    figure a reply would carry - useful for sanity-checking a rule change
    before it reaches customers.
    """
    anchor = db.get(StockItem, payload.stock_item_id)
    if anchor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Stock item {payload.stock_item_id} not found")

    lot_ids = list(
        db.scalars(
            select(StockItem.id).where(
                StockItem.product_type == anchor.product_type,
                StockItem.grade == anchor.grade,
                StockItem.thickness_mm == anchor.thickness_mm,
                StockItem.width_mm == anchor.width_mm,
                StockItem.length_mm == anchor.length_mm,
            )
        )
    )

    customer = db.get(Customer, payload.customer_id) if payload.customer_id else None
    outcome = StockAvailabilityService(db).check(
        lot_ids=lot_ids,
        quantity_mt=payload.quantity_mt,
        customer=customer,
    )

    return StockAvailabilityOut(
        available_qty_mt=outcome.available_qty_mt,
        available_nop=outcome.available_nop,
        sufficient=outcome.sufficient,
        locations=outcome.locations_as_json(),
        ageing_min_days=outcome.ageing_min_days,
        ageing_max_days=outcome.ageing_max_days,
        lot_count=outcome.lot_count,
        suggested_rate=outcome.suggested_rate,
        currency=outcome.currency,
        unit=outcome.unit.value,
        confidence=outcome.confidence.value,
        requires_manual_review=outcome.requires_manual_review,
        rules_version=outcome.rules_version,
        explanation=outcome.explanation,
        breakdown=outcome.breakdown(),
        stock_as_of=outcome.stock_as_of,
    )


# --- Customers -----------------------------------------------------------


@router.get("/customers", response_model=Page[CustomerOut])
def list_customers(
    db: TenantDb,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[CustomerOut]:
    query = select(Customer)
    count_query = select(func.count()).select_from(Customer)

    if search:
        pattern = f"%{search.strip()}%"
        condition = (
            Customer.name.ilike(pattern)
            | Customer.company.ilike(pattern)
            | Customer.email.ilike(pattern)
        )
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = db.scalar(count_query) or 0
    rows = db.scalars(query.order_by(Customer.name).limit(limit).offset(offset)).all()
    return Page(items=[customer_out(c) for c in rows], total=total, limit=limit, offset=offset)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: TenantDb) -> CustomerOut:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Customer {customer_id} not found")
    return customer_out(customer)
