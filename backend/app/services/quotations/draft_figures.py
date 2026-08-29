"""Keeping a stored draft's figures in step with the pricing behind it.

A draft is written once and then lives as text. The item table inside it is
spliced in at generation time, which means the numbers a customer would read
are a copy, taken at that moment, of what the calculator then held.

Everything downstream of the draft rebuilds itself from the live pricing - the
PDF and the HTML part are both rendered from `build_rows` at send time - so the
draft body was the one surface that could still show a superseded figure. In
practice that is the common case rather than the rare one: an enquiry that
arrives without a delivery location or payment terms cannot be priced, its
draft goes out with an empty Rate column, and supplying those terms afterwards
re-priced every line without touching the sentence the reviewer was looking at.

This module closes that gap. It re-splices the table and leaves the prose
alone, because the table is arithmetic this system owns and the prose is not.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import DraftStatus, Organisation, QuotationDraft, QuotationRequest
from ai.guards import find_stale_prices
from app.services.quotations.templates import render_quotation_body
from app.services.quotations.table import (
    build_rows,
    prose_only,
    render_text,
    retable_text,
    totals,
)

logger = get_logger(__name__)

#: Drafts whose text is still ours to correct. An approved or sent draft is the
#: record of what the customer was actually told, and rewriting it would
#: destroy the only evidence of what was promised - the same reason
#: `_require_unsent` guards the pricing endpoints.
_EDITABLE = {DraftStatus.GENERATED, DraftStatus.EDITED}


def refresh_draft_figures(
    db: Session, quotation: QuotationRequest, *, commit: bool = False
) -> QuotationDraft | None:
    """Rewrite the current draft's table from the pricing as it now stands.

    Returns the draft when its body changed, and None when there was nothing to
    do - no current draft, a draft already sent, or a table that already agreed
    with the figures. Callers use that to decide whether to tell the reviewer
    anything; a no-op must stay silent, or the notice becomes noise.

    `draft_stale` is deliberately *not* cleared here. It marks that the prose
    was written against different numbers, and that can remain true even once
    the table is right: an opening line reading "we are pleased to quote" over
    a line that has since lost its price is still wrong in a way only
    regeneration fixes. The flag keeps offering that; this just stops the
    figures themselves from being wrong in the meantime.
    """
    draft = db.scalar(
        select(QuotationDraft).where(
            QuotationDraft.quotation_request_id == quotation.id,
            QuotationDraft.is_current.is_(True),
        )
    )
    if draft is None or draft.status not in _EDITABLE:
        return None

    rows = build_rows(quotation)

    # Two paths, and which one applies is decided by whether the draft still
    # has the template it was generated from.
    #
    # With one, every figure re-renders - the rate in a sentence as much as
    # the one in the table - because the model's prose was stored with the
    # money held behind placeholders. That is the whole point: the LLM ran
    # once, to answer what this customer asked, and no later price change
    # needs it again.
    #
    # Without one - a draft written before this existed, or a body a reviewer
    # has since edited by hand - only the table is re-spliced, as before.
    # Re-rendering someone's edited text from a template they never saw would
    # discard their wording, which is worse than leaving a figure for the
    # stale-price check to flag.
    if draft.body_template:
        organisation = (
            db.get(Organisation, quotation.organisation_id)
            if quotation.organisation_id
            else None
        )
        rendered = render_quotation_body(draft.body_template, quotation, organisation)
        updated = retable_text(rendered, rows)
    else:
        updated = retable_text(draft.body or "", rows)

    if updated == draft.body:
        return None

    logger.info(
        "Refreshed the item table on draft v%s of %s to match current pricing.",
        draft.version,
        quotation.quotation_number,
    )
    draft.body = updated
    db.flush()
    if commit:
        db.commit()
    return draft


def current_figures(quotation: QuotationRequest) -> list[Decimal]:
    """Every money figure the draft is currently allowed to state.

    Rates and line amounts from the table, the order total, and the pricing
    build-up's own components - a draft may legitimately mention freight or a
    loading charge, and those are current figures even though they never
    appear in the customer-facing table.
    """
    values: list[Decimal] = []
    rows = build_rows(quotation)

    for row in rows:
        for figure in (row.rate, row.amount):
            if figure is not None:
                values.append(Decimal(str(figure)))

    _, total_amount = totals(rows)
    if total_amount is not None:
        values.append(Decimal(str(total_amount)))

    for item in quotation.line_items:
        # The stock check's own suggested rate. It is what the draft was
        # written from when the calculator had not priced the line, and
        # `_row_for` falls back to it for the table, so it is current by the
        # same definition the customer-facing document uses.
        availability = item.stock_availability
        if availability is not None and availability.suggested_rate is not None:
            values.append(Decimal(str(availability.suggested_rate)))

        pricing = item.pricing
        if pricing is None:
            continue
        for figure in (pricing.quote_rate, pricing.line_total, pricing.base_rate,
                       pricing.total_cost, pricing.margin_amount):
            if figure is not None:
                values.append(Decimal(str(figure)))
        for component in pricing.components or []:
            amount = component.get("amount")
            if amount is not None:
                try:
                    values.append(Decimal(str(amount)))
                except (ArithmeticError, ValueError):
                    continue

    return values


def stale_prices_in_draft(quotation: QuotationRequest, body: str) -> list[str]:
    """Money figures in the draft's prose that the calculator no longer holds.

    The table is stripped first: it is re-rendered from the pricing on every
    change, so checking it would only compare the figures against themselves.
    """
    return find_stale_prices(prose_only(body), current_figures(quotation))


def draft_shows_prices(quotation: QuotationRequest) -> bool:
    """Whether the current figures would put a Rate column on the document."""
    return any(row.priced for row in build_rows(quotation))


__all__ = [
    "current_figures",
    "draft_shows_prices",
    "refresh_draft_figures",
    "render_text",
    "stale_prices_in_draft",
]
