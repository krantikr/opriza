"""The LLM brain: OpenRouter, structured output, rules as the safety net.

Models (environment):
    AGENT_MODEL_FAST    reading enquiries, choosing a tool   (default LLM_MODEL_CLASSIFY)
    AGENT_MODEL_WRITE   messages to customers, answers       (default LLM_MODEL_DRAFT)

Every method checks the model's output against the facts it was given; a
message that drops the link or an amount, an enquiry line pointing at an item
that does not exist, or an answer that loses the figure all fall back to the
rules brain. `usage.fallbacks` counts how often that happened.
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

import json
import os
import re

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.kb.brain.base import Brain, CatalogEntry, ParsedEnquiry, ToolCall, ToolSpec
from app.kb.brain.rules import RulesBrain

logger = get_logger(__name__)


class _Text(BaseModel):
    text: str = Field(description="The message, plain text, no markdown")


class LLMBrain(Brain):
    name = "llm"

    def __init__(self, client=None) -> None:
        super().__init__()
        from ai.llm.factory import get_client

        self.client = client or get_client()
        self.rules = RulesBrain()
        self.fast = os.getenv("AGENT_MODEL_FAST") or os.getenv("LLM_MODEL_CLASSIFY") or "openai/gpt-4o-mini"
        self.write_model = (
            os.getenv("AGENT_MODEL_WRITE") or os.getenv("LLM_MODEL_DRAFT") or "openai/gpt-4o-mini"
        )

    # ---------------------------------------------------------------- calls

    def _track(self, outcome) -> None:
        u = outcome.usage
        self.usage.calls += 1
        self.usage.tokens_in += u.prompt_tokens or 0
        self.usage.tokens_out += u.completion_tokens or 0
        self.usage.cost_usd += u.cost_usd or 0.0
        self.usage.records.append(u)

    def _structured(self, task: str, model: str, system: str, user: str, schema):
        from ai.llm.base import system as sys_msg
        from ai.llm.base import user as user_msg

        out = self.client.structured(
            task=task, model=model, schema=schema, messages=[sys_msg(system), user_msg(user)]
        )
        self._track(out)
        return out.value

    def _fallback(self, what: str, exc: Exception | str):
        self.usage.fallbacks += 1
        logger.warning("LLM brain fell back to rules for %s: %s", what, exc)

    # ------------------------------------------------------------- enquiries

    def parse_enquiry(self, text: str, catalog: list[CatalogEntry], sites: list[str]) -> ParsedEnquiry:
        cat = "\n".join(
            f"{c.item_id}: {c.name} [{c.unit}] also called: {', '.join(c.aliases) or '-'}" for c in catalog
        )
        system = (
            "You read customer enquiries for an Indian trading business (English or Hinglish). "
            "Return each item asked for with its quantity. Match items ONLY to the catalog ids given; "
            "use null when nothing matches. Never invent quantities: if no quantity is stated, skip the line. "
            "Delivery dates like '21 Oct' and credit terms like '30 days' are not quantities."
        )
        user = f"Catalog:\n{cat}\n\nKnown delivery areas: {', '.join(sites[:60])}\n\nEnquiry:\n{text}"
        try:
            parsed = self._structured("agent_parse_enquiry", self.fast, system, user, ParsedEnquiry)
            ids = {c.item_id for c in catalog}
            if not parsed.lines or any(
                ln.item_id is not None and ln.item_id not in ids for ln in parsed.lines
            ):
                raise ValueError("unknown item or no lines")
            if any(ln.qty <= 0 for ln in parsed.lines):
                raise ValueError("non-positive quantity")
            return parsed
        except Exception as exc:  # noqa: BLE001 - any failure means "use the rules"
            self._fallback("parse_enquiry", exc)
            return self.rules.parse_enquiry(text, catalog, sites)

    # ---------------------------------------------------------------- writing

    def write(self, purpose: str, facts: dict, language: str) -> str:
        draft = self.rules.write(purpose, facts, language)
        system = (
            "You write short messages from an Indian trading business to its customers or suppliers, "
            f"in {'Hinglish (Roman script, natural Hindi-English mix)' if language == 'Hinglish' else 'simple Indian business English'}. "
            "Polite, warm, one or two sentences, under 320 characters. Use ONLY the facts given; "
            "copy amounts, dates and the link exactly. No markdown, no emojis."
        )
        user = f"Purpose: {purpose}\nFacts: {json.dumps(facts, default=str, ensure_ascii=False)}\nA plain version: {draft}"
        try:
            text = self._structured("agent_write", self.write_model, system, user, _Text).text.strip()
            must = [str(facts[k]) for k in ("link", "amount", "total", "quote_no", "po_no") if facts.get(k)]
            if any(m not in text for m in must) or len(text) > 480:
                raise ValueError("dropped a fact or too long")
            return text
        except Exception as exc:  # noqa: BLE001
            self._fallback(f"write:{purpose}", exc)
            return draft

    def headline(self, kind: str, facts: dict) -> str:
        draft = self.rules.headline(kind, facts)
        system = (
            "You write the opening line of a business owner's morning brief. Two sentences, plain English, "
            "the most important thing first. Use only the facts given; copy every amount exactly."
        )
        try:
            text = self._structured(
                "agent_brief",
                self.write_model,
                system,
                f"Facts: {json.dumps(facts, default=str, ensure_ascii=False)}\nPlain version: {draft}",
                _Text,
            ).text.strip()
            amounts = re.findall(r"₹[\d.,]+\s?(?:Cr|L)?", draft)
            if any(a not in text for a in amounts):
                raise ValueError("dropped an amount")
            return text
        except Exception as exc:  # noqa: BLE001
            self._fallback("headline", exc)
            return draft

    # ------------------------------------------------------------- questions

    def plan_answer(self, question: str, tools: list[ToolSpec], context: dict) -> ToolCall:
        spec = "\n".join(
            f"- {t.name}: {t.description}" + (f" Args: {json.dumps(t.args)}" if t.args else "") for t in tools
        )
        system = (
            "You route a business owner's question to exactly one read-only tool over their books. "
            "Pick the tool that answers it and fill its arguments from the question. "
            "Use 'help' if nothing fits. Dates as YYYY-MM-DD; today is " + str(context.get("today")) + "."
        )
        try:
            call = self._structured(
                "agent_route", self.fast, system, f"Tools:\n{spec}\n\nQuestion: {question}", ToolCall
            )
            if call.tool not in {t.name for t in tools}:
                raise ValueError(f"unknown tool {call.tool}")
            return call
        except Exception as exc:  # noqa: BLE001
            self._fallback("plan_answer", exc)
            return self.rules.plan_answer(question, tools, context)

    def phrase_answer(self, question: str, tool: str, result: dict) -> str:
        draft = self.rules.phrase_answer(question, tool, result)
        system = (
            "Answer the business owner's question from the tool result in one to three short sentences. "
            "Copy every figure exactly as written in the plain answer. No markdown except **bold** for the key figure."
        )
        try:
            data = {k: v for k, v in result.items() if k != "table"}
            text = self._structured(
                "agent_answer",
                self.write_model,
                system,
                f"Question: {question}\nTool: {tool}\nResult: {json.dumps(data, default=str, ensure_ascii=False)[:6000]}\n"
                f"Plain answer: {draft}",
                _Text,
            ).text.strip()
            figures = re.findall(r"₹[\d.,]+\s?(?:Cr|L)?", draft)
            if any(f not in text for f in figures):
                raise ValueError("dropped a figure")
            return text
        except Exception as exc:  # noqa: BLE001
            self._fallback("phrase_answer", exc)
            return draft
