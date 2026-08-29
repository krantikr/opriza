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


class SpecPositionOut(ORMModel):
    """One specification: what is held, owed, spare, and short."""

    product_type: str | None = None
    grade: str | None = None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    display_name: str = ""
    lot_count: int = 0
    locations: list[str] = Field(default_factory=list)

    in_stock_mt: Decimal = Decimal(0)
    committed_mt: Decimal = Decimal(0)
    free_mt: Decimal = Decimal(0)
    to_buy_mt: Decimal = Decimal(0)
    prospective_mt: Decimal = Decimal(0)
    #: Weighted average landed cost per MT. Null where no lot carries a cost.
    cost_per_mt: Decimal | None = None


class StockPositionOut(ORMModel):
    """The desk-wide position, and the per-specification breakdown."""

    in_stock_mt: Decimal = Decimal(0)
    committed_mt: Decimal = Decimal(0)
    free_mt: Decimal = Decimal(0)
    to_buy_mt: Decimal = Decimal(0)
    prospective_mt: Decimal = Decimal(0)
    specs_short: int = 0
    specs: list[SpecPositionOut] = Field(default_factory=list)


class StockItemIn(ORMModel):
    """A lot being added by hand.

    Quantity is taken in MT because that is the unit a trader buys and sells
    in; it is stored in kg to match the imported sheets, and the conversion
    happens once, here, rather than in the interface.
    """

    product_type: str = Field(min_length=1, max_length=80)
    grade: str = Field(min_length=1, max_length=60)
    thickness_mm: float | None = Field(default=None, gt=0)
    width_mm: float | None = Field(default=None, gt=0)
    length_mm: float | None = Field(default=None, gt=0)
    diameter_mm: float | None = Field(default=None, gt=0)
    location: str | None = Field(default=None, max_length=120)
    make: str | None = Field(default=None, max_length=120)
    coil_no: str | None = Field(default=None, max_length=120)
    quantity_mt: Decimal = Field(gt=0)
    nop: float | None = Field(default=None, ge=0)
    purchase_rate_per_kg: float | None = Field(default=None, ge=0)
    landed_cost_per_kg: float | None = Field(default=None, ge=0)
    stock_date: date | None = None
