"""Which stage of the pipeline a piece of mail is stuck at.

The mailbox is a queue of work, not a filing cabinet. Every message resolves to
**exactly one** state, and leaves it the moment somebody acts:

    ENQUIRY   an enquiry arrived, no quotation has gone out yet
       |      ...we send the quotation
    FOLLOW_UP the quotation went out and the customer has not replied. When
       |      to chase is the trader's call; until then it is simply waiting
       |      ...they reply asking something
    NEEDS_REPLY  they asked; nobody has answered
       |      ...we answer
    DELIVERY  they confirmed the order and are waiting for the goods, or
       |      they are asking where it is
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
    MailDirection,
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

    # 2. A question about a despatch belongs with the other despatch work,
    #    not in the general reply queue - a trader chasing lorries wants them
    #    in one place. Checked before NEEDS_REPLY, which would otherwise
    #    swallow it.
    if (
        email.category is EmailCategory.DELIVERY_QUERY
        and email.awaiting_us
        and not answered
    ):
        return PipelineState.DELIVERY

    # 3. The customer asked something and is waiting on us.
    if email.awaiting_us and not answered:
        return PipelineState.NEEDS_REPLY

    if quotation is not None:
        # 4. They accepted and are waiting for the goods.
        if quotation.status is QuotationStatus.CUSTOMER_ACCEPTED and not quotation.despatched_at:
            return PipelineState.DELIVERY

        # 5. Nothing has gone out yet, so the enquiry is still ours to answer.
        if quotation.status in UNSENT:
            return PipelineState.ENQUIRY

        # 6. It went out and nobody has replied - the trader's to keep an
        #    eye on until the customer answers.
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


def _awaiting_reply(quotation: QuotationRequest) -> bool:
    """Whether this sent quotation is still waiting on the customer.

    Two halves, and both matter. It belongs here from the moment it goes out -
    there is no timer to consult any more, so a quotation is outstanding the
    instant it reaches the customer. But it stops being outstanding as soon as
    they answer: at that point the ball is back with us, and the reply's own
    row carries the conversation (NEEDS_REPLY until somebody deals with it).
    Counting a replied-to quotation as still "waiting on them" would leave a
    settled conversation permanently unfinished.
    """
    if quotation.sent_at is None:
        return False
    return not any(
        reply.direction is MailDirection.INBOUND for reply in quotation.replies
    )


def follow_up_is_due(quotation: QuotationRequest) -> bool:
    """Kept as the tab's "act today" marker.

    Nothing schedules a nudge any more, so nothing is ever *overdue* by the
    machine's reckoning - the trader decides. Always False rather than
    removed, because the Inbox still distinguishes "waiting" from "act now"
    and other signals may earn that flag later.
    """
    return False


__all__ = ["PipelineState", "follow_up_is_due", "resolve_state"]
