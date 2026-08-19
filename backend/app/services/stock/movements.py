"""Goods in, goods out, and reservations against quoted material.

The design point worth understanding: the stock import **replaces the whole
table**, because the client's spreadsheet is a full point-in-time snapshot with
no natural key to upsert on. If a receipt or a reservation mutated
`StockItem.balance_qty_kg`, the next import would silently erase it.

So movements are stored separately and applied *on top of* the imported
balance. `effective_balance` is what the rest of the application should ask
for; `StockItem.balance_qty_kg` alone is only ever "what the sheet said".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import (
    QuotationRequest,
    StockItem,
    StockMovement,
    StockMovementKind,
)
from app.services import audit

logger = get_logger(__name__)

KG_PER_MT = Decimal(1000)

#: Kinds that reduce what is available to promise. A reservation is not a
#: despatch - the material is still on the floor - but it is spoken for, and
#: quoting it twice is how a desk over-commits.
COMMITTING = (StockMovementKind.ISSUE, StockMovementKind.RESERVATION)

#: Kinds that hold material back without moving it. Both reduce what may be
#: promised; neither changes what is physically on the floor.
HOLDING = (StockMovementKind.RESERVATION, StockMovementKind.BLOCK)


@dataclass(slots=True)
class Balance:
    """What is physically present, and what is actually free to sell."""

    imported_kg: Decimal
    movement_kg: Decimal
    reserved_kg: Decimal

    @property
    def on_hand_kg(self) -> Decimal:
        return self.imported_kg + self.movement_kg

    @property
    def available_kg(self) -> Decimal:
        return self.on_hand_kg - self.reserved_kg

    @property
    def on_hand_mt(self) -> Decimal:
        return self.on_hand_kg / KG_PER_MT

    @property
    def available_mt(self) -> Decimal:
        return self.available_kg / KG_PER_MT


class StockMovementService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Public -----------------------------------------------------------

    def record(
        self,
        *,
        kind: StockMovementKind,
        quantity_kg: Decimal,
        stock_item: StockItem | None = None,
        nop: float | None = None,
        location: str | None = None,
        rate_per_kg: Decimal | None = None,
        reference: str | None = None,
        note: str | None = None,
        movement_date: date | None = None,
        quotation: QuotationRequest | None = None,
        user_id: int | None = None,
        spec: dict | None = None,
    ) -> StockMovement:
        """Record one movement.

        The spec is denormalised onto the row so the movement survives the
        wholesale re-import that will replace the `stock_items` row it points
        at. A receipt recorded in March must still apply after April's sheet
        lands.
        """
        signed = self._sign(kind, quantity_kg)
        source = spec or _spec_of(stock_item)

        movement = StockMovement(
            stock_item_id=stock_item.id if stock_item else None,
            user_id=user_id,
            kind=kind,
            quantity_kg=signed,
            nop=nop,
            location=location or (stock_item.location if stock_item else None),
            rate_per_kg=rate_per_kg,
            reference=reference,
            note=note,
            movement_date=movement_date or date.today(),
            quotation_request_id=quotation.id if quotation else None,
            is_open=True,
            **source,
        )
        self.db.add(movement)
        self.db.flush()

        audit.record(
            self.db,
            entity_type="stock_movement",
            entity_id=movement.id,
            action=f"STOCK_{kind.value}",
            user_id=user_id,
            details={
                "quantity_kg": str(signed),
                "location": movement.location,
                "reference": reference,
                "quotation": quotation.quotation_number if quotation else None,
            },
        )
        self.db.commit()
        logger.info("Stock %s of %s kg recorded", kind.value, signed)
        return movement

    def reserve_for(
        self, quotation: QuotationRequest, *, user_id: int | None = None
    ) -> list[StockMovement]:
        """Hold the material a customer has accepted.

        Called when a quotation is accepted, so the same tonnage is not quoted
        to somebody else while the paperwork is being done.
        """
        movements: list[StockMovement] = []
        for item in quotation.line_items:
            if item.quantity_mt is None or item.matched_stock_item_id is None:
                continue
            lot = self.db.get(StockItem, item.matched_stock_item_id)
            movements.append(
                self.record(
                    kind=StockMovementKind.RESERVATION,
                    quantity_kg=item.quantity_mt * KG_PER_MT,
                    stock_item=lot,
                    reference=quotation.quotation_number,
                    note=f"Reserved against {quotation.quotation_number}",
                    quotation=quotation,
                    user_id=user_id,
                )
            )
        return movements

    def lift_hold(self, movement_id: int, reason: str = "Lifted by a reviewer.") -> bool:
        """Release one open block or reservation, freeing the tonnage again."""
        movement = self.db.get(StockMovement, movement_id)
        if movement is None or not movement.is_open or movement.kind not in HOLDING:
            return False
        movement.is_open = False
        movement.note = f"{movement.note or ''} {reason}".strip()
        audit.record(
            self.db,
            entity_type="stock_movement",
            entity_id=movement.id,
            action="STOCK_HOLD_LIFTED",
            details={"kind": movement.kind.value, "quantity_kg": str(movement.quantity_kg)},
        )
        self.db.commit()
        return True

    def release_for(self, quotation: QuotationRequest, reason: str) -> int:
        """Give reserved material back - the deal fell through."""
        open_reservations = list(
            self.db.scalars(
                select(StockMovement).where(
                    StockMovement.quotation_request_id == quotation.id,
                    StockMovement.kind == StockMovementKind.RESERVATION,
                    StockMovement.is_open.is_(True),
                )
            )
        )
        for movement in open_reservations:
            movement.is_open = False
            movement.note = f"{movement.note or ''} Released: {reason}".strip()
        if open_reservations:
            self.db.commit()
        return len(open_reservations)

    def balance_for_spec(self, spec: dict) -> Balance:
        """Imported balance plus movements, for one product spec."""
        imported = Decimal(0)
        for lot in self.db.scalars(_spec_query(select(StockItem), spec, StockItem)):
            imported += lot.balance_qty_kg or Decimal(0)

        movement_kg = Decimal(0)
        reserved_kg = Decimal(0)
        for movement in self.db.scalars(
            _spec_query(select(StockMovement), spec, StockMovement)
        ):
            if movement.kind in HOLDING:
                # Held, not moved: it stays in `on_hand` and comes out of
                # `available` only while the hold is open.
                if movement.is_open:
                    reserved_kg += abs(movement.quantity_kg)
                continue
            if movement.kind is StockMovementKind.RELEASE:
                continue
            movement_kg += movement.quantity_kg

        return Balance(imported_kg=imported, movement_kg=movement_kg, reserved_kg=reserved_kg)

    def balance_for_lots(self, lots: list[StockItem]) -> Balance:
        """Imported balance plus movements, across a matched group of lots."""
        if not lots:
            return Balance(Decimal(0), Decimal(0), Decimal(0))
        return self.balance_for_spec(_spec_of(lots[0]))

    def history(self, *, limit: int = 100) -> list[StockMovement]:
        return list(
            self.db.scalars(
                select(StockMovement).order_by(StockMovement.created_at.desc()).limit(limit)
            )
        )

    # --- Internals --------------------------------------------------------

    @staticmethod
    def _sign(kind: StockMovementKind, quantity_kg: Decimal) -> Decimal:
        """Normalise direction so callers cannot get the sign wrong.

        A receipt always adds and an issue always removes, whatever sign the
        caller passed - which stops a mistyped minus from inflating stock.
        """
        magnitude = abs(quantity_kg)
        if kind is StockMovementKind.ISSUE:
            return -magnitude
        if kind is StockMovementKind.ADJUSTMENT:
            # The only kind whose direction the caller genuinely decides: a
            # stocktake correction can go either way.
            return quantity_kg
        return magnitude


def _spec_of(lot: StockItem | None) -> dict:
    if lot is None:
        return {}
    return {
        "product_type": lot.product_type,
        "grade": lot.grade,
        "thickness_mm": lot.thickness_mm,
        "width_mm": lot.width_mm,
        "length_mm": lot.length_mm,
        "diameter_mm": lot.diameter_mm,
    }


def _spec_query(query, spec: dict, model):
    for field_name in ("product_type", "grade", "thickness_mm", "width_mm", "length_mm", "diameter_mm"):
        value = spec.get(field_name)
        column = getattr(model, field_name)
        query = query.where(column.is_(None) if value is None else column == value)
    return query


__all__ = ["StockMovementService", "Balance"]
