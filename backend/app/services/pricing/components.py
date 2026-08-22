"""The arithmetic behind each pricing rule kind.

No language model participates in any part of this file, and nothing here is
ever shown to one as something to compute with. Every figure is produced in
`Decimal` from a trader's configured rule and the facts of the enquiry.

Each component returns its amount **and the sentence explaining it**, so the
stored breakdown is a by-product of the calculation rather than a model asked
to justify a number afterwards. That is what keeps a quote raised months ago
answerable today.

The build-up is additive:

    base + transport + handling + financing + risk + adjustments = total cost
    total cost + margin                                          = quote

Percentage components state what they are a percentage *of* - `BASE` or
`RUNNING` cost - because "3% financing" is meaningless without it, and getting
that wrong is a silent pricing error rather than a crash.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Customer,
    LocationDistance,
    PricingComponentKind,
    SalesInvoice,
    VehicleRate,
)

CENT = Decimal("0.01")
DAYS_IN_YEAR = Decimal(365)


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def pct_text(value: Decimal) -> str:
    """Render a percentage the way a trader writes it: 11, not 11.0."""
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        return f"{normalized.to_integral_value():f}"
    return f"{normalized:f}"


def dec(value: Any, default: str = "0") -> Decimal:
    """Tolerant Decimal conversion - rule config arrives as JSON."""
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 - malformed config must not crash pricing
        return Decimal(default)


@dataclass(slots=True)
class PricingContext:
    """Everything a rule may read about the enquiry being priced.

    Deliberately a flat, explicit set of facts rather than the ORM objects: a
    component cannot reach into the database and surprise us, and the whole
    context can be constructed in a test without a session.
    """

    db: Session | None = None

    quantity_mt: Decimal | None = None
    product_type: str | None = None
    grade: str | None = None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    diameter_mm: float | None = None

    customer: Customer | None = None
    customer_tier: str | None = None
    delivery_location: str | None = None
    origin_location: str | None = None
    payment_days: int | None = None

    #: Landed cost per MT of the matched stock, when the material is held.
    stock_cost_per_mt: Decimal | None = None
    #: Supplier offer per MT, used when nothing in stock matches.
    mill_offer_per_mt: Decimal | None = None
    mill_offer_supplier: str | None = None

    today: date = field(default_factory=date.today)


@dataclass(slots=True)
class ComponentResult:
    """What one rule contributed, and why."""

    amount: Decimal
    note: str
    applied: bool = True
    warning: str | None = None
    #: Set by components that replace the running total instead of adding to
    #: it (the floor and rounding), since the build-up cannot express that.
    replaces_total: Decimal | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class Component(Protocol):
    """One rule kind's arithmetic."""

    def __call__(
        self, config: dict, ctx: PricingContext, running: Decimal, base: Decimal
    ) -> ComponentResult: ...


# ---------------------------------------------------------------------------
#: The single wording for an unpriceable line. Shared with the engine's
#: backstop so the component's report and the backstop cannot drift apart into
#: two near-identical banners on the same screen.
NO_BASE_PRICE = "No base price available."


# Base price
# ---------------------------------------------------------------------------


def base_price(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """Landed cost of held stock, or a mill offer when nothing is held.

    Stock is preferred because it is what the business actually owns - a real
    cost already incurred, not an offer that may move. The fallback is what
    lets the desk quote material it would have to buy in, which is the other
    half of the trade.
    """
    prefer = (config.get("prefer") or "STOCK").upper()

    stock = ctx.stock_cost_per_mt
    offer = ctx.mill_offer_per_mt

    chosen: Decimal | None = None
    source = ""
    if prefer == "MILL_OFFER":
        chosen, source = (offer, "MILL_OFFER") if offer is not None else (stock, "STOCK")
    else:
        chosen, source = (stock, "STOCK") if stock is not None else (offer, "MILL_OFFER")

    if chosen is None:
        return ComponentResult(
            amount=Decimal(0),
            note=(
                "No landed cost is recorded for the matched stock and no current mill "
                "offer covers this material, so no base price can be established."
            ),
            applied=False,
            warning=NO_BASE_PRICE,
            meta={"basis": "UNAVAILABLE"},
        )

    if source == "STOCK":
        note = f"Weighted-average landed cost of the matched stock: INR {chosen:,.2f}/MT."
    else:
        supplier = f" from {ctx.mill_offer_supplier}" if ctx.mill_offer_supplier else ""
        note = f"Mill offer{supplier} (material not held in stock): INR {chosen:,.2f}/MT."

    return ComponentResult(amount=money(chosen), note=note, meta={"basis": source})


# ---------------------------------------------------------------------------
# Cost lines
# ---------------------------------------------------------------------------


def transportation(
    config: dict, ctx: PricingContext, running: Decimal, base: Decimal
) -> ComponentResult:
    """Freight per MT, derived from distance and vehicle economics.

    A flat per-destination rate is supported, but the derived form is preferred
    because it shows its working - "trailer at INR 50,000/day for 4 days over
    28 MT" is a figure a customer can argue with, which is the point.
    """
    flat = config.get("amount_per_mt")
    if flat is not None:
        amount = money(dec(flat))
        where = f" to {ctx.delivery_location}" if ctx.delivery_location else ""
        return ComponentResult(
            amount=amount, note=f"Freight{where}: INR {amount:,.2f} per MT."
        )

    if ctx.db is None or not ctx.delivery_location:
        return ComponentResult(
            amount=Decimal(0),
            note="No delivery location was stated, so the quote is on an ex-works basis.",
            applied=False,
        )

    origin = ctx.origin_location or config.get("default_origin")
    distance = _lookup_distance(ctx.db, origin, ctx.delivery_location)
    if distance is None:
        return ComponentResult(
            amount=Decimal(0),
            note=(
                f"No road distance is on file for {ctx.delivery_location}, so freight "
                "is not included and the quote is ex-works."
            ),
            applied=False,
            warning=f"Distance to {ctx.delivery_location} is not configured.",
        )

    vehicle = _lookup_vehicle(ctx.db, config.get("vehicle"))
    if vehicle is None:
        return ComponentResult(
            amount=Decimal(0),
            note="No vehicle rate is configured, so freight cannot be calculated.",
            applied=False,
            warning="No vehicle rate configured.",
        )

    # Round trip: the lorry has to come back, and the trader pays for that.
    round_trip = bool(config.get("round_trip", True))
    km = Decimal(str(distance.distance_km)) * (Decimal(2) if round_trip else Decimal(1))

    if distance.typical_days:
        days = Decimal(str(distance.typical_days))
    else:
        per_day = Decimal(str(vehicle.avg_km_per_day or 350))
        days = (km / per_day).quantize(Decimal("0.1"), rounding=ROUND_CEILING)
    days = max(days, Decimal(str(vehicle.min_days or 1)))

    hire = vehicle.rate_per_day * days

    # How the hire is shared out. A part load does not pay for a whole lorry:
    # below `min_load_pct` of capacity the consignment is assumed to travel
    # with other freight, so the cost spreads over that minimum rather than
    # over the order alone. Without this a 0.5 MT enquiry carries an entire
    # trailer and prices at several lakh per MT - arithmetically true, and
    # commercially nonsense.
    capacity = vehicle.capacity_mt
    min_load_pct = dec(config.get("min_load_pct"), "40")
    shared_floor = capacity * min_load_pct / Decimal(100)

    ordered = ctx.quantity_mt if ctx.quantity_mt and ctx.quantity_mt > 0 else None
    if ordered is None:
        return ComponentResult(
            amount=Decimal(0),
            note="Freight cannot be apportioned without a quantity.",
            applied=False,
            warning="Quantity unknown; freight excluded.",
        )

    part_load = ordered < shared_floor
    basis = max(min(ordered, capacity), shared_floor)

    per_mt = money(hire / basis)
    leg = "round trip" if round_trip else "one way"
    sharing = (
        f" Part load, so the cost is spread over the {basis:g} MT minimum "
        f"({min_load_pct:g}% of a {capacity:g} MT {vehicle.name.lower()}) rather than "
        f"{ordered:g} MT alone."
        if part_load
        else ""
    )
    return ComponentResult(
        amount=per_mt,
        note=(
            f"Freight to {ctx.delivery_location}: {distance.distance_km:g} km ({leg}) by "
            f"{vehicle.name} at INR {vehicle.rate_per_day:,.2f}/day x {days:g} days "
            f"over {basis:g} MT = INR {per_mt:,.2f} per MT.{sharing}"
        ),
        meta={
            "distance_km": float(distance.distance_km),
            "days": float(days),
            "part_load": part_load,
        },
    )


def handling(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """Loading, unloading and other per-MT handling."""
    amount = money(dec(config.get("amount_per_mt")))
    label = config.get("description") or "Loading and unloading"
    return ComponentResult(amount=amount, note=f"{label}: INR {amount:,.2f} per MT.")


def financing(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """Cost of carrying credit for the payment period.

    Charged on the cost accumulated so far, not on the eventual selling price:
    the money tied up is what was spent, and financing the margin would be
    charging the customer interest on the profit.
    """
    # Stated terms beat the configured default: a rule saying 60 days is the
    # house assumption, not a contradiction of what this customer agreed.
    days = ctx.payment_days if ctx.payment_days is not None else config.get("days")
    if days is None:
        return ComponentResult(
            amount=Decimal(0),
            note="No payment period is on file, so no financing cost is applied.",
            applied=False,
        )

    rate_pct = dec(config.get("annual_rate_pct"))
    if rate_pct <= 0:
        return ComponentResult(
            amount=Decimal(0), note="No financing rate is configured.", applied=False
        )

    principal = running if running > 0 else base
    days_dec = dec(days)
    amount = money(principal * rate_pct / Decimal(100) * days_dec / DAYS_IN_YEAR)
    return ComponentResult(
        amount=amount,
        note=(
            f"Financing for {pct_text(days_dec)} days"
            f"{' (as agreed with this customer)' if ctx.payment_days is not None else ''}"
            f" at {pct_text(rate_pct)}% p.a. on INR "
            f"{principal:,.2f}: INR {amount:,.2f} per MT."
        ),
    )


def risk_buffer(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """Market and delivery risk allowance, flat or as a percentage of cost."""
    if config.get("amount_per_mt") is not None:
        amount = money(dec(config.get("amount_per_mt")))
        return ComponentResult(
            amount=amount, note=f"Market and delivery risk buffer: INR {amount:,.2f} per MT."
        )

    pct = dec(config.get("pct"))
    principal = running if running > 0 else base
    amount = money(principal * pct / Decimal(100))
    return ComponentResult(
        amount=amount,
        note=f"Risk buffer of {pct_text(pct)}% on INR {principal:,.2f}: INR {amount:,.2f} per MT.",
    )


def adjustment(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """A named per-MT or percentage adjustment, up or down."""
    label = config.get("description") or "Adjustment"
    if config.get("amount_per_mt") is not None:
        amount = money(dec(config.get("amount_per_mt")))
        direction = "added" if amount >= 0 else "deducted"
        return ComponentResult(amount=amount, note=f"{label}: INR {abs(amount):,.2f} per MT {direction}.")

    pct = dec(config.get("pct"))
    principal = base if (config.get("of") or "BASE").upper() == "BASE" else running
    amount = money(principal * pct / Decimal(100))
    return ComponentResult(
        amount=amount, note=f"{label}: {pct_text(pct)}% of INR {principal:,.2f} = INR {amount:,.2f} per MT."
    )


def quantity_slab(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """Volume adjustment by tonnage band.

    An unknown quantity does not fall in a band. Picking one would be inventing
    an order size, so the rule stands aside instead.
    """
    if ctx.quantity_mt is None:
        return ComponentResult(
            amount=Decimal(0),
            note="Quantity is not stated, so no volume band applies.",
            applied=False,
        )

    slabs = config.get("slabs") or []
    qty = ctx.quantity_mt
    for slab in slabs:
        low = dec(slab.get("min_mt"), "0")
        high = slab.get("max_mt")
        if qty >= low and (high is None or qty < dec(high)):
            pct = dec(slab.get("pct"))
            if pct == 0:
                return ComponentResult(
                    amount=Decimal(0),
                    note=f"Quantity {qty:g} MT falls in the {_slab_label(slab)} band: no adjustment.",
                )
            principal = base if (config.get("of") or "RUNNING").upper() == "BASE" else running
            amount = money(principal * pct / Decimal(100))
            verb = "discount" if pct < 0 else "premium"
            return ComponentResult(
                amount=amount,
                note=(
                    f"Quantity {qty:g} MT falls in the {_slab_label(slab)} band: "
                    f"{pct_text(abs(pct))}% {verb} = INR {amount:,.2f} per MT."
                ),
            )

    return ComponentResult(
        amount=Decimal(0), note=f"Quantity {qty:g} MT falls outside every configured band.", applied=False
    )


def customer_tier(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """A/B/C commercial adjustment.

    An unknown or unverified customer gets no adjustment: a tier nobody has
    confirmed is not grounds for a discount.
    """
    tier = ctx.customer_tier or (ctx.customer.tier.value if ctx.customer else None)
    if not tier:
        return ComponentResult(
            amount=Decimal(0), note="Customer tier is unknown, so no tier adjustment applies.", applied=False
        )
    if ctx.customer is not None and not ctx.customer.is_verified:
        return ComponentResult(
            amount=Decimal(0),
            note=f"Customer record is unverified, so the tier {tier} adjustment is not applied.",
            applied=False,
            warning="Unverified customer: tier adjustment withheld.",
        )

    pct = dec((config.get("tiers") or {}).get(tier))
    if pct == 0:
        return ComponentResult(amount=Decimal(0), note=f"Customer tier {tier}: no adjustment.")

    principal = base if (config.get("of") or "RUNNING").upper() == "BASE" else running
    amount = money(principal * pct / Decimal(100))
    verb = "discount" if pct < 0 else "premium"
    return ComponentResult(
        amount=amount,
        note=f"Customer tier {tier} applies a {pct_text(abs(pct))}% {verb}: INR {amount:,.2f} per MT.",
    )


def invoice_anchor(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """Blend recent comparable sales toward the computed cost.

    Evidence, not authority. A thin or wildly scattered sample is refused
    rather than averaged, and outliers are dropped before the mean is taken -
    one miskeyed invoice must not be able to drag a quote.
    """
    if ctx.db is None:
        return ComponentResult(amount=Decimal(0), note="No invoice history available.", applied=False)

    window_days = int(dec(config.get("window_days"), "30"))
    min_count = int(dec(config.get("min_count"), "3"))
    weight_pct = dec(config.get("weight_pct"), "40")

    rates, used_days = _comparable_rates(ctx, window_days, int(dec(config.get("max_window_days"), "90")))
    if len(rates) < min_count:
        return ComponentResult(
            amount=Decimal(0),
            note=(
                f"Only {len(rates)} comparable sale(s) in the last {used_days} days - "
                f"fewer than the {min_count} required, so history is not used."
            ),
            applied=False,
        )

    kept = _reject_outliers(rates)
    dropped = len(rates) - len(kept)
    if len(kept) < min_count:
        return ComponentResult(
            amount=Decimal(0),
            note="Comparable sales were too scattered to be reliable, so history is not used.",
            applied=False,
        )

    average = money(sum(kept) / Decimal(len(kept)))
    target = running if running > 0 else base
    # Move `weight_pct` of the way from the computed figure toward history.
    amount = money((average - target) * weight_pct / Decimal(100))

    dropped_note = f" ({dropped} outlier(s) rejected)" if dropped else ""
    direction = "up" if amount > 0 else "down"
    return ComponentResult(
        amount=amount,
        note=(
            f"Blended {pct_text(weight_pct)}% of the average of {len(kept)} comparable sale(s) "
            f"in the last {used_days} days{dropped_note} (INR {average:,.2f}): "
            f"adjusts {direction} by INR {abs(amount):,.2f} per MT."
        ),
        meta={"comparable_count": len(kept), "average": float(average), "window_days": used_days},
    )


# ---------------------------------------------------------------------------
# Margin, floor and rounding - these act on the finished cost
# ---------------------------------------------------------------------------


def target_margin(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """The single margin, applied once to total cost."""
    pct = dec(config.get("pct"))
    amount = money(running * pct / Decimal(100))
    return ComponentResult(
        amount=amount,
        note=f"Target margin of {pct_text(pct)}% on total cost INR {running:,.2f}: INR {amount:,.2f} per MT.",
    )


def margin_floor(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """Clamp the quote up to a minimum margin over base, and say so.

    Flagging matters as much as correcting: a quote that only clears the floor
    because the floor caught it is a quote a human should look at.
    """
    pct = dec(config.get("minimum_margin_pct"), "2")
    minimum = money(base * (Decimal(1) + pct / Decimal(100)))

    if running >= minimum:
        return ComponentResult(
            amount=Decimal(0),
            note=f"Price clears the minimum of INR {minimum:,.2f} ({pct_text(pct)}% over base).",
        )

    lift = money(minimum - running)
    return ComponentResult(
        amount=lift,
        replaces_total=minimum,
        note=(
            f"Price was below the {pct_text(pct)}% minimum margin and has been raised by "
            f"INR {lift:,.2f} to INR {minimum:,.2f} per MT."
        ),
        warning=f"Margin floor applied: raised by INR {lift:,.2f}/MT.",
    )


def rounding(config: dict, ctx: PricingContext, running: Decimal, base: Decimal) -> ComponentResult:
    """Round to a quotable figure - never back down through the floor."""
    nearest = dec(config.get("nearest"), "0")
    if nearest <= 0:
        return ComponentResult(amount=Decimal(0), note="No rounding configured.", applied=False)

    mode = (config.get("mode") or "nearest").lower()
    quotient = running / nearest
    if mode == "up":
        rounded = quotient.quantize(Decimal(1), rounding=ROUND_CEILING) * nearest
    elif mode == "down":
        rounded = quotient.quantize(Decimal(1), rounding=ROUND_FLOOR) * nearest
    else:
        rounded = quotient.quantize(Decimal(1), rounding=ROUND_HALF_UP) * nearest

    rounded = money(rounded)
    delta = money(rounded - running)
    if delta == 0:
        return ComponentResult(amount=Decimal(0), note=f"Already a round INR {pct_text(nearest)} figure.")

    return ComponentResult(
        amount=delta,
        replaces_total=rounded,
        note=f"Rounded to the nearest INR {pct_text(nearest)}: INR {rounded:,.2f} per MT.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slab_label(slab: dict) -> str:
    low = slab.get("min_mt") or 0
    high = slab.get("max_mt")
    return f"{low:g}-{high:g} MT" if high else f"{low:g} MT and above"


def _lookup_distance(db: Session, origin: str | None, destination: str) -> LocationDistance | None:
    """Match a free-text destination tolerantly, and treat a route as symmetric."""
    target = destination.strip().lower()
    rows = list(db.scalars(select(LocationDistance)))

    def matches(value: str | None) -> bool:
        if not value:
            return False
        left = value.strip().lower()
        return left == target or left in target or target in left

    if origin:
        source = origin.strip().lower()
        for row in rows:
            if matches(row.destination) and row.origin.strip().lower() == source:
                return row
        for row in rows:
            if matches(row.origin) and row.destination.strip().lower() == source:
                return row

    for row in rows:
        if matches(row.destination):
            return row
    for row in rows:
        if matches(row.origin):
            return row
    return None


def _lookup_vehicle(db: Session, name: str | None) -> VehicleRate | None:
    from app.models import RecordStatus

    query = select(VehicleRate).where(VehicleRate.status == RecordStatus.ACTIVE)
    if name:
        found = db.scalar(query.where(VehicleRate.name == name))
        if found:
            return found
    # Otherwise the largest active vehicle, which is the usual default for a
    # full trailer load and gives the lowest per-MT freight.
    return db.scalar(query.order_by(VehicleRate.capacity_mt.desc()))


def _comparable_rates(ctx: PricingContext, window_days: int, max_window: int) -> tuple[list[Decimal], int]:
    """Comparable sale rates, widening the window before giving up."""
    assert ctx.db is not None

    window = window_days
    while window <= max_window:
        cutoff = ctx.today - timedelta(days=window)
        query = select(SalesInvoice).where(
            SalesInvoice.rate_per_mt.is_not(None),
            SalesInvoice.invoice_date.is_not(None),
            SalesInvoice.invoice_date >= cutoff,
        )
        if ctx.product_type:
            query = query.where(SalesInvoice.product_type == ctx.product_type)
        if ctx.grade:
            query = query.where(SalesInvoice.grade == ctx.grade)
        if ctx.thickness_mm is not None:
            query = query.where(SalesInvoice.thickness_mm == ctx.thickness_mm)

        rates = [Decimal(str(row.rate_per_mt)) for row in ctx.db.scalars(query)]
        if len(rates) >= 3 or window == max_window:
            return rates, window
        window = min(window * 2, max_window)

    return [], window_days


def _reject_outliers(rates: list[Decimal]) -> list[Decimal]:
    """Drop rates more than two standard deviations from the mean.

    A single miskeyed invoice - a rate entered per kg where the rest are per MT
    - would otherwise move the anchor by an order of magnitude.
    """
    if len(rates) < 4:
        return rates
    values = [float(r) for r in rates]
    mean = statistics.fmean(values)
    sd = statistics.pstdev(values)
    if sd == 0:
        return rates
    return [r for r, v in zip(rates, values, strict=True) if abs(v - mean) <= 2 * sd]


#: Dispatch table. A rule kind with no entry here cannot be evaluated, which
#: is the point - the set of things a rule may do is closed and reviewable.
COMPONENTS: dict[PricingComponentKind, Component] = {
    PricingComponentKind.BASE_PRICE: base_price,
    PricingComponentKind.TRANSPORTATION: transportation,
    PricingComponentKind.HANDLING: handling,
    PricingComponentKind.FINANCING: financing,
    PricingComponentKind.RISK_BUFFER: risk_buffer,
    PricingComponentKind.ADJUSTMENT: adjustment,
    PricingComponentKind.QUANTITY_SLAB: quantity_slab,
    PricingComponentKind.CUSTOMER_TIER: customer_tier,
    PricingComponentKind.INVOICE_ANCHOR: invoice_anchor,
    PricingComponentKind.TARGET_MARGIN: target_margin,
    PricingComponentKind.MARGIN_FLOOR: margin_floor,
    PricingComponentKind.ROUNDING: rounding,
}
