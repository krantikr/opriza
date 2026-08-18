"""Excel -> validated rows -> SQLite.

Spreadsheets are an input to this system, never its running store (spec section
30). Every import creates an `ImportBatch` holding the file name, a content
hash, row counts and the validation errors, and every row it writes carries
that batch id - so any figure in the database can be traced back to the file
and the moment it arrived.

A bad row never aborts an import. It is counted, recorded with its row number
and reason, and the run continues; the batch is then marked PARTIAL. Losing 900
good rows because row 901 has a typo would be the wrong trade.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.logging import get_logger
from app.models import Customer, CustomerTier, ImportBatch, ImportEntity, ImportStatus, RecordStatus, StockItem
from app.services.ingestion.column_map import ColumnSpec, build_mapping

logger = get_logger(__name__)

MAX_RECORDED_ERRORS = 200
CUSTOMER_FILE = "customers.xlsx"


class ImportFailed(Exception):
    """Raised when a file cannot be read or is missing required columns."""


@dataclass(slots=True)
class ImportResult:
    entity: ImportEntity
    source_file: str
    status: ImportStatus
    rows_total: int = 0
    rows_imported: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    rows_failed: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    batch_id: int | None = None

    def summary(self) -> str:
        return (
            f"{self.entity.value:10} {self.status.value:9} "
            f"total={self.rows_total:5} new={self.rows_imported:5} "
            f"updated={self.rows_updated:5} skipped={self.rows_skipped:5} "
            f"failed={self.rows_failed:5}"
        )


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------


def clean(value: Any) -> Any:
    """Normalise spreadsheet blanks (NaN, NaT, empty string) to None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return value.strip() or None
    return value


def to_str(value: Any, max_len: int | None = None) -> str | None:
    value = clean(value)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len] if max_len else text


def to_float(value: Any) -> float | None:
    value = clean(value)
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError(f"expected a number, got {value!r}") from None


def to_int(value: Any) -> int | None:
    parsed = to_float(value)
    return int(round(parsed)) if parsed is not None else None


def to_decimal(value: Any) -> Decimal | None:
    value = clean(value)
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"expected a decimal, got {value!r}") from None


def to_date(value: Any) -> date | None:
    value = clean(value)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        raise ValueError(f"expected a date, got {value!r}")
    return parsed.date()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Base importer
# ---------------------------------------------------------------------------


class BaseImporter(ABC):
    entity: ImportEntity
    specs: list[ColumnSpec]
    sheet_name: str | int | None = 0
    header_row: int = 0

    def __init__(self, db: Session, imported_by: str = "system") -> None:
        self.db = db
        self.imported_by = imported_by

    @abstractmethod
    def import_row(self, row: dict[str, Any], batch: ImportBatch) -> str:
        """Handle one mapped row.

        Returns one of "imported", "updated" or "skipped". Raising `ValueError`
        marks the row failed and continues with the next one.
        """

    def _read_frame(self, path: Path) -> pd.DataFrame:
        return pd.read_excel(path, sheet_name=self.sheet_name, header=self.header_row)

    def _before_import(self, path: Path) -> None:
        """Hook for subclasses that need to clear prior state before loading."""

    def run(self, path: Path) -> ImportResult:
        if not path.exists():
            raise ImportFailed(f"File not found: {path}")

        self._before_import(path)

        try:
            frame = self._read_frame(path)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as-is
            raise ImportFailed(f"Could not read {path.name}: {exc}") from exc

        mapping = build_mapping(list(frame.columns), self.specs)
        if not mapping.ok:
            raise ImportFailed(
                f"{path.name} is missing required column(s): {mapping.describe_missing()}"
            )

        batch = ImportBatch(
            entity_type=self.entity,
            source_file=str(path),
            file_hash=file_hash(path),
            status=ImportStatus.PENDING,
            rows_total=len(frame),
            imported_by=self.imported_by,
        )
        self.db.add(batch)
        self.db.flush()

        result = ImportResult(
            entity=self.entity,
            source_file=path.name,
            status=ImportStatus.PENDING,
            rows_total=len(frame),
            batch_id=batch.id,
        )

        renamed = frame.rename(columns=mapping.by_header)
        keep = [c for c in renamed.columns if c in {s.field for s in self.specs}]

        for index, raw in enumerate(renamed[keep].to_dict(orient="records"), start=2):
            try:
                outcome = self.import_row(raw, batch)
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the file
                result.rows_failed += 1
                if len(result.errors) < MAX_RECORDED_ERRORS:
                    result.errors.append({"row": index, "error": str(exc)})
                continue

            if outcome == "imported":
                result.rows_imported += 1
            elif outcome == "updated":
                result.rows_updated += 1
            else:
                result.rows_skipped += 1

        result.status = (
            ImportStatus.FAILED
            if result.rows_failed and not (result.rows_imported or result.rows_updated)
            else ImportStatus.PARTIAL
            if result.rows_failed
            else ImportStatus.COMPLETED
        )

        batch.status = result.status
        batch.rows_imported = result.rows_imported + result.rows_updated
        batch.rows_skipped = result.rows_skipped
        batch.rows_failed = result.rows_failed
        batch.errors = result.errors or None
        batch.completed_at = utcnow()

        self.db.commit()
        logger.info(result.summary())
        return result


# ---------------------------------------------------------------------------
# Concrete importers
# ---------------------------------------------------------------------------


class StockImporter(BaseImporter):
    """Imports the client's stock list - one row per physical lot.

    Reads the `Actual stock list NEW` sheet specifically; the workbook also
    carries several supplier/location ledgers and a historical "Grade wise"
    sales sheet that are not current stock and are intentionally not read.
    Row 1 of that sheet is an "UPDATE DT." stamp, not a header, so the real
    header row is row 2 (`header=1`, zero-indexed).

    `Purchase RATE` / `Landed Cost As on Today` are INR per **kilogram** in
    the source file (confirmed via `VALUE = QTY x Purchase RATE`), so they are
    stored as `*_per_kg` to make the unit impossible to misread downstream.
    """

    entity = ImportEntity.STOCK
    sheet_name = "Actual stock list NEW"
    header_row = 1

    specs = [
        ColumnSpec("product_type", ("product", "type", "material", "category")),
        ColumnSpec("grade", ("material grade", "quality", "steel grade")),
        ColumnSpec("thickness_mm", ("thk", "thickness", "thick")),
        ColumnSpec("width_mm", ("wdth", "width", "size", "wide")),
        ColumnSpec("length_mm", ("lnth", "length", "len", "long")),
        ColumnSpec("location", ("loc", "stock location", "place")),
        ColumnSpec("make", ("mill",)),
        ColumnSpec("coil_no", ()),
        ColumnSpec("ageing_days", ("ageing", "aging", "age")),
        ColumnSpec("purchase_rate_per_kg", ("purchase rate", "purchase price")),
        ColumnSpec("landed_cost_per_kg", ("landed cost as on today", "landed cost")),
        ColumnSpec("nop", ("no of pieces", "pieces", "pcs")),
        ColumnSpec("qty_kg", ("qty", "quantity", "weight")),
        ColumnSpec("balance_nop", ("balance pieces",)),
        ColumnSpec("balance_qty_kg", ("balance qty", "balance quantity", "balance weight")),
        ColumnSpec("stock_date", ("date",)),
        ColumnSpec("curr_dt", ("curr dt", "current date")),
    ]

    def _before_import(self, path: Path) -> None:
        # The file is a full point-in-time snapshot with no natural key to
        # upsert lots on, so each import replaces the table wholesale - this
        # is what stops balance quantity double-counting across repeated
        # monthly imports. Still fully audited: the ImportBatch row this
        # creates records exactly what replaced what, and when.
        self.db.execute(delete(StockItem))
        self.db.commit()

    def import_row(self, row: dict[str, Any], batch: ImportBatch) -> str:
        grade = to_str(row.get("grade"), 60)
        product_type = to_str(row.get("product_type"), 80)
        if not grade and not product_type:
            raise ValueError("row has neither a grade nor a product type; nothing to match against")

        item = StockItem(
            product_type=product_type,
            grade=grade,
            thickness_mm=to_float(row.get("thickness_mm")),
            width_mm=to_float(row.get("width_mm")),
            length_mm=to_float(row.get("length_mm")),
            location=to_str(row.get("location"), 120),
            make=to_str(row.get("make"), 80),
            coil_no=to_str(row.get("coil_no"), 60),
            nop=to_float(row.get("nop")),
            qty_kg=to_decimal(row.get("qty_kg")),
            balance_nop=to_float(row.get("balance_nop")),
            balance_qty_kg=to_decimal(row.get("balance_qty_kg")),
            purchase_rate_per_kg=to_float(row.get("purchase_rate_per_kg")),
            landed_cost_per_kg=to_float(row.get("landed_cost_per_kg")),
            ageing_days=to_int(row.get("ageing_days")),
            stock_date=to_date(row.get("stock_date")),
            curr_dt=to_date(row.get("curr_dt")),
            import_batch_id=batch.id,
        )
        self.db.add(item)
        self.db.flush()
        return "imported"


class CustomerImporter(BaseImporter):
    entity = ImportEntity.CUSTOMERS
    specs = [
        ColumnSpec("customer_code", ("code", "cust code", "account code")),
        ColumnSpec("name", ("customer name", "contact person", "contact name"), required=True),
        ColumnSpec("email", ("email id", "e mail", "mail")),
        ColumnSpec("phone", ("mobile", "contact no", "phone no")),
        ColumnSpec("company", ("company name", "firm", "organisation", "organization")),
        ColumnSpec("billing_address", ("address", "bill to")),
        ColumnSpec("shipping_address", ("ship to", "delivery address")),
        ColumnSpec("default_delivery_location", ("city", "location", "place")),
        ColumnSpec("tier", ("category", "customer class", "segment")),
        ColumnSpec("payment_terms", ("terms", "credit terms")),
        ColumnSpec("status", ("active", "state")),
    ]

    def import_row(self, row: dict[str, Any], batch: ImportBatch) -> str:
        name = to_str(row.get("name"), 200)
        if not name:
            raise ValueError("customer name is blank")

        code = to_str(row.get("customer_code"), 40)
        email = to_str(row.get("email"), 255)

        existing = None
        if code:
            existing = self.db.scalar(select(Customer).where(Customer.customer_code == code))
        if not existing and email:
            existing = self.db.scalar(select(Customer).where(Customer.email == email.lower()))

        target = existing or Customer(customer_code=code)
        target.name = name
        target.email = email.lower() if email else None
        target.phone = to_str(row.get("phone"), 40)
        target.company = to_str(row.get("company"), 200)
        target.billing_address = to_str(row.get("billing_address"))
        target.shipping_address = to_str(row.get("shipping_address"))
        target.default_delivery_location = to_str(row.get("default_delivery_location"), 120)
        target.payment_terms = to_str(row.get("payment_terms"), 200)
        # A row in the master file is by definition confirmed, which also
        # promotes any unverified record the workflow had auto-created from an
        # email from this same address.
        target.is_verified = True

        tier_text = (to_str(row.get("tier")) or "B").strip().upper()[:1]
        target.tier = CustomerTier(tier_text) if tier_text in {"A", "B", "C"} else CustomerTier.B

        status_text = (to_str(row.get("status")) or "ACTIVE").upper()
        target.status = (
            RecordStatus.INACTIVE if status_text.startswith("INACT") else RecordStatus.ACTIVE
        )

        if existing:
            return "updated"
        self.db.add(target)
        self.db.flush()
        return "imported"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def import_directory(
    db: Session,
    directory: Path,
    stock_file: Path | str | None = None,
    imported_by: str = "system",
) -> list[ImportResult]:
    """Import the customer file from `directory` and the stock file, if given.

    There is no fixed stock filename - the client's export is dated per month
    - so it is passed explicitly rather than discovered by convention. Missing
    files are skipped with a warning, not an error.
    """
    results: list[ImportResult] = []

    customer_path = directory / CUSTOMER_FILE
    if customer_path.exists():
        results.append(CustomerImporter(db, imported_by=imported_by).run(customer_path))
    else:
        logger.warning("Skipping %s - not found in %s", CUSTOMER_FILE, directory)

    if stock_file is not None:
        stock_path = Path(stock_file)
        if stock_path.exists():
            results.append(StockImporter(db, imported_by=imported_by).run(stock_path))
        else:
            logger.warning("Stock file not found: %s", stock_path)

    return results
