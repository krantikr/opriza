"""The month pack: one spreadsheet a trader can mail to a partner or an accountant.

Per-table CSV exports are fine for checking a single figure, but nobody sends
seven CSVs to their accountant. This builds one workbook with a summary sheet
that reads like a P&L and a sheet behind every headline, so the whole period
travels as a single attachment.

Numbers are written as numbers, not strings, because the first thing anyone
does with this file is sum a column.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.services.desk import DeskReport
from app.services.reports import Report

HEADER_FILL = PatternFill("solid", fgColor="1F2937")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(bold=True, size=13)
SECTION_FONT = Font(bold=True, size=10, color="374151")
MONEY_FORMAT = '#,##0;[Red]-#,##0'
PCT_FORMAT = '0.0"%"'
THIN = Side(style="thin", color="E5E7EB")
BORDER = Border(bottom=THIN)

#: Column-name suffixes that decide how a cell is formatted.
MONEY_KEYS = ("value", "revenue", "cost", "profit", "_inr", "missed", "quoted")
PCT_KEYS = ("pct", "rate")


def _is_money(key: str) -> bool:
    return any(k in key.lower() for k in MONEY_KEYS)


def _is_pct(key: str) -> bool:
    return any(k in key.lower() for k in PCT_KEYS)


def _humanise(key: str) -> str:
    return (
        key.replace("_inr", " (INR)")
        .replace("_pct", " %")
        .replace("_mt", " (MT)")
        .replace("_", " ")
        .capitalize()
    )


class WorkbookBuilder:
    """Assembles the pack sheet by sheet, then hands back the bytes."""

    def __init__(self, title: str) -> None:
        self.wb = Workbook()
        # openpyxl starts with a blank sheet; the summary claims it.
        self.summary = self.wb.active
        self.summary.title = "Summary"
        self.title = title
        self._row = 1

    # --- Summary ----------------------------------------------------------

    def write_summary(self, desk: DeskReport) -> None:
        """The one page somebody actually reads: money first, then the risks."""
        sheet = self.summary
        self._heading(sheet, self.title)
        self._line(sheet, "Period", f"{desk.period_label}  ({desk.period_range})")
        self._line(sheet, "Compared with", desk.previous_label)
        self._line(sheet, "Generated", date.today().strftime("%d %b %Y"))
        self._blank(sheet)

        won, before = desk.won, desk.won_previous
        enq = desk.enquiries
        if enq:
            self._section(sheet, "1. ENQUIRY AND QUOTATION")
            self._line(sheet, "Mail received", enq.get("received", 0))
            self._line(sheet, "Enquiries identified", enq.get("identified", 0))
            self._line(sheet, "Quotations raised", enq.get("raised", 0))
            self._line(sheet, "Quotations sent", enq.get("sent", 0))
            self._line(sheet, "Accepted", enq.get("won", 0))
            self._line(sheet, "Declined", enq.get("lost", 0))
            self._line(sheet, "Awaiting reply", enq.get("awaiting", 0))
            win = enq.get("win_rate")
            self._line(sheet, "Win rate on decided", "-" if win is None else f"{win}%")
            self._blank(sheet)

        self._section(sheet, "BUSINESS WON")
        self._figure(sheet, "Revenue", won.get("revenue", 0), before.get("revenue", 0))
        self._figure(sheet, "Cost of goods", won.get("cost", 0), before.get("cost", 0))
        self._figure(sheet, "Gross profit", won.get("profit", 0), before.get("profit", 0))
        self._line(sheet, "Margin", f"{won.get('margin_pct', 0)}%",
                   f"was {before.get('margin_pct', 0)}%")
        self._line(sheet, "Tonnes sold", won.get("tonnes", 0), before.get("tonnes", 0))
        self._line(sheet, "Orders", won.get("deals", 0), before.get("deals", 0))
        self._blank(sheet)

        self._section(sheet, "STILL IN PLAY")
        self._figure(sheet, "Value quoted, awaiting reply", desk.open_book.get("revenue", 0))
        self._figure(sheet, "Profit at stake", desk.open_book.get("profit", 0))
        self._blank(sheet)

        sm = desk.stock_movement
        if sm:
            self._section(sheet, "4. STOCK MOVEMENT (MT)")
            self._line(sheet, "Opening stock", sm.get("opening_mt", 0))
            self._line(sheet, "Add: receipts", sm.get("receipts_mt", 0),
                       f"{sm.get('receipt_count', 0)} movements")
            self._line(sheet, "Less: issues", sm.get("issues_mt", 0),
                       f"{sm.get('issue_count', 0)} movements")
            self._line(sheet, "Closing stock", sm.get("closing_mt", 0))
            self._blank(sheet)

        self._section(sheet, "CASH ON THE FLOOR")
        stock = desk.stock
        self._figure(sheet, "Stock at landed cost", stock.get("total_value", 0))
        self._figure(sheet, "Deadstock (over 90 days)", stock.get("deadstock_value", 0))
        self._line(sheet, "Deadstock share", f"{stock.get('deadstock_pct', 0)}%")
        self._line(sheet, "Deadstock lots", stock.get("deadstock_lots", 0))
        self._blank(sheet)

        self._section(sheet, "RISK")
        conc = desk.concentration
        self._line(sheet, "Largest customer share", f"{conc.get('top_1_pct', 0)}%")
        self._line(sheet, "Top 5 customer share", f"{conc.get('top_5_pct', 0)}%")
        delivery = desk.delivery
        on_time = delivery.get("on_time_pct")
        self._line(sheet, "Delivered on time",
                   "no despatches recorded" if on_time is None else f"{on_time}%")
        self._line(sheet, "Promises now overdue", delivery.get("overdue_now", 0))
        self._blank(sheet)

        if desk.lost_reasons:
            self._section(sheet, "WHY WE LOST")
            for row in desk.lost_reasons:
                self._line(sheet, row["label"],
                           f"{row['count']} quotes", f"INR {row['value']:,.0f}")

        sheet.column_dimensions["A"].width = 34
        sheet.column_dimensions["B"].width = 22
        sheet.column_dimensions["C"].width = 24

    # --- Data sheets ------------------------------------------------------

    def add_rows(self, name: str, rows: list[dict[str, Any]],
                 totals: dict[str, Any] | None = None) -> None:
        """One table per sheet, with a frozen, filterable header."""
        sheet = self.wb.create_sheet(name[:31])
        if not rows:
            sheet["A1"] = "Nothing in this period."
            sheet["A1"].font = Font(italic=True, color="6B7280")
            return

        columns = list(rows[0].keys())
        for index, key in enumerate(columns, start=1):
            cell = sheet.cell(row=1, column=index, value=_humanise(key))
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="left", vertical="center")

        for r, row in enumerate(rows, start=2):
            for c, key in enumerate(columns, start=1):
                cell = sheet.cell(row=r, column=c, value=_coerce(row.get(key)))
                cell.border = BORDER
                if isinstance(cell.value, (int, float)):
                    if _is_money(key):
                        cell.number_format = MONEY_FORMAT
                    elif _is_pct(key):
                        cell.number_format = PCT_FORMAT

        if totals:
            r = len(rows) + 3
            sheet.cell(row=r, column=1, value="Totals").font = SECTION_FONT
            for offset, (key, value) in enumerate(
                ((k, v) for k, v in totals.items() if not isinstance(v, dict)), start=1
            ):
                sheet.cell(row=r + offset, column=1, value=_humanise(key))
                cell = sheet.cell(row=r + offset, column=2, value=_coerce(value))
                if isinstance(cell.value, (int, float)) and _is_money(key):
                    cell.number_format = MONEY_FORMAT

        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"
        for index, key in enumerate(columns, start=1):
            width = max(len(_humanise(key)) + 2,
                        *(len(str(row.get(key, ""))) + 2 for row in rows[:60]))
            sheet.column_dimensions[get_column_letter(index)].width = min(width, 46)

    def add_report(self, name: str, report: Report) -> None:
        self.add_rows(name, report.rows, report.totals)

    # --- Output -----------------------------------------------------------

    def to_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self.wb.save(buffer)
        return buffer.getvalue()

    # --- Summary-sheet helpers --------------------------------------------

    def _heading(self, sheet, text: str) -> None:
        cell = sheet.cell(row=self._row, column=1, value=text)
        cell.font = TITLE_FONT
        self._row += 2

    def _section(self, sheet, text: str) -> None:
        cell = sheet.cell(row=self._row, column=1, value=text)
        cell.font = SECTION_FONT
        self._row += 1

    def _line(self, sheet, label: str, value: Any = "", note: Any = "") -> None:
        sheet.cell(row=self._row, column=1, value=label)
        sheet.cell(row=self._row, column=2, value=_coerce(value))
        if note != "":
            cell = sheet.cell(row=self._row, column=3, value=_coerce(note))
            cell.font = Font(color="6B7280", size=9)
        self._row += 1

    def _figure(self, sheet, label: str, value: float, previous: float | None = None) -> None:
        """A rupee figure, with the same figure from the period before beside it."""
        sheet.cell(row=self._row, column=1, value=label)
        cell = sheet.cell(row=self._row, column=2, value=float(value or 0))
        cell.number_format = MONEY_FORMAT
        if previous is not None:
            note = sheet.cell(row=self._row, column=3,
                              value=f"was {float(previous or 0):,.0f}")
            note.font = Font(color="6B7280", size=9)
        self._row += 1

    def _blank(self, sheet) -> None:
        self._row += 1


def _coerce(value: Any) -> Any:
    """Write numbers as numbers so the file can be summed without cleaning."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            return value
    return str(value)


__all__ = ["WorkbookBuilder"]
