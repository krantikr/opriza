"""Trader-editable pricing: rules, their inputs, and the resulting quote.

The commercial numbers used to live only in `business_rules.yaml`, which meant
changing a freight rate was a developer task and a restart. These tables move
that authority to the trader without giving up any of the properties that make
the figures trustworthy:

* **Rule *types* stay in code.** A trader adds, reorders, retunes and disables
  rules, and edits their conditions - but the arithmetic each type performs is
  written here, not composed in the UI. A generic expression builder would let
  someone write a loss-making rule by accident, and margins here floor at 2%.
* **Every rule is versioned.** `PricingRuleSet` is an immutable snapshot; a
  quotation stores the snapshot id that produced it, so a quote raised today is
  still explainable after the rules change tomorrow.
* **The build-up is stored, not recomputed.** `QuotationPricing` holds the
  ordered components with the figure and the sentence each contributed, the
  same self-documenting pattern `StockAvailability` uses.

The shape of the calculation is an **additive cost build-up, then one margin**:

    base + transportation + handling + financing + risk = total cost
    total cost + margin = quote

not a chain of percentage adjustments applied to each other. That is how the
trader reasons about a quote, and it is what the reference design specifies.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import (
    PricingBasis,
    PricingComponentKind,
    RecordStatus,
    RuleScope,
)
from app.models.mixins import CreatedAtMixin, TenantMixin, TimestampMixin, enum_col
from app.models.types import Money, Quantity


class PricingRuleSet(Base, CreatedAtMixin, TenantMixin):
    """An immutable, numbered snapshot of every rule in force at one moment.

    Editing a rule does not mutate history: it writes a new draft set, and
    publishing that set stamps it with a version. Quotations reference the set
    they were priced under, which is what keeps an old explanation honest.
    """

    __tablename__ = "pricing_rule_sets"
    # Versions number from 1 *per desk*, so the uniqueness has to be scoped to
    # the organisation. A global unique on `version` would mean only the first
    # desk on the platform could ever hold v1.
    __table_args__ = (UniqueConstraint("organisation_id", "version", name="uq_rule_set_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    # Exactly one set is live. Enforced in the service, not by a constraint,
    # because publishing is a two-step swap.
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column()
    published_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"))

    rules: Mapped[list["PricingRule"]] = relationship(
        back_populates="rule_set",
        cascade="all, delete-orphan",
        order_by="PricingRule.priority",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PricingRuleSet v{self.version} active={self.is_active}>"


class PricingRule(Base, TimestampMixin, TenantMixin):
    """One line of the cost build-up, as configured by a trader.

    `kind` selects the arithmetic (see `services/pricing/components.py`);
    `config` carries that kind's parameters, and `conditions` decides whether
    the rule applies to a given enquiry at all. Both are JSON because their
    shape is per-kind - they are validated against a typed schema on write, so
    a malformed rule is rejected at the API rather than at pricing time.
    """

    __tablename__ = "pricing_rules"
    __table_args__ = (
        UniqueConstraint("rule_set_id", "code", name="uq_pricing_rule_code"),
        Index("ix_pricing_rules_order", "rule_set_id", "priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("pricing_rule_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    code: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[PricingComponentKind] = mapped_column(
        enum_col(PricingComponentKind), nullable=False
    )
    # Lower runs first. The build-up is additive, so order matters only for
    # presentation and for the few kinds that read the running subtotal
    # (financing on landed cost, margin on total cost).
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    scope: Mapped[RuleScope] = mapped_column(
        enum_col(RuleScope), default=RuleScope.ALL, nullable=False
    )
    # e.g. {"delivery_location": ["Patna"], "min_quantity_mt": 25}
    conditions: Mapped[dict | None] = mapped_column(JSON)
    # e.g. {"pct": 3.0} or {"amount_per_mt": 300}
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    note_template: Mapped[str | None] = mapped_column(String(300))

    rule_set: Mapped[PricingRuleSet] = relationship(back_populates="rules")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PricingRule {self.code} {self.kind} p{self.priority}>"


class QuotationPricing(Base, TimestampMixin, TenantMixin):
    """The stored cost build-up for one quotation line.

    `components` is the ordered list of what each rule contributed, with the
    figure and the sentence explaining it - so the calculator can be rendered,
    and an old quote explained, without re-running anything against rules or
    stock that may since have changed.
    """

    __tablename__ = "quotation_pricing"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_line_item_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_line_items.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    rule_set_id: Mapped[int | None] = mapped_column(ForeignKey("pricing_rule_sets.id"))
    rules_version: Mapped[int | None] = mapped_column(Integer)

    basis: Mapped[PricingBasis] = mapped_column(
        enum_col(PricingBasis), default=PricingBasis.STOCK, nullable=False
    )
    basis_note: Mapped[str | None] = mapped_column(String(300))

    base_rate: Mapped[Decimal | None] = mapped_column(Money)
    total_cost: Mapped[Decimal | None] = mapped_column(Money)
    margin_amount: Mapped[Decimal | None] = mapped_column(Money)
    quote_rate: Mapped[Decimal | None] = mapped_column(Money)
    line_total: Mapped[Decimal | None] = mapped_column(Money)

    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    quantity_mt: Mapped[Decimal | None] = mapped_column(Quantity)

    # [{"code","label","kind","amount","note","overridden","computed_amount"}]
    components: Mapped[list | None] = mapped_column(JSON)
    explanation: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list | None] = mapped_column(JSON)

    # True once any component has been overridden by a human for this line.
    has_overrides: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set when the figures moved after a draft was written against them, so a
    # stale draft is never sent as though it still matched.
    draft_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    line_item: Mapped["QuotationLineItem"] = relationship(  # noqa: F821
        back_populates="pricing"
    )
    overrides: Mapped[list["PricingOverride"]] = relationship(
        back_populates="pricing", cascade="all, delete-orphan", order_by="PricingOverride.created_at"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<QuotationPricing line={self.quotation_line_item_id} {self.quote_rate}>"


class PricingOverride(Base, CreatedAtMixin, TenantMixin):
    """A human's change to one component of one quotation's build-up.

    The computed figure is kept alongside the override. Without it the stored
    breakdown would still add up while quietly misrepresenting what the rules
    produced, and "why is this price what it is?" would stop being answerable.
    """

    __tablename__ = "pricing_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_pricing_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_pricing.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"))

    component_code: Mapped[str] = mapped_column(String(60), nullable=False)
    computed_amount: Mapped[Decimal | None] = mapped_column(Money)
    override_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    pricing: Mapped[QuotationPricing] = relationship(back_populates="overrides")
    user: Mapped["User | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PricingOverride {self.component_code} {self.override_amount}>"


# ---------------------------------------------------------------------------
# Trader-maintained inputs the rules read
# ---------------------------------------------------------------------------


class LocationDistance(Base, TimestampMixin, TenantMixin):
    """Road distance between two places, maintained by the trader.

    Deliberately not a geocoding API call: a price calculation must not depend
    on a network round-trip or an API key, and a trader's own figure for a
    route they run weekly beats a routing engine's estimate.
    """

    __tablename__ = "location_distances"
    __table_args__ = (
        # Org-scoped: a lane is one desk's own figure, and two desks both
        # shipping Nagpur -> Pune is the normal case, not a conflict.
        UniqueConstraint(
            "organisation_id", "origin", "destination", name="uq_location_distance"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    distance_km: Mapped[float] = mapped_column(nullable=False)
    typical_days: Mapped[float | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(String(300))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LocationDistance {self.origin}->{self.destination} {self.distance_km}km>"


class VehicleRate(Base, TimestampMixin, TenantMixin):
    """Hire economics for one class of vehicle.

    Freight per MT is derived from these rather than stored as a flat rate, so
    the note on the quotation can show the working - "trailer at INR 50,000/day
    for 4 days over 100 MT" - instead of an unexplained number.
    """

    __tablename__ = "vehicle_rates"
    # Every desk names its own fleet; "Trailer" is not one desk's to reserve.
    __table_args__ = (
        UniqueConstraint("organisation_id", "name", name="uq_vehicle_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    capacity_mt: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    rate_per_day: Mapped[Decimal] = mapped_column(Money, nullable=False)
    avg_km_per_day: Mapped[float] = mapped_column(nullable=False, default=350.0)
    min_days: Mapped[float] = mapped_column(nullable=False, default=1.0)
    status: Mapped[RecordStatus] = mapped_column(
        enum_col(RecordStatus), default=RecordStatus.ACTIVE, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<VehicleRate {self.name} {self.capacity_mt}MT>"


class MillOffer(Base, TimestampMixin, TenantMixin):
    """A supplier's current offer for material the business does not hold.

    The fallback base price when nothing in stock matches: the trader quotes
    against procurement instead of inventory. Effective-dated, because an offer
    is only good for as long as the mill says it is - an expired offer is never
    used, the same way an expired price never was.
    """

    __tablename__ = "mill_offers"
    __table_args__ = (
        Index("ix_mill_offers_match", "product_type", "grade", "thickness_mm"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier: Mapped[str | None] = mapped_column(String(160))

    product_type: Mapped[str | None] = mapped_column(String(80), index=True)
    grade: Mapped[str | None] = mapped_column(String(60), index=True)
    thickness_mm: Mapped[float | None] = mapped_column()
    width_mm: Mapped[float | None] = mapped_column()
    length_mm: Mapped[float | None] = mapped_column()
    diameter_mm: Mapped[float | None] = mapped_column()

    rate_per_mt: Mapped[Decimal] = mapped_column(Money, nullable=False)
    origin_location: Mapped[str | None] = mapped_column(String(120))
    effective_from: Mapped[date | None] = mapped_column()
    effective_to: Mapped[date | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(String(300))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MillOffer {self.grade} {self.product_type} {self.rate_per_mt}>"


class SalesInvoice(Base, TimestampMixin, TenantMixin):
    """A past sale, used as evidence by the invoice-history rule.

    Reintroduced deliberately: pricing off what comparable material actually
    sold for is one of the things the trader asked for, and it is evidence the
    business already has. Kept as plain recorded fact - the rule decides how
    much weight to give it, and rejects outliers rather than trusting the mean.
    """

    __tablename__ = "sales_invoices"
    __table_args__ = (
        Index("ix_sales_invoices_match", "product_type", "grade", "thickness_mm"),
        Index("ix_sales_invoices_date", "invoice_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str | None] = mapped_column(String(60), index=True)
    invoice_date: Mapped[date | None] = mapped_column()
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)

    product_type: Mapped[str | None] = mapped_column(String(80), index=True)
    grade: Mapped[str | None] = mapped_column(String(60), index=True)
    thickness_mm: Mapped[float | None] = mapped_column()
    width_mm: Mapped[float | None] = mapped_column()
    length_mm: Mapped[float | None] = mapped_column()
    diameter_mm: Mapped[float | None] = mapped_column()

    quantity_mt: Mapped[Decimal | None] = mapped_column(Quantity)
    rate_per_mt: Mapped[Decimal | None] = mapped_column(Money)
    delivery_location: Mapped[str | None] = mapped_column(String(120))

    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))

    customer: Mapped["Customer | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SalesInvoice {self.invoice_no} {self.grade} {self.rate_per_mt}>"


__all__ = [
    "PricingRuleSet",
    "PricingRule",
    "QuotationPricing",
    "PricingOverride",
    "LocationDistance",
    "VehicleRate",
    "MillOffer",
    "SalesInvoice",
]
