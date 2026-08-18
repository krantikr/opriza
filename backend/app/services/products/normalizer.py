"""Deterministic normalisation of steel trade vocabulary.

Runs before matching and resolves the shorthand a trader actually writes -
"MS plate", "IS2062", "tmt bars" - into the canonical tokens used by the
product master. The synonym tables live in `business_rules.yaml`, so a new
regional term is a config edit rather than a code change.

This is deliberately the *first* attempt. The LLM normaliser in `ai/` is only
consulted for descriptions this cannot place, which keeps the common path
free, instant and auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.rules import BusinessRules, get_rules

# "IS2062" -> "IS 2062"; also handles "is 2062" and "IS-2062".
_STANDARD_PATTERN = re.compile(r"^([A-Za-z]+)[\s\-]*(\d+)$")
_PUNCTUATION = re.compile(r"[^a-z0-9\s]+")

# Tokens that describe a material's *grade, standard or size* rather than its
# form. "25", "8mm", "2062" and "E350C" say nothing about whether the customer
# wants a plate or a channel, so they are dropped on the second resolution pass
# (see `_strip_spec_tokens`).
_SIZE_TOKEN = re.compile(r"^\d+(?:\.\d+)?(?:mm|cm|m)?$")
_GRADE_SHAPED_TOKEN = re.compile(r"^[a-z]{1,3}\d{2,4}[a-z]{0,2}$")


def _key(value: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return " ".join(_PUNCTUATION.sub(" ", value.strip().lower()).split())


def _lookup(
    value: str | None, table: dict[str, str], qualifiers: set[str] | None = None
) -> str | None:
    """Resolve a term against a synonym table.

    Three passes, each narrower than a plain substring search:

    1. exact match
    2. singular form ("plates" -> "plate")
    3. the table term plus only *ignorable qualifiers* ("steel plate" -> plate)

    A substring search would be more forgiving and considerably more dangerous:
    "Chequered Plate" contains "plate", but a chequered plate is not a plate,
    and mapping it would produce a confident price for the wrong material. So
    anything with an unrecognised qualifying word stays unresolved and reaches
    a human.
    """
    if not value:
        return None

    key = _key(value)
    if not key:
        return None

    if key in table:
        return table[key]

    # "plates" -> "plate", "tmt bars" -> "tmt bar"
    if key.endswith("s") and key[:-1] in table:
        return table[key[:-1]]

    qualifiers = qualifiers or set()
    tokens = set(key.split())
    best: tuple[int, str] | None = None

    for term, canonical in table.items():
        term_tokens = set(term.split())
        if not term_tokens or not term_tokens <= tokens:
            continue
        # Every remaining word must be a recognised qualifier.
        if (tokens - term_tokens) - qualifiers:
            continue
        if best is None or len(term_tokens) > best[0]:
            best = (len(term_tokens), canonical)

    return best[1] if best else None


def _strip_spec_tokens(value: str, *others: str | None) -> str:
    """Reduce a product-type phrase to the words that describe the *form*.

    An enquiry - or a language model transcribing one - routinely writes the
    whole specification into the product-type field: `"IS 2062 E350C plate"`
    instead of `"plate"`. `_lookup` refuses that on purpose, because it will not
    substring-match, and the field then scores zero against every stock record
    even though every other field agrees.

    So the grade, the standard and any size or grade-shaped token are removed
    and the remainder is offered to `_lookup` a second time. What survives is
    still judged by the same strict rules, which is what keeps this safe:
    "Chequered Plate" contains no size or grade word, so it is unchanged by this
    function and still reaches a human. "SS 304 pipe" loses only `304`, leaving
    `ss pipe`, whose unrecognised `ss` keeps stainless out of the carbon-steel
    pipe stock.
    """
    known: set[str] = set()
    for other in others:
        if other:
            known |= set(_key(other).split())

    kept = [
        token
        for token in _key(value).split()
        if token not in known
        and not _SIZE_TOKEN.match(token)
        and not _GRADE_SHAPED_TOKEN.match(token)
    ]
    return " ".join(kept)


@dataclass(slots=True)
class NormalizedSpec:
    """Canonical form of a requested material, plus what changed."""

    product_type: str | None = None
    grade: str | None = None
    standard: str | None = None
    notes: list[str] = field(default_factory=list)
    # True when a term could not be resolved and the AI fallback is worth trying.
    unresolved: list[str] = field(default_factory=list)


def normalize_standard(value: str | None) -> str | None:
    """`IS2062`, `is-2062` -> `IS 2062`."""
    if not value:
        return None
    text = value.strip().upper()
    if match := _STANDARD_PATTERN.match(text):
        return f"{match.group(1)} {match.group(2)}"
    return " ".join(text.split())


def normalize_spec(
    *,
    product_type: str | None,
    grade: str | None = None,
    standard: str | None = None,
    rules: BusinessRules | None = None,
) -> NormalizedSpec:
    """Map a requested material description to canonical vocabulary."""
    rules = rules or get_rules()
    synonyms = rules.matching.synonyms
    qualifiers = {q.lower() for q in rules.matching.ignorable_qualifiers}
    spec = NormalizedSpec()

    # --- Product type -----------------------------------------------------
    if product_type:
        resolved = _lookup(product_type, synonyms.product_type, qualifiers)
        reduced_from_spec = False

        if resolved is None:
            # Second pass: the whole spec may have been written into this one
            # field. Retry on just the words that describe the material's form.
            reduced = _strip_spec_tokens(product_type, grade, standard)
            if reduced and reduced != _key(product_type):
                resolved = _lookup(reduced, synonyms.product_type, qualifiers)
                reduced_from_spec = resolved is not None

        if resolved:
            spec.product_type = resolved
            if reduced_from_spec:
                spec.notes.append(
                    f"product type {product_type!r} -> {resolved!r} "
                    "(grade, standard and size words ignored)"
                )
            elif _key(product_type) != _key(resolved):
                spec.notes.append(f"product type {product_type!r} -> {resolved!r}")
        else:
            # Keep the original: a term absent from the table may still match
            # the master directly, and discarding it would lose information.
            spec.product_type = product_type.strip().title()
            spec.unresolved.append(f"product_type={product_type!r}")

    # --- Grade ------------------------------------------------------------
    if grade:
        resolved = _lookup(grade, synonyms.grade, qualifiers)
        if resolved:
            spec.grade = resolved
            if _key(grade) != _key(resolved):
                spec.notes.append(f"grade {grade!r} -> {resolved!r}")
        else:
            spec.grade = grade.strip().upper()
            spec.unresolved.append(f"grade={grade!r}")

    # --- Standard ---------------------------------------------------------
    if standard:
        spec.standard = normalize_standard(standard)
        if spec.standard != standard:
            spec.notes.append(f"standard {standard!r} -> {spec.standard!r}")

    # A standard typed into the grade field ("IS 1239") is common; move it
    # across rather than failing to match on both fields.
    #
    # The prefix check is load-bearing. "E250" and "Fe500" have the same
    # letters-then-digits shape as "IS 2062", so a shape test alone would file
    # every grade in the system as a standard and then score it against the
    # product's real standard, losing the grade comparison entirely.
    prefixes = {p.upper() for p in rules.matching.standard_prefixes}
    if spec.grade and not spec.standard:
        compact = spec.grade.replace(" ", "")
        match = _STANDARD_PATTERN.match(compact)
        if match and match.group(1).upper() in prefixes:
            promoted = normalize_standard(spec.grade)
            spec.standard = promoted
            spec.grade = _lookup(spec.grade, synonyms.grade, qualifiers)
            spec.unresolved = [u for u in spec.unresolved if not u.startswith("grade=")]
            spec.notes.append(f"treated {promoted!r} as a standard, not a grade")

    return spec
