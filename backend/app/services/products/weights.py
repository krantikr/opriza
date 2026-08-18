"""Deterministic weight and unit conversion for steel products.

Enquiries arrive in MT, KG, pieces, running metres or square metres. The price
master is per MT. Converting between them is pure physics and standard
sectional-weight formulas - there is no judgement involved, so no language
model is ever asked to do it.

Every conversion returns the arithmetic it used in `basis`, so a reviewer can
check the tonnage on the screen rather than trusting it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ai.schemas import QuantityUnit

# Density of structural steel. The single physical constant in the system.
STEEL_DENSITY_G_CM3 = 7.85

# kg per (mm x mm x mm) of steel: 7.85 g/cm3 -> 7.85e-6 kg/mm3
_KG_PER_MM3 = STEEL_DENSITY_G_CM3 * 1e-6

# Rebar/round-bar shorthand: kg per metre = d^2 / 162.28 (d in mm).
_ROUND_BAR_DIVISOR = 162.28

# Steel tube: kg per metre = 0.02466 * t * (OD - t), both in mm.
_PIPE_COEFFICIENT = 0.02466

_ROUND_TYPES = {"round bar", "tmt bar", "rebar", "bar"}
_TUBULAR_TYPES = {"pipe", "tube", "hollow section"}
_FLAT_TYPES = {"plate", "sheet", "coil", "flat bar", "strip"}
_ANGLE_TYPES = {"angle"}


@dataclass(frozen=True, slots=True)
class Dimensions:
    """Everything needed to weigh a product, from whatever source is available.

    Populated from a matched `StockItem` when one exists, otherwise from the
    dimensions extracted out of the enquiry itself.
    """

    product_type: str | None = None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    diameter_mm: float | None = None
    weight_per_piece_kg: float | None = None

    @classmethod
    def from_obj(cls, obj: Any) -> Dimensions:
        """Build from any object exposing the dimension attributes."""
        return cls(
            product_type=getattr(obj, "product_type", None),
            thickness_mm=getattr(obj, "thickness_mm", None),
            width_mm=getattr(obj, "width_mm", None),
            length_mm=getattr(obj, "length_mm", None),
            diameter_mm=getattr(obj, "diameter_mm", None),
            weight_per_piece_kg=getattr(obj, "weight_per_piece_kg", None),
        )

    @property
    def normalized_type(self) -> str:
        return (self.product_type or "").strip().casefold()


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """A tonnage figure plus the calculation that produced it."""

    quantity_mt: Decimal
    basis: str


def _dec(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


# ---------------------------------------------------------------------------
# Per-metre weights
# ---------------------------------------------------------------------------


def weight_kg_per_metre(dims: Dimensions) -> tuple[float, str] | None:
    """Weight of one running metre, or None if the dimensions are insufficient."""
    ptype = dims.normalized_type

    if ptype in _ROUND_TYPES and dims.diameter_mm:
        d = dims.diameter_mm
        return d * d / _ROUND_BAR_DIVISOR, f"{d:g}mm dia round: d^2/{_ROUND_BAR_DIVISOR}"

    if ptype in _TUBULAR_TYPES and dims.diameter_mm and dims.thickness_mm:
        od, t = dims.diameter_mm, dims.thickness_mm
        kg_m = _PIPE_COEFFICIENT * t * (od - t)
        return kg_m, f"pipe OD {od:g}mm x {t:g}mm: {_PIPE_COEFFICIENT} x t x (OD - t)"

    if ptype in _ANGLE_TYPES and dims.width_mm and dims.thickness_mm:
        leg, t = dims.width_mm, dims.thickness_mm
        kg_m = (2 * leg - t) * t * _KG_PER_MM3 * 1000
        return kg_m, f"equal angle {leg:g}x{leg:g}x{t:g}: (2a - t) x t x density"

    if dims.thickness_mm and dims.width_mm:
        # Plate, sheet, coil, flat bar: a rectangular cross-section.
        t, w = dims.thickness_mm, dims.width_mm
        kg_m = t * w * _KG_PER_MM3 * 1000
        return kg_m, f"section {t:g}mm x {w:g}mm x density {STEEL_DENSITY_G_CM3}"

    return None


def weight_kg_per_piece(dims: Dimensions) -> tuple[float, str] | None:
    """Weight of one piece, or None if it cannot be determined.

    A stored `weight_per_piece_kg` on the product master wins: rolled sections
    such as channels and beams have standard sectional weights that no simple
    formula reproduces accurately.
    """
    if dims.weight_per_piece_kg:
        return dims.weight_per_piece_kg, "product master sectional weight"

    per_metre = weight_kg_per_metre(dims)
    if per_metre and dims.length_mm:
        kg_m, basis = per_metre
        length_m = dims.length_mm / 1000.0
        return kg_m * length_m, f"{basis}, x {length_m:g} m length"

    return None


# ---------------------------------------------------------------------------
# Conversion to metric tonnes
# ---------------------------------------------------------------------------


def convert_to_mt(
    quantity: Decimal | float | None,
    unit: QuantityUnit | str | None,
    dims: Dimensions,
) -> ConversionResult | None:
    """Convert a requested quantity into metric tonnes.

    Returns None when the conversion is not determinable - the caller then
    routes the line to manual review rather than assuming a tonnage.
    """
    if quantity is None:
        return None

    qty = Decimal(str(quantity))
    if qty <= 0:
        return None

    unit_value = QuantityUnit(unit) if unit else QuantityUnit.UNKNOWN

    if unit_value is QuantityUnit.MT:
        return ConversionResult(qty, "quantity already in MT")

    if unit_value is QuantityUnit.KG:
        return ConversionResult(qty / Decimal(1000), f"{qty:g} kg / 1000")

    if unit_value in (QuantityUnit.MTR, QuantityUnit.FT):
        per_metre = weight_kg_per_metre(dims)
        if not per_metre:
            return None
        kg_m, basis = per_metre
        metres = qty if unit_value is QuantityUnit.MTR else qty * Decimal("0.3048")
        kg = metres * _dec(kg_m)
        return ConversionResult(
            kg / Decimal(1000),
            f"{metres:g} m x {kg_m:.3f} kg/m ({basis}) / 1000",
        )

    if unit_value is QuantityUnit.PCS:
        per_piece = weight_kg_per_piece(dims)
        if not per_piece:
            return None
        kg_pc, basis = per_piece
        kg = qty * _dec(kg_pc)
        return ConversionResult(
            kg / Decimal(1000),
            f"{qty:g} pcs x {kg_pc:.3f} kg/pc ({basis}) / 1000",
        )

    if unit_value is QuantityUnit.SQM:
        if not dims.thickness_mm:
            return None
        kg = qty * _dec(dims.thickness_mm * STEEL_DENSITY_G_CM3)
        return ConversionResult(
            kg / Decimal(1000),
            f"{qty:g} m2 x {dims.thickness_mm:g}mm x {STEEL_DENSITY_G_CM3} kg/m2/mm / 1000",
        )

    # QuantityUnit.UNKNOWN - the enquiry did not state a unit. Guessing here
    # would be guessing at the order value, so the line goes to a human.
    return None
