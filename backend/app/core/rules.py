"""Typed loader for `config/business_rules.yaml`.

The YAML is parsed into Pydantic models rather than passed around as nested
dicts. A typo in the rules file then fails loudly at load time with the field
name, instead of silently becoming a `None` in the middle of a price
calculation.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core.paths import PROJECT_ROOT

RULES_FILE = PROJECT_ROOT / "backend" / "app" / "config" / "business_rules.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Matching --------------------------------------------------------------


class MatchWeights(_Strict):
    product_type: float
    grade: float
    standard: float
    thickness: float
    width: float
    length: float
    diameter: float

    @property
    def total(self) -> float:
        return (
            self.product_type
            + self.grade
            + self.standard
            + self.thickness
            + self.width
            + self.length
            + self.diameter
        )


class MatchTolerance(_Strict):
    thickness_pct: float
    width_pct: float
    length_pct: float
    diameter_pct: float


class Synonyms(_Strict):
    product_type: dict[str, str] = Field(default_factory=dict)
    grade: dict[str, str] = Field(default_factory=dict)


class MatchingRules(_Strict):
    accept_score: float
    ambiguity_delta: float
    weights: MatchWeights
    tolerance: MatchTolerance
    ignorable_qualifiers: list[str] = Field(default_factory=list)
    standard_prefixes: list[str] = Field(default_factory=list)
    synonyms: Synonyms


# --- Stock pricing -----------------------------------------------------


class RoundingRule(_Strict):
    enabled: bool
    nearest: int
    mode: str = "nearest"


class StockPricingRule(_Strict):
    """A suggested rate is always cost-plus, never an approved price."""

    enabled: bool
    markup_pct: float
    rounding: RoundingRule


# --- Confidence / review ---------------------------------------------------


class HighConfidenceRule(_Strict):
    require_exact_match: bool
    require_stock_match: bool
    min_lots: int
    require_customer_known: bool


class MediumConfidenceRule(_Strict):
    min_lots: int


class ConfidenceRules(_Strict):
    high: HighConfidenceRule
    medium: MediumConfidenceRule


class ForceManualRule(_Strict):
    missing_information: bool
    no_stock_match: bool
    ambiguous_product_match: bool
    no_product_match: bool
    insufficient_balance: bool
    low_confidence: bool


class ReviewRules(_Strict):
    force_manual_when: ForceManualRule


# --- Commercial terms ------------------------------------------------------


class QuotationRules(_Strict):
    validity_days: int
    gst_extra: bool
    freight_extra: bool
    price_basis: str
    terms: list[str]

    def rendered_terms(self) -> list[str]:
        """Terms with `{validity_days}` style placeholders filled in."""
        return [t.format(validity_days=self.validity_days) for t in self.terms]


class BusinessRules(_Strict):
    version: str
    currency: str
    base_unit: str
    matching: MatchingRules
    stock_pricing: StockPricingRule
    confidence: ConfidenceRules
    review: ReviewRules
    quotation: QuotationRules


@lru_cache(maxsize=1)
def get_rules(path: Path | None = None) -> BusinessRules:
    """Load and validate the business rules. Cached for the process lifetime."""
    rules_path = path or RULES_FILE
    with rules_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return BusinessRules.model_validate(raw)


def reload_rules() -> BusinessRules:
    """Drop the cache and re-read the file (used by tests and the admin API)."""
    get_rules.cache_clear()
    return get_rules()
