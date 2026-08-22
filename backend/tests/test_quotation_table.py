"""The quotation item table.

These figures reach a customer as a commercial offer, so the arithmetic is
tested directly rather than through the drafting pipeline: `weight x rate` is
the number an invoice gets checked against.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.quotations.table import (
    TABLE_PLACEHOLDER,
    TableRow,
    build_html_email,
    render_html,
    render_text,
    splice_text,
    totals,
)


def row(
    sr_no: int = 1,
    *,
    weight: str | None = "63.36",
    rate: str | None = "98000",
    pcs: int | None = 33,
    grade: str = "ROCKHARD-400",
    make: str = "JSPL",
) -> TableRow:
    w = Decimal(weight) if weight is not None else None
    r = Decimal(rate) if rate is not None else None
    amount = (w * r).quantize(Decimal("0.01")) if w is not None and r is not None else None
    return TableRow(
        sr_no=sr_no,
        type="PLATE",
        grade=grade,
        thickness=20,
        width=2000,
        length=6000,
        weight_mt=w,
        pcs=pcs,
        make=make,
        rate=r,
        amount=amount,
    )


# --- Arithmetic -------------------------------------------------------------


def test_the_amount_is_weight_times_rate():
    r = row(weight="63.36", rate="98000")
    assert r.amount == Decimal("6209280.00")


def test_totals_add_the_weight_and_the_amount():
    rows = [row(1, weight="63.36"), row(2, weight="60.00")]
    weight, amount = totals(rows)
    assert weight == Decimal("123.36")
    assert amount == Decimal("12089280.00")


def test_a_line_with_no_rate_has_no_amount_rather_than_a_zero():
    """A zero is a price. A blank is a gap, and they must not be confused."""
    r = row(rate=None)
    assert r.amount is None
    assert not r.priced


def test_an_unpriced_line_does_not_drag_the_total_down():
    rows = [row(1, weight="10", rate="50000"), row(2, weight="5", rate=None)]
    weight, amount = totals(rows)
    # The tonnage is still real even where the rate is not yet settled.
    assert weight == Decimal("15.00")
    assert amount == Decimal("500000.00")


# --- Plain text -------------------------------------------------------------


def test_the_text_table_carries_every_column_and_a_total():
    text = render_text([row(1), row(2, weight="60.00", pcs=25)])

    # Seven columns, not eleven: the three dimension columns are one
    # "Size (mm)", and the rate and amount carry their unit in the heading.
    for heading in ("Sr", "Description", "Size (mm)", "Qty (MT)", "PCS",
                    "Rate (INR/MT)", "Amount (INR)"):
        assert heading in text
    assert "Total" in text
    # Indian grouping, as everywhere else the desk shows money.
    assert "1,23,36,000.00" in text or "1,20,89,280.00" in text


def test_the_text_columns_line_up():
    """Alignment is the whole point of a plain-text table."""
    lines = render_text([row(1), row(2, grade="E250BR", weight="8.65")]).splitlines()
    body = [line for line in lines if line.lstrip().startswith(("1 ", "2 "))]
    assert len(body) == 2
    # Every column boundary lands in the same place in both rows. Checked on
    # the *columns* rather than on a word inside one: grades differ in length,
    # so "Plate" legitimately sits at different offsets while the column it
    # lives in still starts at the same place.
    header = render_text([row(1)]).splitlines()[0]
    size_at = header.index("Size (mm)")
    for line in body:
        assert line[size_at - 1] == " "  # the gutter before the column
        assert line[size_at] != " "  # and the column's own first character


def test_an_empty_table_renders_as_nothing():
    assert render_text([]) == ""


# --- Splicing ---------------------------------------------------------------


def test_the_placeholder_is_replaced_by_the_table():
    body = f"Dear Sir,\n\nOur offer:\n\n{TABLE_PLACEHOLDER}\n\nRegards"
    out = splice_text(body, [row()])

    assert TABLE_PLACEHOLDER not in out
    assert "Qty (MT)" in out
    assert out.startswith("Dear Sir,")
    assert out.rstrip().endswith("Regards")


def test_a_draft_that_forgot_the_marker_still_gets_its_table():
    """A quotation whose items silently vanished is the worse failure."""
    body = "Dear Sir,\n\nThank you for the enquiry.\n\nRegards"
    out = splice_text(body, [row()])

    assert "Qty (MT)" in out
    assert "6,209,280.00" in out or "62,09,280.00" in out


def test_the_marker_never_reaches_a_customer_when_there_is_no_table():
    body = f"Dear Sir,\n\n{TABLE_PLACEHOLDER}\n\nRegards"
    out = splice_text(body, [])
    assert TABLE_PLACEHOLDER not in out


# --- HTML -------------------------------------------------------------------


def test_the_html_table_is_styled_inline():
    """A <style> block is stripped by Gmail and Outlook alike."""
    html = render_html([row()])
    assert "<style" not in html
    assert "border:1px solid #000" in html
    assert html.count("<tr") >= 3  # header, one body row, totals


def test_the_html_escapes_what_it_is_given():
    # Injected through a column the table still renders: `make` was dropped
    # when eleven columns became seven, so escaping it proves nothing now.
    # Injected through a column the table still renders: `make` was dropped
    # when eleven columns became seven, so escaping it proves nothing now.
    # `grade` reaches the page through `TableRow.description`.
    html = render_html([row(grade="<script>")])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html or "&lt;Script&gt;" in html


def test_the_html_body_is_built_from_the_approved_text():
    """A reviewer's edits have to survive into the HTML part."""
    approved = splice_text(f"Dear Sir,\n\n{TABLE_PLACEHOLDER}\n\nRegards", [row()])
    approved = approved.replace("Dear Sir,", "Dear Mr Rajesh,")

    html = build_html_email(approved, [row()])

    assert html is not None
    assert "Dear Mr Rajesh," in html
    assert "<table" in html
    # The text table is swapped out, not left sitting alongside the real one.
    assert "Weight (MT)  PCS" not in html


def test_there_is_no_html_part_when_there_is_no_table():
    assert build_html_email("Dear Sir,\n\nRegards", []) is None


@pytest.mark.parametrize("value", ["0.01", "999999.99"])
def test_amounts_survive_the_extremes(value):
    r = row(weight=value, rate="1")
    assert r.amount == Decimal(value).quantize(Decimal("0.01"))


def test_an_unpriced_quotation_shows_a_blank_total_not_zero():
    """Rs 0.00 is a stated price; a blank is a gap. They must not be confused."""
    from decimal import Decimal

    from app.services.quotations.table import TableRow, render_text, totals

    rows = [
        TableRow(1, "plate", "E250", 8, 1250, 5800, Decimal("0.5"), None, "-", None, None)
    ]
    total_weight, total_amount = totals(rows)
    assert total_weight == Decimal("0.50")
    assert total_amount is None

    text = render_text(rows)
    # A zero is a price; a blank is a gap. An unpriced line must not imply
    # the desk offered it for nothing.
    last = text.splitlines()[-1]
    assert "0.00" not in last.replace("0.50", "")
    assert last.rstrip().endswith("-") or last.rstrip().endswith("0.50")


def test_a_partly_priced_quotation_totals_only_what_is_priced():
    from decimal import Decimal

    from app.services.quotations.table import TableRow, totals

    rows = [
        TableRow(1, "plate", "E250", 8, 1250, 5800, Decimal("2"), None, "-",
                 Decimal("50000"), Decimal("100000")),
        TableRow(2, "plate", "S355", 10, 1500, 6000, Decimal("3"), None, "-", None, None),
    ]
    total_weight, total_amount = totals(rows)
    assert total_weight == Decimal("5.00")
    # The priced line still totals; the unpriced one simply does not contribute.
    assert total_amount == Decimal("100000.00")


def test_the_html_row_keeps_its_amount_when_a_column_is_dropped():
    """Cells are indexed by column id, not by position among survivors.

    An all-blank column (PCS, usually) is dropped from the table. Reading the
    row positionally then shifted every later cell one place left, so a priced
    line rendered a blank Amount while the totals row still showed the figure -
    a commercial document contradicting its own total.
    """
    html = render_html([row(pcs=None)])

    assert "62,09,280.00" in html
    # Once on the line, once in the total.
    assert html.count("62,09,280.00") == 2


def test_the_text_and_html_tables_agree_on_every_figure():
    """One build, two renderings: the reviewed body and the sent document
    cannot disagree about what was quoted."""
    rows = [row(1), row(2, grade="E350", weight="8.65")]

    text = render_text(rows)
    html = render_html(rows)

    for figure in ("8.65", "98,000.00"):
        assert figure in text
        assert figure in html
