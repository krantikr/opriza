"""JSON Schema shaping for structured output, and tolerant JSON recovery.

Strict structured-output mode accepts only a subset of JSON Schema: every
object must list all of its properties as `required` and set
`additionalProperties: false`, and validation keywords such as `minimum` or
`maxLength` are rejected outright. Pydantic emits a richer schema than that, so
this module reduces it.

The constraints are not lost - they are still enforced, by Pydantic, when the
model's reply is validated. Stripping them from the schema only stops the API
rejecting the request; it does not weaken the guarantee on the data.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

# Keywords strict structured-output mode does not accept.
_UNSUPPORTED_KEYWORDS = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minItems",
    "maxItems",
    "uniqueItems",
    "default",
    "examples",
}

_FENCED_JSON = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _strip(node: Any) -> Any:
    """Recursively normalise a schema node for strict mode."""
    if isinstance(node, list):
        return [_strip(item) for item in node]
    if not isinstance(node, dict):
        return node

    cleaned = {k: _strip(v) for k, v in node.items() if k not in _UNSUPPORTED_KEYWORDS}

    # A `$ref` with sibling keys is rejected by several strict-mode
    # implementations. Pydantic emits exactly that for an enum field carrying a
    # description, so the siblings are dropped and the reference stands alone.
    if "$ref" in cleaned and len(cleaned) > 1:
        return {"$ref": cleaned["$ref"]}

    if cleaned.get("type") == "object" and "properties" in cleaned:
        cleaned["additionalProperties"] = False
        # Every property must be required; optionality is expressed by the
        # field being nullable, which is what the AI schemas already do.
        cleaned["required"] = list(cleaned["properties"].keys())

    return cleaned


def to_strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Build a strict-mode-compatible JSON Schema for a Pydantic model."""
    return _strip(model.model_json_schema())


def schema_name(model: type[BaseModel]) -> str:
    """Schema names must match ^[a-zA-Z0-9_-]+$."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", model.__name__)


def describe_schema(model: type[BaseModel]) -> str:
    """Readable schema for prompt-only fallback, when the API cannot enforce one."""
    return json.dumps(to_strict_schema(model), indent=2)


def extract_json(text: str) -> Any:
    """Recover a JSON value from a model reply.

    Handles the three things that actually happen: clean JSON, JSON inside a
    fenced code block, and JSON with prose wrapped around it.
    """
    if not text or not text.strip():
        raise ValueError("model returned an empty response")

    candidate = text.strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    if match := _FENCED_JSON.search(candidate):
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Fall back to the outermost braces or brackets.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError(f"no JSON object found in model response: {candidate[:200]!r}")
