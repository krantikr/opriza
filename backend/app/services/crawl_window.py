"""How often to check a desk's mailbox, right now.

The requirement is a busy window and a quiet one: poll every ten minutes
through the working day, hourly overnight. Two things make that less trivial
than it sounds, and both are handled here rather than at the call site:

* **The day is local to the desk.** A window stored as UTC would drift by half
  an hour for an Indian desk and by a full hour twice a year for a European
  one. The organisation stores an IANA zone and the comparison happens in it.
* **A window may cross midnight.** `22:00 - 06:00` is a legitimate answer to
  "when are we busy" for a desk trading with another hemisphere, and reading
  it as "from 22:00 until 22:00" would poll hourly around the clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.logging import get_logger
from app.models import Organisation

logger = get_logger(__name__)

#: Used when an organisation carries a timezone the host cannot resolve. UTC
#: is chosen over guessing: polling on the wrong clock is a smaller failure
#: than silently not polling.
FALLBACK_ZONE = UTC


@dataclass(frozen=True, slots=True)
class CrawlDecision:
    """Whether to poll now, how often, and why - the reason is for the UI.

    A trader asking "why has nothing arrived since 10pm" deserves an answer in
    the interface rather than in a log file nobody has access to.
    """

    should_poll: bool
    interval_minutes: int
    active: bool
    reason: str


def zone_for(organisation: Organisation) -> ZoneInfo | type[UTC]:
    try:
        return ZoneInfo(organisation.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(
            "Organisation %s has an unknown timezone %r; using UTC.",
            organisation.slug,
            organisation.timezone,
        )
        return FALLBACK_ZONE


def local_now(organisation: Organisation, moment: datetime | None = None) -> datetime:
    """The organisation's own wall-clock time."""
    moment = moment or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(zone_for(organisation))


def in_window(now: time, start: time, end: time) -> bool:
    """Whether `now` falls inside `start`-`end`, including across midnight.

    When `start <= end` the window is an ordinary daytime span. When it is
    later than `end` the window wraps midnight, and membership becomes "at or
    after the start **or** before the end" rather than an `and` of both.
    """
    if start == end:
        # A zero-width window would mean "never", which no desk intends by
        # setting both fields the same. Read as always active.
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


def decide(organisation: Organisation, moment: datetime | None = None) -> CrawlDecision:
    """What the poller should do for this desk at this instant."""
    if not organisation.crawl_enabled:
        return CrawlDecision(
            should_poll=False,
            interval_minutes=organisation.crawl_quiet_minutes,
            active=False,
            reason="Mail checking is switched off for this account.",
        )

    here = local_now(organisation, moment)
    active = in_window(
        here.time(), organisation.crawl_active_from, organisation.crawl_active_to
    )

    if active:
        minutes = organisation.crawl_active_minutes
        reason = (
            f"Working hours ({_hhmm(organisation.crawl_active_from)}-"
            f"{_hhmm(organisation.crawl_active_to)}), checking every "
            f"{_plural(minutes, 'minute')}."
        )
    else:
        minutes = organisation.crawl_quiet_minutes
        reason = (
            f"Outside working hours, checking every {_plural(minutes, 'minute')}. "
            f"Back to every {_plural(organisation.crawl_active_minutes, 'minute')} "
            f"at {_hhmm(organisation.crawl_active_from)}."
        )

    return CrawlDecision(
        should_poll=True, interval_minutes=minutes, active=active, reason=reason
    )


def is_due(
    organisation: Organisation,
    last_polled_at: datetime | None,
    moment: datetime | None = None,
) -> bool:
    """Whether enough time has passed since the last check.

    A mailbox never polled is due immediately - a desk that has just connected
    should not wait an hour to see its first enquiry.
    """
    decision = decide(organisation, moment)
    if not decision.should_poll:
        return False
    if last_polled_at is None:
        return True

    now = moment or datetime.now(UTC)
    if last_polled_at.tzinfo is None:
        last_polled_at = last_polled_at.replace(tzinfo=UTC)
    elapsed = (now - last_polled_at).total_seconds() / 60
    return elapsed >= decision.interval_minutes


def _hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


__all__ = ["CrawlDecision", "decide", "in_window", "is_due", "local_now", "zone_for"]
