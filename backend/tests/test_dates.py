"""Resolving a customer's own words into a date we can act on.

The governing rule is the one the pricing engine follows: refuse rather than
guess. A follow-up raised on a date nobody meant wastes a call and makes the
desk look careless, so anything vague resolves to None.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.dates import parse_promised_date

# A Wednesday, so "Friday" and "end of the week" have unambiguous answers.
ANCHOR = date(2026, 8, 19)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("tomorrow", date(2026, 8, 20)),
        ("day after tomorrow", date(2026, 8, 21)),
        ("today", ANCHOR),
        ("by Friday", date(2026, 8, 21)),
        ("on Monday", date(2026, 8, 24)),
        ("next week", date(2026, 8, 26)),
        ("in 3 days", date(2026, 8, 22)),
        ("within 2 weeks", date(2026, 9, 2)),
        ("give us a week", date(2026, 8, 26)),
        ("after the 25th", date(2026, 8, 25)),
        ("15 Sep", date(2026, 9, 15)),
        ("Sept 2", date(2026, 9, 2)),
        ("end of the month", date(2026, 8, 31)),
    ],
)
def test_a_stated_timeframe_resolves_to_a_date(phrase, expected):
    assert parse_promised_date(phrase, ANCHOR) == expected


@pytest.mark.parametrize(
    "phrase",
    ["soon", "shortly", "in due course", "asap", "we will let you know", "", None],
)
def test_a_vague_promise_is_refused_rather_than_guessed(phrase):
    """Inventing a date the customer never gave is worse than having none."""
    assert parse_promised_date(phrase, ANCHOR) is None


def test_a_weekday_means_the_next_one_not_today(db=None):
    """'Wednesday' said on a Wednesday means next Wednesday, not this morning."""
    assert parse_promised_date("Wednesday", ANCHOR) == date(2026, 8, 26)


def test_a_month_already_past_rolls_into_next_year():
    """'15 Jan', said in August, means January of next year."""
    assert parse_promised_date("15 Jan", ANCHOR) == date(2027, 1, 15)


def test_the_anchor_is_when_the_message_arrived():
    """'Friday' means the Friday after they wrote, not after we processed it."""
    early = parse_promised_date("by Friday", date(2026, 8, 17))
    late = parse_promised_date("by Friday", date(2026, 8, 24))
    assert early == date(2026, 8, 21)
    assert late == date(2026, 8, 28)


def test_an_impossible_date_does_not_raise():
    assert parse_promised_date("31 Feb", ANCHOR) is None
