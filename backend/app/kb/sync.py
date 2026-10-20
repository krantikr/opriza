"""Tally sync: the only writer of the Tally mirror (layer A).

    batch = source.pull(business.last_alter_id)   # mock or real, same shape
    apply_batch(db, batch)                         # upsert by Tally GUID
    facts.refresh(db)                              # layer B follows the books

Each new voucher after the first load becomes a `voucher.posted` event, which
is how a receipt typed into Tally reaches the Collections, Score and Cash
agents within one sync. The first full load publishes a single
`sync.loaded` instead of thousands of events about last year.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.kb import clock, events
from app.kb.models import (
    KbBill,
    KbBillAllocation,
    KbGodown,
    KbItem,
    KbItemAlias,
    KbMember,
    KbParty,
    KbStockBalance,
    KbSyncRun,
    KbVoucher,
    KbVoucherLine,
)
from app.kb.sources.base import SourceUnavailable, TallyBatch
from app.models import User

logger = get_logger(__name__)

RECEIVABLE_TYPES = {"sales", "debit_note"}
PAYABLE_TYPES = {"purchase"}


def run_sync(db: Session, source=None, *, refresh_facts: bool = True) -> KbSyncRun:
    """Pull from the desk's source and apply it. Never raises for an offline Tally."""
    from app.kb import facts
    from app.kb.sources.tally_xml import source_for

    biz = clock.business(db)
    source = source or source_for(biz)
    org = db.info["organisation_id"]
    run = KbSyncRun(organisation_id=org, source=source.name, started_at=clock.now(db), status="running")
    db.add(run)
    db.flush()
    try:
        batch = source.pull(biz.last_alter_id or 0)
        initial = (biz.last_alter_id or 0) == 0
        apply_batch(db, batch, publish=not initial)
        if initial:
            events.publish(
                db, "sync.loaded", "business", biz.id, source="tally_sync", vouchers=len(batch.vouchers)
            )
        run.objects_read = batch.size
        run.last_alter_id = biz.last_alter_id
        run.status = "ok"
        if refresh_facts:
            facts.refresh(db)
    except SourceUnavailable as exc:
        run.status = "failed"
        run.error = str(exc)
        logger.warning("Sync for org %s: %s", org, exc)
    run.finished_at = clock.now(db)
    db.flush()
    return run


def apply_batch(db: Session, batch: TallyBatch, *, publish: bool = True) -> list[int]:
    """Upsert a batch into the mirror. Returns ids of vouchers that are new."""
    org = db.info["organisation_id"]
    biz = clock.business(db)

    # ----------------------------------------------------------- masters
    godowns = {g.tally_guid: g for g in db.scalars(select(KbGodown))}
    for g in batch.godowns:
        row = godowns.get(g.guid)
        if row is None:
            row = KbGodown(organisation_id=org, tally_guid=g.guid, name=g.name)
            db.add(row)
            godowns[g.guid] = row
        row.name = g.name

    items = {i.tally_guid: i for i in db.scalars(select(KbItem))}
    for it in batch.items:
        row = items.get(it.guid)
        if row is None:
            row = KbItem(
                organisation_id=org,
                tally_guid=it.guid,
                name=it.name,
                stock_group=it.group,
                unit=it.unit,
                standard_cost=it.standard_cost,
                standard_rate=it.standard_rate,
            )
            db.add(row)
            items[it.guid] = row
        row.name, row.stock_group, row.unit = it.name, it.group, it.unit
        row.gst_rate, row.hsn = it.gst_rate, it.hsn
        row.standard_cost = it.standard_cost or row.standard_cost
        row.standard_rate = it.standard_rate or row.standard_rate
        row.reorder_level = it.reorder_level
    db.flush()
    known_alias = set(db.scalars(select(KbItemAlias.alias)))
    for it in batch.items:
        for al in it.aliases:
            a = al.strip().lower()
            if a and a not in known_alias:
                known_alias.add(a)
                db.add(KbItemAlias(organisation_id=org, item_id=items[it.guid].id, alias=a, source="tally"))

    users = {u.name.lower(): u.id for u in db.scalars(select(User).where(User.organisation_id == org))}
    parties = {p.tally_guid: p for p in db.scalars(select(KbParty))}
    for led in batch.ledgers:
        row = parties.get(led.guid)
        if row is None:
            row = KbParty(
                organisation_id=org, tally_guid=led.guid, name=led.name, kind=led.kind, tally_group=led.group
            )
            db.add(row)
            parties[led.guid] = row
        row.name, row.kind, row.tally_group = led.name, led.kind, led.group
        for f in ("contact_name", "phone", "email", "gstin", "city", "area", "brand", "since"):
            value = getattr(led, f)
            if value is not None:
                setattr(row, f, value)
        row.credit_days = led.credit_days
        row.credit_limit = led.credit_limit
        if led.salesperson:
            row.salesperson_id = users.get(led.salesperson.lower(), row.salesperson_id)
    db.flush()

    # ----------------------------------------------------------- vouchers
    existing = dict(db.execute(select(KbVoucher.tally_guid, KbVoucher.id)).all())
    changed = [v for v in batch.vouchers if v.guid in existing]
    for v in changed:  # an edited voucher: take it out, then put the new version in
        _remove_voucher(db, existing[v.guid])
    party_id = {g: p.id for g, p in parties.items()}
    item_id = {g: i.id for g, i in items.items()}
    godown_id = {g: x.id for g, x in godowns.items()}

    rows = [
        {
            "organisation_id": org,
            "tally_guid": v.guid,
            "alter_id": v.alter_id,
            "voucher_type": v.vtype,
            "number": v.number,
            "date": v.date,
            "party_id": party_id.get(v.party_guid) if v.party_guid else None,
            "amount": v.amount,
            "tax_amount": v.tax_amount,
            "narration": v.narration,
        }
        for v in batch.vouchers
    ]
    vid: dict[str, int] = {}
    for chunk in _chunks(rows, 2000):
        for guid, new_id in db.execute(
            insert(KbVoucher).returning(KbVoucher.tally_guid, KbVoucher.id), chunk
        ):
            vid[guid] = new_id
    line_rows = [
        {
            "organisation_id": org,
            "voucher_id": vid[v.guid],
            "line_no": n,
            "item_id": item_id[ln.item_guid],
            "godown_id": godown_id.get(ln.godown_guid) if ln.godown_guid else None,
            "qty": ln.qty,
            "rate": ln.rate,
            "amount": ln.amount,
        }
        for v in batch.vouchers
        for n, ln in enumerate(v.lines, 1)
        if ln.item_guid in item_id
    ]
    for chunk in _chunks(line_rows, 4000):
        db.execute(insert(KbVoucherLine), chunk)

    # Bills: New Ref opens a bill, Agst Ref settles one.
    bills = {(b.party_id, b.bill_ref): b for b in db.scalars(select(KbBill))}
    new_bills = []
    by_id = parties_by_id(parties)
    for v in sorted(batch.vouchers, key=lambda x: (x.date, x.alter_id)):
        pid = party_id.get(v.party_guid) if v.party_guid else None
        if pid is None:
            continue
        for ref in v.bills:
            if ref.kind != "new" or (pid, ref.ref) in bills:
                continue
            direction = "payable" if v.vtype in PAYABLE_TYPES else "receivable"
            credit = by_id[pid].credit_days
            row = {
                "organisation_id": org,
                "party_id": pid,
                "direction": direction,
                "bill_ref": ref.ref,
                "bill_date": v.date,
                "due_date": ref.due_date or v.date + timedelta(days=credit),
                "amount": ref.amount,
                "pending_amount": ref.amount,
                "voucher_id": vid[v.guid],
            }
            new_bills.append(row)
            bills[(pid, ref.ref)] = row  # placeholder until inserted
    for chunk in _chunks(new_bills, 2000):
        db.execute(insert(KbBill), chunk)
    bills = {(b.party_id, b.bill_ref): b.id for b in db.scalars(select(KbBill))}

    alloc_rows = []
    for v in batch.vouchers:
        pid = party_id.get(v.party_guid) if v.party_guid else None
        for ref in v.bills:
            if ref.kind != "agst" or pid is None:
                continue
            bill_id = bills.get((pid, ref.ref))
            if bill_id is None:
                logger.warning("Voucher %s settles unknown bill %s; kept on account", v.number, ref.ref)
                continue
            alloc_rows.append(
                {
                    "organisation_id": org,
                    "bill_id": bill_id,
                    "voucher_id": vid[v.guid],
                    "amount": ref.amount,
                    "date": v.date,
                }
            )
    for chunk in _chunks(alloc_rows, 4000):
        db.execute(insert(KbBillAllocation), chunk)
    if alloc_rows or new_bills or changed:
        _recompute_pending(db)

    # ----------------------------------------------------------- stock, bank
    if batch.stock:
        current = {(s.item_id, s.godown_id, s.as_of): s for s in db.scalars(select(KbStockBalance))}
        add = []
        for s in batch.stock:
            key = (item_id.get(s.item_guid), godown_id.get(s.godown_guid), s.as_of)
            if None in key[:2]:
                continue
            if key in current:
                current[key].qty, current[key].value = s.qty, s.value
            else:
                add.append(
                    {
                        "organisation_id": org,
                        "item_id": key[0],
                        "godown_id": key[1],
                        "as_of": s.as_of,
                        "qty": s.qty,
                        "value": s.value,
                    }
                )
        for chunk in _chunks(add, 4000):
            db.execute(insert(KbStockBalance), chunk)
    elif batch.vouchers:
        _roll_stock(db, batch, item_id, godown_id)
    if batch.bank_balance is not None:
        biz.bank_balance = batch.bank_balance
        biz.bank_balance_at = clock.now(db)

    biz.last_alter_id = max(biz.last_alter_id or 0, batch.max_alter_id)
    biz.last_sync_at = clock.now(db)
    db.flush()

    fresh = [vid[v.guid] for v in batch.vouchers if v.guid not in existing]
    if publish:
        for v in batch.vouchers:
            events.publish(
                db,
                "voucher.posted",
                "voucher",
                vid[v.guid],
                source="tally_sync",
                type=v.vtype,
                number=v.number,
                amount=v.amount,
                party_id=party_id.get(v.party_guid),
            )
    return fresh


def _remove_voucher(db: Session, voucher_id: int) -> None:
    db.execute(delete(KbBillAllocation).where(KbBillAllocation.voucher_id == voucher_id))
    db.execute(delete(KbVoucherLine).where(KbVoucherLine.voucher_id == voucher_id))
    db.execute(delete(KbBill).where(KbBill.voucher_id == voucher_id))
    db.execute(delete(KbVoucher).where(KbVoucher.id == voucher_id))


def _recompute_pending(db: Session) -> None:
    paid = dict(
        db.execute(
            select(KbBillAllocation.bill_id, func.sum(KbBillAllocation.amount)).group_by(
                KbBillAllocation.bill_id
            )
        ).all()
    )
    for bill in db.scalars(select(KbBill)):
        pending = round(float(bill.amount) - float(paid.get(bill.id, 0) or 0), 2)
        if abs(pending - float(bill.pending_amount)) > 0.004:
            bill.pending_amount = pending
    db.flush()


def _roll_stock(db: Session, batch: TallyBatch, item_id: dict, godown_id: dict) -> None:
    """No closing stock in the batch: move today's balance by the new vouchers."""
    today = clock.today(db)
    latest = db.scalar(select(func.max(KbStockBalance.as_of)))
    if latest is None:
        return
    rows = {
        (s.item_id, s.godown_id): s
        for s in db.scalars(select(KbStockBalance).where(KbStockBalance.as_of == latest))
    }
    main = db.scalars(select(KbGodown).order_by(KbGodown.id)).first()
    moved = defaultdict(float)
    for v in batch.vouchers:
        sign = -1 if v.vtype == "sales" else 1 if v.vtype == "purchase" else 0
        for ln in v.lines:
            if sign and ln.item_guid in item_id:
                gid = godown_id.get(ln.godown_guid) if ln.godown_guid else (main.id if main else None)
                moved[(item_id[ln.item_guid], gid)] += sign * ln.qty
    for (iid, gid), q in moved.items():
        row = rows.get((iid, gid))
        if latest == today and row is not None:
            row.qty = max(0.0, float(row.qty) + q)
        else:
            base = float(row.qty) if row else 0.0
            item = db.get(KbItem, iid)
            db.add(
                KbStockBalance(
                    organisation_id=db.info["organisation_id"],
                    item_id=iid,
                    godown_id=gid,
                    as_of=today,
                    qty=max(0.0, base + q),
                    value=max(0.0, base + q) * float(item.standard_cost),
                )
            )
    db.flush()


def parties_by_id(parties: dict[str, KbParty]) -> dict[int, KbParty]:
    return {p.id: p for p in parties.values()}


def _chunks(rows: list, n: int):
    for i in range(0, len(rows), n):
        yield rows[i : i + n]


def members(db: Session) -> dict[str, list[int]]:
    """Users by desk role."""
    out: dict[str, list[int]] = defaultdict(list)
    for m in db.scalars(select(KbMember)):
        out[m.desk_role].append(m.user_id)
    return out
