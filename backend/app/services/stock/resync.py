"""Bringing open quotations back in step after the stock behind them moves.

A quotation is priced from the floor as it stood at the moment it was raised.
When the floor changes - a lot's landed cost is corrected, or the whole sheet is
re-imported for the month - every quotation still on the desk is quoting a
number that no longer reflects what the material costs.

Two failures were possible before this existed:

* **A silent stale price.** Nothing watched stock, so the stored figure simply
  stayed as it was. The reviewer saw a confident rate with no indication that it
  was computed against a cost the business no longer pays.
* **A silently unmatched line.** The stock import replaces the table wholesale,
  detaching every `matched_stock_item_id` first because the foreign key would
  otherwise refuse the delete. Nothing re-matched them afterwards, so a routine
  monthly import left open quotations pointing at nothing and re-pricing to
  "no base price available".

Both are repaired here, and only for quotations that have **not** gone out.
A sent quotation is a commitment: its figures are the record of what was
actually offered, and re-pricing it would overwrite that record with a number
the customer never saw.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import (
    PRICING_FROZEN_STATUSES,
    MatchStatus,
    QuotationRequest,
)
from app.services.pricing.service import PricingService
from app.services.quotations.draft_figures import refresh_draft_figures
from app.services.products.matcher import ProductMatcher

logger = get_logger(__name__)


@dataclass(slots=True)
class ResyncResult:
    """What the pass changed, for the caller to report."""

    quotations_examined: int = 0
    quotations_repriced: int = 0
    lines_rematched: int = 0
    drafts_flagged: int = 0
    quotation_numbers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "quotations_examined": self.quotations_examined,
            "quotations_repriced": self.quotations_repriced,
            "lines_rematched": self.lines_rematched,
            "drafts_flagged": self.drafts_flagged,
            "quotation_numbers": self.quotation_numbers,
        }


class StockResyncService:
    """Re-match and re-price the open book against the floor as it stands now."""

    def __init__(self, db: Session, matcher: ProductMatcher | None = None) -> None:
        self.db = db
        self.matcher = matcher or ProductMatcher(db)

    def resync_open_quotations(self, *, rematch: bool = True) -> ResyncResult:
        """Bring every unsent quotation back in step with current stock.

        `rematch` is on by default because the common caller is a stock import,
        which has just detached every line. A caller that only edited one lot's
        cost can skip it: the matches are still valid, and re-running the
        matcher would churn `match_candidates` for no gain.
        """
        result = ResyncResult()
        pricing = PricingService(self.db)

        quotations = list(
            self.db.scalars(
                select(QuotationRequest).where(
                    QuotationRequest.status.not_in(PRICING_FROZEN_STATUSES)
                )
            )
        )

        for quotation in quotations:
            result.quotations_examined += 1
            changed = False

            for item in quotation.line_items:
                lot_ids: list[int] = []

                if rematch:
                    outcome = self.matcher.match_line_item(item)
                    new_id = outcome.stock_item.id if outcome.stock_item else None
                    if new_id != item.matched_stock_item_id:
                        result.lines_rematched += 1
                    item.match_status = outcome.status
                    item.match_score = outcome.score
                    item.match_candidates = outcome.candidates_as_json()
                    item.matched_stock_item_id = new_id
                    lot_ids = (
                        outcome.lot_ids
                        if outcome.status is MatchStatus.MATCH_FOUND
                        else []
                    )

                before = item.pricing.quote_rate if item.pricing else None
                record = pricing.price_line(
                    item, quotation=quotation, lot_ids=lot_ids or None
                ).record
                if record.quote_rate != before:
                    changed = True

            if changed:
                result.quotations_repriced += 1
                result.quotation_numbers.append(quotation.quotation_number)
                # `price_line` already sets draft_stale when a rate moves; count
                # it here so the caller can say how many drafts need rewriting.
                #
                # The table inside that draft is refreshed rather than left for
                # the rewrite: stock moving is exactly when a reviewer is least
                # likely to reread a draft they had already approved of, and a
                # stale Rate column is the figure a customer would act on.
                if quotation.current_draft is not None:
                    result.drafts_flagged += 1
                    refresh_draft_figures(self.db, quotation)

        self.db.commit()
        logger.info(
            "Stock resync: %s examined, %s repriced, %s lines rematched.",
            result.quotations_examined,
            result.quotations_repriced,
            result.lines_rematched,
        )
        return result


__all__ = ["StockResyncService", "ResyncResult"]
