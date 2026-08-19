"""The stock-availability check (spec section 14, stock-pivot version).

No language model participates in any part of this file. Availability comes
from the stock list, not a price master, and the arithmetic is done here in
`Decimal`. `suggested_rate` is always a cost-plus suggestion - weighted-average
landed cost plus a configured markup - never an approved price; the owner
reviews or overrides it before anything sends.

Steps run in this order and each records its own reason, the same
self-documenting pattern the old pricing engine used - so "why did the system
say this?" is answerable from the stored `breakdown` alone:

    stock lookup -> locations -> ageing -> sufficiency -> suggested rate
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.rules import BusinessRules, RoundingRule, get_rules
from app.models import ConfidenceLevel, Customer, MatchStatus, QuantityUnit, StockItem
from app.services.stock.confidence import ConfidenceInputs, ConfidenceResult, assess

logger = get_logger(__name__)

CENT = Decimal("0.01")
KG_PER_MT = Decimal(1000)
QTY_QUANTUM = Decimal("0.001")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _qty(value: Decimal) -> Decimal:
    return value.quantize(QTY_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class AvailabilityStep:
    id: str
    label: str
    reason: str
    applied: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LocationBalance:
    location: str | None
    balance_qty_mt: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {"location": self.location, "balance_qty_mt": float(self.balance_qty_mt)}


@dataclass(slots=True)
class StockOutcome:
    matched: bool = False
    available_qty_mt: Decimal | None = None
    available_nop: float | None = None
    #: What is physically present, before reservations are deducted.
    on_hand_qty_mt: Decimal | None = None
    #: Spoken for by other quotations, so not free to promise.
    reserved_qty_mt: Decimal | None = None
    # None when the requested quantity is unknown - sufficiency was never judged.
    sufficient: bool | None = None
    locations: list[LocationBalance] = field(default_factory=list)
    ageing_min_days: int | None = None
    ageing_max_days: int | None = None
    lot_count: int = 0
    suggested_rate: Decimal | None = None
    currency: str = "INR"
    unit: QuantityUnit = QuantityUnit.MT
    stock_as_of: date | None = None

    steps: list[AvailabilityStep] = field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    requires_manual_review: bool = True
    review_reasons: list[str] = field(default_factory=list)
    confidence_reasons: list[str] = field(default_factory=list)
    rules_version: str = ""

    @property
    def explanation(self) -> str:
        lines = [s.reason for s in self.steps if s.applied]
        if self.review_reasons:
            lines.append("Manual review required: " + " ".join(self.review_reasons))
        return "\n".join(lines)

    def breakdown(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.steps]

    def locations_as_json(self) -> list[dict[str, Any]]:
        return [loc.to_dict() for loc in self.locations]


class StockAvailabilityService:
    def __init__(self, db: Session, rules: BusinessRules | None = None) -> None:
        self.db = db
        self.rules = rules or get_rules()

    def check(
        self,
        *,
        lot_ids: list[int],
        quantity_mt: Decimal | None,
        customer: Customer | None = None,
        match_status: MatchStatus = MatchStatus.MATCH_FOUND,
        has_missing_information: bool = False,
    ) -> StockOutcome:
        outcome = StockOutcome(currency=self.rules.currency, rules_version=self.rules.version)

        lots = (
            list(self.db.scalars(select(StockItem).where(StockItem.id.in_(lot_ids))))
            if lot_ids
            else []
        )
        outcome.matched = bool(lots)
        outcome.lot_count = len(lots)

        if not lots:
            outcome.steps.append(
                AvailabilityStep(
                    id="stock_lookup",
                    label="Stock lookup",
                    reason="No matching stock spec was found, so availability cannot be checked.",
                    applied=False,
                )
            )
            return self._finalise(outcome, match_status, has_missing_information, quantity_mt, customer)

        available_nop = sum((lot.balance_nop or 0) for lot in lots)

        # Movements recorded since the last import - receipts, issues and
        # reservations - are replayed on top. Quoting the imported figure alone
        # would promise material that has since been despatched or held.
        from app.services.stock.movements import StockMovementService

        balance = StockMovementService(self.db).balance_for_lots(lots)
        on_hand_mt = _qty(balance.on_hand_kg / KG_PER_MT)
        available_mt = _qty(balance.available_kg / KG_PER_MT)
        reserved_mt = _qty(balance.reserved_kg / KG_PER_MT)

        outcome.available_qty_mt = available_mt
        outcome.available_nop = available_nop
        outcome.reserved_qty_mt = reserved_mt
        outcome.on_hand_qty_mt = on_hand_mt

        movement_note = ""
        if balance.movement_kg:
            direction = "added" if balance.movement_kg > 0 else "removed"
            movement_note = (
                f" Movements since the last import {direction} "
                f"{abs(balance.movement_kg) / KG_PER_MT:g} MT."
            )
        reserved_note = (
            f" {reserved_mt:g} MT is reserved against other quotations and is not free to sell."
            if reserved_mt > 0
            else ""
        )

        outcome.steps.append(
            AvailabilityStep(
                id="stock_lookup",
                label="Stock lookup",
                reason=(
                    f"{len(lots)} stock lot(s) matched. Free to sell: "
                    f"{available_mt:g} MT of {on_hand_mt:g} MT on hand "
                    f"({available_nop:g} pcs).{movement_note}{reserved_note}"
                ),
            )
        )

        self._add_locations(lots, outcome)
        self._add_ageing(lots, outcome)
        self._add_sufficiency(quantity_mt, available_mt, outcome)

        stock_dates = [lot.curr_dt or lot.stock_date for lot in lots if (lot.curr_dt or lot.stock_date)]
        outcome.stock_as_of = max(stock_dates) if stock_dates else None

        outcome.suggested_rate = self._suggested_rate(lots, outcome)

        return self._finalise(outcome, match_status, has_missing_information, quantity_mt, customer)

    # --- Steps ------------------------------------------------------------

    @staticmethod
    def _add_locations(lots: list[StockItem], outcome: StockOutcome) -> None:
        by_location: dict[str | None, Decimal] = {}
        for lot in lots:
            kg = lot.balance_qty_kg or Decimal(0)
            by_location[lot.location] = by_location.get(lot.location, Decimal(0)) + kg
        outcome.locations = [
            LocationBalance(loc, _qty(kg / KG_PER_MT)) for loc, kg in by_location.items()
        ]
        text = ", ".join(
            f"{loc.location or 'unspecified location'}: {loc.balance_qty_mt:g} MT"
            for loc in outcome.locations
        )
        outcome.steps.append(
            AvailabilityStep(id="locations", label="Locations", reason=f"By location - {text}.")
        )

    @staticmethod
    def _add_ageing(lots: list[StockItem], outcome: StockOutcome) -> None:
        values = [lot.ageing_days for lot in lots if lot.ageing_days is not None]
        if not values:
            outcome.steps.append(
                AvailabilityStep(
                    id="ageing",
                    label="Ageing",
                    reason="Ageing is not recorded for the matched lots.",
                    applied=False,
                )
            )
            return
        outcome.ageing_min_days = min(values)
        outcome.ageing_max_days = max(values)
        span = (
            f"{outcome.ageing_min_days} days"
            if outcome.ageing_min_days == outcome.ageing_max_days
            else f"{outcome.ageing_min_days}-{outcome.ageing_max_days} days"
        )
        outcome.steps.append(AvailabilityStep(id="ageing", label="Ageing", reason=f"In stock {span}."))

    @staticmethod
    def _add_sufficiency(
        quantity_mt: Decimal | None, available_mt: Decimal, outcome: StockOutcome
    ) -> None:
        if quantity_mt is None:
            outcome.sufficient = None
            outcome.steps.append(
                AvailabilityStep(
                    id="sufficiency",
                    label="Sufficiency",
                    reason="Requested quantity is unknown, so sufficiency cannot be judged.",
                    applied=False,
                )
            )
            return
        outcome.sufficient = available_mt >= quantity_mt
        verdict = "meets" if outcome.sufficient else "falls short of"
        outcome.steps.append(
            AvailabilityStep(
                id="sufficiency",
                label="Sufficiency",
                reason=(
                    f"Available balance of {available_mt:g} MT {verdict} the requested "
                    f"{quantity_mt:g} MT."
                ),
            )
        )

    def _suggested_rate(self, lots: list[StockItem], outcome: StockOutcome) -> Decimal | None:
        rule = self.rules.stock_pricing
        if not rule.enabled:
            return None

        weighted = [
            (lot.landed_cost_per_kg, float(lot.balance_qty_kg or 0))
            for lot in lots
            if lot.landed_cost_per_kg is not None and (lot.balance_qty_kg or 0) > 0
        ]
        if not weighted:
            outcome.steps.append(
                AvailabilityStep(
                    id="suggested_rate",
                    label="Suggested rate",
                    reason="No landed cost is recorded for the matched stock, so no rate can be suggested.",
                    applied=False,
                )
            )
            return None

        total_weight = sum(w for _, w in weighted)
        avg_cost_per_kg = sum(cost * w for cost, w in weighted) / total_weight
        cost_per_mt = Decimal(str(avg_cost_per_kg)) * KG_PER_MT
        marked_up = cost_per_mt * (Decimal(1) + Decimal(str(rule.markup_pct)) / Decimal(100))
        rounded = self._round(marked_up, rule.rounding)

        outcome.steps.append(
            AvailabilityStep(
                id="suggested_rate",
                label="Suggested rate",
                reason=(
                    f"Weighted-average landed cost {outcome.currency} {cost_per_mt:,.2f}/MT plus "
                    f"{rule.markup_pct:g}% markup: {outcome.currency} {rounded:,.2f}/MT "
                    "(indicative - subject to confirmation, not an approved price)."
                ),
            )
        )
        return rounded

    @staticmethod
    def _round(price: Decimal, rule: RoundingRule) -> Decimal:
        if not rule.enabled or rule.nearest <= 0:
            return _money(price)
        nearest = Decimal(rule.nearest)
        modes = {"up": ROUND_CEILING, "down": ROUND_FLOOR, "nearest": ROUND_HALF_UP}
        rounding = modes.get(rule.mode, ROUND_HALF_UP)
        return (price / nearest).quantize(Decimal(1), rounding=rounding) * nearest

    # --- Verdict ------------------------------------------------------------

    def _finalise(
        self,
        outcome: StockOutcome,
        match_status: MatchStatus,
        has_missing_information: bool,
        quantity_mt: Decimal | None,
        customer: Customer | None,
    ) -> StockOutcome:
        verdict: ConfidenceResult = assess(
            ConfidenceInputs(
                match_status=match_status,
                stock_found=outcome.matched,
                lot_count=outcome.lot_count,
                # "Known" means confirmed, not merely present. The workflow
                # auto-creates a customer for any new sender, so linkage alone
                # would hand a first-time enquiry the HIGH confidence that is
                # meant to be earned by being an established account.
                customer_known=customer is not None and customer.is_verified,
                quantity_known=quantity_mt is not None,
                has_missing_information=has_missing_information,
                sufficient=outcome.sufficient,
            ),
            self.rules,
        )
        outcome.confidence = verdict.level
        outcome.confidence_reasons = verdict.reasons
        outcome.requires_manual_review = verdict.requires_manual_review
        outcome.review_reasons = verdict.review_reasons
        return outcome
