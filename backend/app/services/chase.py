"""Which open quotations are owed a chase, and in what order.

The Follow-ups screen used to list `FollowUpSchedule` rows: nudges a rule had
already decided were due. That is the machine's to-do list, not the trader's.
Two things went wrong with it.

* **The dangerous quotations were invisible.** A customer replying *cancels*
  the schedule (`FollowUpScheduler._cancel_settled`), so the single most urgent
  thing on a desk - somebody waiting on an answer - was the one thing the
  screen could never show.
* **Chronological order fought the trader.** `order_by(due_at)` puts a ₹2,000
  nudge above an ₹18 lakh quotation because it went overdue an hour earlier.

So the row here is the **quotation**, and a due schedule is merely one of the
signals that makes it hot. The states mirror `pipeline_state.resolve_state`:
exactly one per quotation, resolved by urgency rather than chronology, and a
quotation leaves the moment somebody acts on it.

    YOURS   they replied, sent an order, or the date they promised has passed
            - and nobody has answered
    THEIRS  you answered; the ball is with them, and it has gone quiet
    COLD    nothing has moved for a long time; chase hard or write it off
    SNOOZED deliberately parked until a date the trader chose

Ordering is by **money at risk**, not time: value weighted by whose turn it is,
how long it has been quiet, and how good the customer is. `ChaseRow.score`
carries its own factor breakdown so the UI can show why a row ranked where it
did - an unexplained ranking is one a trader stops trusting, and a ranking he
does not trust is one he scrolls past.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import (
    Customer,
    Email,
    EmailCategory,
    FollowUp,
    FollowUpRule,
    FollowUpSchedule,
    FollowUpStatus,
    MailDirection,
    QuotationRequest,
    QuotationStatus,
)

# --------------------------------------------------------------------------
# States
# --------------------------------------------------------------------------


class ChaseTurn(StrEnum):
    """Whose move it is. Exactly one per quotation."""

    YOURS = "YOURS"
    THEIRS = "THEIRS"
    COLD = "COLD"
    SNOOZED = "SNOOZED"


#: Past this many days with no movement a quotation is cold: worth one last
#: decision, not a fifth polite nudge.
COLD_AFTER_DAYS = 21

#: A quotation only appears once it has actually reached the customer. Before
#: that it is the Inbox's problem, not the chase list's.
IN_FLIGHT = (QuotationStatus.SENT, QuotationStatus.APPROVED)

#: The customer has decided. Nothing is owed either way.
SETTLED = (
    QuotationStatus.CUSTOMER_ACCEPTED,
    QuotationStatus.CUSTOMER_DECLINED,
    QuotationStatus.REJECTED,
)

#: Inbound categories that mean the customer is actively waiting on us. An
#: order outranks a question outranks a haggle, but all three are our move.
AWAITING_US = (
    EmailCategory.ORDER,
    EmailCategory.COMPLAINT,
    EmailCategory.PRICE_NEGOTIATION,
    EmailCategory.QUOTATION_REQUEST,
    EmailCategory.DELIVERY_QUERY,
    EmailCategory.PAYMENT_QUERY,
)


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------


@dataclass(slots=True)
class ScoreFactor:
    """One multiplier, named so the UI can show its working."""

    label: str
    factor: float


@dataclass(slots=True)
class ChaseRow:
    quotation_id: int
    quotation_number: str
    turn: ChaseTurn

    customer_name: str
    customer_email: str | None
    contact_name: str | None

    #: "regular · 210 MT this year" / "new · first enquiry". Relationship in
    #: one phrase, because a stranger and a repeat buyer are not the same row.
    customer_note: str
    quotes_total: int
    quotes_won: int

    material: str
    quantity: str
    quoted_rate: float | None
    value: float

    #: Why this is on screen at all, as a sentence a person would say.
    reason: str
    #: What to do about it, in the imperative. The row's most useful text: a
    #: body snippet was tried first and turned out to be worthless - two
    #: clamped lines of a mail is usually the salutation ("Dear Kranti Kumar,")
    #: and never the ask.
    next_step: str

    #: The last thing that happened on the thread, either direction. Date and
    #: time, not a paraphrase - "who moved last, and when" is the question a
    #: trader actually asks, and it is answerable exactly.
    last_at: datetime | None
    last_direction: str | None
    #: "They replied" / "You quoted" / "You chased".
    last_actor: str
    last_subject: str | None
    message_count: int

    sent_at: datetime | None
    #: Age of the quotation itself, distinct from how long the ball has sat.
    quote_age_days: int
    days_waiting: int
    #: Short label under the age: what the clock is actually counting.
    waiting_note: str
    #: When the desk gives up chasing (`FollowUpRule.stop_after_days`). This
    #: is *not* price validity, which the system does not record - see
    #: `_validity`. Silent unless the deadline is near enough to matter.
    chase_until: date | None
    chase_note: str | None

    delivery_location: str | None
    required_by: str | None
    payment_terms: str | None

    #: Whether the yard can actually cover what was quoted. Chasing an order
    #: that cannot be filled is worse than not chasing it.
    stock_note: str | None
    stock_short: bool

    promised_date: date | None
    promised_words: str | None
    snoozed_until: date | None
    has_attachment: bool
    attempts: int
    last_chased_at: datetime | None
    schedule_id: int | None

    value_at_risk: float
    factors: list[ScoreFactor] = field(default_factory=list)


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------


class ChaseService:
    """Builds the chase board: every open quotation, bucketed and scored."""

    def __init__(self, db: Session, *, now: datetime | None = None) -> None:
        self.db = db
        self.now = now or utcnow()

    # -- public ------------------------------------------------------------

    def board(self) -> list[ChaseRow]:
        """Every open quotation, most money at risk first."""
        rows = [self._row(q) for q in self._open_quotations()]
        rows.sort(key=lambda r: r.value_at_risk, reverse=True)
        return rows

    def counts(self, rows: list[ChaseRow]) -> dict[str, int]:
        return {
            turn.value: sum(1 for r in rows if r.turn is turn) for turn in ChaseTurn
        }

    # -- selection ---------------------------------------------------------

    def _open_quotations(self) -> list[QuotationRequest]:
        """Quotations that reached the customer and are not yet settled.

        Queried explicitly rather than walked off a relationship: the board is
        built after writes in the same request (sending a follow-up, then
        re-reading the list), and a cached collection would miss them.
        """
        return list(
            self.db.scalars(
                select(QuotationRequest)
                .where(
                    QuotationRequest.status.in_(IN_FLIGHT),
                    QuotationRequest.sent_at.is_not(None),
                    QuotationRequest.despatched_at.is_(None),
                )
                .order_by(QuotationRequest.sent_at.desc())
            )
        )

    # -- one row -----------------------------------------------------------

    def _row(self, q: QuotationRequest) -> ChaseRow:
        latest = self._latest_message(q)
        turn, reason, waiting_from, waiting_note = self._resolve(q, latest)

        days = max(0, (self.now - waiting_from).days) if waiting_from else 0
        customer = q.customer
        won, total = self._history(q)

        material, quantity, rate, value = self._what(q)
        stock_note, stock_short = self._stock(q)
        last_nudge = self._last_nudge(q)
        chase_until, chase_note = self._validity(q)

        # The last movement on the thread is our own quotation when nothing
        # has come back since - otherwise the row would read as though the
        # conversation had never started.
        last_at = latest.received_at if latest is not None else q.sent_at
        last_direction = latest.direction.value if latest is not None else "OUTBOUND"
        last_subject = latest.subject if latest is not None else None
        if latest is None and last_nudge is not None and q.sent_at and last_nudge > q.sent_at:
            last_at, last_subject = last_nudge, None

        row = ChaseRow(
            quotation_id=q.id,
            quotation_number=q.quotation_number,
            turn=turn,
            customer_name=(
                q.customer_company_raw
                or (customer.name if customer else None)
                or q.customer_name_raw
                or q.customer_email
                or "Unknown"
            ),
            customer_email=q.customer_email,
            contact_name=q.customer_name_raw,
            customer_note=self._customer_note(customer, total, won),
            quotes_total=total,
            quotes_won=won,
            material=material,
            quantity=quantity,
            quoted_rate=rate,
            value=value,
            reason=reason,
            next_step=self._next_step(q, turn, latest, stock_short),
            last_at=last_at,
            last_direction=last_direction,
            last_actor=_actor(latest, last_nudge, q),
            last_subject=last_subject,
            message_count=self._message_count(q),
            sent_at=q.sent_at,
            quote_age_days=max(0, (self.now - q.sent_at).days) if q.sent_at else 0,
            days_waiting=days,
            waiting_note=waiting_note,
            chase_until=chase_until,
            chase_note=chase_note,
            delivery_location=q.delivery_location,
            required_by=q.required_delivery_date,
            payment_terms=q.payment_terms,
            stock_note=stock_note,
            stock_short=stock_short,
            promised_date=q.promised_date,
            promised_words=latest.promised_date_raw if latest is not None else None,
            snoozed_until=getattr(q, "snoozed_until", None),
            has_attachment=bool(latest and latest.has_attachments),
            attempts=self._attempts(q),
            last_chased_at=last_nudge,
            schedule_id=self._due_schedule_id(q),
            value_at_risk=0.0,
        )
        row.factors = self._factors(row)
        row.value_at_risk = row.value * _product(row.factors)
        return row

    # -- whose turn --------------------------------------------------------

    def _resolve(
        self, q: QuotationRequest, latest: Email | None
    ) -> tuple[ChaseTurn, str, datetime | None, str]:
        """One state per quotation, resolved by urgency.

        Order matters and is deliberate: an unanswered customer outranks a
        passed promise, which outranks a rule's nudge, which outranks plain
        silence. It mirrors `pipeline_state.resolve_state`, where a complaint
        outranks a question outranks a quotation gone quiet.
        """
        snoozed = getattr(q, "snoozed_until", None)
        if snoozed and snoozed > self.now.date():
            return (
                ChaseTurn.SNOOZED,
                f"Parked until {snoozed:%-d %b} at your request.",
                q.sent_at,
                "snoozed",
            )

        # 1. They wrote and nobody has answered. The bucket that loses deals.
        #
        # `answered_at` is the authority, matching `pipeline_state`: it is what
        # replying clears, so the two screens agree on when a customer stops
        # waiting. Direction is the fallback rather than `awaiting_us`, which
        # only classified mail carries - a reply the AI has not read yet is
        # still a customer waiting, and must not be silently dropped here.
        if (
            latest is not None
            and latest.direction is MailDirection.INBOUND
            and latest.answered_at is None
        ):
            return (
                ChaseTurn.YOURS,
                self._inbound_reason(latest),
                latest.received_at,
                _inbound_note(latest),
            )

        # 2. They named a date to come back and it has gone by.
        if q.promised_date is not None and q.promised_date < self.now.date():
            gone = (self.now.date() - q.promised_date).days
            return (
                ChaseTurn.YOURS,
                f"They promised to decide on {q.promised_date:%-d %b}. "
                f"That was {_plural(gone, 'day')} ago.",
                datetime.combine(q.promised_date, datetime.min.time()).replace(
                    tzinfo=self.now.tzinfo
                ),
                "past promise",
            )

        # 3. A rule says a nudge is owed and it is still sitting in the queue.
        schedule_id = self._due_schedule_id(q)
        if schedule_id is not None:
            return (
                ChaseTurn.YOURS,
                "A nudge is due and waiting for you to send it.",
                q.sent_at,
                "nudge due",
            )

        # 4. Nothing has moved for a long time.
        quiet_since = self._last_activity(q)
        quiet_days = max(0, (self.now - quiet_since).days) if quiet_since else 0
        if quiet_days >= COLD_AFTER_DAYS:
            attempts = self._attempts(q)
            chased = (
                f", chased {_plural(attempts, 'time')}" if attempts else ", never chased"
            )
            return (
                ChaseTurn.COLD,
                f"Sent {_plural(quiet_days, 'day')} ago{chased}, no reply.",
                quiet_since,
                "gone cold",
            )

        # 5. You answered; it is their move.
        attempts = self._attempts(q)
        chased = f" Chased {_plural(attempts, 'time')}." if attempts else ""
        return (
            ChaseTurn.THEIRS,
            f"Sent {_plural(quiet_days, 'day')} ago, no reply.{chased}",
            quiet_since,
            "no reply",
        )

    def _inbound_reason(self, latest: Email) -> str:
        """What they sent, said the way a trader would say it."""
        days = max(0, (self.now - latest.received_at).days) if latest.received_at else 0
        when = "today" if days == 0 else f"{_plural(days, 'day')} ago"

        if latest.category is EmailCategory.ORDER:
            what = "sent a purchase order" if latest.has_attachments else "confirmed the order"
            return f"They {what} {when} and nobody has opened it."
        if latest.category is EmailCategory.COMPLAINT:
            return f"They complained {when} and nobody has answered."
        if latest.category is EmailCategory.PRICE_NEGOTIATION:
            return f"They came back on price {when} and nobody has answered."
        if latest.category in (EmailCategory.DELIVERY_QUERY, EmailCategory.PAYMENT_QUERY):
            return f"They asked a question {when} and nobody has answered."
        return f"They replied {when} and nobody has answered."

    # -- supporting reads --------------------------------------------------

    def _latest_message(self, q: QuotationRequest) -> Email | None:
        """The newest message in the conversation, either direction.

        Matched on thread as well as on the reply link, because a trader who
        answers from Gmail creates a row nothing in here linked - and if we
        miss it we will chase a customer who has already been answered.
        """
        clauses = [Email.replied_to_quotation_id == q.id]
        if q.email is not None and q.email.thread_id:
            clauses.append(Email.thread_id == q.email.thread_id)

        return self.db.scalars(
            select(Email)
            .where(or_(*clauses), Email.id != q.email_id)
            .order_by(Email.received_at.desc())
            .limit(1)
        ).first()

    def _last_activity(self, q: QuotationRequest) -> datetime | None:
        """When anything last happened: the quotation, a nudge, or a reply."""
        stamps = [q.sent_at]
        latest = self._latest_message(q)
        if latest is not None:
            stamps.append(latest.received_at)
        nudge = self.db.scalars(
            select(FollowUp)
            .where(FollowUp.quotation_request_id == q.id, FollowUp.sent.is_(True))
            .order_by(FollowUp.created_at.desc())
            .limit(1)
        ).first()
        if nudge is not None:
            stamps.append(nudge.created_at)
        return max([s for s in stamps if s is not None], default=None)

    def _attempts(self, q: QuotationRequest) -> int:
        return int(
            self.db.scalar(
                select(func.count()).where(
                    FollowUp.quotation_request_id == q.id, FollowUp.sent.is_(True)
                )
            )
            or 0
        )

    def _last_nudge(self, q: QuotationRequest) -> datetime | None:
        """When we last chased, so the row can say "chased 2× · last 14 Aug"."""
        return self.db.scalar(
            select(FollowUp.created_at)
            .where(FollowUp.quotation_request_id == q.id, FollowUp.sent.is_(True))
            .order_by(FollowUp.created_at.desc())
            .limit(1)
        )

    def _message_count(self, q: QuotationRequest) -> int:
        """How many messages the thread holds.

        A four-message negotiation and a single unanswered quotation are very
        different situations, and the count says which at a glance.
        """
        clauses = [Email.replied_to_quotation_id == q.id]
        if q.email is not None and q.email.thread_id:
            clauses.append(Email.thread_id == q.email.thread_id)
        replies = int(self.db.scalar(select(func.count()).where(or_(*clauses))) or 0)
        # The enquiry itself may already be counted by the thread clause.
        if q.email is not None and not q.email.thread_id:
            replies += 1
        return max(replies, 1) + self._attempts(q)

    def _validity(self, q: QuotationRequest) -> tuple[date | None, str | None]:
        """When the desk stops chasing this quotation - *not* price validity.

        These were conflated in a first pass and it is worth naming why that
        was wrong. `FollowUpRule.stop_after_days` is "give up after 30 days",
        an internal decision about effort. How long a *price* stands is a
        commitment made to the customer, and this system does not record it
        anywhere. Rendering the first as though it were the second would put a
        number on screen that a trader might honour, so the label says exactly
        what the date is and nothing more.

        It only speaks when the deadline is close enough to change what the
        trader does today; a month out it is noise.
        """
        if q.sent_at is None:
            return (None, None)

        window = self.db.scalar(
            select(FollowUpRule.stop_after_days)
            .where(FollowUpRule.is_active.is_(True), FollowUpRule.stop_after_days.is_not(None))
            .order_by(FollowUpRule.stop_after_days)
            .limit(1)
        )
        if not window:
            return (None, None)

        until = (q.sent_at + timedelta(days=int(window))).date()
        left = (until - self.now.date()).days
        if left < 0:
            return (until, "chasing stopped")
        if left == 0:
            return (until, "last day to chase")
        if left <= 5:
            return (until, f"{_plural(left, 'day')} left to chase")
        return (until, None)

    def _stock(self, q: QuotationRequest) -> tuple[str | None, bool]:
        """Whether the yard can cover what was quoted.

        Chasing an order that cannot be filled is worse than not chasing it,
        so a shortfall belongs on the row rather than three clicks away.
        """
        short: list[str] = []
        ageing = 0
        for item in q.line_items or []:
            availability = item.stock_availability
            if availability is None:
                continue
            if availability.sufficient is False:
                have = float(availability.available_qty_mt or 0)
                want = float(item.quantity_mt or 0)
                gap = want - have
                if gap > 0:
                    short.append(f"{gap:,.3g} MT short")
                else:
                    short.append("not in stock")
            ageing = max(ageing, availability.ageing_max_days or 0)

        if short:
            return (", ".join(short[:2]), True)
        if ageing >= 60:
            return (f"stock ageing {ageing} days", False)
        return (None, False)

    def _next_step(
        self,
        q: QuotationRequest,
        turn: ChaseTurn,
        latest: Email | None,
        stock_short: bool,
    ) -> str:
        """What to do, in the imperative.

        This replaced a body snippet. Two clamped lines of an email are almost
        always the salutation and never the ask, so the column cost real width
        and returned nothing; a trader wants the decision, not the prose.
        """
        if turn is ChaseTurn.SNOOZED:
            return "Nothing yet"
        if stock_short:
            return "Check stock before replying"

        if latest is not None and latest.direction is MailDirection.INBOUND:
            if latest.category is EmailCategory.ORDER:
                return "Confirm the order"
            if latest.category is EmailCategory.COMPLAINT:
                return "Answer the complaint"
            if latest.category is EmailCategory.PRICE_NEGOTIATION:
                return "Answer on price"
            if latest.category in (
                EmailCategory.DELIVERY_QUERY,
                EmailCategory.PAYMENT_QUERY,
            ):
                return "Answer their question"
            return "Reply"

        if q.promised_date is not None and q.promised_date < self.now.date():
            return "Call - their date has passed"
        if turn is ChaseTurn.COLD:
            return "Last attempt, or mark lost"
        return "Chase for a decision"

    def _due_schedule_id(self, q: QuotationRequest) -> int | None:
        return self.db.scalar(
            select(FollowUpSchedule.id)
            .where(
                FollowUpSchedule.quotation_request_id == q.id,
                FollowUpSchedule.status == FollowUpStatus.DUE,
            )
            .order_by(FollowUpSchedule.due_at)
            .limit(1)
        )

    def _history(self, q: QuotationRequest) -> tuple[int, int]:
        """(won, total) quotations for this customer, this one included."""
        if q.customer_id is None:
            return (0, 1)
        total = int(
            self.db.scalar(
                select(func.count()).where(QuotationRequest.customer_id == q.customer_id)
            )
            or 0
        )
        won = int(
            self.db.scalar(
                select(func.count()).where(
                    QuotationRequest.customer_id == q.customer_id,
                    QuotationRequest.status == QuotationStatus.CUSTOMER_ACCEPTED,
                )
            )
            or 0
        )
        return (won, total)

    def _what(self, q: QuotationRequest) -> tuple[str, str, float | None, float]:
        """Material, quantity, rate and value, as the row shows them.

        Money comes off `QuotationPricing`, which is where the calculator
        stores it - the line item itself carries the specification, not the
        price. A line that was never priced contributes nothing to the value
        rather than a zero that would read as free.
        """
        items = list(q.line_items or [])
        if not items:
            return ("—", "—", None, 0.0)

        first = items[0]
        material = _describe(first)
        if len(items) > 1:
            material = f"{material} +{len(items) - 1} more"

        qty_mt = 0.0
        value = 0.0
        rate: float | None = None
        for item in items:
            pricing = item.pricing
            qty = item.quantity_mt or (pricing.quantity_mt if pricing else None)
            qty_mt += float(qty or 0)
            if pricing is not None:
                value += float(pricing.line_total or 0)
                if item is first and pricing.quote_rate is not None:
                    rate = float(pricing.quote_rate)

        quantity = f"{qty_mt:,.3g} MT" if qty_mt else "—"
        if rate:
            quantity = f"{quantity} · ₹{rate:,.0f}/MT"

        return (material, quantity, rate, value)

    def _customer_note(self, customer: Customer | None, total: int, won: int) -> str:
        """The relationship in one phrase."""
        if customer is None or total <= 1:
            return "new · first enquiry"
        if won == 0:
            return f"no orders yet · {total} quotes"
        rate = won / total
        if rate >= 0.4:
            return f"regular · won {won} of {total}"
        return f"slipping · won {won} of {total}"

    # -- scoring -----------------------------------------------------------

    def _factors(self, row: ChaseRow) -> list[ScoreFactor]:
        """Why this row ranks where it does.

        Every factor is named and returned. The trader sees the arithmetic on
        demand, because a ranking whose reasoning is hidden is one he stops
        trusting - and then he goes back to scrolling his inbox.
        """
        out: list[ScoreFactor] = []

        # Whose turn dominates: somebody actively waiting beats any amount of
        # silence, whatever the two quotations are worth.
        turn_weight = {
            ChaseTurn.YOURS: 3.0,
            ChaseTurn.THEIRS: 1.0,
            ChaseTurn.COLD: 0.4,
            ChaseTurn.SNOOZED: 0.0,
        }[row.turn]
        out.append(ScoreFactor(_turn_label(row.turn), turn_weight))

        # Silence with diminishing returns: day 4 matters far more than the
        # step from day 30 to day 31.
        silence = 1.0 + min(row.days_waiting, 21) * 0.05
        if row.days_waiting:
            out.append(
                ScoreFactor(f"Quiet {_plural(row.days_waiting, 'day')}", round(silence, 2))
            )

        # A buyer who actually buys is worth more attention than a stranger.
        if row.quotes_total > 1:
            win = row.quotes_won / row.quotes_total
            rel = 0.7 + win * 0.9
            out.append(
                ScoreFactor(
                    f"Won {row.quotes_won} of {row.quotes_total} with this buyer",
                    round(rel, 2),
                )
            )

        # An old quotation is worth chasing less: the enquiry itself has aged
        # out, whatever the number on it says.
        age_days = max(0, (self.now - row.sent_at).days) if row.sent_at else 0
        if age_days > 30:
            out.append(ScoreFactor("Quotation over a month old", 0.6))

        # An unopened order is not a follow-up. It is revenue on the floor.
        if row.has_attachment and row.turn is ChaseTurn.YOURS:
            out.append(ScoreFactor("Order document unopened", 1.4))

        return out


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _describe(item) -> str:
    """A line item as a trader says it: "12 mm TMT Fe500D".

    Built from the specification rather than shown as a quotation number,
    because the number identifies the row to the system and the material
    identifies it to the person reading.
    """
    parts: list[str] = []
    if item.thickness_mm:
        parts.append(f"{item.thickness_mm:g} mm")
    elif item.diameter_mm:
        parts.append(f"{item.diameter_mm:g} mm")
    if item.product_type:
        parts.append(item.product_type)
    if item.grade:
        parts.append(item.grade)
    if parts:
        return " ".join(parts)
    return (item.raw_text or "").strip()[:60] or "—"


def _product(factors: list[ScoreFactor]) -> float:
    total = 1.0
    for f in factors:
        total *= f.factor
    return total


def _turn_label(turn: ChaseTurn) -> str:
    return {
        ChaseTurn.YOURS: "Your turn — they are waiting",
        ChaseTurn.THEIRS: "Their turn",
        ChaseTurn.COLD: "Gone cold",
        ChaseTurn.SNOOZED: "Snoozed",
    }[turn]


def _actor(latest: Email | None, last_nudge: datetime | None, q: QuotationRequest) -> str:
    """Who moved last, in three words. The row's orientation line."""
    if latest is not None:
        if latest.direction is MailDirection.INBOUND:
            return "They replied"
        return "You replied"
    if last_nudge is not None and q.sent_at is not None and last_nudge > q.sent_at:
        return "You chased"
    return "You quoted"


def _inbound_note(email: Email) -> str:
    if email.category is EmailCategory.ORDER:
        return "order unopened"
    if email.category is EmailCategory.COMPLAINT:
        return "complaint open"
    return "since their reply"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


