"""Deterministic product matching.

The behaviour these tests protect is the refusal to guess. It is easy to write
a matcher that always returns its best candidate; the value here is in the two
cases where it returns nothing and asks a human instead.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.models import MatchStatus, Product, QuantityUnit
from app.services.products.matcher import MatchSpec, ProductMatcher
from app.services.products.normalizer import normalize_spec


@dataclass
class Line:
    """Stand-in for an extracted line item."""

    product_type: str | None = None
    grade: str | None = None
    standard: str | None = None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    diameter_mm: float | None = None


@pytest.fixture()
def catalogue(db, plate: Product, wide_plate: Product) -> dict[str, Product]:
    """The reference plates plus a few products from other families."""
    extras = [
        Product(
            product_code="PLT-E250-12X1500X6000",
            product_type="Plate",
            grade="E250",
            standard="IS 2062",
            thickness_mm=12.0,
            width_mm=1500.0,
            length_mm=6000.0,
        ),
        Product(
            product_code="ANG-E250-75X75X6",
            product_type="Angle",
            grade="E250",
            standard="IS 2062",
            thickness_mm=6.0,
            width_mm=75.0,
            length_mm=6000.0,
        ),
        Product(
            product_code="ANG-E250-75X75X8",
            product_type="Angle",
            grade="E250",
            standard="IS 2062",
            thickness_mm=8.0,
            width_mm=75.0,
            length_mm=6000.0,
        ),
        Product(
            product_code="TMT-FE500-D16",
            product_type="TMT Bar",
            grade="Fe500",
            standard="IS 1786",
            diameter_mm=16.0,
            length_mm=12000.0,
        ),
        Product(
            product_code="TMT-FE500-D20",
            product_type="TMT Bar",
            grade="Fe500",
            standard="IS 1786",
            diameter_mm=20.0,
            length_mm=12000.0,
        ),
        Product(
            product_code="SHT-E250-3X1250X2500",
            product_type="Sheet",
            grade="E250",
            standard="IS 2062",
            thickness_mm=3.0,
            width_mm=1250.0,
            length_mm=2500.0,
        ),
        Product(
            product_code="PIP-E250-OD50X3.2",
            product_type="Pipe",
            grade="E250",
            standard="IS 1239",
            diameter_mm=50.0,
            thickness_mm=3.2,
            length_mm=6000.0,
        ),
        Product(
            product_code="PIP-E250-OD50X2.9",
            product_type="Pipe",
            grade="E250",
            standard="IS 1239",
            diameter_mm=50.0,
            thickness_mm=2.9,
            length_mm=6000.0,
        ),
    ]
    for product in extras:
        product.unit = QuantityUnit.MT
    db.add_all(extras)
    db.commit()
    return {p.product_code: p for p in [plate, wide_plate, *extras]}


# --- The confident path ----------------------------------------------------


def test_fully_specified_enquiry_matches_exactly_one_product(db, catalogue):
    """'IS 2062 E250 plate, 10mm x 1500 x 6000' - the textbook case."""
    outcome = ProductMatcher(db).match_line_item(
        Line("plate", "E250", "IS 2062", thickness_mm=10, width_mm=1500, length_mm=6000)
    )

    assert outcome.status is MatchStatus.MATCH_FOUND
    assert outcome.product.product_code == "PLT-E250-10X1500X6000"
    assert outcome.score == pytest.approx(100.0)


def test_section_designation_matches_on_diameter(db, catalogue):
    """'TMT bars Fe500, 16mm dia' - identified by diameter, not thickness."""
    outcome = ProductMatcher(db).match_line_item(
        Line("TMT bars", "Fe500", diameter_mm=16)
    )

    assert outcome.status is MatchStatus.MATCH_FOUND
    assert outcome.product.product_code == "TMT-FE500-D16"


def test_wall_thickness_separates_otherwise_identical_pipes(db, catalogue):
    outcome = ProductMatcher(db).match_line_item(
        Line("MS Pipe", standard="IS 1239", diameter_mm=50, thickness_mm=3.2)
    )

    assert outcome.status is MatchStatus.MATCH_FOUND
    assert outcome.product.product_code == "PIP-E250-OD50X3.2"


def test_thickness_is_held_exact_so_a_near_size_never_wins(db, catalogue):
    """12 mm is not a near miss for 10 mm - it is a different product."""
    outcome = ProductMatcher(db).match_line_item(
        Line("plate", "E250", thickness_mm=10, width_mm=1500, length_mm=6000)
    )

    assert outcome.product.product_code == "PLT-E250-10X1500X6000"
    scores = {c.product_code: c.score for c in outcome.candidates}
    assert scores["PLT-E250-12X1500X6000"] < scores["PLT-E250-10X1500X6000"]


# --- The refusals ----------------------------------------------------------


def test_underspecified_enquiry_is_reported_as_ambiguous(db, catalogue):
    """'MS plate 10mm' fits two widths equally. The system must not choose."""
    outcome = ProductMatcher(db).match_line_item(Line("MS plate", "MS", thickness_mm=10))

    assert outcome.status is MatchStatus.MULTIPLE_MATCHES
    assert outcome.product is None
    tied = [c.product_code for c in outcome.candidates[:2]]
    assert "PLT-E250-10X1500X6000" in tied
    assert "PLT-E250-10X2000X6300" in tied
    assert "not contain enough detail" in outcome.reason


def test_material_absent_from_the_master_is_no_match(db, catalogue):
    """SS 304 is not stocked. No price may be invented for it."""
    outcome = ProductMatcher(db).match_line_item(Line("sheet", "SS 304", thickness_mm=3))

    assert outcome.status is MatchStatus.NO_MATCH
    assert outcome.product is None
    assert "below the acceptance threshold" in outcome.reason


def test_ambiguous_outcome_still_reports_the_candidates(db, catalogue):
    """The reviewer needs the shortlist, not an empty screen."""
    outcome = ProductMatcher(db).match_line_item(Line("plate", "E250", thickness_mm=10))

    assert len(outcome.candidates_as_json()) >= 2
    first = outcome.candidates_as_json()[0]
    assert "score" in first and "fields" in first


def test_scoring_is_explained_field_by_field(db, catalogue):
    outcome = ProductMatcher(db).match_line_item(
        Line("plate", "E250", thickness_mm=10, width_mm=1500, length_mm=6000)
    )

    fields = {f.field: f for f in outcome.candidates[0].fields}
    assert fields["thickness"].note == "exact"
    assert fields["product_type"].awarded > 0
    # Diameter was never asked for, so it must not be scored at all.
    assert "diameter" not in fields


def test_unstated_fields_do_not_count_against_a_candidate(db, catalogue):
    """An enquiry omitting length is judged on less evidence, not penalised."""
    outcome = ProductMatcher(db).match_line_item(
        Line("Angle", "E250", thickness_mm=6, width_mm=75)
    )

    assert outcome.status is MatchStatus.MATCH_FOUND
    assert outcome.product.product_code == "ANG-E250-75X75X6"
    assert outcome.score == pytest.approx(100.0)


def test_empty_master_yields_no_match_rather_than_an_error(db):
    outcome = ProductMatcher(db).match(MatchSpec(product_type="Plate", thickness_mm=10))
    assert outcome.status is MatchStatus.NO_MATCH


# --- Normalisation ---------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("MS plate", "Plate"),
        ("plates", "Plate"),
        ("HR Coil", "Coil"),
        ("tmt bar", "TMT Bar"),
        ("ISMB", "Beam"),
        ("round bar", "Round Bar"),
    ],
)
def test_product_type_synonyms_resolve(written, expected):
    assert normalize_spec(product_type=written).product_type == expected


@pytest.mark.parametrize(
    ("written", "expected"),
    [("MS", "E250"), ("mild steel", "E250"), ("E 250", "E250"), ("Fe500", "Fe500")],
)
def test_grade_synonyms_resolve(written, expected):
    assert normalize_spec(product_type="Plate", grade=written).grade == expected


def test_a_standard_written_in_the_grade_field_is_moved_across():
    """'IS 1239' is a standard, not a grade, however the customer typed it."""
    spec = normalize_spec(product_type="Pipe", grade="IS 1239")
    assert spec.standard == "IS 1239"
    assert spec.grade is None


def test_standard_spacing_is_canonicalised():
    assert normalize_spec(product_type="Plate", standard="IS2062").standard == "IS 2062"


def test_unresolved_vocabulary_is_reported_not_silently_dropped():
    """Unknown terms are kept and flagged, so the AI fallback can be tried."""
    spec = normalize_spec(product_type="Chequered Plate", grade="SS 304")
    assert spec.product_type == "Chequered Plate"
    assert spec.grade == "SS 304"
    assert len(spec.unresolved) == 2


@pytest.mark.parametrize(
    ("written", "expected"),
    [("Steel Plate", "Plate"), ("MS Plate", "Plate"), ("HR Plate", "Plate")],
)
def test_benign_qualifiers_are_ignored(written, expected):
    """The spec's own example writes 'Steel Plate'. That is still a plate."""
    assert normalize_spec(product_type=written).product_type == expected


@pytest.mark.parametrize("written", ["Chequered Plate", "Perforated Sheet", "SS Pipe"])
def test_meaningful_qualifiers_block_resolution(written):
    """A qualifier that changes the material must not be discarded."""
    spec = normalize_spec(product_type=written)
    assert spec.unresolved, f"{written!r} should not resolve to a canonical type"


@pytest.mark.parametrize("grade", ["E250", "E350", "Fe500", "Fe550"])
def test_grade_tokens_are_not_mistaken_for_standards(grade):
    """'E250' has the same shape as 'IS 2062' but is not a standard."""
    spec = normalize_spec(product_type="Plate", grade=grade)
    assert spec.standard is None
    assert spec.grade == grade
