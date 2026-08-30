"""ORM -> DTO mapping.

Kept out of the route handlers so the API layer stays about HTTP, and so the
same shape is produced wherever a quotation is returned.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import (
    Approval,
    Customer,
    Email,
    FollowUp,
    FollowUpStatus,
    QuotationDraft,
    QuotationLineItem,
    QuotationRequest,
    StockItem,
)
from app.schemas.catalog import CustomerOut, StockItemOut
from app.schemas.pricing import PricingOut
from app.schemas.quotations import (
    ApprovalOut,
    AttachmentOut,
    DraftOut,
    EmailDetailOut,
    EmailOut,
    FollowUpOut,
    LineItemOut,
    QuotationDetailOut,
    QuotationOut,
    StockAvailabilityOut,
)
from app.services.pipeline_state import follow_up_is_due, resolve_state


def email_out(email: Email) -> EmailOut:
    quotation = email.quotation_request
    return EmailOut(
        id=email.id,
        message_id=email.message_id,
        thread_id=email.thread_id,
        source=email.source.value,
        sender_email=email.sender_email,
        sender_name=email.sender_name,
        subject=email.subject,
        snippet=email.snippet,
        received_at=email.received_at,
        category=email.category.value if email.category else None,
        classification_confidence=email.classification_confidence,
        classification_reason=email.classification_reason,
        processing_status=email.processing_status.value,
        processing_ms=email.processing_ms,
        error_message=email.error_message,
        has_attachments=email.has_attachments,
        quotation_id=quotation.id if quotation else None,
        quotation_number=quotation.quotation_number if quotation else None,
        quotation_status=quotation.status.value if quotation else None,
        # A rule decided this, so the mailbox agrees with the follow-up queue
        # rather than applying a second, subtly different definition.
        state=resolve_state(email).value,
        # Being in the Follow up tab and being overdue are different things:
        # everything there is waiting, only some of it is owed a nudge today.
        follow_up_due=bool(quotation and follow_up_is_due(quotation)),
        follow_up_at=next(
            (
                s.due_at
                for s in sorted(
                    quotation.follow_up_schedules, key=lambda s: s.due_at
                )
                if s.status in (FollowUpStatus.SCHEDULED, FollowUpStatus.DUE)
            ),
            None,
        )
        if quotation
        else None,
        replied_to_quotation_id=email.replied_to_quotation_id,
        reply_intent=email.reply_intent.value if email.reply_intent else None,
        reply_intent_confidence=email.reply_intent_confidence,
        reply_intent_reason=email.reply_intent_reason,
        promised_date_raw=email.promised_date_raw,
        promised_date=email.promised_date,
        awaiting_us=email.awaiting_us,
        answered_at=email.answered_at,
    )


def email_detail_out(email: Email) -> EmailDetailOut:
    return EmailDetailOut(
        **email_out(email).model_dump(),
        body_text=email.body_text,
        attachments=[
            AttachmentOut(
                id=a.id,
                filename=a.filename,
                mime_type=a.mime_type,
                size_bytes=a.size_bytes,
                has_text=bool(a.extracted_text),
                extraction_error=a.extraction_error,
            )
            for a in email.attachments
        ],
    )


def stock_availability_out(item: QuotationLineItem) -> StockAvailabilityOut | None:
    availability = item.stock_availability
    if availability is None:
        return None
    return StockAvailabilityOut(
        available_qty_mt=availability.available_qty_mt,
        on_hand_qty_mt=availability.on_hand_qty_mt,
        reserved_qty_mt=availability.reserved_qty_mt,
        available_nop=availability.available_nop,
        sufficient=availability.sufficient,
        locations=availability.locations or [],
        ageing_min_days=availability.ageing_min_days,
        ageing_max_days=availability.ageing_max_days,
        lot_count=availability.lot_count,
        suggested_rate=availability.suggested_rate,
        currency=availability.currency,
        unit=availability.unit.value,
        confidence=availability.confidence.value if availability.confidence else None,
        requires_manual_review=availability.requires_manual_review,
        rules_version=availability.rules_version,
        explanation=availability.explanation,
        breakdown=availability.breakdown or [],
        stock_as_of=availability.stock_as_of,
    )


def line_item_out(item: QuotationLineItem) -> LineItemOut:
    stock_item = item.matched_stock_item
    return LineItemOut(
        id=item.id,
        line_no=item.line_no,
        raw_text=item.raw_text,
        product_type=item.product_type,
        grade=item.grade,
        standard=item.standard,
        thickness_mm=item.thickness_mm,
        width_mm=item.width_mm,
        length_mm=item.length_mm,
        diameter_mm=item.diameter_mm,
        quantity=item.quantity,
        quantity_unit=item.quantity_unit.value,
        quantity_mt=item.quantity_mt,
        conversion_basis=item.conversion_basis,
        remarks=item.remarks,
        match_status=item.match_status.value,
        match_score=item.match_score,
        matched_stock_item_id=item.matched_stock_item_id,
        matched_stock_item_name=stock_item.display_name if stock_item else None,
        matched_stock_item_make=stock_item.make if stock_item else None,
        match_candidates=item.match_candidates or [],
        stock_availability=stock_availability_out(item),
        pricing=PricingOut.model_validate(item.pricing) if item.pricing else None,
    )


def draft_out(draft: QuotationDraft) -> DraftOut:
    return DraftOut(
        id=draft.id,
        version=draft.version,
        is_current=draft.is_current,
        subject=draft.subject,
        body=draft.body,
        status=draft.status.value,
        generated_by=draft.generated_by,
        created_at=draft.created_at,
    )


def approval_out(approval: Approval) -> ApprovalOut:
    return ApprovalOut(
        id=approval.id,
        action=approval.action.value,
        comments=approval.comments,
        was_edited=approval.was_edited,
        acted_at=approval.acted_at,
        user_name=approval.user.name if approval.user else None,
    )


def follow_up_out(follow_up: FollowUp) -> FollowUpOut:
    return FollowUpOut(
        id=follow_up.id,
        subject=follow_up.subject,
        body=follow_up.body,
        sent=follow_up.sent,
        sent_message_id=follow_up.sent_message_id,
        error=follow_up.error,
        created_at=follow_up.created_at,
        user_name=follow_up.user.name if follow_up.user else None,
    )


def _quotation_summary(quotation: QuotationRequest) -> tuple[Decimal | None, bool]:
    """Total indicative value and review flag.

    `QuotationPricing` wins where it exists: it is the figure the calculator
    settled on and the one the customer was actually quoted, whereas
    `StockAvailability.suggested_rate` is the cost-plus suggestion made before
    anybody reviewed it. Falling back to the suggestion keeps a line valued
    while it is still being worked on, and stops a priced quotation showing a
    dash in the list while its own detail pane shows a figure.
    """
    total: Decimal | None = None
    needs_review = False
    for item in quotation.line_items:
        availability = item.stock_availability
        if availability is not None:
            needs_review = needs_review or availability.requires_manual_review

        pricing = item.pricing
        if pricing is not None and pricing.line_total is not None:
            total = (total or Decimal(0)) + pricing.line_total
            continue

        if availability is None or availability.suggested_rate is None:
            continue
        basis = item.quantity_mt if item.quantity_mt is not None else availability.available_qty_mt
        if basis is not None:
            total = (total or Decimal(0)) + availability.suggested_rate * basis
    return total, needs_review


def _headline(item: QuotationLineItem | None) -> str | None:
    """What the line is about, in the words a trader uses.

    Prefers the matched lot's name, then the customer's own wording, and only
    then builds a description from the extracted specification - a line that
    matched nothing and whose raw text was not kept still has a grade and a
    thickness, and "12 mm TMT Fe500D" beats an empty cell.
    """
    if item is None:
        return None
    if item.matched_stock_item is not None:
        return item.matched_stock_item.display_name
    if item.raw_text:
        return item.raw_text[:80]

    parts: list[str] = []
    if item.thickness_mm:
        parts.append(f"{item.thickness_mm:g} mm")
    elif item.diameter_mm:
        parts.append(f"{item.diameter_mm:g} mm")
    if item.product_type:
        parts.append(item.product_type)
    if item.grade:
        parts.append(item.grade)
    return " ".join(parts) or None


def _availability_label(item: QuotationLineItem | None) -> str | None:
    if item is None:
        return None
    availability = item.stock_availability
    if availability is None or availability.available_qty_mt is None:
        return None
    if availability.available_qty_mt <= 0:
        return "Not available"
    if availability.sufficient is False:
        requested = item.quantity_mt
        if requested is not None:
            return f"Partial ({availability.available_qty_mt:g}/{requested:g} MT)"
        return f"Partial ({availability.available_qty_mt:g} MT)"
    return "In stock"


def quotation_out(
    quotation: QuotationRequest,
    priority_products: set[tuple[str, str]] | None = None,
) -> QuotationOut:
    """`priority_products` is a set of `(grade, make)` pairs the caller has
    already fetched once for the whole page - passed in rather than queried
    here so listing N quotations does not cost N extra lookups."""
    from app.services.quotations.stages import stage_of

    total, needs_review = _quotation_summary(quotation)
    first = quotation.line_items[0] if quotation.line_items else None
    pairs = priority_products or set()

    return QuotationOut(
        id=quotation.id,
        quotation_number=quotation.quotation_number,
        email_id=quotation.email_id,
        customer_id=quotation.customer_id,
        # Frozen at enquiry time, deliberately never falling back to the live
        # `Customer` row: a customer's name/company can be filled in or
        # corrected later, and a historical quotation must keep showing what
        # was actually true when it was raised, not today's value.
        customer_name=quotation.customer_name_raw,
        customer_company=quotation.customer_company_raw,
        customer_email=quotation.customer_email,
        status=quotation.status.value,
        stage=stage_of(quotation),
        confidence=quotation.confidence.value if quotation.confidence else None,
        delivery_location=quotation.delivery_location,
        line_count=len(quotation.line_items),
        total_suggested_value=total,
        headline_product=_headline(first),
        headline_availability=_availability_label(first),
        requires_manual_review=needs_review,
        not_sent_reason=quotation.not_sent_reason.value if quotation.not_sent_reason else None,
        not_sent_note=quotation.not_sent_note,
        is_priority_customer=bool(quotation.customer and quotation.customer.is_priority),
        is_priority_product=any(
            (item.grade, item.matched_stock_item.make) in pairs
            for item in quotation.line_items
            if item.matched_stock_item
        ),
        line_items=[line_item_out(item) for item in quotation.line_items],
        created_at=quotation.created_at,
        sent_at=quotation.sent_at,
    )


def quotation_detail_out(
    quotation: QuotationRequest,
    priority_products: set[tuple[str, str]] | None = None,
) -> QuotationDetailOut:
    drafts = sorted(quotation.drafts, key=lambda d: d.version, reverse=True)
    approvals = [a for draft in quotation.drafts for a in draft.approvals]

    return QuotationDetailOut(
        **quotation_out(quotation, priority_products).model_dump(),
        required_delivery_date=quotation.required_delivery_date,
        payment_terms=quotation.payment_terms,
        additional_requirements=quotation.additional_requirements or [],
        missing_information=quotation.missing_information or [],
        review_notes=quotation.review_notes,
        send_error=quotation.send_error,
        email=email_detail_out(quotation.email) if quotation.email else None,
        replies=[email_detail_out(reply) for reply in quotation.replies],
        current_draft=draft_out(quotation.current_draft) if quotation.current_draft else None,
        drafts=[draft_out(d) for d in drafts],
        approvals=[
            approval_out(a) for a in sorted(approvals, key=lambda a: a.id, reverse=True)
        ],
        follow_ups=[
            follow_up_out(f)
            for f in sorted(quotation.follow_ups, key=lambda f: f.created_at, reverse=True)
        ],
    )


def stock_item_out(item: StockItem) -> StockItemOut:
    return StockItemOut(
        id=item.id,
        product_type=item.product_type,
        grade=item.grade,
        thickness_mm=item.thickness_mm,
        width_mm=item.width_mm,
        length_mm=item.length_mm,
        diameter_mm=item.diameter_mm,
        location=item.location,
        make=item.make,
        coil_no=item.coil_no,
        nop=item.nop,
        qty_kg=item.qty_kg,
        balance_nop=item.balance_nop,
        balance_qty_kg=item.balance_qty_kg,
        purchase_rate_per_kg=item.purchase_rate_per_kg,
        landed_cost_per_kg=item.landed_cost_per_kg,
        ageing_days=item.ageing_days,
        stock_date=item.stock_date,
        curr_dt=item.curr_dt,
        display_name=item.display_name,
    )


def customer_out(customer: Customer) -> CustomerOut:
    return CustomerOut(
        id=customer.id,
        customer_code=customer.customer_code,
        name=customer.name,
        email=customer.email,
        phone=customer.phone,
        company=customer.company,
        default_delivery_location=customer.default_delivery_location,
        tier=customer.tier.value,
        payment_terms=customer.payment_terms,
        status=customer.status.value,
        is_verified=customer.is_verified,
        is_priority=customer.is_priority,
    )
