"""Running a rule set over one enquiry line to produce a quotable rate.

The engine's job is narrow on purpose: resolve which rules apply, run them in
order, carry the running total, and record what each one contributed. All the
arithmetic lives in `components.py`; all the authority over which rules exist
lives with the trader. Nothing here decides a commercial figure on its own.

Two properties are worth stating because they are enforced structurally:

* **A component that cannot answer stands aside.** It returns `applied=False`
  with the reason, and the reason is kept. An unpriceable line reads as "no
  base price available", never as a plausible-looking number.
* **Overrides never overwrite the computed figure.** They sit beside it, and
  both are stored, so the breakdown continues to explain itself afterwards.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import (
    PricingBasis,
    PricingComponentKind,
    PricingRule,
    PricingRuleSet,
)
from app.services.pricing.components import (
    COMPONENTS,
    NO_BASE_PRICE,
    PricingContext,
    money,
)

logger = get_logger(__name__)

#: Kinds that act on the finished cost rather than adding to it. They are
#: forced to run after every cost line regardless of configured priority, so a
#: mis-ordered rule set cannot apply margin to a partial cost.
TERMINAL_ORDER = {
    PricingComponentKind.TARGET_MARGIN: 1,
    PricingComponentKind.MARGIN_FLOOR: 2,
    PricingComponentKind.ROUNDING: 3,
}


@dataclass(slots=True)
class ComponentLine:
    """One row of the stored build-up."""

    code: str
    label: str
    kind: str
    amount: Decimal
    note: str
    applied: bool = True
    overridden: bool = False
    computed_amount: Decimal | None = None
    subtotal: Decimal | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("amount", "computed_amount", "subtotal"):
            if data[key] is not None:
                data[key] = str(data[key])
        return data


@dataclass(slots=True)
class PricingOutcome:
    """The finished build-up for one line."""

    basis: PricingBasis = PricingBasis.UNAVAILABLE
    basis_note: str | None = None
    base_rate: Decimal | None = None
    total_cost: Decimal | None = None
    margin_amount: Decimal | None = None
    quote_rate: Decimal | None = None
    line_total: Decimal | None = None
    currency: str = "INR"
    rules_version: int | None = None
    rule_set_id: int | None = None
    components: list[ComponentLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def priced(self) -> bool:
        return self.quote_rate is not None

    def components_as_json(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self.components]

    @property
    def explanation(self) -> str:
        return "\n".join(c.note for c in self.components if c.note)


def active_rule_set(db: Session) -> PricingRuleSet | None:
    return db.scalar(select(PricingRuleSet).where(PricingRuleSet.is_active.is_(True)))


class PricingEngine:
    """Evaluates a rule set against one enquiry line."""

    def __init__(self, db: Session, rule_set: PricingRuleSet | None = None) -> None:
        self.db = db
        self.rule_set = rule_set or active_rule_set(db)

    # --- Public -----------------------------------------------------------

    def price(
        self,
        ctx: PricingContext,
        *,
        overrides: dict[str, Decimal] | None = None,
    ) -> PricingOutcome:
        """Run the active rules over one line.

        `overrides` maps a rule code to the figure a human substituted for it.
        The computed value is kept alongside so the stored breakdown still
        shows what the rules produced.
        """
        ctx.db = ctx.db or self.db
        overrides = overrides or {}
        outcome = PricingOutcome()

        if self.rule_set is None:
            outcome.warnings.append("No pricing rule set is published.")
            outcome.components.append(
                ComponentLine(
                    code="no_rules",
                    label="Pricing rules",
                    kind="NONE",
                    amount=Decimal(0),
                    note="No pricing rule set is published, so no rate can be suggested.",
                    applied=False,
                )
            )
            return outcome

        outcome.rule_set_id = self.rule_set.id
        outcome.rules_version = self.rule_set.version

        running = Decimal(0)
        base = Decimal(0)
        cost_before_margin: Decimal | None = None
        margin_total = Decimal(0)

        for rule in self._ordered_rules(ctx):
            component = COMPONENTS.get(rule.kind)
            if component is None:  # pragma: no cover - guarded by the enum
                logger.warning("No component registered for %s", rule.kind)
                continue

            result = component(rule.config or {}, ctx, running, base)

            computed = money(result.amount)
            amount = computed
            overridden = False
            if rule.code in overrides:
                amount = money(overrides[rule.code])
                overridden = True

            # The margin is the boundary: everything before it is cost.
            if rule.kind is PricingComponentKind.TARGET_MARGIN and cost_before_margin is None:
                cost_before_margin = running

            if result.applied or overridden:
                if result.replaces_total is not None and not overridden:
                    running = money(result.replaces_total)
                else:
                    running = money(running + amount)

                if rule.kind is PricingComponentKind.BASE_PRICE:
                    base = running
                    outcome.base_rate = running
                    # A component that stood aside reports UNAVAILABLE. When a
                    # reviewer has supplied the figure, the basis is the person,
                    # not the absent source - otherwise the line carries a rate
                    # while still labelled as having none.
                    basis = (
                        PricingBasis.MANUAL.value
                        if overridden
                        else result.meta.get("basis")
                    )
                    if basis in {b.value for b in PricingBasis}:
                        outcome.basis = PricingBasis(basis)
                    outcome.basis_note = result.note
                elif rule.kind in {
                    PricingComponentKind.TARGET_MARGIN,
                    PricingComponentKind.MARGIN_FLOOR,
                }:
                    margin_total = money(margin_total + amount)

            note = result.note
            if overridden:
                # Both figures are stated, so the override is visible as an
                # override rather than passing for what the rules produced.
                note = (
                    f"Overridden by a reviewer: INR {amount:,.2f} per MT "
                    f"(calculated: INR {computed:,.2f}). {result.note}"
                ).strip()

            outcome.components.append(
                ComponentLine(
                    code=rule.code,
                    label=rule.label,
                    kind=rule.kind.value,
                    amount=amount,
                    note=note,
                    applied=result.applied or overridden,
                    overridden=overridden,
                    computed_amount=computed if overridden else None,
                    subtotal=running if (result.applied or overridden) else None,
                    meta=result.meta,
                )
            )

            # A component's warning describes why *it* could not produce a
            # figure. Overriding it is the reviewer supplying that figure by
            # hand, so the complaint has been answered: repeating it leaves the
            # screen saying "No base price available" directly above the base
            # price the reviewer just typed in.
            if result.warning and not overridden:
                outcome.warnings.append(result.warning)

        if outcome.base_rate is None:
            # The base-price component reports its own reason for standing
            # aside. This is the backstop for the case where no base rule ran
            # at all, so it must not restate a warning already recorded.
            if NO_BASE_PRICE not in outcome.warnings:
                outcome.warnings.append(NO_BASE_PRICE)
            return outcome

        outcome.total_cost = cost_before_margin if cost_before_margin is not None else running
        outcome.margin_amount = margin_total
        outcome.quote_rate = running
        if ctx.quantity_mt is not None:
            outcome.line_total = money(running * ctx.quantity_mt)

        return outcome

    # --- Internals --------------------------------------------------------

    def _ordered_rules(self, ctx: PricingContext) -> list[PricingRule]:
        """Applicable rules, cost lines first, then margin, floor and rounding."""
        applicable = [
            rule
            for rule in (self.rule_set.rules if self.rule_set else [])
            if rule.is_active and self._matches(rule, ctx)
        ]
        return sorted(
            applicable,
            key=lambda r: (TERMINAL_ORDER.get(r.kind, 0), r.priority, r.id),
        )

    @staticmethod
    def _matches(rule: PricingRule, ctx: PricingContext) -> bool:
        """Whether a rule's conditions hold for this enquiry.

        An unknown fact never satisfies a condition. A rule that says "only for
        Patna" must not fire when the destination was never stated.
        """
        conditions = rule.conditions or {}
        if not conditions:
            return True

        location = (ctx.delivery_location or "").strip().lower()
        wanted = conditions.get("delivery_location")
        if wanted:
            options = [w.strip().lower() for w in wanted]
            if not location or not any(o in location or location in o for o in options):
                return False

        tier = ctx.customer_tier or (ctx.customer.tier.value if ctx.customer else None)
        wanted_tier = conditions.get("customer_tier")
        if wanted_tier and (not tier or tier not in wanted_tier):
            return False

        wanted_type = conditions.get("product_type")
        if wanted_type:
            if not ctx.product_type or ctx.product_type not in wanted_type:
                return False

        wanted_grade = conditions.get("grade")
        if wanted_grade and (not ctx.grade or ctx.grade not in wanted_grade):
            return False

        min_qty = conditions.get("min_quantity_mt")
        if min_qty is not None:
            if ctx.quantity_mt is None or ctx.quantity_mt < Decimal(str(min_qty)):
                return False

        max_qty = conditions.get("max_quantity_mt")
        if max_qty is not None:
            if ctx.quantity_mt is None or ctx.quantity_mt > Decimal(str(max_qty)):
                return False

        return True
