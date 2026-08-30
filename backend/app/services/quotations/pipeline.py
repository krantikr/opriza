"""The desk in tonnes and rupees, stage by stage - and what happens next.

Counts answer "how many pieces of paper"; a steel desk runs on tonnage and on
dates. Twelve quotations is not a workload a trader can feel, but 340 MT to
buy by Friday is, and so is 18 lakh landing in the bank three weeks late.

Three questions, in the order they cost money:

  * **The pipeline** - how much tonnage sits at each stage, and what it is
    worth. Where the desk's effort is.
  * **Deliveries** - what has been won and not shipped, and what must be
    bought to ship it. Where the desk's next purchase order comes from.
  * **Payments** - what has shipped and not been paid for, and when the money
    is actually due under the terms that were agreed.

Payment dates are *derived*, not stored: the terms say "30 days" and the goods
went out on a date, so the money is due thirty days after that. Nobody types
that in, and a desk that waits to be told is a desk that finds out late.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    QuotationLineItem,
    QuotationPricing,
    QuotationRequest,
    QuotationStatus as Q,
)
from app.services.quotations.stages import COMMERCIAL_STAGES, stage_of

ZERO = Decimal("0.000")

#: Assumed when the agreed terms say nothing about a credit period. Stated as
#: a constant rather than buried in a branch: a desk that treats unstated
#: terms as "due immediately" reports every unpaid invoice as overdue on the
#: day it ships, and the whole card becomes noise.
DEFAULT_PAYMENT_DAYS = 30


def payment_days(quotation: QuotationRequest) -> int:
    """The credit period, read from whatever the terms actually say."""
    for text in (quotation.payment_terms,
                 quotation.customer.payment_terms if quotation.customer else None):
        if not text:
            continue
        match = re.search(r"(\d{1,3})\s*days?", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        if re.search(r"advance|against\s+delivery|immediate|cash", text, flags=re.IGNORECASE):
            return 0
    return DEFAULT_PAYMENT_DAYS


@dataclass(slots=True)
class StageTotal:
    key: str
    label: str
    count: int = 0
    tonnes: Decimal = ZERO
    value: Decimal = ZERO


@dataclass(slots=True)
class DeliveryRow:
    """One won order that has not shipped."""

    quotation_id: int
    quotation_number: str
    customer: str
    tonnes: Decimal
    value: Decimal
    wanted_by: str | None
    in_stock_mt: Decimal
    to_buy_mt: Decimal
    material: str


#: Bucket keys in the order a trader should read them: money not yet due,
#: money to chase this week, money already late.
PAYMENT_BUCKETS: tuple[tuple[str, str], ...] = (
    ("not_due", "Not due yet"),
    ("due_soon", "Due this week"),
    ("overdue", "Overdue"),
)


def _payment_bucket(due_on: date | None, days_overdue: int, today: date) -> str:
    if days_overdue > 0:
        return "overdue"
    if due_on is not None and today <= due_on <= today + timedelta(days=7):
        return "due_soon"
    return "not_due"


@dataclass(slots=True)
class PaymentRow:
    """One shipped order that has not been paid for."""

    quotation_id: int
    quotation_number: str
    customer: str
    tonnes: Decimal
    value: Decimal
    despatched_on: date | None
    terms: str | None
    due_on: date | None
    days_overdue: int
    bucket: str


@dataclass(slots=True)
class Pipeline:
    stages: list[StageTotal] = field(default_factory=list)
    deliveries: list[DeliveryRow] = field(default_factory=list)
    payments: list[PaymentRow] = field(default_factory=list)
    payment_buckets: list[StageTotal] = field(default_factory=list)

    # Headline figures, so the interface does not re-derive them.
    to_buy_mt: Decimal = ZERO
    due_this_week: Decimal = ZERO
    overdue_value: Decimal = ZERO
    overdue_count: int = 0


def _line_totals(db: Session) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    """Tonnage and value per quotation, in two passes rather than N queries."""
    tonnes: dict[int, Decimal] = {}
    value: dict[int, Decimal] = {}

    rows = db.execute(
        select(
            QuotationLineItem.quotation_request_id,
            QuotationLineItem.quantity_mt,
            QuotationPricing.line_total,
        ).outerjoin(
            QuotationPricing,
            QuotationPricing.quotation_line_item_id == QuotationLineItem.id,
        )
    ).all()

    for quotation_id, quantity, line_total in rows:
        if quantity is not None:
            tonnes[quotation_id] = tonnes.get(quotation_id, ZERO) + Decimal(str(quantity))
        if line_total is not None:
            value[quotation_id] = value.get(quotation_id, ZERO) + Decimal(str(line_total))

    return tonnes, value


def _customer(quotation: QuotationRequest) -> str:
    return (
        quotation.customer_company_raw
        or quotation.customer_name_raw
        or quotation.customer_email
        or "Unknown"
    )


def _material(quotation: QuotationRequest) -> str:
    """What the order is for, in one line."""
    items = sorted(quotation.line_items, key=lambda i: i.line_no)
    if not items:
        return "—"
    first = items[0]
    name = (
        first.matched_stock_item.display_name
        if first.matched_stock_item
        else (first.raw_text or "Material")
    )
    return name if len(items) == 1 else f"{name} +{len(items) - 1}"


def build(db: Session, *, today: date | None = None) -> Pipeline:
    """The whole picture, in one pass over the open quotations."""
    from app.services.stock.position import spec_positions

    today = today or date.today()
    tonnes, value = _line_totals(db)
    pipeline = Pipeline()

    # --- Stages -----------------------------------------------------------
    buckets = {
        key: StageTotal(key=key, label=label) for key, label, _ in COMMERCIAL_STAGES
    }

    quotations = list(db.scalars(select(QuotationRequest)))
    for quotation in quotations:
        key = stage_of(quotation)
        if key is None:
            continue
        bucket = buckets[key]
        bucket.count += 1
        bucket.tonnes += tonnes.get(quotation.id, ZERO)
        bucket.value += value.get(quotation.id, ZERO)

    pipeline.stages = [buckets[key] for key, _, _ in COMMERCIAL_STAGES]

    # --- Deliveries: won, not yet shipped ---------------------------------
    # The shortfall per specification, so a delivery row can say what has to
    # be bought rather than only what was ordered.
    shortfall = {p.key: p for p in spec_positions(db)}

    for quotation in quotations:
        if quotation.status is not Q.CUSTOMER_ACCEPTED or quotation.despatched_at is not None:
            continue

        ordered = tonnes.get(quotation.id, ZERO)
        held = ZERO
        buy = ZERO
        for item in quotation.line_items:
            from app.services.stock.position import _spec_key

            position = shortfall.get(_spec_key(item))
            if position is None:
                # Nothing on file for this spec: all of it has to be bought.
                buy += Decimal(str(item.quantity_mt or 0))
                continue
            wanted = Decimal(str(item.quantity_mt or 0))
            available = min(wanted, position.in_stock_mt)
            held += available
            buy += wanted - available

        pipeline.deliveries.append(
            DeliveryRow(
                quotation_id=quotation.id,
                quotation_number=quotation.quotation_number,
                customer=_customer(quotation),
                tonnes=ordered,
                value=value.get(quotation.id, ZERO),
                wanted_by=quotation.required_delivery_date,
                in_stock_mt=held,
                to_buy_mt=buy,
                material=_material(quotation),
            )
        )

    pipeline.to_buy_mt = sum((row.to_buy_mt for row in pipeline.deliveries), ZERO)

    # --- Payments: shipped, not yet paid ----------------------------------
    for quotation in quotations:
        shipped = quotation.despatched_at
        if shipped is None or quotation.paid_at is not None:
            continue
        if quotation.status not in (Q.PAYMENT_PENDING, Q.CUSTOMER_ACCEPTED):
            continue

        shipped_on = shipped.date()
        due = shipped_on + timedelta(days=payment_days(quotation))
        days_overdue = max((today - due).days, 0)
        pipeline.payments.append(
            PaymentRow(
                quotation_id=quotation.id,
                quotation_number=quotation.quotation_number,
                customer=_customer(quotation),
                tonnes=tonnes.get(quotation.id, ZERO),
                value=value.get(quotation.id, ZERO),
                despatched_on=shipped_on,
                terms=quotation.payment_terms,
                due_on=due,
                days_overdue=days_overdue,
                bucket=_payment_bucket(due, days_overdue, today),
            )
        )

    # Most overdue first: the money least likely to arrive on its own.
    pipeline.payments.sort(key=lambda r: (-r.days_overdue, r.due_on or today))
    pipeline.overdue_value = sum(
        (row.value for row in pipeline.payments if row.days_overdue > 0), ZERO
    )
    pipeline.overdue_count = sum(1 for row in pipeline.payments if row.days_overdue > 0)
    pipeline.due_this_week = sum(
        (
            row.value
            for row in pipeline.payments
            if row.due_on is not None and today <= row.due_on <= today + timedelta(days=7)
        ),
        ZERO,
    )

    buckets = {key: StageTotal(key=key, label=label) for key, label in PAYMENT_BUCKETS}
    for row in pipeline.payments:
        bucket = buckets[row.bucket]
        bucket.count += 1
        bucket.tonnes += row.tonnes
        bucket.value += row.value
    pipeline.payment_buckets = [buckets[key] for key, _ in PAYMENT_BUCKETS]

    # Soonest wanted first, and anything with no date last: a delivery with a
    # stated date is a promise, and it outranks one without.
    pipeline.deliveries.sort(key=lambda r: (r.wanted_by is None, r.wanted_by or "", -r.to_buy_mt))

    return pipeline


__all__ = ["Pipeline", "DeliveryRow", "PaymentRow", "StageTotal", "build", "payment_days"]
