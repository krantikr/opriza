"""Portable column types.

`Money` and `Quantity` exist because SQLite has no native DECIMAL. Storing
prices as bare floats in a system whose whole purpose is pricing would be a
mistake, so these types keep the Python side exact (`Decimal`) while adapting
storage per dialect: REAL on SQLite, true NUMERIC on PostgreSQL. Swapping the
database later changes storage precision without touching a line of pricing
code.
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Float, Numeric
from sqlalchemy.types import TypeDecorator

MONEY_PLACES = Decimal("0.01")
QUANTITY_PLACES = Decimal("0.001")


class _DecimalType(TypeDecorator):
    """Shared Decimal<->dialect adapter."""

    cache_ok = True
    precision = 14
    scale = 2
    quantum = MONEY_PLACES

    impl = Numeric(14, 2)

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(Float())
        return dialect.type_descriptor(Numeric(self.precision, self.scale))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        quantized = Decimal(str(value)).quantize(self.quantum, rounding=ROUND_HALF_UP)
        return float(quantized) if dialect.name == "sqlite" else quantized

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(str(value)).quantize(self.quantum, rounding=ROUND_HALF_UP)


class Money(_DecimalType):
    """Currency amount, 2 decimal places."""

    # SQLAlchemy checks `cache_ok` on the concrete class, not the base, so it
    # must be restated here or every query using this type skips the compiled
    # statement cache.
    cache_ok = True
    precision = 14
    scale = 2
    quantum = MONEY_PLACES
    impl = Numeric(14, 2)


class Quantity(_DecimalType):
    """Material quantity, 3 decimal places (kg-level precision on an MT figure)."""

    cache_ok = True
    precision = 16
    scale = 3
    quantum = QUANTITY_PLACES
    impl = Numeric(16, 3)
