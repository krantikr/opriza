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
    outcome: PricingOutcome
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
    ) -> PricingResult:
        """Price one line and persist the build-up.

        Existing overrides are re-applied by default: recomputing because stock
        moved should not silently discard a figure a human deliberately set.
        """
        quotation = quotation or item.quotation_request
        ctx = self.build_context(item, quotation, lot_ids=lot_ids)

        existing = self._existing_pricing(item)
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
        record = self._persist(item, outcome, ctx, existing=existing)
        return PricingResult(outcome=outcome, record=record)

    def build_context(
        self,
        item: QuotationLineItem,
        quotation: QuotationRequest | None,
        *,
        lot_ids: list[int] | None = None,
    ) -> PricingContext:
        """Assemble what the rules are allowed to see about this line."""
        customer: Customer | None = quotation.customer if quotation else None

        stock_cost = self._stock_cost_per_mt(item, lot_ids)
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
            origin_location=self._origin_location(item, lot_ids),
            payment_days=_payment_days(quotation, customer),
            stock_cost_per_mt=stock_cost,
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
    ) -> PricingResult:
        """Substitute one component's figure for this quotation only.

        The computed value is captured before recomputation, so the stored
        breakdown continues to show both what the rules said and what the
        reviewer decided.
        """
        pricing = self._existing_pricing(item)
        computed: Decimal | None = None
        if pricing is not None and pricing.components:
            for component in pricing.components:
                if component.get("code") == component_code:
                    raw = component.get("computed_amount") or component.get("amount")
                    computed = Decimal(str(raw)) if raw is not None else None
                    break

        # Ensure a pricing row exists to hang the override off.
        if pricing is None:
            pricing = self.price_line(item, keep_overrides=False).record

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
        return self.price_line(item, keep_overrides=True)

    def clear_override(self, item: QuotationLineItem, component_code: str) -> PricingResult:
        """Put a component back to whatever the rules currently say."""
        pricing = self._existing_pricing(item)
        if pricing is not None:
            self._delete_override(pricing.id, component_code)
        return self.price_line(item, keep_overrides=True)

    def _existing_pricing(self, item: QuotationLineItem) -> QuotationPricing | None:
        """The stored build-up for this line, read authoritatively.

        Queried rather than taken from `item.pricing`: the relationship is
        cached per session, and a row written earlier in the same request would
        otherwise look absent and be inserted twice.
        """
        return self.db.scalar(
            select(QuotationPricing).where(
                QuotationPricing.quotation_line_item_id == item.id
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
    ) -> QuotationPricing:
        record = existing or QuotationPricing(quotation_line_item_id=item.id)

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
        if previous_rate is not None and outcome.quote_rate != previous_rate:
            record.draft_stale = True

        if existing is None:
            self.db.add(record)
        self.db.flush()
        return record

    def _stock_cost_per_mt(self, item: QuotationLineItem, lot_ids: list[int] | None) -> Decimal | None:
        """Weighted-average landed cost across the matched lots, per MT."""
        ids = lot_ids or []
        if not ids and item.matched_stock_item_id:
            ids = [item.matched_stock_item_id]
        if not ids:
            return None

        lots = list(self.db.scalars(select(StockItem).where(StockItem.id.in_(ids))))
        weighted = [
            (Decimal(str(lot.landed_cost_per_kg)), Decimal(str(lot.balance_qty_kg or 0)))
            for lot in lots
            if lot.landed_cost_per_kg is not None and (lot.balance_qty_kg or 0) > 0
        ]
        if not weighted:
            return None

        total_weight = sum(w for _, w in weighted)
        if total_weight <= 0:
            return None
        avg_per_kg = sum(cost * w for cost, w in weighted) / total_weight
        return avg_per_kg * KG_PER_MT

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
