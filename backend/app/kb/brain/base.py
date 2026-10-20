"""The agents' "Decide" step, behind one interface.

Two implementations, chosen by the AGENT_BRAIN environment variable:

    rules   deterministic: regex + alias matching, message templates, a
            keyword router for questions. No network, no cost, and what the
            test suite runs on.
    llm     a language model through OpenRouter, with structured output.
            Every call falls back to the rules brain if the model fails or
            returns something that does not pass the checks, so an outage
            degrades the wording, never the work.
    auto    llm when OPENROUTER_API_KEY is set, otherwise rules (default).

Either way the brain only *reads and writes words*. Prices, grades, totals
and dates come from the knowledge base and are passed in; the brain is never
asked to compute them (design rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class CatalogEntry(BaseModel):
    item_id: int
    name: str
    unit: str
    aliases: list[str] = Field(default_factory=list)


class ParsedLine(BaseModel):
    item_id: int | None = Field(None, description="Catalog item id, or null if no catalog item matches")
    said_as: str = Field(description="The words the customer used for the item")
    qty: float = Field(description="Quantity asked for, as a number")
    unit: str | None = Field(None, description="Unit the customer used, e.g. MT, bags, boxes")


class ParsedEnquiry(BaseModel):
    lines: list[ParsedLine] = Field(default_factory=list)
    site: str | None = Field(None, description="Delivery site or area, if given")
    needed_by: str | None = Field(None, description="Delivery date or urgency as the customer said it")
    notes: str | None = Field(
        None, description="Anything else the salesperson should know (credit, brand, freight)"
    )


class ToolCall(BaseModel):
    tool: str = Field(description="Name of the tool to run")
    args: dict[str, str] = Field(default_factory=dict, description="Arguments as strings")


@dataclass
class ToolSpec:
    name: str
    description: str
    args: dict[str, str] = field(default_factory=dict)  # name -> description


@dataclass
class Usage:
    """What a run spent on the language model."""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    fallbacks: int = 0
    records: list = field(default_factory=list)  # ai.schemas.LLMUsage, for llm_calls telemetry


class Brain:
    name = "base"

    def __init__(self) -> None:
        self.usage = Usage()

    def parse_enquiry(self, text: str, catalog: list[CatalogEntry], sites: list[str]) -> ParsedEnquiry:
        raise NotImplementedError

    def write(self, purpose: str, facts: dict, language: str) -> str:
        """A short message to a customer or supplier. Must include facts['link'] when given."""
        raise NotImplementedError

    def headline(self, kind: str, facts: dict) -> str:
        """One or two sentences for the owner (brief, alerts)."""
        raise NotImplementedError

    def plan_answer(self, question: str, tools: list[ToolSpec], context: dict) -> ToolCall:
        raise NotImplementedError

    def phrase_answer(self, question: str, tool: str, result: dict) -> str:
        raise NotImplementedError
