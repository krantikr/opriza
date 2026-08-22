"""Uploading a stock spreadsheet from the Stock screen.

The import replaces the stock list wholesale, so the cases that matter most
are the failures: a file that cannot be read, or one missing the columns, must
leave the desk's existing stock exactly as it was. Wiping a trader's stock
because they picked the wrong file would be the worst possible outcome here.
"""

from __future__ import annotations

import io

import pandas as pd
from sqlalchemy import select

from app.models import StockItem


def _workbook(rows: list[dict], sheet_name: str = "Sheet1", preamble: bool = False) -> bytes:
    """Build an .xlsx in memory. `preamble` mimics the client's own file,
    which carries an 'UPDATE DT.' stamp above the real header row."""
    buffer = io.BytesIO()
    frame = pd.DataFrame(rows)
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        start = 1 if preamble else 0
        frame.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start)
        if preamble:
            writer.sheets[sheet_name].cell(row=1, column=1, value="UPDATE DT. 21.08.2026")
    return buffer.getvalue()


ROWS = [
    {
        "PRODUCT": "plate",
        "GRADE": "E250",
        "THK": 8,
        "WDTH": 1250,
        "LNTH": 5800,
        "LOC": "Nagpur",
        "QTY": 12000,
        "BALANCE QTY": 12000,
        "PURCHASE RATE": 50.0,
        "LANDED COST": 52.0,
    },
    {
        "PRODUCT": "plate",
        "GRADE": "E350",
        "THK": 10,
        "WDTH": 1500,
        "LNTH": 6000,
        "LOC": "Raipur",
        "QTY": 8000,
        "BALANCE QTY": 8000,
        "PURCHASE RATE": 54.0,
        "LANDED COST": 56.5,
    },
]


def _upload(client, payload: bytes, name: str = "stock.xlsx"):
    return client.post(
        "/api/v1/stock/import",
        files={
            "file": (
                name,
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def test_uploading_a_spreadsheet_loads_the_lots(client, db):
    response = _upload(client, _workbook(ROWS))
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["rows_total"] == 2
    assert body["rows_imported"] == 2
    assert body["rows_failed"] == 0

    lots = db.scalars(select(StockItem)).all()
    assert {lot.grade for lot in lots} == {"E250", "E350"}

    plate = next(lot for lot in lots if lot.grade == "E250")
    # Cost is per kilogram in the source file and must stay that way; the
    # per-MT figure is derived downstream by multiplying by 1000.
    assert plate.landed_cost_per_kg == 52.0
    assert plate.thickness_mm == 8


def test_the_clients_own_layout_still_reads(client, db):
    """A date stamp above the header must not break the import."""
    payload = _workbook(ROWS, sheet_name="Actual stock list NEW", preamble=True)
    response = _upload(client, payload)
    assert response.status_code == 200, response.text
    assert response.json()["rows_imported"] == 2


def test_a_second_upload_replaces_rather_than_doubles(client, db):
    """The file is a snapshot, so re-importing it must not double the balance."""
    assert _upload(client, _workbook(ROWS)).status_code == 200
    assert _upload(client, _workbook(ROWS)).status_code == 200

    lots = db.scalars(select(StockItem)).all()
    assert len(lots) == 2


def test_a_file_missing_its_columns_leaves_stock_untouched(client, db):
    """The guarantee that matters: a wrong file must not empty the desk."""
    assert _upload(client, _workbook(ROWS)).status_code == 200
    before = {lot.id for lot in db.scalars(select(StockItem))}

    junk = _workbook([{"colour": "red", "note": "not a stock file"}])
    response = _upload(client, junk)
    assert response.status_code == 400
    assert "column" in response.json()["detail"].lower()

    db.expire_all()
    after = {lot.id for lot in db.scalars(select(StockItem))}
    assert after == before


def test_an_unreadable_file_leaves_stock_untouched(client, db):
    assert _upload(client, _workbook(ROWS)).status_code == 200
    before = {lot.id for lot in db.scalars(select(StockItem))}

    response = _upload(client, b"this is not a spreadsheet at all")
    assert response.status_code == 400

    db.expire_all()
    after = {lot.id for lot in db.scalars(select(StockItem))}
    assert after == before


def test_a_non_excel_file_is_refused(client):
    response = _upload(client, b"a,b\n1,2", name="stock.csv")
    assert response.status_code == 400
    assert "Excel" in response.json()["detail"]


def test_an_empty_file_is_refused(client):
    response = _upload(client, b"")
    assert response.status_code == 400


def test_a_bad_row_is_reported_without_losing_the_good_ones(client, db):
    rows = [*ROWS, {"PRODUCT": None, "GRADE": None, "THK": 5, "QTY": 100, "BALANCE QTY": 100}]
    response = _upload(client, _workbook(rows))
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["rows_imported"] == 2
    assert body["rows_failed"] == 1
    # The row number is what makes the error actionable in the source file.
    assert body["errors"][0]["row"] == 4
    assert db.scalar(select(StockItem).where(StockItem.grade == "E250")) is not None


def test_import_succeeds_while_a_quotation_points_at_a_lot(client, db, quoted_quotation):
    """The case that 500'd in the browser.

    Any quotation that has been matched holds a foreign key into
    `stock_items`, and stock movements hold another. A wholesale replace that
    does not detach them first is refused by the database, so the very first
    upload on a desk with real work on it would fail.
    """
    from app.models import QuotationLineItem

    line = db.scalars(select(QuotationLineItem)).first()
    assert line.matched_stock_item_id is not None

    response = _upload(client, _workbook(ROWS))
    assert response.status_code == 200, response.text
    assert response.json()["rows_imported"] == 2

    # The match is cleared rather than left dangling: the lot it named is gone,
    # and the line re-matches against the lots that replaced it.
    db.expire_all()
    assert db.get(QuotationLineItem, line.id).matched_stock_item_id is None


def test_movements_survive_an_uploaded_reimport(client, db, plate, default_user):
    """A recorded receipt must outlive the lot it was recorded against."""
    from decimal import Decimal

    from app.models import StockMovement, StockMovementKind
    from app.services.stock.movements import StockMovementService

    StockMovementService(db).record(
        kind=StockMovementKind.RECEIPT, quantity_kg=Decimal("5000"), stock_item=plate
    )
    db.commit()

    assert _upload(client, _workbook(ROWS)).status_code == 200

    db.expire_all()
    movement = db.scalars(select(StockMovement)).first()
    assert movement is not None
    # Detached from the deleted lot, but its own spec is intact, which is what
    # keeps it counting against the re-imported stock.
    assert movement.stock_item_id is None
    assert movement.quantity_kg == Decimal("5000")
    assert movement.grade == plate.grade


# ---------------------------------------------------------------------------
# Real-world spreadsheet values
#
# Every case below is taken from the client's own stock list, where each was
# rejecting a row that described real, sellable stock.
# ---------------------------------------------------------------------------


def test_coil_stock_imports_with_no_length():
    """"C" in a length column means coil, which has no cut length."""
    from app.services.ingestion.excel_importer import to_dimension

    assert to_dimension("C") is None
    assert to_dimension("COIL") is None
    assert to_dimension("coil form") is None


def test_a_length_stated_in_metres_becomes_millimetres():
    from app.services.ingestion.excel_importer import to_dimension

    assert to_dimension("6 MTR") == 6000
    assert to_dimension("300  - 6 MTR  ") == 6000
    assert to_dimension("12 metres") == 12000


def test_plain_dimensions_are_unaffected():
    from app.services.ingestion.excel_importer import to_dimension

    assert to_dimension(6000) == 6000
    assert to_dimension("1,250") == 1250
    assert to_dimension(None) is None


def test_a_dimension_that_means_nothing_still_fails():
    """Tolerance must not become "accept anything"."""
    import pytest

    from app.services.ingestion.excel_importer import to_dimension

    with pytest.raises(ValueError):
        to_dimension("about yay big")


def test_a_piece_count_written_as_a_sum():
    """Traders tally lots that arrived in parts: "34+1" is 35 pieces."""
    from app.services.ingestion.excel_importer import to_count

    assert to_count("34+1") == 35
    assert to_count("11+1") == 12
    assert to_count(12) == 12


def test_excel_error_text_reads_as_a_blank_figure():
    """`#DIV/0!` in a cost column is a lot with no quantity, not a bad row."""
    from app.services.ingestion.excel_importer import clean

    assert clean("#DIV/0!") is None
    assert clean("#N/A") is None
    assert clean("#VALUE!") is None


def test_the_awkward_rows_import_rather_than_being_rejected(client, db):
    """End to end: the four shapes together must cost no rows."""
    rows = [
        # A coil: no cut length, but real tonnage.
        {"PRODUCT": "plate", "GRADE": "E250", "THK": 2, "WDTH": 1250, "LNTH": "C",
         "QTY": 630, "BALANCE QTY": 630, "LANDED COST": 54.6, "NOP": 0},
        # A tube quoted in metres.
        {"PRODUCT": "tube", "GRADE": "TUBE", "THK": 10, "WDTH": 300, "LNTH": "300  - 6 MTR",
         "QTY": 3871, "BALANCE QTY": 3871, "LANDED COST": 64.9, "NOP": 4},
        # A piece count written as a sum.
        {"PRODUCT": "plate", "GRADE": "S700MC", "THK": 6, "WDTH": 1500, "LNTH": 6300,
         "QTY": 15640, "BALANCE QTY": 15640, "LANDED COST": 73.9, "NOP": "34+1"},
        # A cost that failed to compute because the lot is empty.
        {"PRODUCT": "plate", "GRADE": "RK-400", "THK": 16, "WDTH": 2000, "LNTH": 3000,
         "QTY": 0, "BALANCE QTY": 0, "LANDED COST": "#DIV/0!", "NOP": 1},
    ]

    response = _upload(client, _workbook(rows))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows_failed"] == 0, body["errors"]
    assert body["rows_imported"] == 4

    lots = {lot.grade: lot for lot in db.scalars(select(StockItem))}
    assert lots["E250"].length_mm is None          # coil
    assert lots["TUBE"].length_mm == 6000          # 6 MTR
    assert lots["S700MC"].nop == 35                # 34+1
    assert lots["RK-400"].landed_cost_per_kg is None  # #DIV/0!
