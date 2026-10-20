"""The brain (rules and LLM, with fallback) and the Tally XML parser."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

from ai.schemas import AIOutcome, LLMUsage
from app.kb.brain import CatalogEntry, ParsedEnquiry, ParsedLine, RulesBrain, ToolCall, ToolSpec
from app.kb.brain.llm import LLMBrain, _Text
from app.kb.sources.tally_xml import parse_envelope

CATALOG = [
    CatalogEntry(item_id=1, name="TMT 12mm Fe500D", unit="MT", aliases=["12mm saria", "saria", "tmt 12"]),
    CatalogEntry(item_id=2, name="MS Channel 100x50", unit="MT", aliases=["channel 100", "channel"]),
    CatalogEntry(item_id=3, name="HR Coil 3mm", unit="MT", aliases=["hr 3mm"]),
    CatalogEntry(item_id=4, name="OPC 53 Cement", unit="bag", aliases=["cement", "opc"]),
]


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("Need 20 MT TMT 12mm Fe500D at Wagholi site by 21 Oct. Please send best rate.", [(1, 20)]),
        ("Bhai 14 MT 12mm saria ka rate do, delivery Kharadi.", [(1, 14)]),
        ("channel 100 2.5 MT ka bhav batao, urgent hai. Saath mein 8 MT hr 3mm bhi.", [(2, 2.5), (3, 8)]),
        ("Please quote 350 bags OPC 53 Cement, delivery Bopal, 30 days credit.", [(4, 350)]),
        ("Kindly share price for cement - 290 bags. Delivery at Gota.", [(4, 290)]),
    ],
)
def test_rules_brain_reads_enquiries(text, expect):
    parsed = RulesBrain().parse_enquiry(text, CATALOG, ["Wagholi", "Kharadi", "Bopal", "Gota"])
    assert [(ln.item_id, ln.qty) for ln in parsed.lines] == expect


def test_rules_brain_notes_and_site():
    parsed = RulesBrain().parse_enquiry(
        "20 MT saria chahiye Wagholi site pe, urgent. Match the other dealer's rate.", CATALOG, ["Wagholi"]
    )
    assert parsed.site == "Wagholi" and "Urgent" in parsed.notes and "another supplier" in parsed.notes


def test_rules_brain_writes_both_languages():
    facts = {
        "bill": "SBS/S/26-27/00042",
        "amount": "₹1,20,000",
        "due": "22 Oct",
        "link": "https://x/l/abc",
        "name": "Sneha",
        "company": "Shree Balaji Steels",
    }
    en = RulesBrain().write("reminder", facts, "English")
    hi = RulesBrain().write("reminder", facts, "Hinglish")
    assert "https://x/l/abc" in en and "₹1,20,000" in en and en.startswith("Dear Sneha")
    assert "https://x/l/abc" in hi and hi.startswith("Namaste Sneha ji")


class FakeClient:
    """Stands in for OpenRouter: returns whatever the test queues up."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = []

    def structured(self, *, task, messages, schema, model=None, max_tokens=None):
        self.calls.append(task)
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return AIOutcome(
            value=value,
            usage=LLMUsage(
                model=model or "fake", task=task, prompt_tokens=100, completion_tokens=20, cost_usd=0.0001
            ),
        )


def test_llm_brain_uses_the_model_when_it_checks_out():
    good = ParsedEnquiry(lines=[ParsedLine(item_id=1, said_as="saria", qty=12, unit="MT")], site="Wagholi")
    brain = LLMBrain(client=FakeClient(good))
    out = brain.parse_enquiry("12 tonne saria bhejo Wagholi", CATALOG, ["Wagholi"])
    assert out.lines[0].qty == 12 and brain.usage.calls == 1 and brain.usage.fallbacks == 0


def test_llm_brain_falls_back_on_an_invented_item():
    bad = ParsedEnquiry(lines=[ParsedLine(item_id=99, said_as="saria", qty=12, unit="MT")])
    brain = LLMBrain(client=FakeClient(bad))
    out = brain.parse_enquiry("Bhai 12 MT 12mm saria ka rate do", CATALOG, [])
    assert [(ln.item_id, ln.qty) for ln in out.lines] == [(1, 12)] and brain.usage.fallbacks == 1


def test_llm_brain_keeps_the_link_and_amount_or_falls_back():
    facts = {
        "amount": "₹2,00,000",
        "link": "https://x/l/abc",
        "bill": "B1",
        "due": "22 Oct",
        "name": "Sneha",
        "company": "SBS",
    }
    brain = LLMBrain(client=FakeClient(_Text(text="Hi Sneha, please pay soon."), RuntimeError("timeout")))
    first = brain.write("reminder", facts, "English")
    second = brain.write("reminder", facts, "English")
    assert "https://x/l/abc" in first and "https://x/l/abc" in second and brain.usage.fallbacks == 2


def test_llm_brain_routes_questions_to_known_tools_only():
    tools = [ToolSpec("top_debtors", "who owes"), ToolSpec("help", "fallback")]
    route = {"rule_route": lambda q: ToolCall(tool="help", args={}), "today": date(2026, 10, 19)}
    ok = LLMBrain(client=FakeClient(ToolCall(tool="top_debtors", args={"n": "3"}))).plan_answer(
        "who owes", tools, route
    )
    bad = LLMBrain(client=FakeClient(ToolCall(tool="drop_tables", args={}))).plan_answer(
        "who owes", tools, route
    )
    assert ok.tool == "top_debtors" and bad.tool == "help"


def test_tally_xml_parser_reads_the_sample_export(tmp_path: Path):
    root = Path(__file__).resolve().parents[2] / "scripts" / "mock_business"
    sys.path.insert(0, str(root))
    import generate  # type: ignore[import-not-found]

    store, _, _ = generate.build(date(2026, 10, 19))
    generate.write_tally_xml(store, tmp_path)
    batch = parse_envelope((tmp_path / "tally_sample_shree_balaji.xml").read_text())
    assert batch.ledgers and batch.items and batch.vouchers
    kinds = {v.vtype for v in batch.vouchers}
    assert kinds <= {"sales", "purchase", "receipt"} and "sales" in kinds
    sale = next(v for v in batch.vouchers if v.vtype == "sales")
    assert sale.lines and sale.bills and sale.bills[0].kind == "new" and sale.bills[0].due_date > sale.date
    assert sale.amount == pytest.approx(sum(ln.amount for ln in sale.lines) + sale.tax_amount, abs=1)
    receipt = next((v for v in batch.vouchers if v.vtype == "receipt"), None)
    if receipt:
        assert all(b.kind == "agst" for b in receipt.bills)
