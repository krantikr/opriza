"""Typed contracts for every LLM output in the system.

Design rules that make these schemas safe:

* **No defaults on LLM-facing fields.** A field without a default is emitted as
  `required` in the generated JSON Schema, so strict structured-output mode
  forces the model to produce every key explicitly. A value it could not find
  must come back as an explicit `null` rather than a silently missing key -
  that is the difference between "not stated" and "the model forgot".
* **`extra="forbid"`** so the generated schema carries
  `additionalProperties: false`, which strict mode requires.
* **Dimensions are named with their unit** (`thickness_mm`, not `thickness`).
  Unit ambiguity is the cheapest way to mis-price a steel enquiry.
* **`raw_text` on every line item** so a human reviewer can always trace an
  extracted number back to the sentence it came from.

This module deliberately imports nothing from the backend: the `ai` package is
pure language intelligence with no database, HTTP or business-rule knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Words a model writes when it means "nothing here" but is being asked for a
# string. Strict schema mode guarantees the *shape* of the response, never the
# semantics, so `"required_delivery_date": "null"` is a perfectly valid string
# as far as the API is concerned - and then reads downstream as a real value.
# One observed consequence: `missing_information: ["null"]` is a non-empty list,
# which routes a complete enquiry to NEEDS_INFORMATION.
_NULL_PLACEHOLDERS = frozenset(
    {
        "",
        "-",
        "--",
        "n/a",
        "na",
        "nil",
        "none",
        "not applicable",
        "not mentioned",
        "not provided",
        "not specified",
        "not stated",
        "null",
    }
)


def _is_null_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() in _NULL_PLACEHOLDERS


def _allows_none(annotation: Any) -> bool:
    """True for `X | None` fields, i.e. those declared as genuinely optional."""
    return get_origin(annotation) in (Union, UnionType) and type(None) in get_args(annotation)


class EmailCategory(StrEnum):
    """Inbound email taxonomy (spec section 11).

    Only QUOTATION_REQUEST is actioned by the MVP. Everything else is recorded
    and surfaced as unsupported rather than silently generating a commercial
    reply.
    """

    QUOTATION_REQUEST = "QUOTATION_REQUEST"
    PRICE_NEGOTIATION = "PRICE_NEGOTIATION"
    ORDER = "ORDER"
    DELIVERY_QUERY = "DELIVERY_QUERY"
    PAYMENT_QUERY = "PAYMENT_QUERY"
    COMPLAINT = "COMPLAINT"
    GENERAL = "GENERAL"
    SPAM = "SPAM"
    OTHER = "OTHER"


class ReplyIntent(StrEnum):
    """What the customer wants, in a reply to a quotation we already sent."""

    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class QuantityUnit(StrEnum):
    """Units an enquiry may quote in. Converted to MT by the weight service."""

    MT = "MT"
    KG = "KG"
    PCS = "PCS"
    MTR = "MTR"
    FT = "FT"
    SQM = "SQM"
    UNKNOWN = "UNKNOWN"


class LLMBaseModel(BaseModel):
    """Base for structured-output models: strict, no extra keys."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    @model_validator(mode="before")
    @classmethod
    def _drop_null_placeholders(cls, data: Any) -> Any:
        """Turn the *word* "null" back into an actual absence of a value.

        Applied only where the schema already says the value is optional, and
        to the elements of list fields.

        A required field is deliberately left as the model wrote it. Clearing
        `raw_text` or `reason` would fail validation and cost the whole
        extraction - a real enquiry discarded over one cosmetic string - which
        is a worse outcome than a reviewer seeing the word "null" in a field
        they are reading anyway.
        """
        if not isinstance(data, dict):
            return data

        cleaned = dict(data)
        for name, field_info in cls.model_fields.items():
            if name not in cleaned:
                continue
            value = cleaned[name]
            if isinstance(value, list):
                cleaned[name] = [item for item in value if not _is_null_placeholder(item)]
            elif _is_null_placeholder(value) and _allows_none(field_info.annotation):
                cleaned[name] = None
        return cleaned


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class ClassificationResult(LLMBaseModel):
    """Stage 2 output: what kind of email is this?"""

    category: EmailCategory = Field(description="The single best-fitting category.")
    confidence: float = Field(
        description="Model's own confidence in the category, between 0.0 and 1.0.",
        ge=0.0,
        le=1.0,
    )
    reason: str = Field(description="One short sentence justifying the category.")


# ---------------------------------------------------------------------------
# Reply classification
# ---------------------------------------------------------------------------


class ReplyClassification(LLMBaseModel):
    """What a customer's reply to an already-sent quotation is telling us."""

    intent: ReplyIntent = Field(description="The single best-fitting intent.")
    confidence: float = Field(
        description="Model's own confidence in the intent, between 0.0 and 1.0.",
        ge=0.0,
        le=1.0,
    )
    reason: str = Field(description="One short sentence justifying the intent.")
    promised_date: str | None = Field(
        default=None,
        description=(
            "If the customer named a date or timeframe by which they would come "
            "back - 'we will confirm by Friday', 'decision next week', 'after the "
            "15th' - repeat it here exactly as they wrote it. Null if they gave "
            "no timeframe. Never infer or invent one."
        ),
    )
    awaiting_us: bool = Field(
        default=False,
        description=(
            "True when the customer has asked something that needs an answer from "
            "us - a question, a request for a revision, a document. False when the "
            "reply needs nothing back, such as a plain acknowledgement."
        ),
    )


# ---------------------------------------------------------------------------
# Requirement extraction
# ---------------------------------------------------------------------------


class SteelLineItem(LLMBaseModel):
    """One requested material line within an enquiry.

    Real steel RFQs routinely list several items, so extraction always returns a
    list even when the enquiry has a single line.
    """

    raw_text: str = Field(
        description="The verbatim text from the email describing this item, for traceability."
    )
    product_type: str | None = Field(
        description="Material form as stated, e.g. 'Plate', 'Angle', 'Channel', 'Round Bar', 'Coil'."
    )
    grade: str | None = Field(description="Material grade as stated, e.g. 'E250', 'E350', 'IS2062'.")
    standard: str | None = Field(
        description="Governing standard if stated separately, e.g. 'IS 2062', 'IS 1239'."
    )
    thickness_mm: float | None = Field(description="Thickness in millimetres. Null if not stated.")
    width_mm: float | None = Field(description="Width in millimetres. Null if not stated.")
    length_mm: float | None = Field(description="Length in millimetres. Null if not stated.")
    diameter_mm: float | None = Field(
        description="Outer diameter in millimetres for round/tubular products. Null otherwise."
    )
    quantity: float | None = Field(description="Numeric quantity requested. Null if not stated.")
    quantity_unit: QuantityUnit = Field(
        description="Unit of the quantity. Use UNKNOWN if the email does not say."
    )
    remarks: str | None = Field(
        description="Item-specific notes such as 'cut to size' or 'or equivalent'. Null if none."
    )


class ExtractedEnquiry(LLMBaseModel):
    """Stage 3 output: the structured form of a quotation request.

    `missing_information` is how the model reports gaps instead of inventing
    values (spec Rule 6). A non-empty list routes the quotation to
    NEEDS_INFORMATION rather than to pricing.
    """

    customer_name: str | None = Field(description="Contact person's name, if stated.")
    customer_company: str | None = Field(description="Buying company's name, if stated.")
    delivery_location: str | None = Field(
        description="Delivery city/site as stated. Null if not mentioned."
    )
    required_delivery_date: str | None = Field(
        description="Requested delivery date as ISO 'YYYY-MM-DD' if unambiguous, "
        "otherwise the phrase used. Null if not mentioned."
    )
    payment_terms: str | None = Field(
        description="Payment terms if the enquiry states them. Null otherwise."
    )
    additional_requirements: list[str] = Field(
        description="Other commercial or technical requirements, e.g. test certificate, "
        "packing, inspection. Empty list if none."
    )
    line_items: list[SteelLineItem] = Field(
        description="Every distinct material requested. Empty list if none could be identified."
    )
    missing_information: list[str] = Field(
        description="Plain-language list of essential details the email does not provide, "
        "e.g. 'quantity not stated'. Empty list if the enquiry is complete."
    )


# ---------------------------------------------------------------------------
# Product normalisation
# ---------------------------------------------------------------------------


class NormalizedProduct(LLMBaseModel):
    """Canonical form of a free-text material description.

    This only *normalises vocabulary*; it never decides which product matched.
    Matching against the product master is deterministic (see the backend
    product matcher) precisely so a language model cannot pick a product.
    """

    product_type: str | None = Field(description="Canonical product type, title case.")
    grade: str | None = Field(description="Canonical grade token, uppercase, e.g. 'E250'.")
    standard: str | None = Field(description="Canonical standard, e.g. 'IS 2062'.")
    confidence: float = Field(description="Confidence in the normalisation, 0.0-1.0.", ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Draft generation
# ---------------------------------------------------------------------------


class DraftEmail(LLMBaseModel):
    """Stage 7 output: the customer-facing reply, pre-approval."""

    subject: str = Field(description="Reply subject line.")
    body: str = Field(description="Plain-text email body including greeting and sign-off.")


# ---------------------------------------------------------------------------
# Call metadata
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LLMUsage:
    """Per-call observability record (spec section 22).

    `generation_id` is OpenRouter's id, which allows exact cost lookup after the
    fact even when the streaming response does not carry pricing.
    """

    model: str
    task: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0
    generation_id: str | None = None
    attempts: int = 1
    strict_schema_used: bool = False
    succeeded: bool = True
    error: str | None = None
    #: Set when the task's configured model could not be reached and the call
    #: was served by the fallback instead. `model` is then the model that
    #: actually ran, so cost and latency stay attributed correctly, and this
    #: records what was asked for - otherwise a desk silently running on the
    #: fallback for a week looks identical to one whose config was always that.
    fell_back_from: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AIOutcome[T]:
    """An LLM result paired with the usage record that produced it."""

    value: T
    usage: LLMUsage
