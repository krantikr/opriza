"""Pricing one quotation line: gather the facts, run the rules, store the result.

This is the seam between the workflow and the engine. It knows about the ORM;
the engine does not. Keeping that boundary means the arithmetic stays testable
without a database, and the rules cannot quietly depend on something the
enquiry did not actually state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import (
    Customer,
    MillOffer,
    PricingBasis,
    PricingOverride,
    PricingRuleSet,
    QuotationLineItem,
    QuotationPricing,
    QuotationRequest,
    StockItem,
)
from app.services.pricing.components import PricingContext
from app.services.pricing.engine import PricingEngine, PricingOutcome, active_rule_set

logger = get_logger(__name__)

KG_PER_MT = Decimal(1000)


@dataclass(slots=True)
class PricingResult:
    #: `None` for a manual pricing option - there is no rule engine outcome
    #: behind a build-up the trader typed in by hand.
    outcome: PricingOutcome | None
    record: QuotationPricing


class PricingService:
    def __init__(self, db: Session, rule_set: PricingRuleSet | None = None) -> None:
        self.db = db
        self.rule_set = rule_set or active_rule_set(db)
        self.engine = PricingEngine(db, self.rule_set)

    # --- Public -----------------------------------------------------------

    def price_line(
        self,
        item: QuotationLineItem,
        *,
        quotation: QuotationRequest | None = None,
        lot_ids: list[int] | None = None,
        keep_overrides: bool = True,
        despatch_location: str | None = None,
    ) -> PricingResult:
        """Price one line and persist the build-up.

        Existing overrides are re-applied by default: recomputing because stock
        moved should not silently discard a figure a human deliberately set.

        `despatch_location` targets one specific pricing option when a line
        has more than one (comparing sourcing from different warehouses).
        Omitted, it means what it always meant: the line's one build-up.
        """
        quotation = quotation or item.quotation_request
        ctx = self.build_context(item, quotation, lot_ids=lot_ids, despatch_location=despatch_location)

        existing = self._existing_pricing(item, despatch_location)
        overrides: dict[str, Decimal] = {}
        if keep_overrides and existing is not None:
            overrides = {
                row.component_code: row.override_amount
                for row in self.db.scalars(
                    select(PricingOverride).where(
                        PricingOverride.quotation_pricing_id == existing.id
                    )
                )
            }

        outcome = self.engine.price(ctx, overrides=overrides)
        record = self._persist(
            item, outcome, ctx, existing=existing, despatch_location=despatch_location
        )
        return PricingResult(outcome=outcome, record=record)

    def build_context(
        self,
        item: QuotationLineItem,
        quotation: QuotationRequest | None,
        *,
        lot_ids: list[int] | None = None,
        despatch_location: str | None = None,
    ) -> PricingContext:
        """Assemble what the rules are allowed to see about this line.

        `despatch_location` narrows the stock lookup to lots at that one
        warehouse - comparing "priced from Jamshedpur" against "priced from
        Varanasi" requires each option to see only its own location's stock,
        not the item's matched lot everywhere it happens to sit.
        """
        customer: Customer | None = quotation.customer if quotation else None

        self._stock_cost_basis = "LANDED_COST"
        stock_cost = self._stock_cost_per_mt(item, lot_ids, despatch_location)
        offer = self._mill_offer(item) if stock_cost is None else None

        return PricingContext(
            db=self.db,
            quantity_mt=item.quantity_mt,
            product_type=item.product_type,
            grade=item.grade,
            thickness_mm=item.thickness_mm,
            width_mm=item.width_mm,
            length_mm=item.length_mm,
            diameter_mm=item.diameter_mm,
            customer=customer,
            customer_tier=customer.tier.value if customer else None,
            delivery_location=(quotation.delivery_location if quotation else None)
            or (customer.default_delivery_location if customer else None),
            origin_location=despatch_location or self._origin_location(item, lot_ids),
            payment_days=_payment_days(quotation, customer),
            stock_cost_per_mt=stock_cost,
            stock_cost_basis=self._stock_cost_basis,
            mill_offer_per_mt=Decimal(str(offer.rate_per_mt)) if offer else None,
            mill_offer_supplier=offer.supplier if offer else None,
        )

    def set_override(
        self,
        item: QuotationLineItem,
        *,
        component_code: str,
        amount: Decimal,
        user_id: int | None = None,
        reason: str | None = None,
        despatch_location: str | None = None,
    ) -> PricingResult:
        """Substitute one component's figure for this quotation only.

        The computed value is captured before recomputation, so the stored
        breakdown continues to show both what the rules said and what the
        reviewer decided.
        """
        pricing = self._existing_pricing(item, despatch_location)
        computed: Decimal | None = None
        if pricing is not None and pricing.components:
            for component in pricing.components:
                if component.get("code") == component_code:
                    raw = component.get("computed_amount") or component.get("amount")
                    computed = Decimal(str(raw)) if raw is not None else None
                    break

        # Ensure a pricing row exists to hang the override off.
        if pricing is None:
            pricing = self.price_line(
                item, keep_overrides=False, despatch_location=despatch_location
            ).record

        self._delete_override(pricing.id, component_code)
        self.db.add(
            PricingOverride(
                quotation_pricing_id=pricing.id,
                user_id=user_id,
                component_code=component_code,
                computed_amount=computed,
                override_amount=amount,
                reason=reason,
            )
        )
        self.db.flush()

        if pricing.is_manual:
            # A manual option has no engine build-up to recompute - just
            # re-read the override straight onto the stored component so the
            # figure the trader typed is what the row shows.
            return self._apply_manual_override(pricing, component_code, amount)
        return self.price_line(item, keep_overrides=True, despatch_location=despatch_location)

    def clear_override(
        self,
        item: QuotationLineItem,
        component_code: str,
        *,
        despatch_location: str | None = None,
    ) -> PricingResult:
        """Put a component back to whatever the rules currently say."""
        pricing = self._existing_pricing(item, despatch_location)
        if pricing is not None:
            self._delete_override(pricing.id, component_code)
        if pricing is not None and pricing.is_manual:
            return PricingResult(outcome=None, record=pricing)
        return self.price_line(item, keep_overrides=True, despatch_location=despatch_location)

    def select_option(self, item: QuotationLineItem, pricing_id: int) -> QuotationPricing:
        """Make one pricing option the line's selected price.

        This is what `item.pricing` resolves to afterwards, and therefore
        what the draft, the PDF and every report read. Callers must check
        `PRICING_FROZEN_STATUSES` themselves before calling this, the same
        way every other pricing write already does - the freeze is an API
        concern (`_require_unsent` in the route layer), not this service's.
        """
        target = next((p for p in item.pricing_options if p.id == pricing_id), None)
        if target is None:
            raise ValueError(f"Pricing option {pricing_id} does not belong to this line")
        for option in item.pricing_options:
            option.is_selected = option.id == pricing_id
        self.db.flush()
        return target

    def add_manual_option(
        self, item: QuotationLineItem, despatch_location: str
    ) -> QuotationPricing:
        """Start a hand-priced option for a location with no matched stock -
        the "Other" choice. Empty until the trader fills it in via
        `set_override`; nothing here runs the rule engine."""
        record = QuotationPricing(
            despatch_location=despatch_location,
            is_manual=True,
            is_selected=not item.pricing_options,
            basis=PricingBasis.MANUAL,
            currency="INR",
            quantity_mt=item.quantity_mt,
            components=[],
        )
        # Appended, not just given the FK - see the matching comment in
        # `_persist` for why that matters within a single session.
        item.pricing_options.append(record)
        self.db.flush()
        return record

    def known_locations(self) -> list[str]:
        """Every distinct warehouse location on file, for the "+" picker.

        There is no canonical location list anywhere in this system -
        locations are free text from whatever the last stock import
        contained - so this is the only honest source of "known" ones.
        """
        rows = self.db.scalars(
            select(StockItem.location)
            .where(StockItem.location.is_not(None))
            .distinct()
            .order_by(StockItem.location)
        )
        return [loc for loc in rows if loc]

    def _apply_manual_override(
        self, pricing: QuotationPricing, component_code: str, amount: Decimal
    ) -> PricingResult:
        """Write one component's amount directly onto a manual option's
        stored build-up, with no rule engine involved at all."""
        components = list(pricing.components or [])
        found = False
        for component in components:
            if component.get("code") == component_code:
                component["amount"] = str(amount)
                component["overridden"] = True
                found = True
                break
        if not found:
            components.append(
                {
                    "code": component_code,
                    "label": component_code.replace("_", " ").title(),
                    "kind": "MANUAL",
                    "amount": str(amount),
                    "note": "Entered by hand.",
                    "overridden": True,
                    "computed_amount": None,
                }
            )
        pricing.components = components
        pricing.has_overrides = True
        pricing.quote_rate = sum(
            (Decimal(str(c["amount"])) for c in components), Decimal(0)
        )
        pricing.line_total = (
            pricing.quote_rate * pricing.quantity_mt if pricing.quantity_mt else None
        )
        self.db.flush()
        return PricingResult(outcome=None, record=pricing)

    def _existing_pricing(
        self, item: QuotationLineItem, despatch_location: str | None = None
    ) -> QuotationPricing | None:
        """The stored build-up for this line, read authoritatively.

        Queried rather than taken from `item.pricing`: the relationship is
        cached per session, and a row written earlier in the same request would
        otherwise look absent and be inserted twice.

        `despatch_location` picks out one specific option among several; the
        default `None` matches the line's original, unlabelled option - the
        same row `item.pricing` still resolves to when nothing else was added.
        """
        return self.db.scalar(
            select(QuotationPricing).where(
                QuotationPricing.quotation_line_item_id == item.id,
                QuotationPricing.despatch_location == despatch_location,
            )
        )

    def _delete_override(self, pricing_id: int, component_code: str) -> None:
        for row in self.db.scalars(
            select(PricingOverride).where(
                PricingOverride.quotation_pricing_id == pricing_id,
                PricingOverride.component_code == component_code,
            )
        ):
            self.db.delete(row)
        self.db.flush()

    # --- Internals --------------------------------------------------------

    def _persist(
        self,
        item: QuotationLineItem,
        outcome: PricingOutcome,
        ctx: PricingContext,
        *,
        existing: QuotationPricing | None,
        despatch_location: str | None = None,
    ) -> QuotationPricing:
        if existing is not None:
            record = existing
        else:
            record = QuotationPricing(
                despatch_location=despatch_location,
                # The first option a line gets is selected by default -
                # there is nothing to compare it against yet. A second or
                # third option added later starts unselected until the
                # trader picks it; see `select_option`.
                is_selected=not item.pricing_options,
            )
            # Appended to the relationship, not just given the FK: `item` may
            # already have `pricing_options` loaded in this session (e.g. the
            # `is_selected` check just above touched it), and setting only
            # `quotation_line_item_id` would leave that cached collection out
            # of sync with what the database now holds - `item.pricing`
            # would then read an empty list until the next fresh query,
            # rather than the row just created.
            item.pricing_options.append(record)

        previous_rate = record.quote_rate if existing is not None else None

        record.rule_set_id = outcome.rule_set_id
        record.rules_version = outcome.rules_version
        record.basis = outcome.basis
        record.basis_note = outcome.basis_note
        record.base_rate = outcome.base_rate
        record.total_cost = outcome.total_cost
        record.margin_amount = outcome.margin_amount
        record.quote_rate = outcome.quote_rate
        record.line_total = outcome.line_total
        record.currency = outcome.currency
        record.quantity_mt = ctx.quantity_mt
        record.components = outcome.components_as_json()
        record.explanation = outcome.explanation
        record.warnings = outcome.warnings or None
        record.has_overrides = any(c.overridden for c in outcome.components)

        # A draft written against a figure that has since moved must not be
        # sent as though it still matched. The reviewer is told, and the
        # drafting service regenerates rather than the change passing silently.
        #
        # `existing is not None` rather than `previous_rate is not None`: a line
        # that could not be priced at all has no previous rate, and going from
        # no price to a price is the largest change there is - guarding on the
        # old rate meant exactly that case never raised the warning, so a draft
        # saying "no rate available" could be sent over a line that now has one.
        if existing is not None and outcome.quote_rate != previous_rate:
            record.draft_stale = True

        self.db.flush()
        return record

    def _stock_cost_per_mt(
        self,
        item: QuotationLineItem,
        lot_ids: list[int] | None,
        despatch_location: str | None = None,
    ) -> Decimal | None:
        """Weighted-average cost across the matched lots, per MT.

        Landed cost is preferred because it is what the material actually cost
        to have on the floor - purchase rate plus freight and duty. But a stock
        sheet that carries only a purchase rate is ordinary, and refusing to
        price from it leaves a line reading "no base price available" while the
        floor plainly holds the material at a known cost. So purchase rate is
        the fallback, per lot, and `stock_cost_basis` records which was used so
        the note on the screen can say so rather than implying a landed figure.
        """
        ids = lot_ids or []
        if not ids and item.matched_stock_item_id:
            # `matched_stock_item_id` names one representative lot, chosen by
            # freshest ageing for display - not by which lot has cost data.
            # Several lots commonly share a spec (see `StockItem`'s own
            # docstring), so a caller that didn't thread the matcher's full
            # `lot_ids` through must not price off that one lot alone: if it
            # happens to carry no cost, a sibling lot with real cost and stock
            # gets silently ignored and the line reads "unavailable" despite
            # the floor plainly holding the material at a known price.
            #
            # A specific despatch location narrows this further: comparing
            # "priced from Jamshedpur" against "priced from Varanasi" means
            # each option must see only its own warehouse's lots.
            ids = self._sibling_lot_ids(item.matched_stock_item_id, despatch_location)
        if not ids:
            return None

        lots = list(self.db.scalars(select(StockItem).where(StockItem.id.in_(ids))))
        weighted: list[tuple[Decimal, Decimal]] = []
        used_purchase_rate = False
        for lot in lots:
            balance = Decimal(str(lot.balance_qty_kg or 0))
            if balance <= 0:
                continue
            if lot.landed_cost_per_kg is not None:
                weighted.append((Decimal(str(lot.landed_cost_per_kg)), balance))
            elif lot.purchase_rate_per_kg is not None:
                weighted.append((Decimal(str(lot.purchase_rate_per_kg)), balance))
                used_purchase_rate = True

        if not weighted:
            return None

        self._stock_cost_basis = "PURCHASE_RATE" if used_purchase_rate else "LANDED_COST"

        total_weight = sum(w for _, w in weighted)
        if total_weight <= 0:
            return None
        avg_per_kg = sum(cost * w for cost, w in weighted) / total_weight
        return avg_per_kg * KG_PER_MT

    def _sibling_lot_ids(
        self, stock_item_id: int, despatch_location: str | None = None
    ) -> list[int]:
        """Every lot sharing this one's spec (product type, grade, dimensions).

        `matched_stock_item_id` names a single representative lot; several
        lots commonly share a spec at different ages, locations or costs
        (see `StockItem`'s own docstring). Pricing has to see all of them,
        the same way `StockAvailabilityService` already does, or a lot with
        no cost on file can shadow a sibling that has one.

        `despatch_location`, when given, narrows this to lots at that one
        warehouse - a location-specific pricing option must not blend in
        cost from a different warehouse's stock.
        """
        lot = self.db.get(StockItem, stock_item_id)
        if lot is None:
            return [stock_item_id]
        query = select(StockItem.id).where(
            StockItem.product_type == lot.product_type,
            StockItem.grade == lot.grade,
            StockItem.thickness_mm == lot.thickness_mm,
            StockItem.width_mm == lot.width_mm,
            StockItem.length_mm == lot.length_mm,
        )
        if despatch_location:
            query = query.where(StockItem.location == despatch_location)
        return list(self.db.scalars(query))

    def _origin_location(self, item: QuotationLineItem, lot_ids: list[int] | None) -> str | None:
        ids = lot_ids or ([item.matched_stock_item_id] if item.matched_stock_item_id else [])
        if not ids:
            return None
        lot = self.db.scalar(select(StockItem).where(StockItem.id.in_(ids)))
        return lot.location if lot else None

    def _mill_offer(self, item: QuotationLineItem) -> MillOffer | None:
        """The current offer for this material, if one is on file.

        Effective-dated: an expired offer is never used, the same way an
        expired price never was.
        """
        today = date.today()
        query = select(MillOffer).where(
            or_(MillOffer.effective_from.is_(None), MillOffer.effective_from <= today),
            or_(MillOffer.effective_to.is_(None), MillOffer.effective_to >= today),
        )
        if item.product_type:
            query = query.where(MillOffer.product_type == item.product_type)
        if item.grade:
            query = query.where(MillOffer.grade == item.grade)
        if item.thickness_mm is not None:
            query = query.where(
                or_(MillOffer.thickness_mm.is_(None), MillOffer.thickness_mm == item.thickness_mm)
            )
        return self.db.scalar(query.order_by(MillOffer.effective_from.desc().nullslast()))


def _payment_days(quotation: QuotationRequest | None, customer: Customer | None) -> int | None:
    """Credit period in days, read from stated terms where possible."""
    import re

    for text in (
        quotation.payment_terms if quotation else None,
        customer.payment_terms if customer else None,
    ):
        if not text:
            continue
        match = re.search(r"(\d{1,3})\s*days?", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


__all__ = ["PricingService", "PricingResult"]
