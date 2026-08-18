"""Customer and stock DTOs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import Field

from app.schemas.common import ORMModel


class StockItemOut(ORMModel):
    """One physical lot."""

    id: int
    product_type: str | None = None
    grade: str | None = None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    diameter_mm: float | None = None
    location: str | None = None
    make: str | None = None
    coil_no: str | None = None
    nop: float | None = None
    qty_kg: Decimal | None = None
    balance_nop: float | None = None
    balance_qty_kg: Decimal | None = None
    purchase_rate_per_kg: float | None = None
    landed_cost_per_kg: float | None = None
    ageing_days: int | None = None
    stock_date: date | None = None
    curr_dt: date | None = None
    display_name: str = ""


class StockSummaryOut(ORMModel):
    """Lots grouped by distinct spec - what the Stock page shows.

    The rollup answers "what do we have"; `lots` carries the underlying rows
    so the page can expand a spec and show the per-lot columns the rollup has
    to collapse (make, coil no, cost, purchase date), which differ lot to lot.
    """

    product_type: str | None = None
    grade: str | None = None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    display_name: str = ""
    lot_count: int = 0
    balance_qty_mt: Decimal = Decimal(0)
    balance_nop: float = 0
    locations: list[str] = Field(default_factory=list)
    ageing_min_days: int | None = None
    ageing_max_days: int | None = None
    avg_landed_cost_per_kg: float | None = None
    lots: list[StockItemOut] = Field(default_factory=list)


class CustomerOut(ORMModel):
    id: int
    customer_code: str | None = None
    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    default_delivery_location: str | None = None
    tier: str
    payment_terms: str | None = None
    status: str
    is_verified: bool = False


class StockCheckRequest(ORMModel):
    """Ad-hoc availability check, for the stock sandbox in the dashboard."""

    stock_item_id: int
    quantity_mt: Decimal | None = None
    customer_id: int | None = None
