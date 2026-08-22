"""API shapes for the pricing rule engine.

Rule `config` is validated per kind on write rather than being accepted as
free-form JSON. A malformed rule is then rejected at the API with a field name,
instead of silently producing a wrong figure the next time something is priced.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import PricingBasis, PricingComponentKind
from app.schemas.common import ORMModel


class ComponentOut(BaseModel):
    """One row of a stored build-up, as the calculator renders it."""

    code: str
    label: str
    kind: str
    amount: Decimal
    note: str
    applied: bool = True
    overridden: bool = False
    computed_amount: Decimal | None = None
    subtotal: Decimal | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class PricingOut(ORMModel):
    id: int
    basis: PricingBasis
    basis_note: str | None = None
    base_rate: Decimal | None = None
    total_cost: Decimal | None = None
    margin_amount: Decimal | None = None
    quote_rate: Decimal | None = None
    line_total: Decimal | None = None
    currency: str = "INR"
    quantity_mt: Decimal | None = None
    rules_version: int | None = None
    components: list[ComponentOut] = Field(default_factory=list)
    explanation: str | None = None
    # Stored as NULL when empty, so coerce rather than reject.
    warnings: list[str] | None = Field(default=None)
    has_overrides: bool = False
    draft_stale: bool = False
    #: True when this row was computed against a *different* rule set than the
    #: one live now - typically it was priced before any rules were published.
    #: The stored warnings then describe a state that no longer exists, and
    #: rendering them as current is how a desk with working rules ends up
    #: being told it has none.
    rules_stale: bool = False

    @field_validator("components", "warnings", mode="before")
    @classmethod
    def _null_to_empty(cls, value: Any) -> Any:
        return value if value is not None else []


class RuleOut(ORMModel):
    id: int
    code: str
    label: str
    kind: PricingComponentKind
    priority: int
    is_active: bool
    conditions: dict[str, Any] | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    note_template: str | None = None


class RuleSetOut(ORMModel):
    id: int
    version: int
    label: str | None = None
    notes: str | None = None
    is_active: bool
    published_at: datetime | None = None
    created_at: datetime
    rules: list[RuleOut] = Field(default_factory=list)


# --- Requests --------------------------------------------------------------

#: Required config keys per kind. Anything else is optional and passed through,
#: so a new option can be added without a migration - but a rule that cannot
#: possibly compute is refused at the door.
REQUIRED_CONFIG: dict[PricingComponentKind, tuple[str, ...]] = {
    PricingComponentKind.HANDLING: ("amount_per_mt",),
    PricingComponentKind.FINANCING: ("annual_rate_pct",),
    PricingComponentKind.TARGET_MARGIN: ("pct",),
    PricingComponentKind.MARGIN_FLOOR: ("minimum_margin_pct",),
    PricingComponentKind.ROUNDING: ("nearest",),
    PricingComponentKind.QUANTITY_SLAB: ("slabs",),
    PricingComponentKind.CUSTOMER_TIER: ("tiers",),
    PricingComponentKind.INVOICE_ANCHOR: ("weight_pct",),
}


class RuleIn(BaseModel):
    code: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1, max_length=120)
    kind: PricingComponentKind
    priority: int = 100
    is_active: bool = True
    conditions: dict[str, Any] | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    note_template: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _check_config(self) -> RuleIn:
        missing = [key for key in REQUIRED_CONFIG.get(self.kind, ()) if self.config.get(key) is None]
        if missing:
            raise ValueError(
                f"{self.kind.value} needs {', '.join(missing)} in config"
            )

        if self.kind is PricingComponentKind.QUANTITY_SLAB:
            slabs = self.config.get("slabs")
            if not isinstance(slabs, list) or not slabs:
                raise ValueError("slabs must be a non-empty list")
            for slab in slabs:
                if "pct" not in slab:
                    raise ValueError("every slab needs a pct")

        if self.kind is PricingComponentKind.ROUNDING:
            if Decimal(str(self.config.get("nearest", 0))) <= 0:
                raise ValueError("nearest must be greater than zero")

        return self


class RuleSetIn(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    rules: list[RuleIn]

    @field_validator("rules")
    @classmethod
    def _unique_codes(cls, rules: list[RuleIn]) -> list[RuleIn]:
        codes = [r.code for r in rules]
        duplicates = {c for c in codes if codes.count(c) > 1}
        if duplicates:
            raise ValueError(f"duplicate rule codes: {', '.join(sorted(duplicates))}")
        if not any(r.kind is PricingComponentKind.BASE_PRICE for r in rules):
            raise ValueError("a rule set needs a BASE_PRICE rule to price anything")
        return rules


class PreviewIn(BaseModel):
    """A what-if scenario, so a trader can test a change before publishing it."""

    rule_set_id: int | None = None
    rules: list[RuleIn] | None = None

    base_rate: Decimal | None = None
    quantity_mt: Decimal | None = None
    product_type: str | None = None
    grade: str | None = None
    thickness_mm: float | None = None
    customer_id: int | None = None
    customer_tier: Literal["A", "B", "C"] | None = None
    delivery_location: str | None = None
    origin_location: str | None = None
    payment_days: int | None = None


class PreviewOut(BaseModel):
    basis: PricingBasis
    base_rate: Decimal | None = None
    total_cost: Decimal | None = None
    margin_amount: Decimal | None = None
    quote_rate: Decimal | None = None
    line_total: Decimal | None = None
    currency: str = "INR"
    rules_version: int | None = None
    components: list[ComponentOut] = Field(default_factory=list)
    explanation: str | None = None
    warnings: list[str] = Field(default_factory=list)


class OverrideIn(BaseModel):
    component_code: str = Field(min_length=1, max_length=60)
    amount: Decimal
    reason: str | None = None


# --- Trader-maintained inputs ----------------------------------------------


class DistanceIn(BaseModel):
    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    distance_km: float = Field(gt=0)
    typical_days: float | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=300)


class DistanceOut(ORMModel):
    id: int
    origin: str
    destination: str
    distance_km: float
    typical_days: float | None = None
    notes: str | None = None


class VehicleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    capacity_mt: Decimal = Field(gt=0)
    rate_per_day: Decimal = Field(ge=0)
    avg_km_per_day: float = Field(default=350.0, gt=0)
    min_days: float = Field(default=1.0, gt=0)


class VehicleOut(ORMModel):
    id: int
    name: str
    capacity_mt: Decimal
    rate_per_day: Decimal
    avg_km_per_day: float
    min_days: float
    status: str


class MillOfferIn(BaseModel):
    supplier: str | None = Field(default=None, max_length=160)
    product_type: str | None = Field(default=None, max_length=80)
    grade: str | None = Field(default=None, max_length=60)
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    diameter_mm: float | None = None
    rate_per_mt: Decimal = Field(gt=0)
    origin_location: str | None = Field(default=None, max_length=120)
    effective_from: Any | None = None
    effective_to: Any | None = None
    notes: str | None = Field(default=None, max_length=300)


class MillOfferOut(ORMModel):
    id: int
    supplier: str | None = None
    product_type: str | None = None
    grade: str | None = None
    thickness_mm: float | None = None
    rate_per_mt: Decimal
    origin_location: str | None = None
    effective_from: Any | None = None
    effective_to: Any | None = None
    notes: str | None = None
