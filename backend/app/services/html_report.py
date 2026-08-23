"""The period report as one self-contained HTML file.

The workbook is for somebody who wants to sum a column; this is for somebody who
wants to *read* the report - a partner, a banker, an accountant who will not
open a spreadsheet. It is a single file with no external stylesheet, font or
image, so it survives being emailed, opened from a USB stick, or archived for
seven years, and it prints to the same four pages the application does.

The markup deliberately mirrors `frontend/src/pages/Reports.tsx`: the same four
numbered statements, the same dot leaders, the same schedules. A downloaded
report that disagreed with the screen would be worse than no download at all.
"""

from __future__ import annotations

from datetime import date
from html import escape
from typing import Any

from app.services.desk import DeskReport
from app.services.reports import Report

#: Inlined rather than linked: a report that needs a stylesheet from a server
#: stops rendering the moment it is moved, which defeats the point of a file.
STYLES = """
:root {
  --ink: #0F172A; --ink-soft: #475569; --ink-faint: #94A3B8;
  --rule: #E2E8F0; --rule-firm: #CBD5E1; --sunk: #F1F5F9;
  --brand: #2563EB; --settled: #059669; --danger: #DC2626;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 16px; background: #F8FAFC; color: var(--ink);
  font: 13px/1.5 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.sheet {
  max-width: 60rem; margin: 0 auto; background: #FFFFFF;
  padding: 36px 40px; box-shadow: 0 1px 3px rgba(15, 23, 42, .1);
}
.head { border-bottom: 4px double var(--ink); padding-bottom: 16px;
  display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.org { font-size: 18px; font-weight: 700; letter-spacing: -.01em; }
.doctype { margin-top: 2px; font-size: 13px; font-weight: 600;
  text-transform: uppercase; letter-spacing: .14em; color: var(--ink-soft); }
.meta { font-size: 11px; text-align: right; line-height: 1.7; }
.meta span { color: var(--ink-faint); margin-right: 8px; }
.meta b { font-weight: 600; }

.stmt { border-top: 2px solid var(--ink); padding-top: 12px; margin-top: 24px;
  break-inside: avoid; page-break-inside: avoid; }
.stmt h2 { margin: 0; font-size: 14px; font-weight: 700; }
.stmt h2 i { font-style: normal; color: var(--ink-faint); margin-right: 6px; }
.q { margin: 2px 0 10px; font-size: 12px; font-style: italic; color: var(--ink-faint); }
.cols { display: flex; gap: 32px; align-items: flex-start; }
.cols > .lines { flex: 1.15 1 0; min-width: 0; }
.cols > .fig { flex: 1 1 0; min-width: 0; align-self: flex-start; }

.line { display: flex; align-items: baseline; gap: 6px; padding: 4px 0; }
.line.rule { border-top: 1px solid var(--ink); }
.line.indent { padding-left: 20px; }
.line .lbl { flex: 0 0 auto; color: var(--ink-soft); }
.line .note { flex: 0 0 auto; font-size: 11px; font-style: italic; color: var(--ink-faint); }
.line .lead { flex: 1 1 auto; min-width: 16px; border-bottom: 1px dotted var(--rule-firm);
  transform: translateY(-3px); }
.line .val { flex: 0 0 auto; font-weight: 500; font-variant-numeric: tabular-nums; }
.line .unit { flex: 0 0 32px; font-size: 11px; color: var(--ink-faint); }
.line.strong .lbl { font-weight: 600; color: var(--ink); }
.line.strong .val { font-weight: 700; }
.line.muted .lbl, .line.muted .val { color: var(--ink-faint); }
.line.muted .lead { border-bottom-color: var(--rule); }

.note-block { margin-top: 8px; border-left: 2px solid var(--rule); padding-left: 10px;
  font-size: 11px; line-height: 1.6; color: var(--ink-faint); }
.sub { margin-top: 10px; border-top: 1px solid var(--rule); padding-top: 6px; }
.sub-h { margin: 0 0 4px; font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: .04em; color: var(--ink-soft); }

/* Contents cards */
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 20px; }
.card { border: 1px solid var(--rule); padding: 10px 14px; min-width: 0; }
.card .ci { font-size: 11px; font-weight: 600; color: var(--ink-faint); margin-right: 6px; }
.card .ct { font-size: 11px; font-weight: 500; text-transform: uppercase;
  letter-spacing: .06em; color: var(--ink-soft); }
.card .cv { margin: 6px 0 3px; font-size: 20px; font-weight: 700; line-height: 1;
  font-variant-numeric: tabular-nums; }
.card .ch { font-size: 11px; color: var(--ink-faint); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }

.fig-empty { font-size: 12px; font-style: italic; color: var(--ink-faint); }

/* Funnel */
.funnel { display: flex; flex-direction: column; gap: 5px; }
.fn { display: grid; grid-template-columns: 8.5rem 1fr 2.6rem; align-items: center; gap: 8px; }
.fn .fl { font-size: 11px; color: var(--ink-soft); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.fn .ft { position: relative; height: 16px; background: var(--sunk); display: block; }
.fn .ff { display: block; height: 100%; background: var(--brand); }
.fn .ft b { position: absolute; left: 6px; top: 0; line-height: 16px; font-size: 10px;
  font-weight: 600; color: #FFFFFF; font-variant-numeric: tabular-nums; }
.fn .fd { font-size: 10px; color: var(--ink-faint); text-align: right;
  font-variant-numeric: tabular-nums; }

/* Multi-line */
.linechart { width: 100%; height: 130px; display: block; }
.lkey { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px 14px; }
.lk { display: inline-flex; align-items: center; gap: 6px; font-size: 11px;
  color: var(--ink-soft); }
.lk i { display: inline-block; width: 14px; height: 0; }

/* Waterfall */
/* `height` on the plot row, not on the flex parent: a percentage-positioned
   bar needs an ancestor with a resolved height, and `flex: 1 1 auto` inside a
   row does not give it one - the bars collapse to nothing while the labels
   below still draw, which reads as a styling quirk rather than a broken chart. */
.water { display: flex; align-items: stretch; gap: 8px; }
.wf { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center; }
.wf .wb { position: relative; width: 100%; height: 120px; }
.wf .wfill { position: absolute; left: 50%; transform: translateX(-50%);
  width: 100%; max-width: 44px; }
.wf .wv { margin-top: 6px; font-size: 11px; font-weight: 500;
  font-variant-numeric: tabular-nums; }
.wf .wl { font-size: 10px; color: var(--ink-faint); }

/* Donut */
.donut { display: flex; align-items: center; gap: 16px; }
.dlegend { min-width: 0; }
.dcentre { margin-bottom: 6px; }
.dcentre b { display: block; font-size: 16px; font-weight: 700;
  font-variant-numeric: tabular-nums; }
.dcentre span { font-size: 10px; color: var(--ink-faint); }
.dk { display: flex; align-items: center; gap: 6px; font-size: 11px; padding: 1px 0; }
.dk i { width: 8px; height: 8px; flex: 0 0 auto; }
.dk .dl { color: var(--ink-soft); }
.dk b { margin-left: auto; font-weight: 600; font-variant-numeric: tabular-nums; }

h2.sched-head { border-top: 2px solid var(--ink); padding-top: 12px; margin: 28px 0 12px;
  font-size: 14px; font-weight: 700; page-break-before: always; }
.sched { margin-bottom: 20px; break-inside: avoid; page-break-inside: avoid; }
.sched h3 { margin: 0 0 6px; font-size: 12px; font-weight: 700; }
.sched h3 span { color: var(--ink-faint); margin-right: 6px; }
.sched h3 em { font-weight: 400; color: var(--ink-faint); }
table { width: 100%; border-collapse: collapse; border-top: 1px solid var(--ink); }
th { padding: 6px 8px; font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .03em; color: var(--ink-soft); border-bottom: 1px solid var(--rule-firm); }
td { padding: 6px 8px; font-size: 12px; border-bottom: 1px solid var(--rule);
  font-variant-numeric: tabular-nums; }
th.r, td.r { text-align: right; }
th.l, td.l { text-align: left; }
td.name { font-variant-numeric: normal; }
.empty { padding: 8px; font-size: 12px; font-style: italic; color: var(--ink-faint); }

.foot { margin-top: 28px; border-top: 1px solid var(--rule); padding-top: 12px;
  font-size: 10px; line-height: 1.6; color: var(--ink-faint); }

@media print {
  body { background: #FFFFFF; padding: 0; }
  .cards { break-inside: avoid; page-break-inside: avoid; }
  .sheet { max-width: none; box-shadow: none; padding: 0; }
  @page { margin: 14mm; }
}
"""


# --- Formatting -------------------------------------------------------------


def rupees(value: float | int | None) -> str:
    """Indian grouping, because a report read in India is read in lakhs."""
    if value is None:
        return "—"
    negative = value < 0
    whole = f"{abs(float(value)):.2f}"
    intpart, dec = whole.split(".")
    if len(intpart) > 3:
        head, tail = intpart[:-3], intpart[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        intpart = ",".join([*groups, tail])
    out = f"₹{intpart}.{dec}"
    return f"({out})" if negative else out


def short(value: float | int | None) -> str:
    """Crore and lakh, the units a trading desk actually speaks in."""
    if value is None:
        return "—"
    n = float(value)
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1e7:
        return f"{sign}₹{n / 1e7:.2f}Cr"
    if n >= 1e5:
        return f"{sign}₹{n / 1e5:.2f}L"
    if n >= 1e3:
        return f"{sign}₹{n / 1e3:.1f}k"
    return f"{sign}₹{n:.0f}"


def tonnes(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.3f}".rstrip("0").rstrip(".") or "0"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _e(value: Any) -> str:
    return escape(str(value if value is not None else ""))


# --- Building blocks --------------------------------------------------------


def _line(
    label: str,
    value: str,
    *,
    unit: str = "",
    note: str = "",
    indent: bool = False,
    muted: bool = False,
    strong: bool = False,
    rule: bool = False,
) -> str:
    classes = " ".join(
        c
        for c, on in (
            ("indent", indent),
            ("muted", muted),
            ("strong", strong),
            ("rule", rule),
        )
        if on
    )
    note_html = f'<span class="note">{_e(note)}</span>' if note else ""
    unit_html = f'<span class="unit">{_e(unit)}</span>' if unit else ""
    return (
        f'<div class="line {classes}"><span class="lbl">{_e(label)}</span>{note_html}'
        f'<span class="lead"></span><span class="val">{_e(value)}</span>{unit_html}</div>'
    )


def _funnel(stages: list[tuple[str, int]]) -> str:
    """Statement 1: each stage is a subset of the one before it."""
    peak = max([c for _, c in stages] + [1])
    rows = []
    for i, (label, count) in enumerate(stages):
        width = count / peak * 100
        prev = stages[i - 1][1] if i else None
        drop = f"−{(1 - count / prev) * 100:.0f}%" if prev else ""
        rows.append(
            f'<div class="fn"><span class="fl">{_e(label)}</span>'
            f'<span class="ft"><span class="ff" style="width:{width:.1f}%"></span>'
            f'<b>{count}</b></span>'
            f'<span class="fd">{_e(drop)}</span></div>'
        )
    return f'<div class="funnel">{"".join(rows)}</div>'


def _lines(points: list[dict[str, Any]], series: list[tuple[str, str, str, bool]]) -> str:
    """Statement 2: two series against a shared scale.

    Stacking quoted and sold would hide the gap between them, and the gap is
    the conversion story - so they are drawn as separate lines.
    """
    if len(points) < 2:
        return '<p class="fig-empty">A trend needs at least two buckets.</p>'

    peak = max(
        [abs(p["values"].get(key, 0)) for p in points for key, _, _, _ in series] + [1]
    )
    W, H, pad = 320.0, 120.0, 4.0

    def x(i: int) -> float:
        return pad + (i / (len(points) - 1)) * (W - pad * 2)

    def y(v: float) -> float:
        return H - pad - (abs(v) / peak) * (H - pad * 2)

    grid = "".join(
        f'<line x1="0" x2="{W}" y1="{pad + f * (H - pad * 2):.1f}" '
        f'y2="{pad + f * (H - pad * 2):.1f}" stroke="#E2E8F0" stroke-width=".5"/>'
        for f in (0.25, 0.5, 0.75)
    )
    paths = "".join(
        f'<polyline fill="none" stroke="{colour}" stroke-width="1.5" '
        f'{"stroke-dasharray=\"3 2\" " if dashed else ""}'
        f'stroke-linejoin="round" vector-effect="non-scaling-stroke" points="'
        + " ".join(f'{x(i):.1f},{y(p["values"].get(key, 0)):.1f}' for i, p in enumerate(points))
        + '"/>'
        for key, _, colour, dashed in series
    )
    key_html = "".join(
        f'<span class="lk"><i style="border-top:2px {"dashed" if dashed else "solid"} '
        f'{colour}"></i>{_e(label)}</span>'
        for _, label, colour, dashed in series
    )
    return (
        f'<svg viewBox="0 0 {W:.0f} {H:.0f}" class="linechart" preserveAspectRatio="none" '
        f'role="img">{grid}{paths}</svg><div class="lkey">{key_html}</div>'
    )


def _waterfall(steps: list[tuple[str, float, bool, str]]) -> str:
    """Statement 3: revenue less cost equals profit, drawn as a subtraction."""
    running = 0.0
    bars = []
    for label, value, total, colour in steps:
        start_v = 0.0 if total else running
        end_v = value if total else running + value
        running = value if total else running + value
        bars.append((label, value, start_v, end_v, colour))

    peak = max([max(abs(b[2]), abs(b[3])) for b in bars] + [1])
    if peak <= 1:
        return '<p class="fig-empty">Nothing to reconcile in this period.</p>'

    cells = []
    for label, value, start_v, end_v, colour in bars:
        top, bottom = max(start_v, end_v), min(start_v, end_v)
        cells.append(
            f'<div class="wf"><span class="wb">'
            f'<span class="wfill" style="background:{colour};'
            f'bottom:{bottom / peak * 100:.1f}%;'
            f'height:{max((top - bottom) / peak * 100, 1):.1f}%"></span></span>'
            f'<span class="wv">{_e(short(value))}</span>'
            f'<span class="wl">{_e(label)}</span></div>'
        )
    return f'<div class="water">{"".join(cells)}</div>'


def _donut(slices: list[tuple[str, float, str]], centre: str, caption: str) -> str:
    """Statement 4: the floor is a whole, and the question is a share."""
    total = sum(v for _, v, _ in slices)
    if total <= 0:
        return '<p class="fig-empty">No stock on the floor.</p>'

    size, stroke = 112.0, 13.0
    r = size / 2 - stroke / 2
    circumference = 2 * 3.141592653589793 * r
    offset = 0.0
    arcs = []
    for _, value, colour in slices:
        dash = value / total * circumference
        arcs.append(
            f'<circle cx="{size / 2}" cy="{size / 2}" r="{r:.2f}" fill="none" '
            f'stroke="{colour}" stroke-width="{stroke}" '
            f'stroke-dasharray="{dash:.2f} {circumference - dash:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}"/>'
        )
        offset += dash

    legend = "".join(
        f'<div class="dk"><i style="background:{colour}"></i>'
        f'<span class="dl">{_e(label)}</span>'
        f'<b>{_e(short(value))}</b></div>'
        for label, value, colour in slices
    )
    return (
        f'<div class="donut">'
        f'<svg width="{size:.0f}" height="{size:.0f}" viewBox="0 0 {size:.0f} {size:.0f}" '
        f'style="transform:rotate(-90deg)" role="img">'
        f'<circle cx="{size / 2}" cy="{size / 2}" r="{r:.2f}" fill="none" stroke="#F1F5F9" '
        f'stroke-width="{stroke}"/>{"".join(arcs)}</svg>'
        f'<div class="dlegend"><div class="dcentre"><b>{_e(centre)}</b>'
        f'<span>{_e(caption)}</span></div>{legend}</div></div>'
    )


def _table(letter: str, title: str, note: str, headers: list[tuple[str, str]],
           rows: list[list[str]], empty: str) -> str:
    head = "".join(f'<th class="{align}">{_e(text)}</th>' for text, align in headers)
    if rows:
        body = "".join(
            "<tr>"
            + "".join(
                f'<td class="{headers[i][1]}{" name" if headers[i][1] == "l" else ""}">{_e(cell)}</td>'
                for i, cell in enumerate(row)
            )
            + "</tr>"
            for row in rows
        )
    else:
        body = f'<tr><td class="empty" colspan="{len(headers)}">{_e(empty)}</td></tr>'
    return (
        f'<div class="sched"><h3><span>Schedule {_e(letter)}</span>{_e(title)}'
        f'{f" <em>· {_e(note)}</em>" if note else ""}</h3>'
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


# --- The document -----------------------------------------------------------


def build(desk: DeskReport, *, organisation: str, registers: dict[str, Report] | None = None) -> str:
    """Render the whole report as one HTML string."""
    enq = desk.enquiries or {}
    won, before = desk.won or {}, desk.won_previous or {}
    quoted, open_book = desk.quoted or {}, desk.open_book or {}
    stock, sm = desk.stock or {}, desk.stock_movement or {}
    generated = date.today().strftime("%d %b %Y")

    def g(d: dict, key: str, default: Any = 0) -> Any:
        value = d.get(key, default)
        return default if value is None else value

    parts: list[str] = []

    # --- Contents cards ----------------------------------------------------
    def card(index: int, title: str, value: str, hint: str, tone: str = "") -> str:
        style = f' style="color:{tone}"' if tone else ""
        return (
            f'<div class="card"><div><span class="ci">{index}</span>'
            f'<span class="ct">{_e(title)}</span></div>'
            f'<p class="cv"{style}>{_e(value)}</p>'
            f'<p class="ch">{_e(hint)}</p></div>'
        )

    parts.append(
        '<div class="cards">'
        + card(1, "Enquiry", str(g(enq, "identified")),
               f'{g(enq, "raised")} quoted · {g(enq, "sent")} sent')
        + card(2, "Sales", short(g(won, "revenue")),
               f'{tonnes(g(won, "tonnes"))} MT over {g(won, "deals")} orders')
        + card(3, "Gross profit", short(g(won, "profit")),
               f'{g(won, "margin_pct"):.1f}% margin',
               "#059669" if g(won, "profit") > 0 else "")
        + card(4, "Stock", short(g(stock, "total_value")),
               f'{g(stock, "deadstock_pct")}% over 90 days',
               "#DC2626" if g(stock, "deadstock_pct") > 20 else "")
        + "</div>"
    )

    # --- Statement 1 -------------------------------------------------------
    parts.append(
        '<section class="stmt"><h2><i>1.</i>Enquiry and quotation</h2>'
        '<p class="q">How much work came in, and how much of it did we answer?</p>'
        '<div class="cols"><div class="lines">'
        + _line("Mail received", str(g(enq, "received")), unit="no.")
        + _line("Not an enquiry", f'({g(enq, "not_enquiries")})', unit="no.",
                indent=True, muted=True)
        + _line("Enquiries identified", str(g(enq, "identified")), unit="no.", rule=True)
        + _line("Not quoted", f'({g(enq, "not_raised")})', unit="no.", indent=True, muted=True)
        + _line("Quotations raised", str(g(enq, "raised")), unit="no.", rule=True)
        + _line("Not yet sent", f'({g(enq, "not_sent")})', unit="no.", indent=True, muted=True)
        + _line("Quotations sent", str(g(enq, "sent")), unit="no.", strong=True, rule=True)
        + '<div class="sub">'
        + _line("Accepted", str(g(enq, "won")), unit="no.")
        + _line("Declined", str(g(enq, "lost")), unit="no.")
        + _line("Awaiting reply", str(g(enq, "awaiting")), unit="no.", muted=True)
        + _line("Win rate on decided", _pct(enq.get("win_rate")), strong=True, rule=True)
        + "</div>"
        + '<p class="note-block">Each line is a subset of the one above it. A quotation '
          "counts in the period it was raised, not the period it was answered.</p>"
        + '</div><div class="fig">'
        + _funnel([
            ("Mail received", g(enq, "received")),
            ("Enquiries identified", g(enq, "identified")),
            ("Quotations raised", g(enq, "raised")),
            ("Quotations sent", g(enq, "sent")),
            ("Accepted", g(enq, "won")),
        ])
        + "</div></div></section>"
    )

    # --- Statement 2 -------------------------------------------------------
    sold_t, sold_v = g(won, "tonnes"), g(won, "revenue")
    quoted_v = g(quoted, "revenue")
    parts.append(
        '<section class="stmt"><h2><i>2.</i>Sales and realisation</h2>'
        '<p class="q">What did we sell, and at what rate?</p>'
        '<div class="cols"><div class="lines">'
        + _line("Tonnage quoted", tonnes(g(quoted, "tonnes")), unit="MT")
        + _line("Tonnage sold", tonnes(sold_t), unit="MT", strong=True, rule=True)
        + '<div class="sub" style="border:0;padding-top:10px">'
        + _line("Value quoted", rupees(quoted_v))
        + _line("Value sold", rupees(sold_v), strong=True, rule=True)
        + _line("Average realisation", rupees(sold_v / sold_t) if sold_t else "—",
                note="per MT")
        + _line("Orders", str(g(won, "deals")), unit="no.", muted=True)
        + "</div><div class=\"sub\">"
        + _line("Still with customers", rupees(g(open_book, "revenue")), muted=True)
        + _line("Conversion on value",
                f"{sold_v / quoted_v * 100:.1f}%" if quoted_v else "—", muted=True)
        + "</div>"
        + '<p class="note-block">Sold means a customer accepted the quotation. Value is '
          "counted at the rate quoted, excluding tax or freight billed separately.</p>"
        + '</div><div class="fig">'
        + _lines(
            [{"label": p["label"], "values": {"quoted": p["quoted"], "sold": p["revenue"]}}
             for p in (desk.trend or [])],
            [("quoted", "Quoted", "#94A3B8", True), ("sold", "Sold", "#2563EB", False)],
        )
        + "</div></div></section>"
    )

    # --- Statement 3 -------------------------------------------------------
    prev_profit = g(before, "profit")
    movement = (
        f'{(g(won, "profit") - prev_profit) / abs(prev_profit) * 100:.1f}%'
        if prev_profit
        else "—"
    )
    lost_rows = "".join(
        _line(r["label"], rupees(r["value"]),
              note=f'{r["count"]} quotation{"" if r["count"] == 1 else "s"}')
        for r in (desk.lost_reasons or [])
    )
    parts.append(
        '<section class="stmt"><h2><i>3.</i>Trading and profit</h2>'
        '<p class="q">What did it cost, and what did we keep?</p>'
        '<div class="cols"><div class="lines">'
        + _line("Revenue from sales", rupees(g(won, "revenue")))
        + _line("Less: cost of goods sold", f'({rupees(g(won, "cost"))})', indent=True)
        + _line("Gross profit", rupees(g(won, "profit")), strong=True, rule=True)
        + '<div class="sub" style="border:0;padding-top:10px">'
        + _line("Gross margin", f'{g(won, "margin_pct"):.2f}%')
        + _line("Profit per tonne", rupees(g(won, "profit_per_mt")) if sold_t else "—",
                note="per MT")
        + _line("Gross profit, previous period", rupees(prev_profit), muted=True)
        + _line("Movement", movement, muted=True)
        + "</div>"
        + (f'<div class="sub"><p class="sub-h">Business declined, by reason</p>{lost_rows}</div>'
           if lost_rows else "")
        + '<p class="note-block">Cost of goods is the landed cost recorded against each line '
          "when it was priced, under the rules then in force. Lines priced without a recorded "
          "cost are excluded from both figures rather than treated as pure profit.</p>"
        + '</div><div class="fig">'
        + _waterfall([
            ("Revenue", g(won, "revenue"), True, "#475569"),
            ("Less cost", -g(won, "cost"), False, "#2563EB"),
            ("Gross profit", g(won, "profit"), True, "#059669"),
        ])
        + "</div></div></section>"
    )

    # --- Statement 4 -------------------------------------------------------
    #: Deadstock first, so the ring opens on the slice that matters.
    tone = {"0-30 days": "#2563EB", "31-60 days": "#60A5FA",
            "61-90 days": "#D97706", "Over 90 days": "#DC2626"}
    buckets = [b for b in stock.get("buckets", []) if b.get("value", 0) > 0]
    ageing = [
        (b["label"], b["value"], tone.get(b["label"], "#2563EB"))
        for b in sorted(buckets, key=lambda b: b["label"] != "Over 90 days")
    ]
    parts.append(
        '<section class="stmt"><h2><i>4.</i>Stock</h2>'
        '<p class="q">What did the floor hold, and what moved?</p>'
        '<div class="cols"><div class="lines">'
        + _line("Opening stock", tonnes(g(sm, "opening_mt")), unit="MT")
        + _line("Add: receipts", tonnes(g(sm, "receipts_mt")), unit="MT", indent=True,
                note=f'{g(sm, "receipt_count")} movements')
        + _line("Less: issues", f'({tonnes(g(sm, "issues_mt"))})', unit="MT", indent=True,
                note=f'{g(sm, "issue_count")} movements')
        + _line("Closing stock", tonnes(g(sm, "closing_mt")), unit="MT", strong=True, rule=True)
        + '<div class="sub" style="border:0;padding-top:10px">'
        + _line("Closing stock at landed cost", rupees(g(stock, "total_value")))
        + _line("Of which ageing over 90 days", rupees(g(stock, "deadstock_value")),
                indent=True,
                note=f'{g(stock, "deadstock_pct")}% · {g(stock, "deadstock_lots")} lots')
        + "</div>"
        + '<p class="note-block">Closing stock is taken from the current stock sheet; opening '
          "is derived backwards from it using the movement ledger, so the statement always "
          "reconciles against what the floor holds. Reservations and blocks are holds, not "
          "movements of ownership, and are excluded.</p>"
        + '</div><div class="fig">'
        + _donut(ageing, short(g(stock, "deadstock_value")),
                 f'over 90 days · {g(stock, "deadstock_pct")}%')
        + "</div></div></section>"
    )

    # --- Schedules ---------------------------------------------------------
    parts.append('<h2 class="sched-head">Schedules</h2>')

    parts.append(_table(
        "A", "Customers", "ranked by revenue",
        [("Customer", "l"), ("Quoted", "r"), ("Revenue", "r"), ("Profit", "r"),
         ("Win rate", "r")],
        [[c["customer"], short(c["quoted_value"]),
          short(c["revenue"]) if c["revenue"] else "—",
          short(c["profit"]) if c["profit"] else "—", _pct(c.get("win_rate"))]
         for c in (desk.customers or [])],
        "No customer activity in this period.",
    ))

    parts.append(_table(
        "B", "Products", "tonnage and spread",
        [("Product", "l"), ("Quoted MT", "r"), ("Sold MT", "r"), ("Profit", "r"),
         ("₹ / MT", "r")],
        [[p["product"], tonnes(p["tonnes_quoted"]), tonnes(p["tonnes_won"]),
          short(p["profit"]) if p["profit"] else "—",
          rupees(p["profit_per_mt"]) if p["tonnes_won"] else "—"]
         for p in (desk.products or [])],
        "No products quoted in this period.",
    ))

    if stock.get("oldest"):
        parts.append(_table(
            "C", "Oldest lots", "longest standing first",
            [("Specification", "l"), ("Location", "l"), ("Age", "r"),
             ("Balance MT", "r"), ("Value", "r")],
            [[lot["spec"], lot.get("location") or "—", f'{lot["ageing_days"]}d',
              tonnes(lot["tonnes"]), short(lot["value"])]
             for lot in stock["oldest"][:12]],
            "Nothing has aged past 90 days.",
        ))

    if desk.quiet_customers:
        parts.append(_table(
            "D", "Customers gone quiet", "no enquiry in 60 days",
            [("Customer", "l"), ("Last seen", "r"), ("Orders", "r"),
             ("Lifetime revenue", "r")],
            [[c["customer"], f'{c["days_quiet"]}d ago', str(c["orders"]),
              short(c["lifetime_revenue"])]
             for c in desk.quiet_customers],
            "",
        ))

    # `strict=False` is deliberate: the letters are a supply of labels, not a
    # parallel sequence, so a caller passing fewer registers than letters is
    # normal rather than a length mismatch worth raising on.
    for letter, (title, report) in zip("EFGHIJ", (registers or {}).items(), strict=False):
        if not report.rows:
            continue
        headers = [
            (key.replace("_inr", " (₹)").replace("_pct", " %").replace("_mt", " MT")
                .replace("_", " ").capitalize(),
             "r" if key.endswith(("_inr", "_pct", "_mt")) else "l")
            for key in report.rows[0]
        ]
        parts.append(_table(
            letter, title, report.period, headers,
            [[str(v) for v in row.values()] for row in report.rows[:60]], "",
        ))

    body = "".join(parts)
    org = escape(organisation)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{org} — Trading period report — {escape(desk.period_label)}</title>
<style>{STYLES}</style></head>
<body><div class="sheet">
<header class="head">
  <div><div class="org">{org}</div>
  <div class="doctype">Trading period report</div></div>
  <dl class="meta">
    <div><span>Period</span><b>{escape(desk.period_label)}</b></div>
    <div><span>Covering</span>{escape(desk.period_range)}</div>
    <div><span>Compared with</span>{escape(desk.previous_label)}</div>
    <div><span>Prepared</span>{generated}</div>
  </dl>
</header>
{body}
<footer class="foot">
  <p>Prepared from stored records for {escape(desk.period_range)}. Figures are counted at
  the pricing rules in force when each quotation was raised, so this report does not change
  if the rules are edited later.</p>
  <p>{org} · {escape(desk.period_label)} · Prepared {generated}</p>
</footer>
</div></body></html>"""


__all__ = ["build", "rupees", "short", "tonnes"]
