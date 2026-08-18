"""Deterministic spec matching against physical stock (spec section 13).

The single most important property of this module: **it never guesses.**

A language model normalises vocabulary before this runs, but the decision of
which stock spec a customer asked for is made here, by weighted comparison.
Three outcomes are possible and only one of them proceeds automatically:

* ``MATCH_FOUND``      - one candidate clears the acceptance score and is
                         clearly ahead of the runner-up.
* ``MULTIPLE_MATCHES`` - two or more candidates are within `ambiguity_delta`.
                         A human picks.
* ``NO_MATCH``         - nothing clears the bar. A human picks.

Only fields the enquiry actually states are scored, and the total is
renormalised over those. An enquiry that omits width is not penalised for the
omission - it is simply judged on less evidence, which naturally narrows the
gap between candidates and surfaces as ambiguity rather than as a confident
wrong answer.

Stock is lots, not a product master: several `StockItem` rows commonly share
the same spec (grade + dimensions) at different ages, locations or costs.
Scoring those as separate near-duplicate candidates would falsely trip
`MULTIPLE_MATCHES` (two identical-spec lots score identically, which is
``ambiguity_delta`` of zero), so candidates are built from *distinct specs*,
grouped in Python after fetching. The winning spec carries every lot id that
belongs to it, for the availability step to aggregate over.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rules import BusinessRules, get_rules
from app.models import MatchStatus, StockItem
from app.services.products.normalizer import NormalizedSpec, normalize_spec

# Float comparison guard for "exact" dimension matching.
EPSILON = 1e-6
MAX_CANDIDATES_RETURNED = 5


@dataclass(slots=True)
class MatchSpec:
    """What the customer asked for, after normalisation."""

    product_type: str | None = None
    grade: str | None = None
    standard: str | None = None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    diameter_mm: float | None = None

    @classmethod
    def from_line_item(
        cls, item: Any, rules: BusinessRules | None = None
    ) -> tuple[MatchSpec, NormalizedSpec]:
        """Build a normalised spec from an extracted line item."""
        normalized = normalize_spec(
            product_type=getattr(item, "product_type", None),
            grade=getattr(item, "grade", None),
            standard=getattr(item, "standard", None),
            rules=rules,
        )
        spec = cls(
            product_type=normalized.product_type,
            grade=normalized.grade,
            standard=normalized.standard,
            thickness_mm=getattr(item, "thickness_mm", None),
            width_mm=getattr(item, "width_mm", None),
            length_mm=getattr(item, "length_mm", None),
            diameter_mm=getattr(item, "diameter_mm", None),
        )
        return spec, normalized


@dataclass(slots=True)
class FieldScore:
    field: str
    weight: float
    awarded: float
    requested: Any = None
    candidate: Any = None
    note: str = ""


@dataclass(slots=True)
class SpecGroup:
    """A distinct grade+dimension spec, aggregated from one or more lots."""

    product_type: str | None
    grade: str | None
    thickness_mm: float | None
    width_mm: float | None
    length_mm: float | None
    diameter_mm: float | None
    representative_id: int
    lot_ids: list[int] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        return (
            (self.product_type or "").casefold(),
            (self.grade or "").casefold(),
            self.thickness_mm,
            self.width_mm,
            self.length_mm,
            self.diameter_mm,
        )


@dataclass(slots=True)
class MatchCandidate:
    stock_item_id: int
    display_name: str
    score: float
    applicable_weight: float
    lot_ids: list[int]
    fields: list[FieldScore] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_item_id": self.stock_item_id,
            "display_name": self.display_name,
            "score": round(self.score, 2),
            "lot_count": len(self.lot_ids),
            "fields": [asdict(f) for f in self.fields],
        }


@dataclass(slots=True)
class MatchOutcome:
    status: MatchStatus
    stock_item: StockItem | None = None
    lot_ids: list[int] = field(default_factory=list)
    score: float | None = None
    candidates: list[MatchCandidate] = field(default_factory=list)
    reason: str = ""
    normalization_notes: list[str] = field(default_factory=list)

    @property
    def is_confident(self) -> bool:
        return self.status is MatchStatus.MATCH_FOUND

    def candidates_as_json(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self.candidates[:MAX_CANDIDATES_RETURNED]]


class ProductMatcher:
    def __init__(self, db: Session, rules: BusinessRules | None = None) -> None:
        self.db = db
        self.rules = rules or get_rules()

    # --- Public -----------------------------------------------------------

    def match(self, spec: MatchSpec, notes: list[str] | None = None) -> MatchOutcome:
        config = self.rules.matching
        candidates = self._score_all(spec)

        if not candidates:
            return MatchOutcome(
                status=MatchStatus.NO_MATCH,
                reason="No stock of this type exists.",
                normalization_notes=notes or [],
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None

        if best.score < config.accept_score:
            return MatchOutcome(
                status=MatchStatus.NO_MATCH,
                score=best.score,
                candidates=candidates,
                reason=(
                    f"Best candidate scored {best.score:.1f}, "
                    f"below the acceptance threshold of {config.accept_score:.0f}."
                ),
                normalization_notes=notes or [],
            )

        if runner_up and (best.score - runner_up.score) <= config.ambiguity_delta:
            tied = [c for c in candidates if best.score - c.score <= config.ambiguity_delta]
            return MatchOutcome(
                status=MatchStatus.MULTIPLE_MATCHES,
                score=best.score,
                candidates=candidates,
                reason=(
                    f"{len(tied)} stock specs score within {config.ambiguity_delta:.0f} points "
                    f"of each other ({', '.join(c.display_name for c in tied[:4])}). "
                    "The enquiry does not contain enough detail to choose."
                ),
                normalization_notes=notes or [],
            )

        return MatchOutcome(
            status=MatchStatus.MATCH_FOUND,
            stock_item=self.db.get(StockItem, best.stock_item_id),
            lot_ids=best.lot_ids,
            score=best.score,
            candidates=candidates,
            reason=(
                f"{best.display_name} scored {best.score:.1f}"
                + (
                    f", ahead of {runner_up.display_name} at {runner_up.score:.1f}."
                    if runner_up
                    else " and is the only candidate."
                )
            ),
            normalization_notes=notes or [],
        )

    def match_line_item(self, item: Any) -> MatchOutcome:
        """Convenience entry point: normalise then match."""
        spec, normalized = MatchSpec.from_line_item(item, self.rules)
        return self.match(spec, notes=normalized.notes)

    # --- Scoring ----------------------------------------------------------

    def _fetch_lots(self, spec: MatchSpec) -> list[StockItem]:
        """Narrow to a plausible set of lots before grouping into specs.

        Filtering on product type uses the index and typically cuts the stock
        list by an order of magnitude. With no stated type there is nothing to
        filter on, so every lot is considered.
        """
        query = select(StockItem)
        if spec.product_type:
            query = query.where(StockItem.product_type == spec.product_type)
        return list(self.db.scalars(query))

    def _group_specs(self, lots: list[StockItem]) -> list[SpecGroup]:
        by_id = {lot.id: lot for lot in lots}
        groups: dict[tuple, SpecGroup] = {}
        for lot in lots:
            group = SpecGroup(
                product_type=lot.product_type,
                grade=lot.grade,
                thickness_mm=lot.thickness_mm,
                width_mm=lot.width_mm,
                length_mm=lot.length_mm,
                diameter_mm=lot.diameter_mm,
                representative_id=lot.id,
            )
            existing = groups.get(group.key)
            if existing is None:
                groups[group.key] = group
                group.lot_ids.append(lot.id)
            else:
                existing.lot_ids.append(lot.id)
                # Prefer the freshest lot (lowest ageing) as the representative
                # used for display and dimension-conversion purposes.
                if (lot.ageing_days or 0) < (by_id[existing.representative_id].ageing_days or 0):
                    existing.representative_id = lot.id
        return list(groups.values())

    def _score_all(self, spec: MatchSpec) -> list[MatchCandidate]:
        lots = self._fetch_lots(spec)
        if not lots and spec.product_type:
            # The stated type has no stock at all. Fall back to scoring
            # everything so the reviewer sees the nearest alternatives rather
            # than an empty screen.
            lots = list(self.db.scalars(select(StockItem)))
        groups = self._group_specs(lots)
        return [self._score(spec, group) for group in groups]

    def _score(self, spec: MatchSpec, group: SpecGroup) -> MatchCandidate:
        weights = self.rules.matching.weights
        tolerance = self.rules.matching.tolerance
        scores: list[FieldScore] = []

        scores.append(
            self._score_text("product_type", weights.product_type, spec.product_type, group.product_type)
        )
        scores.append(self._score_text("grade", weights.grade, spec.grade, group.grade))
        # The stock list carries no separate "standard" column, so a stated
        # standard never matches - it simply widens the score gap rather than
        # blocking a match outright.
        scores.append(self._score_text("standard", weights.standard, spec.standard, None))
        scores.append(
            self._score_dimension(
                "thickness",
                weights.thickness,
                spec.thickness_mm,
                group.thickness_mm,
                tolerance.thickness_pct,
            )
        )
        scores.append(
            self._score_dimension(
                "width", weights.width, spec.width_mm, group.width_mm, tolerance.width_pct
            )
        )
        scores.append(
            self._score_dimension(
                "length", weights.length, spec.length_mm, group.length_mm, tolerance.length_pct
            )
        )
        scores.append(
            self._score_dimension(
                "diameter", weights.diameter, spec.diameter_mm, group.diameter_mm, tolerance.diameter_pct
            )
        )

        applicable = [s for s in scores if s.weight > 0]
        total_weight = sum(s.weight for s in applicable)
        awarded = sum(s.awarded for s in applicable)
        score = (awarded / total_weight * 100.0) if total_weight else 0.0

        representative = self.db.get(StockItem, group.representative_id)
        return MatchCandidate(
            stock_item_id=group.representative_id,
            display_name=representative.display_name if representative else "",
            score=score,
            applicable_weight=total_weight,
            lot_ids=group.lot_ids,
            fields=applicable,
        )

    @staticmethod
    def _score_text(name: str, weight: float, requested: str | None, candidate: str | None) -> FieldScore:
        """Text fields score all-or-nothing. Not stated means not scored."""
        if not requested:
            return FieldScore(name, 0.0, 0.0, requested, candidate, "not stated in enquiry")
        if not candidate:
            return FieldScore(name, weight, 0.0, requested, candidate, "absent on stock record")
        matched = requested.strip().casefold() == candidate.strip().casefold()
        return FieldScore(
            name,
            weight,
            weight if matched else 0.0,
            requested,
            candidate,
            "match" if matched else "differs",
        )

    @staticmethod
    def _score_dimension(
        name: str,
        weight: float,
        requested: float | None,
        candidate: float | None,
        tolerance_pct: float,
    ) -> FieldScore:
        """Dimensions score full marks inside tolerance and nothing outside it.

        A partial-credit curve would let a 12 mm plate creep up on a 10 mm one.
        In steel that is not a near miss, it is a different product, so the
        boundary is hard.
        """
        if requested is None:
            return FieldScore(name, 0.0, 0.0, requested, candidate, "not stated in enquiry")
        if candidate is None:
            return FieldScore(name, weight, 0.0, requested, candidate, "absent on stock record")

        allowed = abs(requested) * tolerance_pct / 100.0
        difference = abs(requested - candidate)
        within = difference <= max(allowed, EPSILON)

        note = (
            "exact" if difference <= EPSILON
            else f"within {tolerance_pct:g}% tolerance" if within
            else f"differs by {difference:g}mm (tolerance {tolerance_pct:g}%)"
        )
        return FieldScore(name, weight, weight if within else 0.0, requested, candidate, note)
