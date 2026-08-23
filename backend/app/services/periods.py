"""Named reporting periods, the way a trading desk actually closes its books.

A rolling "last 30 days" can never be reconciled against anything. It ends on
a Tuesday, straddles two months, and moves every time you look at it. A trader
closing the month wants *the month* - and when the accountant asks for the
year, they mean the Indian financial year, April to March.

So periods here are named and calendar-aligned, and every one of them carries
the comparable window immediately before it: this month against last month,
this week against last week, Q2 against Q1. Like for like, always, because a
partial period compared against a whole one flatters or damns for no reason.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from app.services.reports import DateRange

#: Indian financial year starts 1 April.
FY_START_MONTH = 4


@dataclass(slots=True)
class Period:
    """A named window, its label, and the comparable window before it."""

    key: str
    label: str
    current: DateRange
    previous: DateRange
    #: How to slice the window for a trend: by day, week or month.
    grain: str = "day"

    @property
    def previous_label(self) -> str:
        return self.previous.label()


def _month_end(day: date) -> date:
    return day.replace(day=monthrange(day.year, day.month)[1])


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _shift_month(day: date, months: int) -> date:
    """The same day-of-month `months` away, clamped to a real date."""
    total = day.year * 12 + (day.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _week_start(day: date) -> date:
    """Monday of the week containing `day`."""
    return day - timedelta(days=day.weekday())


def _fy_start(day: date) -> date:
    """1 April of the financial year containing `day`."""
    year = day.year if day.month >= FY_START_MONTH else day.year - 1
    return date(year, FY_START_MONTH, 1)


def _quarter_start(day: date) -> date:
    """Start of the financial quarter (Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar)."""
    fy = _fy_start(day)
    elapsed = (day.year - fy.year) * 12 + (day.month - fy.month)
    return _shift_month(fy, (elapsed // 3) * 3)


def _grain_for(span_days: int) -> str:
    """Buckets a person can read. Sixty daily columns is a smear, not a trend."""
    if span_days <= 31:
        return "day"
    if span_days <= 120:
        return "week"
    return "month"


def _fy_label(start: date) -> str:
    return f"FY {start.year % 100:02d}-{(start.year + 1) % 100:02d}"


def resolve(key: str, today: date | None = None) -> Period:
    """Build a named period, or fall back to the last 30 days.

    Every branch pairs the window with the equivalent one before it, so the
    comparison is like for like even when the current period is still running.
    """
    today = today or date.today()

    if key == "this-week":
        start = _week_start(today)
        return _build("this-week", "This week", start, today, start - timedelta(days=7),
                      start - timedelta(days=1))

    if key == "last-week":
        end = _week_start(today) - timedelta(days=1)
        start = end - timedelta(days=6)
        return _build("last-week", "Last week", start, end, start - timedelta(days=7),
                      start - timedelta(days=1))

    if key == "this-month":
        start = _month_start(today)
        before = _shift_month(start, -1)
        return _build("this-month", today.strftime("%B %Y"), start, today, before,
                      start - timedelta(days=1))

    if key == "last-month":
        end = _month_start(today) - timedelta(days=1)
        start = _month_start(end)
        before = _shift_month(start, -1)
        return _build("last-month", start.strftime("%B %Y"), start, end, before,
                      start - timedelta(days=1))

    if key == "this-quarter":
        start = _quarter_start(today)
        return _build("this-quarter", f"Quarter from {start:%b %Y}", start, today,
                      _shift_month(start, -3), start - timedelta(days=1))

    if key == "last-quarter":
        end = _quarter_start(today) - timedelta(days=1)
        start = _quarter_start(end)
        return _build("last-quarter", f"Quarter from {start:%b %Y}", start, end,
                      _shift_month(start, -3), start - timedelta(days=1))

    if key == "this-fy":
        start = _fy_start(today)
        return _build("this-fy", _fy_label(start), start, today,
                      date(start.year - 1, FY_START_MONTH, 1), start - timedelta(days=1))

    if key == "last-fy":
        end = _fy_start(today) - timedelta(days=1)
        start = date(end.year if end.month >= FY_START_MONTH else end.year - 1,
                     FY_START_MONTH, 1)
        return _build("last-fy", _fy_label(start), start, end,
                      date(start.year - 1, FY_START_MONTH, 1), start - timedelta(days=1))

    # "30" / "90" - rolling day windows, kept so old links still work.
    if key.isdigit():
        days = int(key)
        start = today - timedelta(days=days)
        return _build(key, f"Last {days} days", start, today,
                      start - timedelta(days=days), start - timedelta(days=1))

    return resolve("this-month", today)


def custom(start: date, end: date) -> Period:
    """An arbitrary range, compared with the same number of days before it."""
    span = (end - start).days + 1
    return _build("custom", f"{start:%d %b} to {end:%d %b %Y}", start, end,
                  start - timedelta(days=span), start - timedelta(days=1))


def _build(key: str, label: str, start: date, end: date, prev_start: date,
           prev_end: date) -> Period:
    span = (end - start).days + 1
    return Period(
        key=key,
        label=label,
        current=DateRange(start=start, end=end),
        previous=DateRange(start=prev_start, end=prev_end),
        grain=_grain_for(span),
    )


#: Offered in the period picker, in the order a trader reaches for them.
CHOICES = [
    ("this-week", "This week"),
    ("last-week", "Last week"),
    ("this-month", "This month"),
    ("last-month", "Last month"),
    ("this-quarter", "This quarter"),
    ("last-quarter", "Last quarter"),
    ("this-fy", "This FY"),
    ("last-fy", "Last FY"),
]

__all__ = ["Period", "resolve", "custom", "CHOICES"]
