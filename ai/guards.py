"""Post-generation checks on a draft.

The draft prompt instructs the model not to alter any figure. This module
verifies that it did not.

The distinction matters. A prompt is a request; a quotation that quietly rounds
₹59,200 to "about ₹59,000" is a commercial document that misstates a price, and
"we asked it not to" is not a control. So every price, quantity and total handed
to the model is checked for presence in the text it produced, and a draft that
drops or changes one is regenerated - and if it happens again, flagged for a
human rather than sent.

Number matching is lenient about *formatting* and strict about *value*:
`₹59,200.00`, `Rs 59,200`, `59200/-` all satisfy a required 59200.00, while
59,000 does not.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

# Stripped before matching so formatting choices do not cause false failures.
_NOISE = re.compile(r"[,₹$]|(?:\brs\.?\b)|(?:\binr\b)", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")

# Claims the model is told never to make. Presence is a warning for the
# reviewer, not a hard failure - wording is a judgement call, figures are not.
#
# Availability phrases ("in stock", "ex-stock", ...) are deliberately *not*
# here: in this flow availability is a verified fact the draft is supposed to
# report (see draft.md), unlike the old pricing flow where it was never
# checked and so could never be claimed.
UNSUPPORTED_CLAIMS = (
    ("special discount", "offers a discount"),
    ("negotiable", "signals the price is negotiable"),
    ("best possible price", "makes an unsupported price claim"),
    ("guarantee", "makes a guarantee"),
    ("final price", "claims the suggested rate is final rather than indicative"),
    ("immediate delivery", "promises immediate delivery"),
)


@dataclass(frozen=True, slots=True)
class RequiredFact:
    """A figure that must survive into the generated body unchanged."""

    label: str
    variants: tuple[str, ...]

    def satisfied_by(self, normalized_body: str) -> bool:
        return any(_contains_number(normalized_body, v) for v in self.variants)


def _normalize(text: str) -> str:
    """Strip currency noise and thousands separators, collapse whitespace."""
    return _WHITESPACE.sub(" ", _NOISE.sub("", text or "")).strip().lower()


def _contains_number(normalized_body: str, value: str) -> bool:
    """Match a numeric token, refusing to match inside a longer number.

    Without the boundaries, a required quantity of 20 would be satisfied by the
    year 2026 appearing in the signature.
    """
    pattern = rf"(?<![\d.]){re.escape(value)}(?![\d])"
    return re.search(pattern, normalized_body) is not None


def _decimal_variants(value: Decimal | float | int) -> tuple[str, ...]:
    """Acceptable renderings of one number.

    Trailing zeros are optional - `59200`, `59200.0` and `59200.00` are the same
    price - but a different value is a different price.
    """
    amount = Decimal(str(value))
    variants = {f"{amount:.2f}", f"{amount:.1f}", format(amount.normalize(), "f")}
    if amount == amount.to_integral_value():
        variants.add(f"{amount:.0f}")
    return tuple(sorted(variants))


def money_fact(label: str, value: Decimal | float | int | None) -> RequiredFact | None:
    return RequiredFact(label, _decimal_variants(value)) if value is not None else None


def quantity_fact(label: str, value: Decimal | float | int | None) -> RequiredFact | None:
    return RequiredFact(label, _decimal_variants(value)) if value is not None else None


def verify_draft_facts(body: str, required: Sequence[RequiredFact | None]) -> list[str]:
    """Return one violation message per figure missing from the draft."""
    if not body or not body.strip():
        return ["The draft body is empty."]

    normalized = _normalize(body)
    return [
        f"{fact.label} is missing or was altered (expected {fact.variants[0]})"
        for fact in required
        if fact is not None and not fact.satisfied_by(normalized)
    ]


def find_unsupported_claims(body: str) -> list[str]:
    """Flag commitments the system has no basis to make."""
    lowered = (body or "").lower()
    return [description for phrase, description in UNSUPPORTED_CLAIMS if phrase in lowered]
