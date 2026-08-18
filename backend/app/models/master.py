"""Master business data: customers and physical stock.

`Customer` is populated from two directions: an optional `customers.xlsx`
master file, and inbound mail - a sender nobody has on file is created on
first enquiry with `is_verified=False`, so the tab fills itself instead of
sitting empty. Imported rows are trusted (`is_verified=True`); auto-created
ones carry only what the email said until a human confirms them.
`StockItem` is populated by importing the
client's stock list (spec section 30) - Excel is an input, never the running
store, and every import is recorded against an `ImportBatch` so any figure can
be traced back to the file and the moment it arrived.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import CustomerTier, RecordStatus
from app.models.mixins import TimestampMixin, enum_col
from app.models.types import Quantity


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_code: Mapped[str | None] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    company: Mapped[str | None] = mapped_column(String(200))
    billing_address: Mapped[str | None] = mapped_column(Text)
    shipping_address: Mapped[str | None] = mapped_column(Text)
    default_delivery_location: Mapped[str | None] = mapped_column(String(120))
    # Kept for reference / future use - not used by the stock-availability flow.
    tier: Mapped[CustomerTier] = mapped_column(
        enum_col(CustomerTier), default=CustomerTier.B, nullable=False
    )
    payment_terms: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[RecordStatus] = mapped_column(
        enum_col(RecordStatus), default=RecordStatus.ACTIVE, nullable=False
    )
    # False for rows built from an email signature. Pricing still works off
    # them, but the UI marks them so a reviewer knows the tier and payment
    # terms are defaults nobody has confirmed yet.
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Customer {self.id} {self.name!r}>"


class StockItem(Base, TimestampMixin):
    """One lot of physical stock, as reported in the client's stock list.

    A lot is a row of the source spreadsheet - one purchase, at one location,
    of one grade and size. Several lots commonly share the same spec (grade +
    dimensions) at different ages, locations or costs, so this table is never
    deduped at import time; the matcher groups lots into distinct specs and
    the availability service sums `balance_qty_kg` across every lot in the
    winning group.

    `purchase_rate_per_kg` / `landed_cost_per_kg` are INR **per kilogram**,
    not per MT - confirmed against the source file, where `VALUE = QTY (kg) x
    Purchase RATE`. Anything customer-facing (the suggested per-MT rate) must
    multiply by 1000 before applying a markup.

    Each import replaces the table wholesale (see
    `services/ingestion/excel_importer.py::StockImporter`) because the file is
    a full point-in-time snapshot with no natural key to upsert on - keeping
    stale lots around would double-count balance quantity across imports.
    """

    __tablename__ = "stock_items"
    __table_args__ = (
        Index("ix_stock_items_match", "product_type", "grade", "thickness_mm"),
        Index("ix_stock_items_dims", "thickness_mm", "width_mm", "length_mm"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_type: Mapped[str | None] = mapped_column(String(80), index=True)
    grade: Mapped[str | None] = mapped_column(String(60), index=True)

    thickness_mm: Mapped[float | None] = mapped_column()
    width_mm: Mapped[float | None] = mapped_column()
    length_mm: Mapped[float | None] = mapped_column()
    diameter_mm: Mapped[float | None] = mapped_column()

    location: Mapped[str | None] = mapped_column(String(120), index=True)
    make: Mapped[str | None] = mapped_column(String(80))
    coil_no: Mapped[str | None] = mapped_column(String(60))

    nop: Mapped[float | None] = mapped_column()
    qty_kg: Mapped[Decimal | None] = mapped_column(Quantity)
    balance_nop: Mapped[float | None] = mapped_column()
    balance_qty_kg: Mapped[Decimal | None] = mapped_column(Quantity)

    purchase_rate_per_kg: Mapped[float | None] = mapped_column()
    landed_cost_per_kg: Mapped[float | None] = mapped_column()
    ageing_days: Mapped[int | None] = mapped_column()

    stock_date: Mapped[date | None] = mapped_column()
    curr_dt: Mapped[date | None] = mapped_column()

    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))

    @property
    def display_name(self) -> str:
        """Human-readable spec used in drafts and the dashboard."""
        parts = [p for p in (self.grade, self.product_type) if p]
        dims = self.dimension_text
        if dims:
            parts.append(dims)
        return " ".join(parts)

    @property
    def dimension_text(self) -> str:
        if self.diameter_mm:
            base = f"OD {self.diameter_mm:g}mm"
            return f"{base} x {self.thickness_mm:g}mm" if self.thickness_mm else base
        dims = [d for d in (self.thickness_mm, self.width_mm, self.length_mm) if d]
        return " x ".join(f"{d:g}" for d in dims) + " mm" if dims else ""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<StockItem {self.grade} {self.dimension_text} loc={self.location!r}>"


# Re-exported for type checkers reading this module in isolation.
__all__ = ["Customer", "StockItem", "date", "datetime"]
