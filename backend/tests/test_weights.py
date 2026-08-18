"""Weight and unit conversion.

These numbers are checked against standard sectional weights rather than
against the implementation, because the whole point of the module is that a
20 MT enquiry and a 40-piece enquiry for the same material arrive at the same
tonnage.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ai.schemas import QuantityUnit
from app.services.products.weights import (
    Dimensions,
    convert_to_mt,
    weight_kg_per_metre,
    weight_kg_per_piece,
)


def test_plate_weight_matches_the_standard_calculation():
    """10 x 1500 x 6000 mm plate weighs 706.5 kg."""
    dims = Dimensions(product_type="Plate", thickness_mm=10, width_mm=1500, length_mm=6000)
    weight, _ = weight_kg_per_piece(dims)
    assert weight == pytest.approx(706.5, abs=0.1)


def test_round_bar_uses_the_d_squared_over_162_rule():
    """16 mm bar is 1.578 kg/m."""
    dims = Dimensions(product_type="Round Bar", diameter_mm=16)
    kg_per_m, basis = weight_kg_per_metre(dims)
    assert kg_per_m == pytest.approx(1.578, abs=0.005)
    assert "162" in basis


def test_pipe_uses_the_tube_formula():
    """OD 50 x 3.2 mm pipe is 3.693 kg/m."""
    dims = Dimensions(product_type="Pipe", diameter_mm=50, thickness_mm=3.2)
    kg_per_m, _ = weight_kg_per_metre(dims)
    assert kg_per_m == pytest.approx(3.693, abs=0.005)


def test_equal_angle_matches_the_published_sectional_weight():
    """ISA 75 x 75 x 6 is 6.8 kg/m in the standard."""
    dims = Dimensions(product_type="Angle", width_mm=75, thickness_mm=6)
    kg_per_m, _ = weight_kg_per_metre(dims)
    assert kg_per_m == pytest.approx(6.8, abs=0.05)


def test_stored_sectional_weight_wins_over_any_formula():
    """Rolled sections such as beams have no simple formula, so the master wins."""
    dims = Dimensions(product_type="Beam", width_mm=200, length_mm=6000, weight_per_piece_kg=152.4)
    weight, basis = weight_kg_per_piece(dims)
    assert weight == 152.4
    assert "master" in basis


# --- Conversion to MT ------------------------------------------------------


def test_mt_passes_through_unchanged():
    result = convert_to_mt(Decimal("20"), QuantityUnit.MT, Dimensions())
    assert result.quantity_mt == Decimal("20")


def test_kilograms_convert_to_tonnes():
    result = convert_to_mt(Decimal("2500"), QuantityUnit.KG, Dimensions())
    assert result.quantity_mt == Decimal("2.5")


def test_pieces_convert_using_piece_weight():
    """40 ISMB 200 beams at 152.4 kg each = 6.096 MT."""
    dims = Dimensions(product_type="Beam", weight_per_piece_kg=152.4)
    result = convert_to_mt(Decimal("40"), QuantityUnit.PCS, dims)
    assert result.quantity_mt == pytest.approx(Decimal("6.096"), abs=Decimal("0.001"))
    assert "40 pcs" in result.basis


def test_running_metres_convert_using_per_metre_weight():
    """1200 m of OD 50 x 3.2 pipe at 3.693 kg/m = 4.43 MT."""
    dims = Dimensions(product_type="Pipe", diameter_mm=50, thickness_mm=3.2)
    result = convert_to_mt(Decimal("1200"), QuantityUnit.MTR, dims)
    assert float(result.quantity_mt) == pytest.approx(4.432, abs=0.01)


def test_square_metres_convert_using_thickness():
    """100 m2 of 10 mm plate = 7.85 MT."""
    dims = Dimensions(product_type="Plate", thickness_mm=10)
    result = convert_to_mt(Decimal("100"), QuantityUnit.SQM, dims)
    assert float(result.quantity_mt) == pytest.approx(7.85, abs=0.01)


def test_the_conversion_explains_its_own_arithmetic():
    """A reviewer must be able to check the tonnage, not just trust it."""
    dims = Dimensions(product_type="Round Bar", diameter_mm=16)
    result = convert_to_mt(Decimal("500"), QuantityUnit.MTR, dims)
    assert "kg/m" in result.basis
    assert "162" in result.basis


# --- Refusals --------------------------------------------------------------


def test_unknown_unit_refuses_to_guess():
    """A quantity with no unit is an unknown order value, so it goes to a human."""
    dims = Dimensions(product_type="Plate", thickness_mm=10, width_mm=1500, length_mm=6000)
    assert convert_to_mt(Decimal("20"), QuantityUnit.UNKNOWN, dims) is None


def test_pieces_without_dimensions_refuses_to_guess():
    assert convert_to_mt(Decimal("40"), QuantityUnit.PCS, Dimensions(product_type="Beam")) is None


def test_metres_without_a_cross_section_refuses_to_guess():
    assert convert_to_mt(Decimal("100"), QuantityUnit.MTR, Dimensions(product_type="Pipe")) is None


@pytest.mark.parametrize("quantity", [None, Decimal("0"), Decimal("-5")])
def test_non_positive_quantities_are_rejected(quantity):
    assert convert_to_mt(quantity, QuantityUnit.MT, Dimensions()) is None
