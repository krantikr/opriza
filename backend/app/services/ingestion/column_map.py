"""Tolerant spreadsheet header mapping.

Real business files never use the column names a developer would pick. Rather
than demanding the customer reshape their Excel, each importer declares the
fields it needs plus the aliases it will accept, and this module resolves the
actual headers against them.

Headers are normalised before matching: case folded, unit suffixes in
parentheses dropped, punctuation collapsed. So "Thickness (mm)", "THICKNESS",
"Thk." and "thickness_mm" all resolve to the same field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def normalize_header(header: object) -> str:
    """Reduce a spreadsheet header to a comparable token string."""
    text = str(header or "").strip().lower()
    text = re.sub(r"\(.*?\)", " ", text)  # "(mm)", "(kg)", "(INR)"
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One target field and the headers that may stand for it."""

    field: str
    aliases: tuple[str, ...]
    required: bool = False

    @property
    def normalized_aliases(self) -> set[str]:
        return {normalize_header(a) for a in (self.field, *self.aliases)}


@dataclass(slots=True)
class ColumnMapping:
    """Resolved header -> field mapping for one sheet."""

    by_header: dict[str, str]
    missing_required: list[str]
    unmapped_headers: list[str]

    @property
    def ok(self) -> bool:
        return not self.missing_required

    def describe_missing(self) -> str:
        return ", ".join(self.missing_required)


def build_mapping(headers: list[object], specs: list[ColumnSpec]) -> ColumnMapping:
    """Resolve sheet headers against the importer's column specs.

    The first header matching a field wins; later duplicates are reported as
    unmapped rather than silently overwriting.
    """
    normalized = {h: normalize_header(h) for h in headers}
    by_header: dict[str, str] = {}
    taken: set[str] = set()
    used_headers: set[str] = set()

    for spec in specs:
        aliases = spec.normalized_aliases
        for header, norm in normalized.items():
            key = str(header)
            # A header may only satisfy one field, and a field only takes one
            # header - otherwise a later spec would silently steal a column an
            # earlier one had already claimed.
            if key in used_headers or spec.field in taken:
                continue
            if norm and norm in aliases:
                by_header[key] = spec.field
                taken.add(spec.field)
                used_headers.add(key)

    missing = [s.field for s in specs if s.required and s.field not in taken]
    unmapped = [str(h) for h in headers if str(h) not in by_header]
    return ColumnMapping(by_header=by_header, missing_required=missing, unmapped_headers=unmapped)
