"""Numbers and dates the way an Indian business owner reads them."""

from __future__ import annotations

from datetime import date, datetime


def indian(n: float, places: int = 0) -> str:
    """12,34,567 grouping."""
    neg = n < 0
    n = abs(n)
    whole = int(round(n)) if places == 0 else int(n)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    if places:
        s += f"{n - whole:.{places}f}"[1:]
    return ("-" if neg else "") + s


def inr(amount: float | None, short: bool = True) -> str:
    """₹3.25 Cr, ₹85.6 L, ₹42,350."""
    if amount is None:
        return "—"
    a = float(amount)
    sign = "-" if a < 0 else ""
    a = abs(a)
    if short and a >= 1e7:
        return f"{sign}₹{a / 1e7:.2f} Cr"
    if short and a >= 1e5:
        return f"{sign}₹{a / 1e5:.1f} L"
    return f"{sign}₹{indian(a)}"


def rate(amount: float) -> str:
    return f"₹{indian(amount)}" if amount >= 100 else f"₹{amount:.2f}"


def qty(q: float, unit: str = "") -> str:
    text = f"{q:,.3f}".rstrip("0").rstrip(".") if q % 1 else f"{int(q):,}"
    return f"{text} {unit}".strip()


def as_date(d: date | datetime | str | None) -> date | None:
    if d is None or isinstance(d, date):
        return d
    return (
        datetime.fromisoformat(str(d)).date()
        if "T" in str(d) or " " in str(d)
        else date.fromisoformat(str(d))
    )


def day(d: date | datetime | str | None) -> str:
    if d is None:
        return "—"
    if isinstance(d, str):
        d = as_date(d)
    return f"{d.day} {d:%b}"


def clock(d: datetime) -> str:
    return f"{d:%I:%M %p}".lstrip("0").lower()
