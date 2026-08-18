"""Assembles the verified facts handed to the draft model.

This is the boundary between "settled" and "written". Everything in the block
this module produces has already been decided by deterministic code: the spec
came from the matcher, availability and the suggested rate from the
stock-availability service, the terms from configuration. The model's job is
to wrap prose around it.

The same values are also emitted as `RequiredFact`s so the generated body can be
checked for having reproduced them. Building both from one place means the check
cannot drift from what was actually supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ai.guards import RequiredFact, money_fact, quantity_fact
from app.core.config import settings
from app.core.rules import BusinessRules, get_rules
from app.models import QuotationRequest


def format_inr(value: Decimal | float | int | None) -> str:
    """Format with Indian digit grouping: 1184000 -> 11,84,000.00."""
    if value is None:
        return "-"
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    sign = "-" if amount < 0 else ""
    whole, _, fraction = f"{abs(amount):.2f}".partition(".")

    if len(whole) <= 3:
        grouped = whole
    else:
        # Last three digits, then pairs: 1184000 -> 11,84,000
        head, tail = whole[:-3], whole[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        grouped = ",".join([*pairs, tail])

    return f"{sign}{grouped}.{fraction}"


def format_quantity(value: Decimal | float | int | None) -> str:
    """Trim trailing zeros: 20.000 -> 20, 6.096 -> 6.096."""
    if value is None:
        return "-"
    amount = Decimal(str(value))
    normalized = amount.normalize()
    # normalize() renders integers in exponent form (2E+1); undo that.
    if normalized == normalized.to_integral_value():
        return f"{normalized.to_integral_value():f}"
    return f"{normalized:f}"


@dataclass(slots=True)
class DraftContext:
    facts: str
    required_facts: list[RequiredFact] = field(default_factory=list)
    matched_line_count: int = 0
    unmatched_line_count: int = 0


def build_draft_context(
    quotation: QuotationRequest, rules: BusinessRules | None = None
) -> DraftContext:
    """Render the verified-facts block for one quotation."""
    rules = rules or get_rules()
    lines: list[str] = []
    required: list[RequiredFact | None] = []

    # --- Company ----------------------------------------------------------
    lines += [
        "COMPANY",
        f"Name: {settings.company_name}",
        f"Email: {settings.company_email}",
        f"Phone: {settings.company_phone}",
        f"Signatory: {settings.company_signatory}",
        "",
    ]

    # --- Customer ---------------------------------------------------------
    contact = quotation.customer_name_raw or (
        quotation.customer.name if quotation.customer else None
    )
    company = quotation.customer_company_raw or (
        quotation.customer.company if quotation.customer else None
    )
    lines.append("CUSTOMER")
    if contact:
        lines.append(f"Contact person: {contact}")
    if company:
        lines.append(f"Company: {company}")
    if quotation.customer_email:
        lines.append(f"Email: {quotation.customer_email}")
    lines.append("")

    # --- Quotation header -------------------------------------------------
    lines += ["QUOTATION", f"Reference: {quotation.quotation_number}", f"Date: {date.today():%d %B %Y}"]
    if quotation.delivery_location:
        lines.append(f"Delivery location: {quotation.delivery_location}")
    if quotation.required_delivery_date:
        lines.append(f"Delivery requested by customer: {quotation.required_delivery_date}")
    if quotation.payment_terms:
        lines.append(f"Payment terms requested: {quotation.payment_terms}")
    lines.append("")

    # --- Items ------------------------------------------------------------
    lines.append("ITEMS")
    matched = unmatched = 0

    for item in quotation.line_items:
        availability = item.stock_availability
        description = (
            item.matched_stock_item.display_name
            if item.matched_stock_item
            else (item.raw_text or "Material as per enquiry")
        )
        lines.append(f"{item.line_no}. {description}")

        if item.quantity is not None:
            unit = item.quantity_unit.value
            lines.append(f"   Quantity requested: {format_quantity(item.quantity)} {unit}")
            required.append(quantity_fact(f"Quantity on line {item.line_no}", item.quantity))
            if item.quantity_mt is not None and unit != "MT":
                # The tonnage availability is checked against, when the customer
                # asked in another unit. Stated so the customer can check it.
                lines.append(f"   Equivalent weight: {format_quantity(item.quantity_mt)} MT")
                required.append(quantity_fact(f"Tonnage on line {item.line_no}", item.quantity_mt))

        if availability and availability.available_qty_mt is not None:
            matched += 1
            if availability.available_qty_mt > 0:
                where = ", ".join(
                    f"{loc.get('location') or 'unspecified location'} "
                    f"({format_quantity(loc.get('balance_qty_mt'))} MT)"
                    for loc in (availability.locations or [])
                )
                lines.append(
                    f"   Available: {format_quantity(availability.available_qty_mt)} MT"
                    + (f" - {where}" if where else "")
                )
                required.append(
                    quantity_fact(f"Available quantity on line {item.line_no}", availability.available_qty_mt)
                )
                if availability.ageing_min_days is not None:
                    span = (
                        f"{availability.ageing_min_days} days"
                        if availability.ageing_min_days == availability.ageing_max_days
                        else f"{availability.ageing_min_days}-{availability.ageing_max_days} days"
                    )
                    lines.append(f"   In stock: {span}")
            else:
                lines.append("   Available: not currently in stock")

            if availability.suggested_rate is not None:
                lines.append(
                    f"   Suggested rate (indicative, subject to confirmation): "
                    f"INR {format_inr(availability.suggested_rate)} per {availability.unit.value}"
                )
                required.append(
                    money_fact(f"Suggested rate on line {item.line_no}", availability.suggested_rate)
                )
        else:
            unmatched += 1
            lines.append("   Availability: to be confirmed")

        lines.append("")

    # --- Customer's other requirements ------------------------------------
    if quotation.additional_requirements:
        lines.append("CUSTOMER REQUIREMENTS NOTED")
        lines += [f"- {requirement}" for requirement in quotation.additional_requirements]
        lines.append("")

    # --- Terms ------------------------------------------------------------
    lines.append("COMMERCIAL TERMS")
    lines += [f"- {term}" for term in rules.quotation.rendered_terms()]
    lines.append("")

    lines += ["SIGN-OFF", settings.company_signatory, settings.company_name]

    return DraftContext(
        facts="\n".join(lines).strip(),
        required_facts=[f for f in required if f is not None],
        matched_line_count=matched,
        unmatched_line_count=unmatched,
    )
