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

import re
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
    Organisation,
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


#: A quotation reference as this system writes them: two-to-four letters, a
#: hyphen, then digits. Deliberately not anchored to one desk's prefix, so a
#: customer quoting any reference is matched and row-level security decides
#: whether it belongs to the reader.
QUOTATION_REFERENCE = re.compile(r"\b([A-Z]{1,4}-\d{4,8})\b", re.IGNORECASE)


def quotation_numbers_in(text: str | None) -> list[str]:
    """Every quotation reference mentioned in a piece of text.

    Customers frequently answer a quotation by starting a *new* email that
    quotes the reference - "Response to Quotation KK-000004" - which shares no
    mail thread with anything. The number is the only reliable link back, and
    it is one we wrote ourselves, so matching on it is deterministic rather
    than a guess.
    """
    if not text:
        return []
    seen: list[str] = []
    for match in QUOTATION_REFERENCE.finditer(text):
        value = match.group(1).upper()
        if value not in seen:
            seen.append(value)
    return seen


def quotation_prefix(organisation: Organisation | None) -> str:
    """The desk's own letters, taken from its name: "KK Traders" -> "KK".

    Each desk numbers its own quotations, so a trader's references run 1, 2, 3
    from the day they start rather than continuing somebody else's count. The
    prefix keeps two desks' references visibly distinct in a support
    conversation.

    Falls back to "Q" when a name yields no letters at all, because a
    quotation must always get a reference.
    """
    if organisation is None:
        return "Q"
    letters = [c for c in (organisation.name or "") if c.isalpha()]
    return "".join(letters[:2]).upper() or "Q"


def next_quotation_number(db: Session, organisation_id: int | None = None) -> str:
    """The next reference for this desk: KK-000001, KK-000002, ...

    Counted from the desk's own highest number rather than from a row id.
    Row ids are shared across every organisation, so numbering from them
    would start a new customer at whatever the platform total happened to be
    and leak how many quotations other desks have written.
    """
    organisation = (
        db.get(Organisation, organisation_id) if organisation_id is not None else None
    )
    prefix = quotation_prefix(organisation)

    # Scoped by row-level security, so this counts only this desk's numbers.
    # The LIKE narrows it further for a desk whose prefix has changed - the
    # old series keeps its numbers and the new one starts its own.
    highest = db.scalar(
        select(func.max(QuotationRequest.quotation_number)).where(
            QuotationRequest.quotation_number.like(f"{prefix}-%")
        )
    )

    nextval = 1
    if highest:
        try:
            nextval = int(highest.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            # A reference that does not parse should not stop a quotation
            # being written; fall back to counting rows for this prefix.
            nextval = (
                db.scalar(
                    select(func.count()).select_from(QuotationRequest).where(
                        QuotationRequest.quotation_number.like(f"{prefix}-%")
                    )
                )
                or 0
            ) + 1

    return f"{prefix}-{nextval:06d}"


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
    # Flushed first because `organisation_id` is stamped by the tenancy hook
    # at flush time, and the reference is derived from it.
    db.flush()

    quotation.quotation_number = next_quotation_number(db, quotation.organisation_id)

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
