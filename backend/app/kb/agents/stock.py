"""Stock & Purchase: don't run out, don't sit on stock nobody buys.

Daily it checks every item's days of stock (from the facts). An item below
the reorder line with no purchase order open gets rate requests to the usual
suppliers; once rates are in, it drafts the PO with the best one. A PO above
the owner's limit waits for approval. Stock with no sale for months is
offered to the customers who bought it before, at a price the owner OKs.
"""

# ruff: noqa: E501 - customer-facing message text and prompts are kept whole, one sentence per line.

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select

from app.kb import events, fmt
from app.kb.agents.base import Agent, send_message
from app.kb.models import (
    KbApproval,
    KbItem,
    KbItemMetric,
    KbParty,
    KbPoLine,
    KbPricePoint,
    KbPurchaseOrder,
    KbRfq,
    KbSupplierQuote,
    KbTallyPosting,
    KbVoucher,
    KbVoucherLine,
)
from app.kb.runtime import Ctx, Proposal, close_tasks, post, task

OPEN_PO = ("draft", "pending_approval", "sent")


def round_qty(q: float, unit: str) -> float:
    if unit == "MT":
        return round(q, 1) if q < 10 else float(round(q))
    step = 50 if q >= 500 else 10 if q >= 50 else 1
    return float(max(step, round(q / step) * step))


class StockAgent(Agent):
    name = "stock"
    label = "Stock & Purchase"
    jobs = {"stock_daily": (10, 15)}

    # ---------------------------------------------------------------- gather

    def gather(self, ctx: Ctx, case: dict) -> dict:
        db = ctx.db
        if "voucher_id" in case:
            v = db.get(KbVoucher, case["voucher_id"])
            items = db.scalars(select(KbVoucherLine.item_id).where(KbVoucherLine.voucher_id == v.id)).all()
            pos = db.scalars(
                select(KbPurchaseOrder).where(
                    KbPurchaseOrder.supplier_id == v.party_id, KbPurchaseOrder.status == "sent"
                )
            ).all()
            match = [
                po.id
                for po in pos
                if set(db.scalars(select(KbPoLine.item_id).where(KbPoLine.po_id == po.id))) & set(items)
            ]
            return {"voucher_id": v.id, "pos": match}
        metrics = db.scalars(select(KbItemMetric)).all()
        items = {i.id: i for i in db.scalars(select(KbItem))}
        on_order = set()
        for po in db.scalars(select(KbPurchaseOrder).where(KbPurchaseOrder.status.in_(OPEN_PO))):
            on_order |= set(db.scalars(select(KbPoLine.item_id).where(KbPoLine.po_id == po.id)))
        rfqs = {}
        for r in db.scalars(select(KbRfq).where(KbRfq.status == "open")):
            quotes = db.scalars(select(KbSupplierQuote).where(KbSupplierQuote.rfq_id == r.id)).all()
            rfqs[str(r.item_id)] = {
                "rfq_id": r.id,
                "qty": float(r.qty),
                "created": r.created_at,
                "quotes": [
                    {
                        "supplier_id": q.supplier_id,
                        "rate": float(q.rate),
                        "days": q.delivery_days,
                        "valid": q.valid_until,
                    }
                    for q in quotes
                ],
            }
        waiting_offers = {
            str((a.payload or {}).get("item_id"))
            for a in db.scalars(
                select(KbApproval).where(
                    KbApproval.action_type == "send_offer", KbApproval.status == "waiting"
                )
            )
        }
        offered = {
            str((a.payload or {}).get("item_id"))
            for a in db.scalars(
                select(KbApproval).where(
                    KbApproval.action_type == "send_offer",
                    KbApproval.requested_at >= ctx.now - timedelta(days=30),
                )
            )
        }
        # Usual suppliers: who we bought each item from, most recent first.
        bought = defaultdict(list)
        for pp in db.scalars(
            select(KbPricePoint).where(KbPricePoint.source == "purchase").order_by(KbPricePoint.date.desc())
        ):
            if pp.party_id and pp.party_id not in bought[pp.item_id]:
                bought[pp.item_id].append(pp.party_id)
        last_buy = {}
        for pp in db.scalars(
            select(KbPricePoint).where(KbPricePoint.source == "purchase").order_by(KbPricePoint.date)
        ):
            last_buy[pp.item_id] = float(pp.rate)
        suppliers = [p.id for p in db.scalars(select(KbParty).where(KbParty.kind == "supplier"))]
        target = case.get("item_id")
        out = []
        for m in metrics:
            if target and m.item_id != target:
                continue
            it = items[m.item_id]
            out.append(
                {
                    "item_id": m.item_id,
                    "name": it.name,
                    "unit": it.unit,
                    "status": m.status,
                    "days_left": m.days_left,
                    "per_day": float(m.per_day),
                    "stock": float(m.stock_qty),
                    "value": float(m.stock_value),
                    "idle_days": m.idle_days,
                    "reorder_qty": float(m.reorder_qty or 0),
                    "on_order": m.item_id in on_order,
                    "rfq": rfqs.get(str(m.item_id)),
                    "suppliers": (bought.get(m.item_id) or suppliers)[:6],
                    "last_buy": last_buy.get(m.item_id),
                    "cost": float(it.standard_cost),
                    "list": float(it.standard_rate),
                    "gst": float(it.gst_rate),
                    "offer_waiting": str(m.item_id) in waiting_offers or str(m.item_id) in offered,
                }
            )
        return {"items": out}

    # ---------------------------------------------------------------- decide

    def decide(self, ctx: Ctx, case: dict, data: dict) -> list[Proposal]:
        if "voucher_id" in case:
            return [
                {"kind": "receive_po", "title": "PO received", "payload": {"po_id": pid}}
                for pid in data["pos"]
            ]
        out: list[Proposal] = []
        rfq_n = int(ctx.rule("rfq_suppliers"))
        for it in data["items"]:
            if it["status"] == "reorder" and not it["on_order"]:
                qty = round_qty(max(it["per_day"] * 30 - it["stock"], it["per_day"] * 7), it["unit"])
                rfq = it["rfq"]
                ready = (
                    rfq
                    and rfq["quotes"]
                    and (len(rfq["quotes"]) >= 2 or ctx.now - rfq["created"] > timedelta(days=1))
                )
                if ready:
                    best = min(rfq["quotes"], key=lambda q: (q["rate"], q["days"]))
                    # Enough for 30 days on top of what's left, at least a week's worth.
                    q_qty = round_qty(max(it["per_day"] * 30 - it["stock"], it["per_day"] * 7), it["unit"])
                    total = round(q_qty * best["rate"] * (1 + it["gst"] / 100), 2)
                    saving = (
                        round((it["last_buy"] - best["rate"]) / it["last_buy"] * 100, 1)
                        if it["last_buy"]
                        else None
                    )
                    out.append(
                        {
                            "kind": "place_po",
                            "title": f"PO for {fmt.qty(q_qty, it['unit'])} {it['name']}",
                            "amount": total,
                            "entity_type": "item",
                            "entity_id": it["item_id"],
                            "payload": {
                                "item_id": it["item_id"],
                                "supplier_id": best["supplier_id"],
                                "rate": best["rate"],
                                "qty": q_qty,
                                "total": total,
                                "rfq_id": rfq["rfq_id"],
                                "last_purchase_rate": it["last_buy"],
                                "saving_pct": saving,
                                "days_left": it["days_left"],
                                "quotes": rfq["quotes"],
                            },
                        }
                    )
                elif not rfq:
                    out.append(
                        {
                            "kind": "send_rfq",
                            "title": f"Ask {rfq_n} suppliers for {it['name']} rates",
                            "entity_type": "item",
                            "entity_id": it["item_id"],
                            "payload": {
                                "item_id": it["item_id"],
                                "qty": qty,
                                "supplier_ids": it["suppliers"][:rfq_n],
                                "days_left": it["days_left"],
                            },
                        }
                    )
            elif it["status"] == "idle" and it["stock"] > 0 and not it["offer_waiting"]:
                buyers = self._past_buyers(ctx, it["item_id"])
                if not buyers:
                    continue
                cost = it["last_buy"] or it["cost"]
                price = float(round(it["list"] * 0.95))
                out.append(
                    {
                        "kind": "send_offer",
                        "title": f"Offer {it['name']} to {len(buyers)} past buyers",
                        "amount": it["value"],
                        "entity_type": "item",
                        "entity_id": it["item_id"],
                        "payload": {
                            "item_id": it["item_id"],
                            "price": price,
                            "list": it["list"],
                            "cost": cost,
                            "qty": it["stock"],
                            "to": buyers,
                            "idle_days": it["idle_days"],
                            "value": it["value"],
                        },
                    }
                )
        return out

    def _past_buyers(self, ctx: Ctx, item_id: int) -> list[int]:
        rows = (
            ctx.db.execute(
                select(KbVoucher.party_id)
                .join(KbVoucherLine, KbVoucherLine.voucher_id == KbVoucher.id)
                .where(KbVoucherLine.item_id == item_id, KbVoucher.voucher_type == "sales")
            )
            .scalars()
            .all()
        )
        return sorted({r for r in rows if r})

    # ------------------------------------------------------------------ gate

    def needs_approval(self, ctx: Ctx, p: Proposal) -> str | None:
        if p["kind"] == "place_po":
            limit = float(ctx.rule("po_limit"))
            if p["payload"]["total"] > limit:
                return f"PO of {fmt.inr(p['payload']['total'])} is above your {fmt.inr(limit)} limit"
        if p["kind"] == "send_offer":
            pl = p["payload"]
            return (
                f"Offer at {fmt.rate(pl['price'])}, 5% below your list price {fmt.rate(pl['list'])}"
                f" (cost {fmt.rate(pl['cost'])}), to clear stock idle for {pl['idle_days']} days"
            )
        return None

    def on_approval_requested(self, ctx: Ctx, p: Proposal, approval) -> None:
        if p["kind"] == "place_po":
            pl = p["payload"]
            item = ctx.db.get(KbItem, pl["item_id"])
            names = {
                s.id: s
                for s in ctx.db.scalars(
                    select(KbParty).where(KbParty.id.in_([q["supplier_id"] for q in pl["quotes"]]))
                )
            }
            post(
                ctx,
                text=f"**{item.name}** has {pl['days_left']} days of stock left. Rates came in; "
                f"the best is {fmt.rate(pl['rate'])}/{item.unit}"
                + (f", {pl['saving_pct']}% below our last buy." if pl.get("saving_pct") else "."),
                card={
                    "kind": "rates",
                    "product": item.name,
                    "qty": pl["qty"],
                    "unit": item.unit,
                    "rows": [
                        {
                            "supplier": names[q["supplier_id"]].name,
                            "brand": names[q["supplier_id"]].brand or "",
                            "rate": q["rate"],
                            "days": q["days"],
                            "onTime": 0,
                            "best": q["supplier_id"] == pl["supplier_id"],
                        }
                        for q in sorted(pl["quotes"], key=lambda x: x["rate"])
                    ],
                    "note": approval.reason,
                },
                actions=[
                    {"id": "approve", "label": f"Place PO ({fmt.inr(pl['total'])})", "primary": True},
                    {"id": "reject", "label": "Not now"},
                ],
                ref={"approval_id": approval.id},
            )
            return
        super().on_approval_requested(ctx, p, approval)

    # ------------------------------------------------------------------- act

    def do_send_rfq(self, ctx: Ctx, pl: dict) -> dict:
        item = ctx.db.get(KbItem, pl["item_id"])
        rfq = KbRfq(
            organisation_id=ctx.org, item_id=item.id, qty=pl["qty"], created_at=ctx.now, status="open"
        )
        ctx.db.add(rfq)
        ctx.db.flush()
        names = []
        from app.kb import clock

        city = clock.business(ctx.db).city or ""
        for sid in pl["supplier_ids"]:
            sup = ctx.db.get(KbParty, sid)
            send_message(
                ctx,
                sup,
                "rfq",
                {"qty": fmt.qty(pl["qty"], item.unit), "item": item.name, "city": city},
                entity_type="rfq",
                entity_id=rfq.id,
                link_purpose="rfq",
                link_entity=("rfq", rfq.id),
            )
            names.append(sup.name)
        post(
            ctx,
            text=f"**{item.name}** is down to {pl['days_left']} days of stock. I've asked {', '.join(names)} "
            f"for rates on {fmt.qty(pl['qty'], item.unit)}; I'll bring you the best one.",
        )
        return {"rfq": rfq.id}

    def do_place_po(self, ctx: Ctx, pl: dict) -> dict:
        db = ctx.db
        item = db.get(KbItem, pl["item_id"])
        sup = db.get(KbParty, pl["supplier_id"])
        nums = [
            int(n.split("-")[-1])
            for n in db.scalars(select(KbPurchaseOrder.number))
            if n.split("-")[-1].isdigit()
        ]
        po = KbPurchaseOrder(
            organisation_id=ctx.org,
            number=f"PO-{(max(nums) + 1) if nums else 1:04d}",
            supplier_id=sup.id,
            status="sent",
            created_at=ctx.now,
            total=pl["total"],
            rfq_id=pl.get("rfq_id"),
        )
        db.add(po)
        db.flush()
        db.add(
            KbPoLine(organisation_id=ctx.org, po_id=po.id, item_id=item.id, qty=pl["qty"], rate=pl["rate"])
        )
        if pl.get("rfq_id"):
            rfq = db.get(KbRfq, pl["rfq_id"])
            if rfq:
                rfq.status = "closed"
        send_message(
            ctx,
            sup,
            "po",
            {
                "po_no": po.number,
                "qty": fmt.qty(pl["qty"], item.unit),
                "item": item.name,
                "rate": fmt.rate(pl["rate"]),
                "unit": item.unit,
                "total": fmt.inr(pl["total"], short=False),
            },
            entity_type="purchase_order",
            entity_id=po.id,
            link_purpose="po",
            link_entity=("purchase_order", po.id),
        )
        db.add(
            KbTallyPosting(
                organisation_id=ctx.org,
                kind="purchase_order",
                entity_type="purchase_order",
                entity_id=po.id,
                payload={
                    "po": po.number,
                    "supplier": sup.name,
                    "item": item.name,
                    "qty": pl["qty"],
                    "rate": pl["rate"],
                },
                created_at=ctx.now,
            )
        )
        events.publish(
            db,
            "po.sent",
            "purchase_order",
            po.id,
            source="agent",
            actor=self.name,
            number=po.number,
            total=pl["total"],
            supplier_id=sup.id,
        )
        close_tasks(ctx, kind="reorder", entity_type="item", entity_id=item.id)
        post(
            ctx,
            card={
                "kind": "po",
                "no": po.number,
                "supplier": sup.name,
                "product": item.name,
                "qty": pl["qty"],
                "unit": item.unit,
                "rate": pl["rate"],
                "status": "posted",
            },
            text=f"PO {po.number} sent to {sup.name}.",
        )
        return {"po": po.number, "supplier": sup.name, "rate": pl["rate"], "total": pl["total"]}

    def do_send_offer(self, ctx: Ctx, pl: dict) -> dict:
        item = ctx.db.get(KbItem, pl["item_id"])
        n = 0
        for pid in pl["to"]:
            party = ctx.db.get(KbParty, pid)
            if not party:
                continue
            send_message(
                ctx,
                party,
                "offer",
                {
                    "item": item.name,
                    "rate": fmt.rate(pl["price"]),
                    "unit": item.unit,
                    "list_rate": fmt.rate(pl["list"]),
                    "qty": fmt.qty(pl["qty"], item.unit),
                    "valid": fmt.day(ctx.today + timedelta(days=7)),
                },
                entity_type="item",
                entity_id=item.id,
                link_purpose="offer",
                link_entity=("item", item.id),
            )
            n += 1
        post(
            ctx,
            text=f"Offer for **{item.name}** sent to {n} past buyers at {fmt.rate(pl['price'])}/{item.unit}.",
        )
        return {"offers": n}

    def do_receive_po(self, ctx: Ctx, pl: dict) -> dict:
        po = ctx.db.get(KbPurchaseOrder, pl["po_id"])
        if po and po.status == "sent":
            po.status = "received"
            events.publish(
                ctx.db,
                "po.received",
                "purchase_order",
                po.id,
                source="tally_sync",
                actor=self.name,
                number=po.number,
            )
        return {"received": pl["po_id"]}

    def on_rejected(self, ctx: Ctx, p: Proposal, approval) -> None:
        if p["kind"] == "place_po":
            item = ctx.db.get(KbItem, p["payload"]["item_id"])
            task(
                ctx,
                kind="reorder",
                title=f"Reorder {item.name}",
                role="purchase",
                detail=f"{p['payload']['days_left']} days of stock left. You held the PO back; decide the order yourself.",
                entity_type="item",
                entity_id=item.id,
                amount=p["payload"]["total"],
                priority=1,
                dedupe=f"reorder:{item.id}",
            )
        super().on_rejected(ctx, p, approval)

    # ---------------------------------------------------------------- events

    def on_event(self, run, event) -> None:
        p = event.payload or {}
        if event.type == "supplier_quote.received" and p.get("item_id"):
            run({"item_id": int(p["item_id"])}, f"rate from supplier {p.get('supplier_id')}")
        elif event.type == "voucher.posted" and p.get("type") == "purchase":
            run({"voucher_id": event.entity_id}, f"purchase {p.get('number')}")
