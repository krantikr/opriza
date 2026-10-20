"""The real Tally: TallyPrime / Tally.ERP 9 over XML on port 9000.

Tally exposes an XML-over-HTTP interface on the PC where it runs (enable it
under F1 Help > Settings > Connectivity, "TallyPrime acts as: Server", port
9000). We POST an export request and read back an ENVELOPE of TALLYMESSAGE
records: LEDGER, STOCKITEM, GODOWN and VOUCHER with its ledger entries,
bill-wise allocations and inventory entries.

Reaching it: the office PC is usually not on the internet. The connector runs
there (or on the same LAN) and the backend reaches it at `source_url`. Until
that connector exists, the same parser is exercised by the tests against the
sample export in data/mock_business/.

What still needs checking on a real TallyPrime before go-live (marked TODO
below): the exact collection filter for AlterID, how the customer's Tally
names bank ledgers, and godown-wise closing stock for their version.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import httpx

from app.kb.sources.base import (
    SourceUnavailable,
    TallyBatch,
    TBillRef,
    TGodown,
    TItem,
    TLedger,
    TLine,
    TVoucher,
)

VTYPES = {
    "sales": "sales",
    "purchase": "purchase",
    "receipt": "receipt",
    "payment": "payment",
    "credit note": "credit_note",
    "debit note": "debit_note",
    "journal": "journal",
}

#: Export every voucher changed after an AlterID. TODO(go-live): confirm the
#: filter on the customer's TallyPrime release; older ERP 9 builds need the
#: $$IsGreater form shown here rather than a TDL FILTER on AlterID.
VOUCHER_REQUEST = """<ENVELOPE>
 <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>OprisaVouchers</ID></HEADER>
 <BODY><DESC>
  <STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{company}</STATICVARIABLES>
  <TDL><TDLMESSAGE>
   <COLLECTION NAME="OprisaVouchers" ISMODIFY="No"><TYPE>Voucher</TYPE>
    <FETCH>*, AllLedgerEntries.*, AllInventoryEntries.*, LedgerEntries.BillAllocations.*</FETCH>
    <FILTER>OprisaChanged</FILTER>
   </COLLECTION>
   <SYSTEM TYPE="Formulae" NAME="OprisaChanged">$$IsGreater:$AlterID:{since}</SYSTEM>
  </TDLMESSAGE></TDL>
 </DESC></BODY>
</ENVELOPE>"""

MASTERS_REQUEST = """<ENVELOPE>
 <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>OprisaMasters</ID></HEADER>
 <BODY><DESC>
  <STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{company}</STATICVARIABLES>
  <TDL><TDLMESSAGE>
   <COLLECTION NAME="OprisaMasters" ISMODIFY="No"><TYPE>{type}</TYPE><FETCH>*</FETCH></COLLECTION>
  </TDLMESSAGE></TDL>
 </DESC></BODY>
</ENVELOPE>"""


def _t(el: ET.Element | None, tag: str, default: str = "") -> str:
    if el is None:
        return default
    found = el.find(tag)
    return (found.text or "").strip() if found is not None and found.text else default


def _num(text: str) -> float:
    """Tally numbers: '1,23,456.00', '-578284.56', '60808.05/MT', ' 9.51 MT'."""
    m = re.search(r"-?[\d,]*\.?\d+", text or "")
    return float(m.group(0).replace(",", "")) if m else 0.0


def _days(text: str) -> int:
    return int(_num(text)) if text else 30


def _date(text: str) -> date:
    return datetime.strptime(text.strip(), "%Y%m%d").date()


def parse_envelope(xml_text: str, bank_ledgers: tuple[str, ...] = ()) -> TallyBatch:
    """Turn a Tally export into a batch. Accepts masters, vouchers, or both."""
    root = ET.fromstring(xml_text)
    batch = TallyBatch()
    ledger_guid: dict[str, str] = {}
    item_guid: dict[str, str] = {}
    godown_guid: dict[str, str] = {}

    for msg in root.iter("TALLYMESSAGE"):
        for led in msg.findall("LEDGER"):
            name = led.get("NAME") or _t(led, "NAME")
            parent = _t(led, "PARENT")
            guid = _t(led, "GUID") or f"ledger:{name}"
            ledger_guid[name] = guid
            if parent.lower() in ("bank accounts", "bank od a/c", "bank occ a/c") or name in bank_ledgers:
                bal = _num(_t(led, "CLOSINGBALANCE"))
                batch.bank_balance = (batch.bank_balance or 0) + (-bal if bal < 0 else bal)
                continue
            if parent not in ("Sundry Debtors", "Sundry Creditors"):
                continue
            batch.ledgers.append(
                TLedger(
                    guid=guid,
                    name=name,
                    kind="customer" if parent == "Sundry Debtors" else "supplier",
                    group=parent,
                    contact_name=_t(led, "LEDGERCONTACT") or None,
                    phone=_t(led, "LEDGERPHONE") or _t(led, "LEDGERMOBILE") or None,
                    email=_t(led, "EMAIL") or None,
                    gstin=_t(led, "PARTYGSTIN") or None,
                    city=_t(led, "LEDSTATENAME") or None,
                    credit_days=_days(_t(led, "BILLCREDITPERIOD")),
                    credit_limit=abs(_num(_t(led, "CREDITLIMIT"))) or None,
                )
            )
        for it in msg.findall("STOCKITEM"):
            name = it.get("NAME") or _t(it, "NAME")
            guid = _t(it, "GUID") or f"item:{name}"
            item_guid[name] = guid
            gst = it.find("GSTDETAILS.LIST")
            aliases = [(_t(a, "NAME")) for a in it.findall("LANGUAGENAME.LIST/NAME.LIST")]
            batch.items.append(
                TItem(
                    guid=guid,
                    name=name,
                    group=_t(it, "PARENT") or "Primary",
                    unit=_t(it, "BASEUNITS") or "nos",
                    gst_rate=_num(_t(gst, "RATE")) if gst is not None else 18.0,
                    hsn=_t(gst, "HSNCODE") or None,
                    standard_cost=_num(_t(it, "STANDARDCOST")),
                    standard_rate=_num(_t(it, "STANDARDPRICE")),
                    reorder_level=_num(_t(it, "REORDERBASE")) or None,
                    aliases=[a for a in aliases if a and a != name],
                )
            )
        for gd in msg.findall("GODOWN"):
            name = gd.get("NAME") or _t(gd, "NAME")
            guid = _t(gd, "GUID") or f"godown:{name}"
            godown_guid[name] = guid
            batch.godowns.append(TGodown(guid=guid, name=name))

    for msg in root.iter("TALLYMESSAGE"):
        for v in msg.findall("VOUCHER"):
            vtype = VTYPES.get((v.get("VCHTYPE") or _t(v, "VOUCHERTYPENAME")).lower())
            if not vtype:
                continue
            party = _t(v, "PARTYLEDGERNAME")
            amount = 0.0
            bills: list[TBillRef] = []
            tax = 0.0
            for le in v.findall("LEDGERENTRIES.LIST") + v.findall("ALLLEDGERENTRIES.LIST"):
                lname = _t(le, "LEDGERNAME")
                value = abs(_num(_t(le, "AMOUNT")))
                if lname == party:
                    amount = value
                    vdate = _date(_t(v, "DATE"))
                    for ba in le.findall("BILLALLOCATIONS.LIST"):
                        kind = _t(ba, "BILLTYPE").lower()
                        credit = _t(ba, "BILLCREDITPERIOD")
                        bills.append(
                            TBillRef(
                                ref=_t(ba, "NAME"),
                                kind="new" if kind.startswith("new") else "agst",
                                amount=abs(_num(_t(ba, "AMOUNT"))),
                                due_date=vdate + timedelta(days=_days(credit)) if credit else None,
                            )
                        )
                elif re.search(r"gst|tax|cgst|sgst|igst", lname, re.I):
                    tax += value
            lines = []
            for ie in v.findall("ALLINVENTORYENTRIES.LIST") + v.findall("INVENTORYENTRIES.LIST"):
                name = _t(ie, "STOCKITEMNAME")
                gd = ie.find("BATCHALLOCATIONS.LIST")
                lines.append(
                    TLine(
                        item_guid=item_guid.get(name, f"item:{name}"),
                        qty=abs(_num(_t(ie, "BILLEDQTY") or _t(ie, "ACTUALQTY"))),
                        rate=_num(_t(ie, "RATE")),
                        amount=abs(_num(_t(ie, "AMOUNT"))),
                        godown_guid=godown_guid.get(_t(gd, "GODOWNNAME")) if gd is not None else None,
                    )
                )
            if not tax and lines:
                tax = max(0.0, round(amount - sum(ln.amount for ln in lines), 2))
            alter = int(_num(_t(v, "ALTERID")))
            batch.vouchers.append(
                TVoucher(
                    guid=_t(v, "GUID"),
                    alter_id=alter,
                    vtype=vtype,
                    number=_t(v, "VOUCHERNUMBER"),
                    date=_date(_t(v, "DATE")),
                    party_guid=ledger_guid.get(party, f"ledger:{party}") if party else None,
                    amount=amount,
                    tax_amount=tax,
                    narration=_t(v, "NARRATION") or None,
                    lines=lines,
                    bills=bills,
                )
            )
            batch.max_alter_id = max(batch.max_alter_id, alter)
    return batch


class TallyXmlSource:
    """Pulls from a Tally XML server (directly, or through the connector)."""

    name = "tally_xml"

    def __init__(self, url: str, company: str | None = None, timeout: float = 30.0) -> None:
        self.url = url.rstrip("/")
        self.company = company
        self.timeout = timeout

    def describe(self) -> str:
        return f"Tally XML at {self.url}" + (f" ({self.company})" if self.company else "")

    def _company(self) -> str:
        return f"<SVCURRENTCOMPANY>{self.company}</SVCURRENTCOMPANY>" if self.company else ""

    def _post(self, body: str) -> str:
        try:
            r = httpx.post(
                self.url,
                content=body.encode("utf-8"),
                timeout=self.timeout,
                headers={"Content-Type": "text/xml"},
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:  # PC off, Tally closed, company not open
            raise SourceUnavailable(f"Tally did not answer at {self.url}: {exc}") from exc
        return r.text

    def pull(self, since_alter_id: int) -> TallyBatch:
        masters = TallyBatch()
        if since_alter_id == 0:
            for kind in ("Ledger", "StockItem", "Godown"):
                part = parse_envelope(self._post(MASTERS_REQUEST.format(company=self._company(), type=kind)))
                masters.ledgers += part.ledgers
                masters.items += part.items
                masters.godowns += part.godowns
                if part.bank_balance is not None:
                    masters.bank_balance = part.bank_balance
            # TODO(go-live): godown-wise closing stock via a StockItem collection
            # with ClosingBalance per godown; until then stock comes from movements.
        vouchers = parse_envelope(
            self._post(VOUCHER_REQUEST.format(company=self._company(), since=since_alter_id))
        )
        masters.vouchers = vouchers.vouchers
        masters.max_alter_id = max(since_alter_id, vouchers.max_alter_id)
        return masters


def source_for(business) -> object:
    """The source a desk is configured for."""
    from app.kb.sources.mock import MockTallySource

    if business.source == "tally_xml":
        if not business.source_url:
            raise SourceUnavailable("This desk is set to Tally XML but has no connector address.")
        return TallyXmlSource(business.source_url)
    return MockTallySource(business.mock_key or "shree-balaji-steels")
