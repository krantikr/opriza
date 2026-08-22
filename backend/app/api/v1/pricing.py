"""Pricing rules, the preview, and the trader-maintained inputs rules read.

Publishing is a copy, never an edit in place: `PUT /pricing/rules` writes a new
`PricingRuleSet` and activates it, leaving the previous version intact. A
quotation priced last week still points at the rules that produced it, so its
explanation stays true after the trader retunes anything.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import TenantDb, current_user
from app.core.db import utcnow
from app.models import (
    Customer,
    LocationDistance,
    MillOffer,
    PricingRule,
    PricingRuleSet,
    RecordStatus,
    User,
    VehicleRate,
)
from app.schemas.pricing import (
    DistanceIn,
    DistanceOut,
    MillOfferIn,
    MillOfferOut,
    PreviewIn,
    PreviewOut,
    RuleSetIn,
    RuleSetOut,
    VehicleIn,
    VehicleOut,
)
from app.services import audit
from app.services.pricing import PricingContext, PricingEngine, active_rule_set
from app.services.pricing.defaults import next_version, seed_pricing_defaults

router = APIRouter(tags=["pricing"])


# --- Rule sets -------------------------------------------------------------


@router.get("/pricing/rules", response_model=RuleSetOut)
def get_active_rules(db: TenantDb) -> PricingRuleSet:
    """The rule set currently pricing every enquiry."""
    rule_set = active_rule_set(db)
    if rule_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pricing rule set is published yet.",
        )
    return rule_set


@router.post(
    "/pricing/rules/seed", response_model=RuleSetOut, status_code=status.HTTP_201_CREATED
)
def seed_starting_rules(db: TenantDb) -> PricingRuleSet:
    """Publish the starting rule set for a desk that has none.

    A desk with no rule set cannot be fixed from the rules editor, because the
    editor edits a version and there is no version to edit. This is the way out
    of that corner. It refuses if rules already exist rather than quietly
    adding a second version, so it cannot be used to discard someone's work.
    """
    existing = db.scalar(select(PricingRuleSet).limit(1))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This desk already has pricing rules.",
        )
    rule_set = seed_pricing_defaults(db, commit=False)
    db.commit()
    db.refresh(rule_set)
    return rule_set


@router.get("/pricing/rules/history", response_model=list[RuleSetOut])
def list_rule_versions(db: TenantDb, limit: int = Query(20, ge=1, le=100)) -> list[PricingRuleSet]:
    """Every published version, newest first - the audit trail for pricing."""
    return list(
        db.scalars(select(PricingRuleSet).order_by(PricingRuleSet.version.desc()).limit(limit))
    )


@router.put("/pricing/rules", response_model=RuleSetOut, status_code=status.HTTP_201_CREATED)
def publish_rules(
    payload: RuleSetIn,
    db: TenantDb,
    user: User | None = Depends(current_user),
) -> PricingRuleSet:
    """Publish a new version and make it active.

    The previous version is deactivated but kept. Nothing is edited in place,
    because a quotation that stored `rules_version: 3` must still be able to
    show the rules that produced it.
    """
    previous = active_rule_set(db)

    rule_set = PricingRuleSet(
        version=next_version(db),
        label=payload.label,
        notes=payload.notes,
        is_active=True,
        published_at=utcnow(),
        published_by_id=user.id if user else None,
    )
    db.add(rule_set)
    db.flush()

    for spec in payload.rules:
        db.add(
            PricingRule(
                rule_set_id=rule_set.id,
                code=spec.code,
                label=spec.label,
                kind=spec.kind,
                priority=spec.priority,
                is_active=spec.is_active,
                conditions=spec.conditions,
                config=spec.config,
                note_template=spec.note_template,
            )
        )

    if previous is not None:
        previous.is_active = False

    audit.record(
        db,
        entity_type="pricing_rule_set",
        entity_id=rule_set.id,
        action="PRICING_RULES_PUBLISHED",
        user_id=user.id if user else None,
        details={
            "version": rule_set.version,
            "replaces_version": previous.version if previous else None,
            "rule_count": len(payload.rules),
        },
    )
    db.commit()
    db.refresh(rule_set)
    return rule_set


@router.post("/pricing/rules/{version}/restore", response_model=RuleSetOut)
def restore_version(
    version: int,
    db: TenantDb,
    user: User | None = Depends(current_user),
) -> PricingRuleSet:
    """Republish an earlier version's rules as a new version.

    A rollback is itself a publish, so the history reads forward and the set
    that was live at any moment stays recoverable.
    """
    source = db.scalar(select(PricingRuleSet).where(PricingRuleSet.version == version))
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version} not found"
        )

    previous = active_rule_set(db)
    restored = PricingRuleSet(
        version=next_version(db),
        label=f"Restored from v{version}",
        notes=source.notes,
        is_active=True,
        published_at=utcnow(),
        published_by_id=user.id if user else None,
    )
    db.add(restored)
    db.flush()

    for rule in source.rules:
        db.add(
            PricingRule(
                rule_set_id=restored.id,
                code=rule.code,
                label=rule.label,
                kind=rule.kind,
                priority=rule.priority,
                is_active=rule.is_active,
                conditions=rule.conditions,
                config=rule.config,
                note_template=rule.note_template,
            )
        )

    if previous is not None:
        previous.is_active = False

    audit.record(
        db,
        entity_type="pricing_rule_set",
        entity_id=restored.id,
        action="PRICING_RULES_RESTORED",
        user_id=user.id if user else None,
        details={"restored_from": version, "new_version": restored.version},
    )
    db.commit()
    db.refresh(restored)
    return restored


# --- Preview ---------------------------------------------------------------


@router.post("/pricing/preview", response_model=PreviewOut)
def preview(payload: PreviewIn, db: TenantDb) -> PreviewOut:
    """Run a scenario through a rule set without saving anything.

    This is what makes self-service pricing safe: a trader sees the whole
    build-up for a worked example before the rules go live, rather than
    discovering the effect on a real customer's quote.
    """
    if payload.rules is not None:
        # An unsaved draft, so the editor can preview edits before publishing.
        rule_set = PricingRuleSet(version=0, label="Preview", is_active=False)
        rule_set.rules = [
            PricingRule(
                code=spec.code,
                label=spec.label,
                kind=spec.kind,
                priority=spec.priority,
                is_active=spec.is_active,
                conditions=spec.conditions,
                config=spec.config,
            )
            for spec in payload.rules
        ]
    elif payload.rule_set_id is not None:
        rule_set = db.get(PricingRuleSet, payload.rule_set_id)
        if rule_set is None:
            raise HTTPException(status_code=404, detail="Rule set not found")
    else:
        rule_set = active_rule_set(db)
        if rule_set is None:
            raise HTTPException(status_code=404, detail="No pricing rule set is published yet.")

    customer = db.get(Customer, payload.customer_id) if payload.customer_id else None

    ctx = PricingContext(
        db=db,
        quantity_mt=payload.quantity_mt,
        product_type=payload.product_type,
        grade=payload.grade,
        thickness_mm=payload.thickness_mm,
        customer=customer,
        customer_tier=payload.customer_tier or (customer.tier.value if customer else None),
        delivery_location=payload.delivery_location,
        origin_location=payload.origin_location,
        payment_days=payload.payment_days,
        stock_cost_per_mt=payload.base_rate,
    )

    outcome = PricingEngine(db, rule_set).price(ctx)
    return PreviewOut(
        basis=outcome.basis,
        base_rate=outcome.base_rate,
        total_cost=outcome.total_cost,
        margin_amount=outcome.margin_amount,
        quote_rate=outcome.quote_rate,
        line_total=outcome.line_total,
        currency=outcome.currency,
        rules_version=outcome.rules_version,
        components=[c.to_dict() for c in outcome.components],  # type: ignore[arg-type]
        explanation=outcome.explanation,
        warnings=outcome.warnings,
    )


# --- Distances -------------------------------------------------------------


@router.get("/pricing/distances", response_model=list[DistanceOut])
def list_distances(db: TenantDb) -> list[LocationDistance]:
    return list(db.scalars(select(LocationDistance).order_by(LocationDistance.destination)))


@router.post("/pricing/distances", response_model=DistanceOut, status_code=status.HTTP_201_CREATED)
def upsert_distance(payload: DistanceIn, db: TenantDb) -> LocationDistance:
    existing = db.scalar(
        select(LocationDistance).where(
            LocationDistance.origin == payload.origin,
            LocationDistance.destination == payload.destination,
        )
    )
    row = existing or LocationDistance(origin=payload.origin, destination=payload.destination)
    row.distance_km = payload.distance_km
    row.typical_days = payload.typical_days
    row.notes = payload.notes
    if existing is None:
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/pricing/distances/{distance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_distance(distance_id: int, db: TenantDb) -> None:
    row = db.get(LocationDistance, distance_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Distance not found")
    db.delete(row)
    db.commit()


# --- Vehicles --------------------------------------------------------------


@router.get("/pricing/vehicles", response_model=list[VehicleOut])
def list_vehicles(db: TenantDb) -> list[VehicleRate]:
    return list(db.scalars(select(VehicleRate).order_by(VehicleRate.capacity_mt.desc())))


@router.post("/pricing/vehicles", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
def upsert_vehicle(payload: VehicleIn, db: TenantDb) -> VehicleRate:
    existing = db.scalar(select(VehicleRate).where(VehicleRate.name == payload.name))
    row = existing or VehicleRate(name=payload.name)
    row.capacity_mt = payload.capacity_mt
    row.rate_per_day = payload.rate_per_day
    row.avg_km_per_day = payload.avg_km_per_day
    row.min_days = payload.min_days
    row.status = RecordStatus.ACTIVE
    if existing is None:
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/pricing/vehicles/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle(vehicle_id: int, db: TenantDb) -> None:
    row = db.get(VehicleRate, vehicle_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    # Retired rather than deleted: a stored build-up may name it.
    row.status = RecordStatus.INACTIVE
    db.commit()


# --- Mill offers -----------------------------------------------------------


@router.get("/pricing/mill-offers", response_model=list[MillOfferOut])
def list_mill_offers(db: TenantDb) -> list[MillOffer]:
    return list(db.scalars(select(MillOffer).order_by(MillOffer.created_at.desc())))


@router.post("/pricing/mill-offers", response_model=MillOfferOut, status_code=status.HTTP_201_CREATED)
def create_mill_offer(payload: MillOfferIn, db: TenantDb) -> MillOffer:
    row = MillOffer(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/pricing/mill-offers/{offer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mill_offer(offer_id: int, db: TenantDb) -> None:
    row = db.get(MillOffer, offer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    db.delete(row)
    db.commit()
