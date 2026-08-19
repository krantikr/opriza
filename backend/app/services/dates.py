"""Turning what a customer wrote into a date we can act on.

The model repeats a customer's own words - "by Friday", "after the 15th",
"next week" - and this resolves them against the day the message arrived.

The governing rule is the same one the pricing engine follows: **refuse rather
than guess.** A follow-up raised on a date nobody meant is worse than no
follow-up at all, because it wastes a call and makes the desk look careless. So
anything vague ("soon", "shortly", "in due course") resolves to `None`, and the
raw phrase is kept alongside so a human can read what was actually said.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

#: Phrases that sound like a commitment but name no day. Resolving these would
#: be inventing a date the customer never gave.
VAGUE = (
    "soon",
    "shortly",
    "in due course",
    "asap",
    "later",
    "sometime",
    "in a while",
    "when possible",
)


def parse_promised_date(phrase: str | None, received: datetime | date | None = None) -> date | None:
    """Resolve a customer's phrase to a date, or `None` if it is not one.

    `received` anchors relative phrases, because "Friday" means the Friday
    after the message was written, not after it was processed.
    """
    if not phrase:
        return None

    text = phrase.strip().lower()
    if not text:
        return None

    anchor = _as_date(received) or date.today()

    if any(word in text for word in VAGUE):
        return None

    # "tomorrow", "today"
    if "day after tomorrow" in text:
        return anchor + timedelta(days=2)
    if "tomorrow" in text:
        return anchor + timedelta(days=1)
    if "today" in text or "end of day" in text or "eod" in text:
        return anchor

    # "in 3 days", "within 2 weeks", "give us a week"
    unit_match = re.search(r"(\d+)\s*(day|week|month)s?", text)
    if unit_match:
        count = int(unit_match.group(1))
        unit = unit_match.group(2)
        days = {"day": 1, "week": 7, "month": 30}[unit]
        return anchor + timedelta(days=count * days)
    if re.search(r"\b(a|one)\s+week\b", text) or "next week" in text:
        return anchor + timedelta(days=7)
    if "fortnight" in text:
        return anchor + timedelta(days=14)
    if re.search(r"\b(a|one)\s+month\b", text) or "next month" in text:
        return anchor + timedelta(days=30)

    # "15 Aug", "15th August", "Aug 15"
    explicit = _explicit_date(text, anchor)
    if explicit:
        return explicit

    # "by Friday", "on Monday" - the next such weekday after the anchor.
    for name, index in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", text):
            ahead = (index - anchor.weekday()) % 7
            return anchor + timedelta(days=ahead or 7)

    # "end of the week" / "end of the month"
    if "end of the week" in text or "end of week" in text:
        return anchor + timedelta(days=(4 - anchor.weekday()) % 7 or 7)
    if "end of the month" in text or "end of month" in text:
        first_next = (anchor.replace(day=1) + timedelta(days=32)).replace(day=1)
        return first_next - timedelta(days=1)

    return None


def _explicit_date(text: str, anchor: date) -> date | None:
    """A stated day and month, with the year inferred forward."""
    # "15 Aug" / "15th August"
    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\b", text)
    if match and match.group(2) in MONTHS:
        return _build(anchor, int(match.group(1)), MONTHS[match.group(2)])

    # "Aug 15" / "August 15th"
    match = re.search(r"\b([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\b", text)
    if match and match.group(1) in MONTHS:
        return _build(anchor, int(match.group(2)), MONTHS[match.group(1)])

    # "on the 15th" - this month, or next if it has passed.
    match = re.search(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b", text)
    if match:
        return _build(anchor, int(match.group(1)), anchor.month)

    return None


def _build(anchor: date, day: int, month: int) -> date | None:
    """A date at or after the anchor, rolling to next year if it has passed."""
    for year in (anchor.year, anchor.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate >= anchor:
            return candidate
    return None


def _as_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


__all__ = ["parse_promised_date"]
