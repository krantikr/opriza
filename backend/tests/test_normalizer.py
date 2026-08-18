"""Product-type normalisation, and specifically its tolerance of a sloppy
extraction.

The bug these tests pin down: an enquiry for "IS 2062 E350C plate, 25mm x 2500
x 12000" was extracted once with `product_type="plate"` and, on an identical
email a day later, with `product_type="IS 2062 E350C plate"`. The second form
resolved to nothing, scored zero on a 30-point field, and dropped a 95.6 match
to 62.2 - below the acceptance threshold - so no draft was produced.

The fix must not be bought with a loosening of the rule that keeps
"Chequered Plate" and "SS Pipe" away from plain plate and pipe stock, so those
refusals are asserted here alongside the new behaviour.
"""

from __future__ import annotations

import pytest

from app.services.products.normalizer import normalize_spec

# --- The regression --------------------------------------------------------


def test_whole_spec_written_into_the_product_type_still_resolves():
    """The exact string that broke Q-000014."""
    spec = normalize_spec(
        product_type="IS 2062 E350C plate", grade="E350C", standard="IS 2062"
    )

    assert spec.product_type == "Plate"
    assert spec.grade == "E350C"
    assert spec.standard == "IS 2062"
    # E350C is absent from the grade synonym table and so is still reported as
    # unresolved - correctly, since it matches the stock list verbatim. What
    # must no longer be unresolved is the product type.
    assert not any(u.startswith("product_type=") for u in spec.unresolved)


def test_the_reduction_is_recorded_for_the_reviewer():
    """A silent repair is a repair nobody can audit."""
    spec = normalize_spec(
        product_type="IS 2062 E350C plate", grade="E350C", standard="IS 2062"
    )

    assert any("grade, standard and size words ignored" in note for note in spec.notes)


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("IS 2062 E350C plate", "Plate"),
        ("E250 plate", "Plate"),
        ("25mm plate", "Plate"),
        ("IS2062 E250 MS Plate", "Plate"),
        ("Fe500 tmt bar", "TMT Bar"),
        ("ISMB 200", "Beam"),
        ("IS 1239 pipe", "Pipe"),
    ],
)
def test_grade_standard_and_size_words_do_not_block_the_form(written, expected):
    """None of these words say whether it is a plate or a channel."""
    assert normalize_spec(product_type=written).product_type == expected


def test_the_second_pass_does_not_need_grade_to_be_extracted_separately():
    """The failure mode is duplication, but the tokens may appear only here."""
    spec = normalize_spec(product_type="IS 2062 E350C plate")
    assert spec.product_type == "Plate"


# --- The refusals that must survive it -------------------------------------


@pytest.mark.parametrize(
    "written",
    [
        "Chequered Plate",
        "Perforated Sheet",
        "SS Pipe",
        "SS 304 pipe",
        "IS 2062 chequered plate",
        "E350C chequered plate",
    ],
)
def test_a_qualifier_that_changes_the_material_still_blocks_resolution(written):
    """Stripping grade and size words must not strip meaning.

    `SS 304 pipe` loses only `304`; the `ss` that makes it stainless survives,
    so it stays unresolved rather than being priced as carbon-steel pipe.
    """
    spec = normalize_spec(product_type=written)
    assert spec.unresolved, f"{written!r} must not resolve to a canonical type"


def test_a_product_type_of_only_grade_and_size_words_resolves_to_nothing():
    """Reducing to an empty string must not be read as a match."""
    spec = normalize_spec(product_type="IS 2062 E350C")
    assert spec.product_type == "Is 2062 E350C"
    assert spec.unresolved


# --- Unchanged behaviour ---------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("MS plate", "Plate"),
        ("plates", "Plate"),
        ("HR Coil", "Coil"),
        ("tmt bar", "TMT Bar"),
        ("ISMB", "Beam"),
        ("round bar", "Round Bar"),
        ("Steel Plate", "Plate"),
    ],
)
def test_first_pass_resolution_is_untouched(written, expected):
    assert normalize_spec(product_type=written).product_type == expected


def test_a_first_pass_hit_is_not_annotated_as_a_reduction():
    spec = normalize_spec(product_type="MS plate")
    assert not any("ignored" in note for note in spec.notes)
