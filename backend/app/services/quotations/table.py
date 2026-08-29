"""The quotation item table, rendered from settled figures.

Built in code rather than by the draft model, and the reason is the same one
`ai.guards.verify_draft_facts` exists for: this table is arithmetic over a
commercial document. Weight times rate is an amount a customer will be invoiced
against, and a language model that quietly rounds one has misstated a price.
The prompt tells the model not to compute line totals; this module is what
supplies them instead, so the instruction has something to defer to.

Two renderings come from one build:

* **Plain text** - monospace, column-aligned, for the body a reviewer edits and
  for any client that will not show HTML.
* **HTML** - the bordered table the desk asked for, styled inline because mail
  clients discard a stylesheet.

Both are generated from the same `TableRow` list, so the figures cannot drift
between what is reviewed and what is received.
"""

from __future__ import annotations

import re as _re
from dataclasses import dataclass
from decimal import Decimal
from html import escape

from app.models import QuotationLineItem, QuotationRequest

#: Marks where the table belongs in the drafted prose. The model is asked to
#: leave this line alone; whatever it does with the rest, the table is spliced
#: in here deterministically.
TABLE_PLACEHOLDER = "[[QUOTATION_TABLE]]"

#: Column headings, in the order the desk's own quotation sheet uses.
#:
#: Thickness, width and length are one "Size (mm)" column rather than three.
#: Eleven columns overflowed a phone and a narrow mail client, and a trader
#: reads "8 x 1250 x 5800" as a single fact anyway - splitting it across three
#: headings made the row wider without making it clearer.
#:
#: Rate and Amount carry their unit in the heading. A bare "Rate" over
#: "70,800.00" leaves the reader to infer per MT, and on a commercial document
#: that inference is the one thing that must not be left to them.
COLUMNS = (
    "Sr",
    "Description",
    "Size (mm)",
    "Qty (MT)",
    "PCS",
    "Rate (INR/MT)",
    "Amount (INR)",
)

#: Columns that hold figures, so a column of money reads as a column of money.
NUMERIC_COLUMNS = frozenset({0, 3, 4, 5, 6})

#: Where the table lands when a draft forgot the marker: after the greeting and
#: the opening sentence, which is where a reader expects the offer to begin.
_FALLBACK_AFTER_PARAGRAPHS = 2


def format_inr(value: Decimal | float | int | None) -> str:
    """Format with Indian digit grouping: 1184000 -> 11,84,000.00."""
    if value is None:
        return "-"
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    sign = "-" if amount < 0 else ""
    whole, _, fraction = f"{abs(amount):.2f}".partition(".")

    if len(whole) <= 3:
        grouped = whole
    else:
        # Last three digits, then pairs: 1184000 -> 11,84,000
        head, tail = whole[:-3], whole[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        grouped = ",".join([*pairs, tail])

    return f"{sign}{grouped}.{fraction}"


#: Product words the trade writes in capitals. Title-casing them reads as a
#: mistake to anyone in the business.
_UPPER_PRODUCTS = {"tmt", "ms", "hr", "cr", "gi", "gp", "ppgi", "ppgl", "crca"}


def _title_product(value: str) -> str:
    """Title-case a product name without flattening trade abbreviations."""
    return " ".join(
        word.upper() if word.lower() in _UPPER_PRODUCTS else word.capitalize()
        for word in value.split()
    )


def _fmt_dim(value: float | None) -> str:
    """Dimensions read as whole millimetres unless they genuinely are not."""
    if value is None:
        return "-"
    return f"{value:g}"


def _fmt_qty(value: Decimal | None, places: str = "0.01") -> str:
    if value is None:
        return "-"
    return f"{Decimal(str(value)).quantize(Decimal(places)):,}"


def _fmt_money(value: Decimal | None) -> str:
    """Indian digit grouping, as everywhere else the desk shows money."""
    if value is None:
        return "-"
    return format_inr(value)


@dataclass(slots=True)
class TableRow:
    """One priced line, already reduced to what the customer sees."""

    sr_no: int
    type: str
    grade: str
    thickness: float | None
    width: float | None
    length: float | None
    weight_mt: Decimal | None
    pcs: int | None
    make: str
    rate: Decimal | None
    amount: Decimal | None

    @property
    def priced(self) -> bool:
        return self.amount is not None

    @property
    def description(self) -> str:
        """Grade and product as one phrase: "E250 Plate", "Fe500D TMT".

        The *product* is title-cased because the extractor yields whatever the
        customer typed and "plate" beside "E250" reads as a typo. The **grade
        is left exactly as given**: it is a standards designation, and
        `.title()` turns E250BR into "E250Br", which is a different thing
        written on a commercial document.
        """
        product = _title_product(self.type) if self.type and self.type != "-" else ""
        grade = self.grade if self.grade and self.grade != "-" else ""
        return " ".join(p for p in (grade, product) if p) or "-"

    @property
    def size(self) -> str:
        """Dimensions as a trader writes them: "8 x 1250 x 5800"."""
        dims = [d for d in (self.thickness, self.width, self.length) if d]
        return " x ".join(_fmt_dim(d) for d in dims) if dims else "-"

    def cells(self) -> list[str]:
        """The row as the table prints it, in column order."""
        return [
            str(self.sr_no),
            self.description,
            self.size,
            _fmt_qty(self.weight_mt),
            str(self.pcs) if self.pcs is not None else "-",
            _fmt_money(self.rate),
            _fmt_money(self.amount),
        ]


def _row_for(item: QuotationLineItem, sr_no: int) -> TableRow:
    """Reduce one line item to its table row.

    Prefers the matched stock lot for anything descriptive - it is the material
    actually being offered - and falls back to what the customer asked for, so
    an unmatched line still appears rather than silently vanishing from the
    quotation.
    """
    lot = item.matched_stock_item
    availability = item.stock_availability

    weight = item.quantity_mt if item.quantity_mt is not None else None

    # `QuotationPricing.quote_rate` is the figure the calculator settled on and
    # the one the reviewer sees; `suggested_rate` is the cost-plus starting
    # point produced before any of that. Reading only the latter meant a fully
    # priced quotation went out with "-" in the Rate and Amount columns while
    # the Pricing Calculator showed a rate - the document and the screen
    # disagreeing about the same line.
    pricing = item.pricing
    rate = pricing.quote_rate if pricing and pricing.quote_rate is not None else None
    if rate is None and availability is not None:
        rate = availability.suggested_rate

    # The rate is per MT, so the amount is a straight product. Prefer the
    # stored line total where the calculator computed one, so the document
    # cannot round differently from the screen. Anything without both figures
    # is left blank rather than shown as zero - a zero is a price, a blank is
    # a gap.
    amount = None
    if pricing is not None and pricing.line_total is not None:
        amount = Decimal(str(pricing.line_total)).quantize(Decimal("0.01"))
    elif weight is not None and rate is not None:
        amount = (Decimal(str(weight)) * Decimal(str(rate))).quantize(Decimal("0.01"))

    pcs = None
    if availability and availability.available_nop is not None:
        pcs = int(availability.available_nop)

    return TableRow(
        sr_no=sr_no,
        type=(lot.product_type if lot and lot.product_type else item.product_type) or "-",
        grade=(lot.grade if lot and lot.grade else item.grade) or "-",
        thickness=(lot.thickness_mm if lot and lot.thickness_mm else item.thickness_mm),
        width=(lot.width_mm if lot and lot.width_mm else item.width_mm),
        length=(lot.length_mm if lot and lot.length_mm else item.length_mm),
        weight_mt=weight,
        pcs=pcs,
        make=(lot.make if lot and lot.make else None) or "-",
        rate=rate,
        amount=amount,
    )


def build_rows(quotation: QuotationRequest) -> list[TableRow]:
    """Every line on the quotation, in the order the customer listed them."""
    ordered = sorted(quotation.line_items, key=lambda i: i.line_no)
    return [_row_for(item, index) for index, item in enumerate(ordered, start=1)]


def totals(rows: list[TableRow]) -> tuple[Decimal, Decimal | None]:
    """Total tonnage and total amount, over the rows that carry a figure.

    The amount is None when no line is priced. A zero would be a stated price
    - "this consignment costs nothing" - where the truth is that no price has
    been established yet, so the cell is left blank exactly as the line rows
    are. Tonnage is always known, because it is what the customer asked for.
    """
    weight = sum(
        (Decimal(str(r.weight_mt)) for r in rows if r.weight_mt is not None), Decimal("0")
    )
    priced = [r.amount for r in rows if r.amount is not None]
    amount = sum(priced, Decimal("0")).quantize(Decimal("0.01")) if priced else None
    return weight.quantize(Decimal("0.01")), amount


# --- Plain text -------------------------------------------------------------


def render_text(rows: list[TableRow]) -> str:
    """A column-aligned table for the plain-text body.

    Aligned with spaces rather than tabs: a tab is re-interpreted by every mail
    client differently, and the columns have to still line up in the reviewer's
    textarea as well as in the sent message.
    """
    if not rows:
        return ""

    body = [r.cells() for r in rows]

    # A column every row leaves blank is noise on a commercial document. PCS
    # is the usual casualty - it is only known for lots counted in pieces.
    keep = [
        i
        for i in range(len(COLUMNS))
        if i < 3 or any(cells[i] not in ("", "-") for cells in body)
    ]

    headers = [COLUMNS[i] for i in keep]
    body = [[cells[i] for i in keep] for cells in body]

    total_weight, total_amount = totals(rows)
    grid = [headers, *body]
    widths = [max(len(row[i]) for row in grid) for i in range(len(headers))]
    numeric = {n for n, i in enumerate(keep) if i in NUMERIC_COLUMNS}

    def line(cells: list[str]) -> str:
        return "  ".join(
            cell.rjust(widths[i]) if i in numeric else cell.ljust(widths[i])
            for i, cell in enumerate(cells)
        ).rstrip()

    width = max(len(line(headers)), *(len(line(c)) for c in body))
    rule = "-" * width
    out = [line(headers), rule, *(line(cells) for cells in body)]

    # The totals sit under the columns they total, so the eye can check them.
    # Built through the same `line()` so the columns cannot drift, but the
    # label occupies the first two cells: "Total" is a word in a numeric
    # column, and right-justifying it pushed every figure out of line.
    total_cells = [""] * len(headers)
    total_cells[1 if len(headers) > 1 else 0] = "Total"
    for n, i in enumerate(keep):
        if i == 3:
            total_cells[n] = _fmt_qty(total_weight)
        elif i == 6:
            total_cells[n] = _fmt_money(total_amount)
    out += [rule, line(total_cells)]

    return "\n".join(out)


# --- HTML -------------------------------------------------------------------

_TH = (
    "border:1px solid #000;padding:6px 8px;background:#ffffff;"
    "font-weight:bold;text-align:center;white-space:nowrap;"
)
_TD = "border:1px solid #000;padding:5px 8px;"


def render_html(rows: list[TableRow], *, title: str | None = None, tagline: str | None = None) -> str:
    """The bordered table, styled inline.

    Every rule is written onto the element itself: Gmail and Outlook both strip
    a `<style>` block, so a stylesheet would arrive as an unstyled list of
    numbers.

    Columns match `render_text` exactly, and an all-blank column is dropped
    from both, so the document a customer receives and the body a reviewer
    edited cannot disagree about what was quoted.
    """
    if not rows:
        return ""

    body = [r.cells() for r in rows]
    keep = [
        i
        for i in range(len(COLUMNS))
        if i < 3 or any(cells[i] not in ("", "-") for cells in body)
    ]
    span = len(keep)

    total_weight, total_amount = totals(rows)

    parts = [
        '<table cellspacing="0" cellpadding="0" role="presentation" '
        'style="border-collapse:collapse;font-family:Arial,Helvetica,sans-serif;'
        'font-size:13px;color:#111;">'
    ]

    if title:
        parts.append(
            f'<tr><td colspan="{span}" style="{_TD}background:#0F172A;color:#fff;'
            f'text-align:center;font-weight:bold;font-size:15px;letter-spacing:.3px;">'
            f"{escape(title)}</td></tr>"
        )
    if tagline:
        parts.append(
            f'<tr><td colspan="{span}" style="{_TD}background:#0F172A;color:#93B4FB;'
            f'text-align:center;font-size:12px;">{escape(tagline)}</td></tr>'
        )

    parts.append("<tr>")
    for i in keep:
        parts.append(f'<th style="{_TH}">{escape(COLUMNS[i])}</th>')
    parts.append("</tr>")

    for cells in body:
        parts.append("<tr>")
        # Indexed by the *original* column id, not by position among the
        # survivors: `cells` is always the full row, so reading it positionally
        # shifts every cell left of a dropped column.
        for i in keep:
            align = "right" if i in NUMERIC_COLUMNS else "left"
            if i == 0:
                align = "center"
            parts.append(
                f'<td style="{_TD}text-align:{align};">{escape(cells[i])}</td>'
            )
        parts.append("</tr>")

    # Totals, aligned under the columns they total rather than floated to one
    # side, so a reader can check the arithmetic by eye.
    parts.append("<tr>")
    for i in keep:
        style = f"{_TD}font-weight:bold;background:#F1F5F9;"
        if i == 1:
            parts.append(f'<td style="{style}">Total</td>')
        elif i == 3:
            parts.append(
                f'<td style="{style}text-align:right;">{escape(_fmt_qty(total_weight))}</td>'
            )
        elif i == 6:
            parts.append(
                f'<td style="{style}text-align:right;">{escape(_fmt_money(total_amount))}</td>'
            )
        else:
            parts.append(f'<td style="{style}"></td>')
    parts.append("</tr>")

    parts.append("</table>")
    return "".join(parts)


def splice_text(body: str, rows: list[TableRow]) -> str:
    """Put the rendered text table into a drafted body.

    The model is asked to emit `TABLE_PLACEHOLDER` on its own line, but a draft
    that omitted it must still go out with its figures: a quotation whose items
    silently vanished is worse than one whose table sits a paragraph early. So
    a missing marker is inserted after the opening rather than dropped.
    """
    table = render_text(rows)
    if not table:
        # Nothing to show - strip the marker so it never reaches a customer.
        return _strip_placeholder(body)

    if TABLE_PLACEHOLDER in body:
        return _replace_placeholder(body, table)

    paragraphs = body.split("\n\n")
    at = min(_FALLBACK_AFTER_PARAGRAPHS, len(paragraphs))
    return "\n\n".join([*paragraphs[:at], table, *paragraphs[at:]])


def _replace_placeholder(body: str, table: str) -> str:
    """Swap the marker for the table, whatever whitespace surrounds it."""
    out = []
    for line in body.splitlines():
        if TABLE_PLACEHOLDER in line.strip():
            out.append(table)
        else:
            out.append(line)
    return "\n".join(out)


def _strip_placeholder(body: str) -> str:
    return "\n".join(
        line for line in body.splitlines() if TABLE_PLACEHOLDER not in line.strip()
    )


def has_placeholder(body: str) -> bool:
    return TABLE_PLACEHOLDER in body


# --- The HTML counterpart of an approved body -------------------------------


def build_html_email(body: str, rows: list[TableRow], *, title: str | None = None,
                     tagline: str | None = None) -> str | None:
    """Render an approved plain-text body as HTML, table and all.

    Built from the *approved* text rather than regenerated, so a reviewer's
    edits survive into the HTML part instead of being silently replaced by a
    fresh render. The text table is located by its own first and last line and
    swapped for the bordered one; the prose around it is escaped and wrapped.

    Returns None when there is no table to draw - a plain-text-only message is
    correct then, and a single-part message is one less thing to render wrong.
    """
    if not rows:
        return None

    text_table = render_text(rows)
    if not text_table:
        return None

    html_table = render_html(rows, title=title, tagline=tagline)
    table_lines = text_table.splitlines()

    out: list[str] = []
    lines = body.splitlines()
    index = 0
    replaced = False

    while index < len(lines):
        window = lines[index : index + len(table_lines)]
        if not replaced and window == table_lines:
            out.append(html_table)
            index += len(table_lines)
            replaced = True
            continue
        out.append(_html_paragraph(lines[index]))
        index += 1

    # A body whose table was edited beyond recognition still has to carry one.
    if not replaced:
        out.append(html_table)

    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        'line-height:1.5;color:#000;">' + "".join(out) + "</div>"
    )


def _html_paragraph(line: str) -> str:
    if not line.strip():
        return '<div style="height:10px;line-height:10px;">&nbsp;</div>'
    return f'<div>{escape(line)}</div>'




# --- Re-splicing a table whose figures have moved ---------------------------

#: A line of the rendered table's horizontal rule. Three or more dashes and
#: nothing else - short enough to match the narrowest table, specific enough
#: that ordinary prose (an em-dash, a signature underline of one or two) does
#: not look like one.
_RULE_RE = _re.compile(r"^-{3,}$")


def _table_span(lines: list[str]) -> tuple[int, int] | None:
    """Locate a previously spliced table inside a body, as [start, end).

    The table is recognised by its own shape rather than by remembering where
    it was put: a header line, then a rule, then rows, then a closing rule and
    a totals line. That matters because the reviewer may have typed above it,
    which moves it, and because the figures inside it are exactly what is about
    to change - so it cannot be found by matching its text.

    Anchored on the *first* rule and closed after the last one, so a table
    whose middle rows were edited is still replaced whole.
    """
    rules = [i for i, line in enumerate(lines) if _RULE_RE.match(line.strip())]
    if len(rules) < 2:
        return None

    first, last = rules[0], rules[-1]
    # The header sits immediately above the opening rule.
    start = first - 1
    if start < 0:
        return None
    # The totals line sits immediately below the closing rule; a table whose
    # totals row was trimmed still ends at the rule itself.
    end = last + 1
    if end < len(lines) and lines[end].strip():
        end += 1
    return start, end


def retable_text(body: str, rows: list[TableRow]) -> str:
    """Rewrite a stored draft body so its table shows the current figures.

    Splicing happens once, at generation, and bakes the numbers into prose.
    When the figures later move - terms are supplied, a component is
    overridden, stock is re-costed - the body still reads as the quotation it
    was, which is how a draft came to show a blank Rate column while the
    calculator showed a price.

    Regenerating would fix it too, but that is an LLM call, it costs a version,
    and it rewrites sentences a reviewer may have deliberately worded. The
    table is settled arithmetic that was never the model's to author, so it is
    replaced in place and the prose around it is left exactly as written.

    A body that still carries the placeholder is spliced normally. A body with
    no recognisable table gets one appended by `splice_text`'s own fallback,
    rather than being returned without its figures.
    """
    if TABLE_PLACEHOLDER in body:
        return splice_text(body, rows)

    table = render_text(rows)
    lines = body.splitlines()
    span = _table_span(lines)

    if span is None:
        # Never seen a table, or it was edited past recognition. Fall back to
        # the same placement a fresh draft would have used.
        return splice_text(body, rows)

    start, end = span
    if not table:
        # Nothing to show any more: drop the stale table rather than leaving
        # figures that no longer have a basis.
        replacement: list[str] = []
        # Collapse the blank lines the removed block sat between.
        while start > 0 and not lines[start - 1].strip() and end < len(lines) and not lines[end].strip():
            start -= 1
            break
    else:
        replacement = table.splitlines()

    return "\n".join([*lines[:start], *replacement, *lines[end:]])


def prose_only(body: str) -> str:
    """The body with its item table removed.

    Used by the stale-price check: the table is regenerated from the
    calculator and is always current, so including it would compare the
    figures against themselves. What needs checking is the prose around it.
    """
    lines = (body or "").splitlines()
    span = _table_span(lines)
    if span is None:
        return body or ""
    start, end = span
    return "\n".join([*lines[:start], *lines[end:]])


__all__ = [
    "COLUMNS",
    "build_html_email",
    "TABLE_PLACEHOLDER",
    "TableRow",
    "build_rows",
    "has_placeholder",
    "render_html",
    "prose_only",
    "render_text",
    "retable_text",
    "splice_text",
    "totals",
]
