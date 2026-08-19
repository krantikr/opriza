"""The starting rule set a new installation gets.

Modelled on the reference calculator the client specified, so the first screen
a trader opens shows a build-up they recognise rather than an empty table they
have to design from nothing. Every figure here is a starting point they are
expected to change - which is the entire point of the feature.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.logging import get_logger
from app.models import (
    LocationDistance,
    PricingComponentKind,
    PricingRule,
    PricingRuleSet,
    VehicleRate,
)

logger = get_logger(__name__)

DEFAULT_RULES: list[dict] = [
    {
        "code": "base_price",
        "label": "Base purchase price",
        "kind": PricingComponentKind.BASE_PRICE,
        "priority": 10,
        "config": {"prefer": "STOCK"},
    },
    {
        "code": "transportation",
        "label": "Transportation",
        "kind": PricingComponentKind.TRANSPORTATION,
        "priority": 20,
        "config": {"round_trip": True},
    },
    {
        "code": "handling",
        "label": "Loading / unloading",
        "kind": PricingComponentKind.HANDLING,
        "priority": 30,
        "config": {"amount_per_mt": 300, "description": "Loading and unloading"},
    },
    {
        "code": "financing",
        "label": "Financing cost",
        "kind": PricingComponentKind.FINANCING,
        "priority": 40,
        "config": {"annual_rate_pct": 11.0, "days": 60},
    },
    {
        "code": "risk_buffer",
        "label": "Other / risk buffer",
        "kind": PricingComponentKind.RISK_BUFFER,
        "priority": 50,
        "config": {"amount_per_mt": 200},
    },
    {
        "code": "target_margin",
        "label": "Target margin",
        "kind": PricingComponentKind.TARGET_MARGIN,
        "priority": 100,
        "config": {"pct": 3.0},
    },
    {
        "code": "margin_floor",
        "label": "Minimum margin",
        "kind": PricingComponentKind.MARGIN_FLOOR,
        "priority": 110,
        "config": {"minimum_margin_pct": 2.0},
    },
    {
        "code": "rounding",
        "label": "Rounding",
        "kind": PricingComponentKind.ROUNDING,
        "priority": 120,
        "config": {"nearest": 50, "mode": "nearest"},
    },
]

#: Optional rules, off by default. They are seeded inactive so a trader can see
#: what is available and switch one on, rather than having to know it exists.
OPTIONAL_RULES: list[dict] = [
    {
        "code": "quantity_slab",
        "label": "Volume pricing",
        "kind": PricingComponentKind.QUANTITY_SLAB,
        "priority": 60,
        "is_active": False,
        "config": {
            "of": "RUNNING",
            "slabs": [
                {"min_mt": 0, "max_mt": 5, "pct": 1.5},
                {"min_mt": 5, "max_mt": 25, "pct": 0},
                {"min_mt": 25, "max_mt": 100, "pct": -0.75},
                {"min_mt": 100, "max_mt": None, "pct": -1.5},
            ],
        },
    },
    {
        "code": "customer_tier",
        "label": "Customer tier",
        "kind": PricingComponentKind.CUSTOMER_TIER,
        "priority": 70,
        "is_active": False,
        "config": {"of": "RUNNING", "tiers": {"A": -0.5, "B": 0, "C": 0.5}},
    },
    {
        "code": "invoice_anchor",
        "label": "Recent sales anchor",
        "kind": PricingComponentKind.INVOICE_ANCHOR,
        "priority": 80,
        "is_active": False,
        "config": {"window_days": 30, "max_window_days": 90, "min_count": 3, "weight_pct": 40},
    },
]

DEFAULT_VEHICLES: list[dict] = [
    {"name": "Trailer", "capacity_mt": 25, "rate_per_day": 50000, "avg_km_per_day": 350, "min_days": 1},
    {"name": "Truck (16 MT)", "capacity_mt": 16, "rate_per_day": 32000, "avg_km_per_day": 400, "min_days": 1},
    {"name": "LCV (9 MT)", "capacity_mt": 9, "rate_per_day": 18000, "avg_km_per_day": 400, "min_days": 1},
]


def seed_pricing_defaults(db: Session, *, origin: str = "Nagpur") -> PricingRuleSet:
    """Create and publish version 1, if no rule set exists yet.

    Idempotent: an installation that already has rules is left untouched, so
    this is safe to call from `init_db.py` on every run.
    """
    existing = db.scalar(select(PricingRuleSet).limit(1))
    if existing is not None:
        return existing

    rule_set = PricingRuleSet(
        version=1,
        label="Starting rules",
        notes=(
            "Seeded defaults modelled on the reference cost build-up. Every figure "
            "here is a starting point and is expected to be tuned."
        ),
        is_active=True,
        published_at=utcnow(),
    )
    db.add(rule_set)
    db.flush()

    for spec in [*DEFAULT_RULES, *OPTIONAL_RULES]:
        db.add(
            PricingRule(
                rule_set_id=rule_set.id,
                code=spec["code"],
                label=spec["label"],
                kind=spec["kind"],
                priority=spec["priority"],
                is_active=spec.get("is_active", True),
                config=spec["config"],
            )
        )

    if db.scalar(select(func.count()).select_from(VehicleRate)) == 0:
        for vehicle in DEFAULT_VEHICLES:
            db.add(VehicleRate(**vehicle))

    if db.scalar(select(func.count()).select_from(LocationDistance)) == 0:
        for destination, km, days in (
            ("Patna", 1050, 3),
            ("Raipur", 290, 1),
            ("Pune", 700, 2),
            ("Mumbai", 840, 2),
            ("Hyderabad", 500, 2),
        ):
            db.add(
                LocationDistance(
                    origin=origin,
                    destination=destination,
                    distance_km=km,
                    typical_days=days,
                    notes="Seeded example - replace with your own figures.",
                )
            )

    db.commit()
    logger.info("Seeded pricing rule set v1 with %d rules", len(DEFAULT_RULES) + len(OPTIONAL_RULES))
    return rule_set


def next_version(db: Session) -> int:
    highest = db.scalar(select(func.max(PricingRuleSet.version))) or 0
    return int(highest) + 1


__all__ = ["seed_pricing_defaults", "next_version", "DEFAULT_RULES", "OPTIONAL_RULES"]
