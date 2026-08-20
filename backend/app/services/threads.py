"""The conversation with a customer, in the order it happened.

A quotation is a correspondence, not a record. What a trader needs to see is
what a mail client shows: they asked, we quoted, they replied, we chased -
each message in sequence, with what changed as a result.

The pieces already exist, but in three tables that nobody joins:

* `Email` - what arrived, both the original enquiry and every reply
* `QuotationDraft` - what we sent, once approved and posted
* `FollowUp` - the nudges we sent when it went quiet

This assembles them into one ordered list. Deliberately a read-model: nothing
here writes, so the thread can never disagree with the pipeline state - it is
a second view of the same rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Email,
    FollowUp,
    MailDirection,
    QuotationDraft,
    QuotationRequest,
)


class MessageDirection(StrEnum):
    """Who wrote it. The single most important thing to see at a glance."""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MessageKind(StrEnum):
    """What the message was, which decides how it is presented."""

    ENQUIRY = "ENQUIRY"
    QUOTATION = "QUOTATION"
    REPLY = "REPLY"
    FOLLOW_UP = "FOLLOW_UP"


@dataclass(slots=True)
class ThreadMessage:
    """One message in the conversation."""

    id: str
    direction: MessageDirection
    kind: MessageKind
    at: datetime
    sender_name: str | None
    sender_email: str | None
    subject: str | None
    body: str | None
    #: Set on our own messages that were drafted but never actually sent, so
    #: an unsent draft is never mistaken for something the customer received.
    sent: bool = True
    #: What this message caused, in a few words: "Customer accepted",
    #: "Quotation sent". Shown beside the message rather than left implicit.
    outcome: str | None = None
    email_id: int | None = None
    has_attachments: bool = False


def thread_for_email(db: Session, email: Email) -> list[ThreadMessage]:
    """The conversation an inbox message belongs to.

    The mailbox works in emails, not quotations, so it needs its own way in.
    Where a quotation exists the full thread is built from it - that is the
    view with our sent quotations and nudges in it. Otherwise the messages
    sharing this mail thread are returned, so a conversation with no quotation
    (a delivery query, a complaint) still reads as a conversation rather than
    as one message in isolation.
    """
    quotation = email.quotation_request or email.replied_to_quotation
    if quotation is not None:
        return build_thread(db, quotation)

    if not email.thread_id:
        return [_from_email(email, MessageKind.ENQUIRY)]

    messages: list[ThreadMessage] = []
    for message in db.scalars(
        select(Email)
        .where(Email.thread_id == email.thread_id)
        .order_by(Email.received_at)
    ):
        if message.direction is MailDirection.OUTBOUND:
            messages.append(
                ThreadMessage(
                    id=f"email-{message.id}",
                    direction=MessageDirection.OUTBOUND,
                    kind=MessageKind.QUOTATION,
                    at=message.received_at,
                    sender_name="You",
                    sender_email=message.sender_email,
                    subject=message.subject,
                    body=message.body_text,
                    outcome="Sent from your mailbox",
                    email_id=message.id,
                    has_attachments=message.has_attachments,
                )
            )
        else:
            kind = MessageKind.ENQUIRY if message.id == email.id else MessageKind.REPLY
            messages.append(_from_email(message, kind))
    return messages


def build_thread(db: Session, quotation: QuotationRequest) -> list[ThreadMessage]:
    """Every message exchanged about this quotation, oldest first.

    Queried explicitly rather than read off relationships: this runs after
    writes in the same request, and a cached collection would miss the reply
    that was just recorded.
    """
    messages: list[ThreadMessage] = []

    # 1. The enquiry that started it.
    if quotation.email is not None:
        messages.append(_from_email(quotation.email, MessageKind.ENQUIRY))

    # 2. Every quotation we sent. Drafts that were never approved are left
    #    out - the thread shows the correspondence, not the working.
    drafts = db.scalars(
        select(QuotationDraft)
        .where(QuotationDraft.quotation_request_id == quotation.id)
        .order_by(QuotationDraft.version)
    )
    for draft in drafts:
        if quotation.sent_at is None:
            continue
        messages.append(
            ThreadMessage(
                id=f"draft-{draft.id}",
                direction=MessageDirection.OUTBOUND,
                kind=MessageKind.QUOTATION,
                at=quotation.sent_at,
                sender_name="You",
                # Looked up rather than read through a relationship:
                # `TenantMixin` supplies the column, not a mapped attribute.
                sender_email=_desk_address(db, quotation.organisation_id),
                subject=draft.subject,
                body=draft.body,
                outcome="Quotation sent",
            )
        )

    # 3. Everything else in the conversation - the customer's replies, and
    #    our own mail sent from Gmail rather than through this system.
    #
    #    Matched by mail thread rather than only by `replied_to_quotation_id`,
    #    because a trader who answers in Gmail creates a row nothing here
    #    linked. The thread is what a customer sees, so it is what the trader
    #    should see too.
    seen = {quotation.email_id}
    conversation = db.scalars(
        select(Email)
        .where(
            or_(
                Email.replied_to_quotation_id == quotation.id,
                Email.thread_id == quotation.email.thread_id
                if quotation.email is not None and quotation.email.thread_id
                else False,
            )
        )
        .order_by(Email.received_at)
    )
    for message in conversation:
        if message.id in seen:
            continue
        seen.add(message.id)
        if message.direction is MailDirection.OUTBOUND:
            messages.append(
                ThreadMessage(
                    id=f"email-{message.id}",
                    direction=MessageDirection.OUTBOUND,
                    kind=MessageKind.QUOTATION,
                    at=message.received_at,
                    sender_name="You",
                    sender_email=message.sender_email,
                    subject=message.subject,
                    body=message.body_text,
                    outcome="Sent from your mailbox",
                    email_id=message.id,
                    has_attachments=message.has_attachments,
                )
            )
        else:
            messages.append(_from_email(message, MessageKind.REPLY))

    # 4. Nudges we sent when it went quiet.
    follow_ups = db.scalars(
        select(FollowUp)
        .where(FollowUp.quotation_request_id == quotation.id)
        .order_by(FollowUp.created_at)
    )
    for nudge in follow_ups:
        messages.append(
            ThreadMessage(
                id=f"followup-{nudge.id}",
                direction=MessageDirection.OUTBOUND,
                kind=MessageKind.FOLLOW_UP,
                at=nudge.created_at,
                sender_name=nudge.user.name if nudge.user else "You",
                sender_email=None,
                subject=nudge.subject,
                body=nudge.body,
                sent=nudge.sent,
                outcome="Follow-up sent" if nudge.sent else "Follow-up not sent",
            )
        )

    # Chronological, because that is the only order a conversation reads in.
    messages.sort(key=lambda m: (m.at is None, m.at))
    return messages


def _desk_address(db: Session, organisation_id: int | None) -> str | None:
    """The address this desk sends from, for labelling our own messages."""
    from app.models import Organisation

    if organisation_id is None:
        return None
    org = db.get(Organisation, organisation_id)
    return org.company_email if org else None


def _from_email(email: Email, kind: MessageKind) -> ThreadMessage:
    return ThreadMessage(
        id=f"email-{email.id}",
        direction=MessageDirection.INBOUND,
        kind=kind,
        at=email.received_at,
        sender_name=email.sender_name,
        sender_email=email.sender_email,
        subject=email.subject,
        body=email.body_text,
        outcome=_reply_outcome(email),
        email_id=email.id,
        has_attachments=email.has_attachments,
    )


def _reply_outcome(email: Email) -> str | None:
    """What a customer's reply was understood to mean.

    Only what the model decided, phrased for a trader. Nothing is invented
    when there is no reading - an absent outcome is more honest than a guess.
    """
    if email.reply_intent is None:
        return None
    return {
        "ACCEPTED": "Customer accepted",
        "DECLINED": "Customer declined",
        "NEEDS_REVIEW": "Needs a person to read it",
    }.get(email.reply_intent.value)


#: Most urgent first. A conversation is at the earliest of these that any of
#: its messages is waiting at, which is the same ordering `resolve_state` uses
#: within a single message.
_URGENCY = (
    "COMPLAINT",
    "NEEDS_REPLY",
    "DELIVERY",
    "FOLLOW_UP",
    "ENQUIRY",
    "DONE",
)


def thread_state(db: Session, quotation: QuotationRequest) -> str:
    """Where the whole conversation stands, not just its first message.

    A customer's reply is a separate `Email` row, and it is that row which
    carries `NEEDS_REPLY`. Reading only the original enquiry - which is
    `DONE` once it has been quoted - would show a conversation that is
    actively waiting on us as finished, which is the one thing the mailbox
    exists to prevent.
    """
    from app.services.pipeline_state import resolve_state

    states = set()
    if quotation.email is not None:
        states.add(resolve_state(quotation.email).value)
    for reply in db.scalars(
        select(Email).where(Email.replied_to_quotation_id == quotation.id)
    ):
        states.add(resolve_state(reply).value)

    for candidate in _URGENCY:
        if candidate in states:
            return candidate
    return "DONE"


__all__ = [
    "MessageDirection",
    "thread_for_email",
    "MessageKind",
    "ThreadMessage",
    "build_thread",
    "thread_state",
]
