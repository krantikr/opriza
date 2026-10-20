"""What a Tally source hands the sync: plain records, keyed by Tally GUIDs.

This is the seam between "where the books come from" and everything else.
The sync (app.kb.sync) only ever sees a `TallyBatch`; it does not know or care
whether the batch came from the mock generator or from a TallyPrime connector
on the customer's office PC. Swapping mock data for the real thing means
pointing a desk at `TallyXmlSource` instead of `MockTallySource` - nothing
downstream changes.

Bill-wise details follow Tally's own model: an invoice opens a bill with a
"New Ref"; a receipt, payment or credit note settles it with an "Agst Ref".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


@dataclass(slots=True)
class TLedger:
    guid: str
    name: str
    kind: str  # customer | supplier
    group: str  # Sundry Debtors | Sundry Creditors
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    gstin: str | None = None
    city: str | None = None
    area: str | None = None
    credit_days: int = 30
    credit_limit: float | None = None
    brand: str | None = None
    since: date | None = None
    #: Name of the salesperson the ledger is assigned to, when Tally has it
    #: (a cost centre or a ledger note); matched to a user by name.
    salesperson: str | None = None


@dataclass(slots=True)
class TItem:
    guid: str
    name: str
    group: str
    unit: str
    gst_rate: float = 18.0
    standard_cost: float = 0.0
    standard_rate: float = 0.0
    hsn: str | None = None
    reorder_level: float | None = None
    aliases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TGodown:
    guid: str
    name: str


@dataclass(slots=True)
class TLine:
    item_guid: str
    qty: float
    rate: float
    amount: float
    godown_guid: str | None = None


@dataclass(slots=True)
class TBillRef:
    """One bill-wise allocation on a voucher."""

    ref: str
    kind: str  # new | agst
    amount: float
    due_date: date | None = None


@dataclass(slots=True)
class TVoucher:
    guid: str
    alter_id: int
    vtype: str  # sales | purchase | receipt | payment | credit_note | debit_note | journal
    number: str
    date: date
    party_guid: str | None
    amount: float
    tax_amount: float = 0.0
    narration: str | None = None
    lines: list[TLine] = field(default_factory=list)
    bills: list[TBillRef] = field(default_factory=list)


@dataclass(slots=True)
class TStock:
    item_guid: str
    godown_guid: str
    as_of: date
    qty: float
    value: float


@dataclass(slots=True)
class TallyBatch:
    """Everything that changed since the last sync."""

    ledgers: list[TLedger] = field(default_factory=list)
    items: list[TItem] = field(default_factory=list)
    godowns: list[TGodown] = field(default_factory=list)
    vouchers: list[TVoucher] = field(default_factory=list)
    stock: list[TStock] = field(default_factory=list)
    #: Closing balance of the bank ledger(s), when the source reports it.
    bank_balance: float | None = None
    #: The highest Tally `AlterID` in this batch; the next sync asks for more.
    max_alter_id: int = 0

    @property
    def size(self) -> int:
        return len(self.ledgers) + len(self.items) + len(self.godowns) + len(self.vouchers) + len(self.stock)


class SourceUnavailable(RuntimeError):
    """Tally could not be reached (PC off, Tally closed, company not open)."""


class TallySource(Protocol):
    """Where a desk's books come from."""

    name: str

    def pull(self, since_alter_id: int) -> TallyBatch:
        """Everything with an AlterID above `since_alter_id`."""
        ...

    def describe(self) -> str: ...
