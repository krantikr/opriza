"""What we have, what we owe, and what we still have to buy.

The Stock page used to answer only "what is on the floor", which is the least
useful of the three numbers a trader works from. On its own a balance of 28 MT
says nothing about whether the desk is comfortable or about to disappoint
somebody: 28 MT against 5 MT of accepted orders is idle capital, and against
40 MT it is a purchase that needs making this week.

So the position is expressed as a short chain, per specification:

    in stock  -  committed  =  free          (what may still be sold)
    committed -  in stock   =  to buy        (what must be bought to deliver)
    prospective                              (quoted, not yet won)

`committed` is deliberately narrow - accepted and not yet despatched. That is
material the desk is obliged to hand over, and nothing else belongs in a
figure a purchase decision is made from. Quotations still out with the
customer are counted separately as `prospective`, because treating a quote as
an order is how a desk ends up buying steel for business it never won.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    QuotationLineItem,
    QuotationRequest,
    QuotationStatus,
    StockItem,
)

KG_PER_MT = Decimal(1000)
ZERO = Decimal("0.000")

#: Won, and still owed to the customer.
COMMITTED_STATUSES = (QuotationStatus.CUSTOMER_ACCEPTED,)

#: Quoted and still live - the customer has neither accepted nor declined.
PROSPECTIVE_STATUSES = (QuotationStatus.SENT,)


#: Product words that describe the same form of steel. The stock sheet says
#: "Plate"; the customer wrote "C-45 Plates" and the extractor kept their
#: wording. Both are plate, and keying on the raw text put identical material
#: - same grade, same three dimensions - into two rows, one holding the stock
#: and the other holding the demand, so a trader saw two half-answers and no
#: shortfall where there was one.
_FORMS = (
    "PLATE", "SHEET", "COIL", "ANGLE", "CHANNEL", "BEAM", "ROUND",
    "SQUARE", "FLAT", "PIPE", "TUBE", "TMT", "BAR", "STRIP", "BILLET",
)


def _form(product_type: str | None) -> str | None:
    """The form of steel named in a free-text product description.

    Matched on the word rather than the whole string, and singularised, so
    "Plate", "Plates" and "C-45 Plates" all reduce to PLATE. Anything with no
    recognisable form keeps its own text: an unfamiliar product is better
    shown as its own row than silently merged into one it is not.
    """
    text = (product_type or "").strip().upper()
    if not text:
        return None
    for word in text.replace("/", " ").replace("-", " ").split():
        singular = word[:-1] if word.endswith("S") and len(word) > 3 else word
        if singular in _FORMS:
            return singular
    return text


def _spec_key(row) -> tuple:
    """Group by what makes two pieces of steel interchangeable.

    Grade and the three dimensions are the identity; the product *form* is
    normalised because it is free text on both sides and the same steel is
    described differently by a stock sheet and by a customer.
    """
    return (
        _form(row.product_type),
        (row.grade or "").strip().upper() or None,
        row.thickness_mm,
        row.width_mm,
        row.length_mm,
    )


@dataclass(slots=True)
class SpecPosition:
    """The demand and supply picture for one specification."""

    key: tuple
    product_type: str | None = None
    grade: str | None = None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    display_name: str = ""

    in_stock_mt: Decimal = ZERO
    committed_mt: Decimal = ZERO
    prospective_mt: Decimal = ZERO
    lot_count: int = 0
    locations: list[str] = field(default_factory=list)
    #: Weighted average landed cost per MT, across the lots that carry one.
    #: Weighted rather than a plain mean: two lots bought months apart at
    #: different prices are not equally represented in what is on the floor,
    #: and averaging them flat overstates the cheaper one.
    cost_per_mt: Decimal | None = None
    #: Running weights for that average, discarded once it is computed.
    _cost_weighted: Decimal = ZERO
    _cost_weight: Decimal = ZERO

    @property
    def free_mt(self) -> Decimal:
        """On the floor and not already owed to anyone. Never below zero."""
        return max(self.in_stock_mt - self.committed_mt, ZERO)

    @property
    def to_buy_mt(self) -> Decimal:
        """What must be bought to meet what is already committed.

        Only the shortfall against *accepted* orders. A quotation still with
        the customer is not a reason to buy steel, and a purchase list that
        cannot tell the two apart is one that overbuys.
        """
        return max(self.committed_mt - self.in_stock_mt, ZERO)

    @property
    def short(self) -> bool:
        return self.to_buy_mt > 0


def _quantity_mt(item: QuotationLineItem) -> Decimal:
    return Decimal(str(item.quantity_mt)) if item.quantity_mt is not None else ZERO


def spec_positions(db: Session) -> list[SpecPosition]:
    """The position for every specification the desk holds or owes."""
    positions: dict[tuple, SpecPosition] = {}

    def bucket(row) -> SpecPosition:
        key = _spec_key(row)
        existing = positions.get(key)
        if existing is None:
            existing = SpecPosition(
                key=key,
                product_type=row.product_type,
                grade=row.grade,
                thickness_mm=row.thickness_mm,
                width_mm=row.width_mm,
                length_mm=row.length_mm,
            )
            positions[key] = existing
        return existing

    # --- Supply -----------------------------------------------------------
    for lot in db.scalars(select(StockItem)):
        position = bucket(lot)
        balance_kg = Decimal(str(lot.balance_qty_kg or 0))
        position.in_stock_mt += balance_kg / KG_PER_MT
        position.lot_count += 1

        # Landed cost is what the material actually cost to have on the floor;
        # purchase rate is the fallback, the same order the pricing engine
        # uses, so the figure here matches what a quote would be built from.
        cost = lot.landed_cost_per_kg
        if cost is None:
            cost = lot.purchase_rate_per_kg
        if cost is not None and balance_kg > 0:
            position._cost_weighted += Decimal(str(cost)) * balance_kg
            position._cost_weight += balance_kg
        if lot.location and lot.location not in position.locations:
            position.locations.append(lot.location)
        if not position.display_name:
            position.display_name = lot.display_name

    # --- Demand -----------------------------------------------------------
    # Read from the line items rather than the stock hold: a line the matcher
    # could not place against a lot is still tonnage the desk has to find, and
    # it is exactly the case a purchase list must not miss.
    wanted = COMMITTED_STATUSES + PROSPECTIVE_STATUSES
    rows = db.execute(
        select(QuotationLineItem, QuotationRequest)
        .join(QuotationRequest, QuotationLineItem.quotation_request_id == QuotationRequest.id)
        .where(QuotationRequest.status.in_(wanted))
    ).all()

    for item, quotation in rows:
        # Despatched material has left the floor and is no longer owed.
        if quotation.status in COMMITTED_STATUSES and quotation.despatched_at is not None:
            continue

        position = bucket(item)
        quantity = _quantity_mt(item)
        if quotation.status in COMMITTED_STATUSES:
            position.committed_mt += quantity
        else:
            position.prospective_mt += quantity

        if not position.display_name:
            position.display_name = item.raw_text or ""

    for position in positions.values():
        if position._cost_weight > 0:
            per_kg = position._cost_weighted / position._cost_weight
            position.cost_per_mt = (per_kg * KG_PER_MT).quantize(Decimal("0.01"))
        position.in_stock_mt = position.in_stock_mt.quantize(Decimal("0.001"))
        position.committed_mt = position.committed_mt.quantize(Decimal("0.001"))
        position.prospective_mt = position.prospective_mt.quantize(Decimal("0.001"))
        position.locations.sort()

    # Shortfalls first: the rows that need a purchase decision are the reason
    # a trader opens this page, and they must not be below the fold.
    return sorted(
        positions.values(),
        key=lambda p: (-p.to_buy_mt, -p.committed_mt, p.grade or "", p.thickness_mm or 0),
    )


@dataclass(slots=True)
class StockTotals:
    """The desk-wide position, for the row of figures above the table."""

    in_stock_mt: Decimal = ZERO
    committed_mt: Decimal = ZERO
    free_mt: Decimal = ZERO
    to_buy_mt: Decimal = ZERO
    prospective_mt: Decimal = ZERO
    specs_short: int = 0


def totals(positions: list[SpecPosition]) -> StockTotals:
    """Roll the per-spec positions up.

    `free` and `to_buy` are summed from the per-spec figures rather than
    derived from the totals: 10 MT spare of one grade does not cover a 10 MT
    shortfall of another, and netting them off would report a desk as balanced
    while it was simultaneously overstocked and unable to deliver.
    """
    return StockTotals(
        in_stock_mt=sum((p.in_stock_mt for p in positions), ZERO),
        committed_mt=sum((p.committed_mt for p in positions), ZERO),
        free_mt=sum((p.free_mt for p in positions), ZERO),
        to_buy_mt=sum((p.to_buy_mt for p in positions), ZERO),
        prospective_mt=sum((p.prospective_mt for p in positions), ZERO),
        specs_short=sum(1 for p in positions if p.short),
    )


__all__ = ["SpecPosition", "StockTotals", "spec_positions", "totals"]
