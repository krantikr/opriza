"""The five working stages a trader thinks in.

The status machine has grown to fourteen states because it records what
happened - a draft was edited, a send failed, a customer declined. That is the
right level of detail for an audit trail and the wrong one for a dashboard: a
trader does not run a desk by counting EDITED and APPROVED separately, they
ask how much is waiting to be answered, how much is out, and how much money is
still to come in.

So the stages are a *view* over the statuses, defined once here and read by
both the dashboard and the board. Nothing stores a stage; deriving it means a
quotation cannot be in a state its stage disagrees with.

The order is the order of the working day, and it is the order they appear on
screen - money moves left to right, from an enquiry nobody has answered to
cash that has not arrived.
"""

from __future__ import annotations

from app.models import QuotationStatus as Q

#: `(key, label, statuses)`, in the order a desk reads them.
COMMERCIAL_STAGES: tuple[tuple[str, str, tuple[Q, ...]], ...] = (
    (
        "received",
        "Quotations received",
        # Everything that has arrived and not yet gone back out, including the
        # ones still being worked on. A quotation waiting on a missing
        # delivery address is as unanswered, to the customer, as one nobody
        # has looked at.
        (Q.NEW, Q.PROCESSING, Q.NEEDS_INFORMATION, Q.READY_FOR_REVIEW, Q.EDITED, Q.APPROVED),
    ),
    (
        "sent",
        "Quotations sent",
        # Out with the customer, no reply yet. Not "everything ever sent" -
        # that is a historical total, and a stage that only grows tells a
        # trader nothing about today.
        (Q.SENT,),
    ),
    ("negotiation", "Negotiation", (Q.NEGOTIATION,)),
    (
        "delivery_pending",
        "Delivery pending",
        # Won, and the steel has not left. `despatched_at` is what actually
        # ends this stage, so the count filters on it too - see `stage_of`.
        (Q.CUSTOMER_ACCEPTED,),
    ),
    ("payment_pending", "Payment pending", (Q.PAYMENT_PENDING,)),
)

#: Stages a trader may set by hand. Every one of them, deliberately: a deal is
#: agreed on the phone as often as by email, and a board that cannot be
#: corrected is one that stops being trusted and then stops being used.
#:
#: The status is what moves; the record of what was actually sent - the draft,
#: the approval, the message id - is untouched by it, so an honest audit trail
#: survives a trader dragging a card.
SETTABLE = tuple(key for key, _, _ in COMMERCIAL_STAGES) + ("won", "lost")

_BY_STATUS: dict[Q, str] = {
    status: key for key, _, statuses in COMMERCIAL_STAGES for status in statuses
}

#: Stage keys to the status a manual move should write.
STATUS_FOR_STAGE: dict[str, Q] = {
    "received": Q.READY_FOR_REVIEW,
    "sent": Q.SENT,
    "negotiation": Q.NEGOTIATION,
    "delivery_pending": Q.CUSTOMER_ACCEPTED,
    "payment_pending": Q.PAYMENT_PENDING,
    "won": Q.PAID,
    "lost": Q.CUSTOMER_DECLINED,
}

LABELS: dict[str, str] = {key: label for key, label, _ in COMMERCIAL_STAGES}


def stage_of(quotation) -> str | None:
    """Which working stage this quotation is in, or None if it is settled.

    Despatch is read here rather than being another status: an accepted
    quotation whose goods have gone is no longer "delivery pending" even
    though nobody changed its status, and making the dashboard say otherwise
    would have a trader chasing a lorry that left last week.
    """
    status = quotation.status

    if status is Q.CUSTOMER_ACCEPTED and getattr(quotation, "despatched_at", None) is not None:
        # Despatched but not marked paid: the money is what is outstanding.
        return "payment_pending"

    return _BY_STATUS.get(status)


__all__ = ["COMMERCIAL_STAGES", "LABELS", "SETTABLE", "STATUS_FOR_STAGE", "stage_of"]
