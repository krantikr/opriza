"""Turns an extracted enquiry into persisted quotation records.

Two decisions here are worth stating explicitly:

* **An unknown sender is created as an unverified customer.** Leaving
  first-time enquiries unlinked meant every quote from a new address silently
  lost its delivery location and payment terms, and the customer list stayed
  empty however much mail arrived. So a sender nobody has on file now becomes
  a `Customer` with `is_verified=False`, carrying only what the email itself
  said. Tier stays at the default until a human confirms it, so an unverified
  row can never win a better price than a known customer.
* **What the email said is stored next to what it resolved to.**
  `customer_name_raw` sits beside `customer_id`, so a wrong resolution is
  visible on screen rather than hidden behind a foreign key.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai.schemas import ExtractedEnquiry, SteelLineItem
from app.core.logging import get_logger
from app.models import (
    Customer,
    Email,
    MatchStatus,
    QuantityUnit,
    QuotationLineItem,
    QuotationRequest,
    QuotationStatus,
    RecordStatus,
)

logger = get_logger(__name__)


def find_customer(db: Session, email: Email, extracted: ExtractedEnquiry) -> Customer | None:
    """Look the sender up in the customer master. Never creates one."""
    if email.sender_email:
        match = db.scalar(
            select(Customer).where(
                func.lower(Customer.email) == email.sender_email.lower(),
                Customer.status == RecordStatus.ACTIVE,
            )
        )
        if match:
            return match

    # Fall back to an exact company-name match; anything looser risks pricing
    # one customer's enquiry on another's tier.
    if extracted.customer_company:
        return db.scalar(
            select(Customer).where(
                func.lower(Customer.company) == extracted.customer_company.strip().lower(),
                Customer.status == RecordStatus.ACTIVE,
            )
        )

    return None


def _display_name(email: Email, extracted: ExtractedEnquiry) -> str | None:
    """Best available human name for a sender we have never seen."""
    for candidate in (extracted.customer_name, email.sender_name, extracted.customer_company):
        text = (candidate or "").strip()
        if text:
            return text[:200]
    # Last resort: the local part of the address, so the row is still
    # recognisable in a list rather than showing up blank.
    if email.sender_email and "@" in email.sender_email:
        return email.sender_email.split("@", 1)[0][:200] or None
    return None


def resolve_customer(db: Session, email: Email, extracted: ExtractedEnquiry) -> Customer | None:
    """Find the sender, creating an unverified record if they are new.

    Only what the email actually stated is written. Tier and payment terms are
    left at their defaults, because guessing either would let an unknown
    sender's quote be priced as though someone had approved them.
    """
    existing = find_customer(db, email, extracted)
    if existing:
        # Fill blanks the enquiry can answer, but never overwrite - a value
        # already on file was either imported or reviewed, and an email
        # signature is not grounds to replace it.
        if not existing.company and extracted.customer_company:
            existing.company = extracted.customer_company.strip()[:200]
        if not existing.email and email.sender_email:
            existing.email = email.sender_email.lower()[:255]
        return existing

    # Without an address there is nothing to match a future enquiry on, so a
    # record here would be an orphan that never resolves again.
    if not email.sender_email:
        return None

    name = _display_name(email, extracted)
    if not name:
        return None

    customer = Customer(
        name=name,
        email=email.sender_email.lower()[:255],
        company=(extracted.customer_company or "").strip()[:200] or None,
        status=RecordStatus.ACTIVE,
        is_verified=False,
    )
    db.add(customer)
    db.flush()
    logger.info(
        "Created unverified customer %s (%s) from email %s",
        customer.id,
        customer.email,
        email.message_id,
    )
    return customer


def next_quotation_number(db: Session) -> str:
    """Sequential reference, assigned after the row has an id."""
    highest = db.scalar(select(func.max(QuotationRequest.id))) or 0
    return f"Q-{highest + 1:06d}"


def _to_decimal(value: float | int | None) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount > 0 else None


def _line_item(item: SteelLineItem, line_no: int) -> QuotationLineItem:
    return QuotationLineItem(
        line_no=line_no,
        raw_text=item.raw_text,
        product_type=item.product_type,
        grade=item.grade,
        standard=item.standard,
        thickness_mm=item.thickness_mm,
        width_mm=item.width_mm,
        length_mm=item.length_mm,
        diameter_mm=item.diameter_mm,
        quantity=_to_decimal(item.quantity),
        quantity_unit=item.quantity_unit or QuantityUnit.UNKNOWN,
        remarks=item.remarks,
        match_status=MatchStatus.PENDING,
    )


def create_quotation(
    db: Session, email: Email, extracted: ExtractedEnquiry
) -> QuotationRequest:
    """Persist a quotation request and its line items from an extraction."""
    customer = resolve_customer(db, email, extracted)

    delivery_location = extracted.delivery_location or (
        customer.default_delivery_location if customer else None
    )

    missing = list(extracted.missing_information)
    if not extracted.line_items:
        missing.append("no material could be identified in the enquiry")

    quotation = QuotationRequest(
        # Temporary unique placeholder; replaced once the row has an id.
        quotation_number=f"TMP-{uuid4().hex[:12]}",
        email_id=email.id,
        customer_id=customer.id if customer else None,
        customer_name_raw=extracted.customer_name or email.sender_name,
        customer_company_raw=extracted.customer_company,
        customer_email=email.sender_email,
        status=QuotationStatus.PROCESSING,
        delivery_location=delivery_location,
        required_delivery_date=extracted.required_delivery_date,
        payment_terms=extracted.payment_terms or (customer.payment_terms if customer else None),
        additional_requirements=list(extracted.additional_requirements),
        missing_information=missing,
    )
    db.add(quotation)
    db.flush()

    quotation.quotation_number = f"Q-{quotation.id:06d}"

    for index, item in enumerate(extracted.line_items, start=1):
        line = _line_item(item, index)
        line.quotation_request_id = quotation.id
        db.add(line)

    db.flush()
    logger.info(
        "Created %s from email %s with %d line item(s)",
        quotation.quotation_number,
        email.message_id,
        len(extracted.line_items),
    )
    return quotation
