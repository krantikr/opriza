"""What a customer has bought and been quoted before.

Assembled for one question, asked every time a rate is about to go out: *is
this consistent with what this buyer has actually paid?* A trader answers it
today by digging through a spreadsheet, and usually skips it.

Two sources, and they answer different halves:

* **Invoices** (`SalesInvoice`) are money that changed hands. They are the
  honest anchor, and the same table `components.invoice_anchor` prices
  against - so the tab shows the evidence the calculator is already using
  rather than a second opinion assembled differently.
* **Earlier quotations** say whether this buyer converts or shops the desk
  around. A customer quoted eight times and won once is a different
  conversation from one who buys on the first number.

Rows matching the *specification* being quoted are marked `same_material`.
Those are the ones that actually anchor a price; the rest are relationship
context, and the UI separates them for that reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Customer,
    QuotationRequest,
    QuotationStatus,
    SalesInvoice,
)

#: How many rows of each kind to return. Enough to see a pattern, few enough
#: that the tab stays readable without paging.
LIMIT = 25


@dataclass(slots=True)
class PastInvoice:
    invoice_no: str | None
    invoice_date: date | None
    material: str
    quantity_mt: Decimal | None
    rate_per_mt: Decimal | None
    line_total: Decimal | None
    delivery_location: str | None
    same_material: bool


@dataclass(slots=True)
class PastQuotation:
    id: int
    quotation_number: str
    created_at: object
    sent_at: object
    status: str
    material: str
    quantity_mt: Decimal | None
    rate_per_mt: Decimal | None
    value: Decimal | None
    won: bool
    same_material: bool


@dataclass(slots=True)
class PastOrders:
    customer_name: str | None
    invoices: list[PastInvoice]
    quotations: list[PastQuotation]
    orders_count: int
    total_value: Decimal | None
    total_quantity_mt: Decimal | None
    last_order_at: date | None
    quotes_count: int
    quotes_won: int
    avg_rate_same_material: Decimal | None
    current_rate: Decimal | None
    rate_delta: Decimal | None


class PastOrdersService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def for_quotation(self, quotation: QuotationRequest) -> PastOrders:
        customer = quotation.customer
        spec = self._spec(quotation)

        invoices = self._invoices(quotation, customer, spec)
        quotations = self._quotations(quotation, spec)

        billed = [i for i in invoices if i.line_total is not None]
        total_value = sum((i.line_total for i in billed), Decimal(0)) if billed else None
        quantities = [i.quantity_mt for i in invoices if i.quantity_mt is not None]
        total_qty = sum(quantities, Decimal(0)) if quantities else None
        dates = [i.invoice_date for i in invoices if i.invoice_date is not None]

        # The anchor: what this customer has paid for *this* material. A mean
        # over mixed specifications would be a number with no meaning.
        matched = [
            i.rate_per_mt
            for i in invoices
            if i.same_material and i.rate_per_mt is not None
        ]
        avg = (sum(matched, Decimal(0)) / len(matched)) if matched else None

        current = self._current_rate(quotation)
        delta = (current - avg) if (current is not None and avg is not None) else None

        return PastOrders(
            customer_name=(
                quotation.customer_company_raw
                or (customer.name if customer else None)
                or quotation.customer_name_raw
            ),
            invoices=invoices,
            quotations=quotations,
            orders_count=len(invoices),
            total_value=total_value,
            total_quantity_mt=total_qty,
            last_order_at=max(dates) if dates else None,
            quotes_count=len(quotations),
            quotes_won=sum(1 for q in quotations if q.won),
            avg_rate_same_material=_round(avg),
            current_rate=_round(current),
            rate_delta=_round(delta),
        )

    # -- sources -----------------------------------------------------------

    def _invoices(
        self,
        quotation: QuotationRequest,
        customer: Customer | None,
        spec: tuple,
    ) -> list[PastInvoice]:
        """Billed sales to this customer, newest first.

        Matched on `customer_id` where the quotation resolved to a customer
        record. Imported invoices that were never linked to one are out of
        reach here, which is correct: guessing by name would attribute another
        buyer's rate to this conversation, and a wrong anchor is worse than
        none.
        """
        if customer is None:
            return []

        rows = self.db.scalars(
            select(SalesInvoice)
            .where(SalesInvoice.customer_id == customer.id)
            .order_by(SalesInvoice.invoice_date.desc().nullslast())
            .limit(LIMIT)
        ).all()

        out: list[PastInvoice] = []
        for row in rows:
            qty = row.quantity_mt
            rate = row.rate_per_mt
            out.append(
                PastInvoice(
                    invoice_no=row.invoice_no,
                    invoice_date=row.invoice_date,
                    material=_describe(row.thickness_mm, row.product_type, row.grade)
                    or "—",
                    quantity_mt=qty,
                    rate_per_mt=rate,
                    line_total=(qty * rate) if (qty is not None and rate is not None) else None,
                    delivery_location=row.delivery_location,
                    same_material=_matches(
                        spec, row.product_type, row.grade, row.thickness_mm
                    ),
                )
            )
        return out

    def _quotations(
        self, quotation: QuotationRequest, spec: tuple
    ) -> list[PastQuotation]:
        """Earlier quotations to the same customer, this one excluded.

        Matched on the customer record where there is one and on the email
        address otherwise, so a buyer who was never resolved into the master
        still gets their own history rather than an empty tab.
        """
        clauses = []
        if quotation.customer_id is not None:
            clauses.append(QuotationRequest.customer_id == quotation.customer_id)
        if quotation.customer_email:
            clauses.append(QuotationRequest.customer_email == quotation.customer_email)
        if not clauses:
            return []

        rows = self.db.scalars(
            select(QuotationRequest)
            .where(or_(*clauses), QuotationRequest.id != quotation.id)
            .order_by(QuotationRequest.created_at.desc())
            .limit(LIMIT)
        ).all()

        out: list[PastQuotation] = []
        for row in rows:
            first = row.line_items[0] if row.line_items else None
            pricing = first.pricing if first is not None else None
            out.append(
                PastQuotation(
                    id=row.id,
                    quotation_number=row.quotation_number,
                    created_at=row.created_at,
                    sent_at=row.sent_at,
                    status=row.status.value,
                    material=(
                        _describe(
                            first.thickness_mm if first else None,
                            first.product_type if first else None,
                            first.grade if first else None,
                        )
                        or "—"
                    ),
                    quantity_mt=first.quantity_mt if first else None,
                    rate_per_mt=pricing.quote_rate if pricing else None,
                    value=pricing.line_total if pricing else None,
                    won=row.status is QuotationStatus.CUSTOMER_ACCEPTED,
                    same_material=_matches(
                        spec,
                        first.product_type if first else None,
                        first.grade if first else None,
                        first.thickness_mm if first else None,
                    ),
                )
            )
        return out

    # -- helpers -----------------------------------------------------------

    def _spec(self, quotation: QuotationRequest) -> tuple:
        """The specification being quoted, for the `same_material` test."""
        first = quotation.line_items[0] if quotation.line_items else None
        if first is None:
            return (None, None, None)
        return (first.product_type, first.grade, first.thickness_mm)

    def _current_rate(self, quotation: QuotationRequest) -> Decimal | None:
        """Today's rate on the first line, to compare the history against."""
        for item in quotation.line_items or []:
            if item.pricing is not None and item.pricing.quote_rate is not None:
                return item.pricing.quote_rate
            if (
                item.stock_availability is not None
                and item.stock_availability.suggested_rate is not None
            ):
                return item.stock_availability.suggested_rate
        return None


def _matches(
    spec: tuple, product_type: str | None, grade: str | None, thickness: float | None
) -> bool:
    """Whether a historic line is the same material as the one being quoted.

    Compared case-insensitively on product and grade, exactly on thickness.
    All three must be present on both sides: a partial match would mark rows
    as comparable that a trader would not accept as comparable.
    """
    want_type, want_grade, want_thickness = spec
    if not want_type or not want_grade or want_thickness is None:
        return False
    if not product_type or not grade or thickness is None:
        return False
    return (
        product_type.strip().lower() == want_type.strip().lower()
        and grade.strip().lower() == want_grade.strip().lower()
        and float(thickness) == float(want_thickness)
    )


def _describe(
    thickness: float | None, product_type: str | None, grade: str | None
) -> str | None:
    """A line as a trader says it: "12 mm TMT Fe500D"."""
    parts: list[str] = []
    if thickness:
        parts.append(f"{thickness:g} mm")
    if product_type:
        parts.append(product_type)
    if grade:
        parts.append(grade)
    return " ".join(parts) or None


def _round(value: Decimal | None) -> Decimal | None:
    return value.quantize(Decimal("0.01")) if value is not None else None
