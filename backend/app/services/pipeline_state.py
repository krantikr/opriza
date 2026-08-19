"""Which stage of the pipeline a piece of mail is stuck at.

The mailbox is a queue of work, not a filing cabinet. Every message resolves to
**exactly one** state, and leaves it the moment somebody acts:

    ENQUIRY   an enquiry arrived, no quotation has gone out yet
       |      ...we send the quotation
    FOLLOW_UP the quotation went out and the customer has not replied. The
       |      rule says when a nudge is owed; until then it is simply waiting
       |      ...they reply asking something
    NEEDS_REPLY  they asked; nobody has answered
       |      ...we answer
    DELIVERY  they confirmed the order and are waiting for the goods
       |      ...someone marks it despatched, or we reply
    COMPLAINT they complained; nobody has answered
       |      ...we answer
    DONE      nothing is owed by anybody

Two properties follow from this and are what make the tabs trustworthy:

* **A message is in one place.** No double-counting, so a tab's number is a
  true count of outstanding work rather than a view over the same mail.
* **An empty tab means done.** Under a filing scheme a tab is never empty, so
  its count says nothing; here, all tabs empty means the desk is clear.

Resolution is ordered by urgency, not by chronology - a complaint that also
awaits a reply is a complaint, because that is the more serious thing to see.
"""

from __future__ import annotations

from enum import StrEnum

from app.models import (
    Email,
    EmailCategory,
    FollowUpStatus,
    QuotationRequest,
    QuotationStatus,
)


class PipelineState(StrEnum):
    """The single stage a message is waiting at."""

    ENQUIRY = "ENQUIRY"
    FOLLOW_UP = "FOLLOW_UP"
    NEEDS_REPLY = "NEEDS_REPLY"
    DELIVERY = "DELIVERY"
    COMPLAINT = "COMPLAINT"
    #: Nothing is owed. Reachable only through All mail.
    DONE = "DONE"


#: A quotation that has gone out and not yet been settled by the customer.
IN_FLIGHT = (QuotationStatus.SENT, QuotationStatus.APPROVED)

#: Statuses meaning the quotation is still being worked on internally - the
#: enquiry stage, because nothing has reached the customer yet.
UNSENT = (
    QuotationStatus.NEW,
    QuotationStatus.PROCESSING,
    QuotationStatus.READY_FOR_REVIEW,
    QuotationStatus.NEEDS_INFORMATION,
    QuotationStatus.EDITED,
)


def resolve_state(email: Email) -> PipelineState:
    """Where this message is stuck, or DONE if nothing is owed.

    Ordered by what a trader most needs to see first. A complaint outranks a
    plain question; an unanswered question outranks a quotation gone quiet,
    because the customer is actively waiting in the first case and merely
    silent in the second.
    """
    answered = email.answered_at is not None

    # 1. A complaint nobody has answered. The most serious thing in the
    #    mailbox, so it is checked before anything else.
    if email.category is EmailCategory.COMPLAINT and not answered:
        return PipelineState.COMPLAINT

    quotation = _quotation_for(email)

    # 2. The customer asked something and is waiting on us.
    if email.awaiting_us and not answered:
        return PipelineState.NEEDS_REPLY

    if quotation is not None:
        # 3. They accepted and are waiting for the goods.
        if quotation.status is QuotationStatus.CUSTOMER_ACCEPTED and not quotation.despatched_at:
            return PipelineState.DELIVERY

        # 4. Nothing has gone out yet, so the enquiry is still ours to answer.
        if quotation.status in UNSENT:
            return PipelineState.ENQUIRY

        # 5. It went out and nobody has replied. Owed a chase now, or waiting
        #    on the clock - either way it is the trader's to keep an eye on.
        if quotation.status in IN_FLIGHT and _awaiting_reply(quotation):
            return PipelineState.FOLLOW_UP

    # An enquiry we have not managed to turn into a quotation at all still
    # needs a person - it must not vanish just because processing failed.
    if (
        email.category is EmailCategory.QUOTATION_REQUEST
        and quotation is None
        and not answered
    ):
        return PipelineState.ENQUIRY

    return PipelineState.DONE


def _quotation_for(email: Email) -> QuotationRequest | None:
    """The quotation this mail belongs to, whether it started it or replied to it."""
    return email.quotation_request or email.replied_to_quotation


#: A nudge that has not happened yet - either owed now, or on the clock.
PENDING_NUDGE = (FollowUpStatus.DUE, FollowUpStatus.SCHEDULED)


def _awaiting_reply(quotation: QuotationRequest) -> bool:
    """Whether this sent quotation is still waiting on the customer.

    A quotation belongs here from the moment it goes out, not only once its
    timer expires. Waiting until `DUE` left a sent quotation in no tab at all
    for the whole of its first interval - the trader had sent something, was
    owed a reply, and the mailbox showed nothing anywhere.

    Read from the scheduler's own queue rather than recomputed, so the tab and
    the follow-up screen can never disagree about what is outstanding.
    """
    return any(s.status in PENDING_NUDGE for s in quotation.follow_up_schedules)


def follow_up_is_due(quotation: QuotationRequest) -> bool:
    """Whether a nudge is owed *now* - the trader should act today.

    Distinct from being in the tab: everything in Follow up is waiting, but
    only some of it is overdue, and the interface says which is which.
    """
    return any(s.status is FollowUpStatus.DUE for s in quotation.follow_up_schedules)


__all__ = ["PipelineState", "follow_up_is_due", "resolve_state"]
