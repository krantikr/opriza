"""The rules brain: deterministic reading and writing, no model involved.

It is the fallback for every LLM call and the brain the tests run on, so it
has to be good enough to run a desk on by itself: it reads the enquiry styles
seen in the data (English and Hinglish, the customers' own words for items),
writes short polite messages in both languages, and answers the common owner
questions through the Ask agent's router.
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

import re

from app.kb.brain.base import Brain, CatalogEntry, ParsedEnquiry, ParsedLine, ToolCall, ToolSpec

UNIT_WORDS = {
    "mt": "MT",
    "ton": "MT",
    "tons": "MT",
    "tonne": "MT",
    "tonnes": "MT",
    "t": "MT",
    "bag": "bag",
    "bags": "bag",
    "bori": "bag",
    "pc": "pc",
    "pcs": "pc",
    "piece": "pc",
    "pieces": "pc",
    "nos": "pc",
    "no": "pc",
    "box": "box",
    "boxes": "box",
    "carton": "box",
    "cartons": "box",
    "can": "can",
    "cans": "can",
    "bucket": "can",
    "buckets": "can",
    "sheet": "sheet",
    "sheets": "sheet",
    "length": "length",
    "lengths": "length",
    "kg": "kg",
    "kgs": "kg",
}
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
NUM = re.compile(
    rf"(?<![\w.])(\d+(?:\.\d+)?)\s*({'|'.join(sorted(UNIT_WORDS, key=len, reverse=True))})?\b(?!\s*(?:{MONTHS}|days?|din)\b)",
    re.I,
)


class RulesBrain(Brain):
    name = "rules"

    # ------------------------------------------------------------- enquiries

    def parse_enquiry(self, text: str, catalog: list[CatalogEntry], sites: list[str]) -> ParsedEnquiry:
        low = " " + text.lower().replace("\n", " ") + " "
        vocab: list[tuple[str, CatalogEntry]] = []
        for c in catalog:
            vocab.append((c.name.lower(), c))
            vocab += [(a.lower(), c) for a in c.aliases if a]
        vocab.sort(key=lambda x: -len(x[0]))

        taken: list[tuple[int, int]] = []
        found: list[tuple[int, int, str, CatalogEntry]] = []
        for word, entry in vocab:
            for m in re.finditer(rf"(?<![\w]){re.escape(word)}(?![\w])", low):
                s, e = m.span()
                if any(s < te and e > ts for ts, te in taken):
                    continue
                taken.append((s, e))
                found.append((s, e, text[s - 1 : e - 1] if s > 0 else word, entry))
        found.sort(key=lambda x: x[0])

        numbers = []
        for m in NUM.finditer(low):
            s, e = m.span(1)
            if any(s >= ts and e <= te for ts, te in taken):
                continue  # part of an item's name ("channel 100", "12mm")
            if re.match(r"\s*(?:mm|inch|g|kg\b|ml|%)", low[e : e + 5]) and not m.group(2):
                continue
            unit = UNIT_WORDS.get((m.group(2) or "").lower())
            numbers.append((s, float(m.group(1)), unit, m.group(2)))

        lines: list[ParsedLine] = []
        used = set()
        for s, e, said, entry in found:
            best = None
            for k, (ns, _value, unit, _raw) in enumerate(numbers):
                if k in used:
                    continue
                dist = s - ns if ns < s else ns - e
                if dist > 40:
                    continue
                score = dist - (15 if unit else 0)
                if best is None or score < best[0]:
                    best = (score, k)
            if best is None:
                continue
            k = best[1]
            used.add(k)
            _, value, unit, _ = numbers[k]
            lines.append(
                ParsedLine(item_id=entry.item_id, said_as=said.strip(), qty=value, unit=unit or entry.unit)
            )

        site = None
        for name in sorted(sites, key=len, reverse=True):
            if name and re.search(rf"\b{re.escape(name.lower())}\b", low):
                site = name
                break
        needed = re.search(rf"\b(\d{{1,2}}\s*(?:{MONTHS})[a-z]*)\b", low)
        notes = []
        if re.search(r"credit", low):
            notes.append("Asks about credit terms")
        if re.search(r"freight", low):
            notes.append("Wants freight included")
        if re.search(r"match|other dealer|less|kam", low):
            notes.append("Comparing with another supplier's rate")
        if re.search(r"urgent|jaldi", low):
            notes.append("Urgent")
        return ParsedEnquiry(
            lines=lines,
            site=site,
            needed_by=needed.group(1) if needed else None,
            notes="; ".join(notes) or None,
        )

    # ---------------------------------------------------------------- writing

    def write(self, purpose: str, facts: dict, language: str) -> str:
        hi = language == "Hinglish"
        f = {k: v for k, v in facts.items()}
        f.setdefault("name", "Sir")
        f.setdefault("link", "")
        t = TEMPLATES_HI if hi else TEMPLATES_EN
        template = t.get(purpose) or TEMPLATES_EN.get(purpose) or "{text} {link}"
        try:
            return " ".join(template.format(**f).split())
        except KeyError:
            return " ".join(f"{f.get('text', '')} {f['link']}".split())

    def headline(self, kind: str, facts: dict) -> str:
        if kind == "brief":
            parts = [f"Good morning{(' ' + facts['owner']) if facts.get('owner') else ''}."]
            if facts.get("cash_short_week"):
                parts.append(
                    f"Cash runs short in the week of {facts['cash_short_week']} by {facts['cash_short_by']}."
                )
            else:
                parts.append(f"Cash looks fine for {facts.get('weeks', 4)} weeks.")
            parts.append(
                f"{facts['overdue']} is overdue across {facts['overdue_count']} customers"
                f" and {facts['collect_this_week']} should come in this week."
            )
            if facts.get("approvals"):
                parts.append(
                    f"{facts['approvals']} item{'s' if facts['approvals'] != 1 else ''} wait for your approval."
                )
            return " ".join(parts)
        return facts.get("text", "")

    # ------------------------------------------------------------- questions

    def plan_answer(self, question: str, tools: list[ToolSpec], context: dict) -> ToolCall:
        route = context.get("rule_route")
        if route is None:
            return ToolCall(tool="help", args={})
        return route(question)

    def phrase_answer(self, question: str, tool: str, result: dict) -> str:
        return result.get("answer") or "I could not find that in your books."


TEMPLATES_EN = {
    "reminder": "Dear {name}, a gentle reminder from {company}: bill {bill} for {amount} is due on {due}. "
    "See your bills and pick a payment date here: {link}",
    "statement": "Dear {name}, your statement from {company}: {amount} is pending across {bills} bills, "
    "the oldest {oldest} days overdue. Please pick a payment date: {link}",
    "quote": "Dear {name}, our quote {quote_no} for {items}: {total} including GST, valid till {valid}. "
    "Tap to accept: {link}",
    "nudge": "Dear {name}, sharing quote {quote_no} again ({total}). Rates hold till {valid}. "
    "Tap to accept or tell us what to change: {link}",
    "rfq": "Dear {name}, please send your best rate for {qty} of {item}, delivery to {city}. "
    "Reply here in one tap: {link}",
    "po": "Dear {name}, purchase order {po_no}: {qty} of {item} at {rate} per {unit}, total {total}. "
    "Please confirm delivery: {link}",
    "offer": "Dear {name}, a special price for you: {item} at {rate} per {unit} (list {list_rate}), "
    "{qty} available. Valid till {valid}. Reserve it here: {link}",
    "early_payment": "Dear {name}, could you clear {amount} by {by}? We'd be grateful for the early payment. "
    "Pick a date here: {link}",
    "payment_delay": "Dear {name}, about bill {bill} for {amount} due {due}: may we pay it on {new_date}? "
    "Thank you for working with us.",
    "thanks": "Dear {name}, received {amount} with thanks. - {company}",
}

TEMPLATES_HI = {
    "reminder": "Namaste {name} ji, {company} se yaad dilana tha: bill {bill} ka {amount} {due} ko due hai. "
    "Apne bills dekhein aur payment ki date chunein: {link}",
    "statement": "Namaste {name} ji, {company} ka statement: {bills} bills ka {amount} baaki hai, sabse purana "
    "{oldest} din se overdue. Payment ki date yahan chunein: {link}",
    "quote": "Namaste {name} ji, quote {quote_no} - {items}: {total} GST ke saath, {valid} tak valid. "
    "Accept karne ke liye tap karein: {link}",
    "nudge": "Namaste {name} ji, quote {quote_no} ({total}) dobara bhej rahe hain. Rate {valid} tak hai. "
    "Accept karein ya batayein kya badalna hai: {link}",
    "rfq": "Namaste {name} ji, {item} {qty} ka best rate bhejiye, delivery {city}. Ek tap mein yahan: {link}",
    "po": "Namaste {name} ji, PO {po_no}: {item} {qty} @ {rate}/{unit}, total {total}. Delivery confirm karein: {link}",
    "offer": "Namaste {name} ji, aapke liye special rate: {item} {rate}/{unit} (list {list_rate}), {qty} available. "
    "{valid} tak. Yahan book karein: {link}",
    "early_payment": "Namaste {name} ji, kya aap {amount} {by} tak clear kar sakte hain? Early payment se badi madad "
    "hogi. Date yahan chunein: {link}",
    "payment_delay": "Namaste {name} ji, bill {bill} ({amount}, due {due}) ka payment {new_date} ko kar dein? "
    "Dhanyavaad.",
    "thanks": "Namaste {name} ji, {amount} mil gaya, dhanyavaad. - {company}",
}
