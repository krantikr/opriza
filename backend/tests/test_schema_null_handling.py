"""Structured-output schemas: the word "null" is not a value.

Strict `json_schema` mode guarantees the *shape* of a model's response and
nothing about its meaning, so `"payment_terms": "null"` is a valid string as
far as the API is concerned. Q-000014 was recorded with
`required_delivery_date="null"`, `payment_terms="null"` and
`missing_information=["null"]` - the last of which is a non-empty list, and so
routed a complete enquiry to NEEDS_INFORMATION.
"""

from __future__ import annotations

import pytest

from ai.schemas import ClassificationResult, ExtractedEnquiry, QuantityUnit, SteelLineItem

LINE = {
    "raw_text": "IS 2062 E350C plate, 25mm x 2500 x 12000",
    "product_type": "plate",
    "grade": "E350C",
    "standard": "IS 2062",
    "thickness_mm": 25.0,
    "width_mm": 2500.0,
    "length_mm": 12000.0,
    "diameter_mm": None,
    "quantity": 30.0,
    "quantity_unit": "MT",
    "remarks": None,
}


def enquiry(**overrides) -> dict:
    return {
        "customer_name": "Ramesh Gupta",
        "customer_company": "Gupta Steel Traders",
        "delivery_location": "Nagpur",
        "required_delivery_date": None,
        "payment_terms": None,
        "additional_requirements": [],
        "line_items": [LINE],
        "missing_information": [],
        **overrides,
    }


# --- The regression --------------------------------------------------------


def test_the_word_null_becomes_an_absent_value():
    """Exactly what the extractor returned for Q-000014."""
    result = ExtractedEnquiry.model_validate(
        enquiry(required_delivery_date="null", payment_terms="null")
    )

    assert result.required_delivery_date is None
    assert result.payment_terms is None


def test_a_placeholder_is_not_a_missing_information_entry():
    """`["null"]` is non-empty, and a non-empty list blocks the auto path."""
    result = ExtractedEnquiry.model_validate(enquiry(missing_information=["null"]))
    assert result.missing_information == []


def test_real_gaps_are_still_reported():
    result = ExtractedEnquiry.model_validate(
        enquiry(missing_information=["quantity not stated", "null"])
    )
    assert result.missing_information == ["quantity not stated"]


@pytest.mark.parametrize(
    "written", ["null", "NULL", "None", "n/a", "N/A", "nil", "-", "", "  null  ", "not stated"]
)
def test_placeholder_spellings(written):
    result = ExtractedEnquiry.model_validate(enquiry(payment_terms=written))
    assert result.payment_terms is None


def test_placeholders_are_cleaned_on_nested_line_items():
    line = {**LINE, "grade": "null", "remarks": "none"}
    result = ExtractedEnquiry.model_validate(enquiry(line_items=[line]))

    assert result.line_items[0].grade is None
    assert result.line_items[0].remarks is None
    assert result.line_items[0].product_type == "plate"


def test_additional_requirements_placeholders_are_dropped():
    result = ExtractedEnquiry.model_validate(
        enquiry(additional_requirements=["none", "mill test certificate"])
    )
    assert result.additional_requirements == ["mill test certificate"]


# --- What must not be cleaned ----------------------------------------------


def test_real_values_survive_untouched():
    result = ExtractedEnquiry.model_validate(
        enquiry(required_delivery_date="2026-09-01", payment_terms="30 days credit")
    )

    assert result.required_delivery_date == "2026-09-01"
    assert result.payment_terms == "30 days credit"
    assert result.line_items[0].quantity_unit is QuantityUnit.MT


def test_a_required_field_is_left_exactly_as_the_model_wrote_it():
    """Clearing it would fail validation and discard the whole extraction.

    Losing a real enquiry over one cosmetic string is a worse outcome than a
    reviewer seeing the word in a field they are reading anyway.
    """
    item = SteelLineItem.model_validate({**LINE, "raw_text": "null"})
    assert item.raw_text == "null"


def test_a_required_classification_reason_is_left_alone():
    result = ClassificationResult.model_validate(
        {"category": "QUOTATION_REQUEST", "confidence": 0.95, "reason": "null"}
    )
    assert result.reason == "null"


def test_a_genuine_hyphen_in_a_longer_string_is_not_a_placeholder():
    result = ExtractedEnquiry.model_validate(enquiry(delivery_location="Nagpur - MIDC"))
    assert result.delivery_location == "Nagpur - MIDC"
