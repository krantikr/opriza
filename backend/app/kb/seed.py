"""Load a sample business onto a desk: books, team and a month of history.

    uv run python scripts/oprisa_seed.py            # all three sample businesses

Steps for one desk:
  1. organisation, sign-in users for the team, their desk roles
  2. `kb_business` pointing at the mock source, clock frozen at the data's today
  3. a Tally sync from the mock source (the same code path a live desk uses)
  4. the month of work history (enquiries, quotes, promises, supplier rates...)
  5. facts, then one full agent cycle builds today's Inbox, approvals and chat

Step 5 is the proof the agents work: nothing in today's Inbox is copied from
the generator; every task and approval is produced by an agent from the data.
"""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import hash_password
from app.core.tenancy import bind_session
from app.kb import clock, facts, rules, sync
from app.kb.models import (
    KbBusiness,
    KbDocument,
    KbDocumentChunk,
    KbEnquiry,
    KbItem,
    KbItemAlias,
    KbMember,
    KbMemory,
    KbMessage,
    KbParty,
    KbPoLine,
    KbPromise,
    KbPurchaseOrder,
    KbQuote,
    KbQuoteLine,
    KbRfq,
    KbShareLink,
    KbSupplierQuote,
    KbVoucher,
)
from app.kb.sources.mock import MOCK_TODAY, MockTallySource
from app.models import Organisation, User, UserRole

logger = get_logger(__name__)

#: Every sample user signs in with this password. Development data only.
SAMPLE_PASSWORD = "oprisa-demo-1"


def email_for(name: str, slug: str) -> str:
    return f"{name.split()[0].lower()}@{slug}.demo"


def seed_business(db: Session, key: str, *, run_agents: bool = True) -> Organisation:
    """Create (or rebuild) one sample desk. `db` must be a super-admin session."""
    source = MockTallySource(key)
    info = source.business
    org = db.scalars(select(Organisation).where(Organisation.slug == key)).first()
    if org is not None:
        db.delete(org)  # cascades to every kb_* row and the users
        db.flush()
    org = Organisation(slug=key, name=info["name"], timezone="Asia/Kolkata")
    db.add(org)
    db.flush()

    bind_session(db, org.id)
    users = {}
    for person in source.team():
        role = UserRole.OWNER if person["role"] == "owner" else UserRole.MEMBER
        u = User(
            organisation_id=org.id,
            name=person["name"],
            email=email_for(person["name"], key),
            password_hash=hash_password(SAMPLE_PASSWORD),
            role=role,
        )
        db.add(u)
        db.flush()
        db.add(
            KbMember(organisation_id=org.id, user_id=u.id, desk_role=person["role"], phone=person["phone"])
        )
        users[person["name"]] = u
    as_of = datetime.combine(MOCK_TODAY, time(10, 30), tzinfo=clock.IST)
    db.add(
        KbBusiness(
            organisation_id=org.id,
            trade=info["trade"],
            city=info["city"],
            language=info["language"],
            tally_version=info["tally_version"],
            source="mock",
            mock_key=key,
            as_of=as_of,
        )
    )
    db.flush()

    run = sync.run_sync(db, source, refresh_facts=False)
    if run.status != "ok":
        raise RuntimeError(f"Mock sync failed: {run.error}")
    load_history(db, source, users)
    facts.refresh(db, kpi_history=True)
    db.flush()
    if run_agents:
        from app.kb.jobs import first_run

        first_run(db)
    logger.info("Seeded %s", info["name"])
    return org


def load_history(db: Session, source: MockTallySource, users: dict[str, User]) -> dict:
    """The month of work before today, remapped from generator ids to ours."""
    org = db.info["organisation_id"]
    h = source.history()
    party_guid = {p["id"]: p["tally_guid"] for p in h["_parties"]}
    item_guid = {i["id"]: i["tally_guid"] for i in h["_items"]}
    voucher_guid = {v["id"]: v["tally_guid"] for v in h["_vouchers"]}
    user_name = {u["id"]: u["name"] for u in h["_users"]}
    parties = {p.tally_guid: p.id for p in db.scalars(select(KbParty))}
    items = {i.tally_guid: i.id for i in db.scalars(select(KbItem))}
    vouchers = dict(db.execute(select(KbVoucher.tally_guid, KbVoucher.id)).all())

    def P(gen_id):  # noqa: N802
        return parties.get(party_guid.get(gen_id)) if gen_id else None

    def I(gen_id):  # noqa: N802, E743
        return items.get(item_guid.get(gen_id)) if gen_id else None

    def U(gen_id):  # noqa: N802
        u = users.get(user_name.get(gen_id, ""))
        return u.id if u else None

    def V(gen_id):  # noqa: N802
        return vouchers.get(voucher_guid.get(gen_id)) if gen_id else None

    today = clock.today(db)
    ids: dict[str, dict[int, int]] = {}

    def add(table: str, model, rows, **mapping):
        out = {}
        for r in rows:
            data = {
                k: v
                for k, v in r.items()
                if k not in ("id", "organisation_id") and k in model.__table__.columns
            }
            for col, fn in mapping.items():
                if col in data:
                    data[col] = fn(r[col])
            obj = model(organisation_id=org, **data)
            db.add(obj)
            db.flush()
            out[r["id"]] = obj.id
        ids[table] = out
        return out

    enquiries = add("enquiries", KbEnquiry, h["enquiries"], party_id=P, assigned_to=U)
    quotes = add(
        "quotes",
        KbQuote,
        h["quotes"],
        party_id=P,
        owner_id=U,
        sales_voucher_id=V,
        enquiry_id=lambda x: enquiries.get(x),
    )
    add("quote_lines", KbQuoteLine, h["quote_lines"], quote_id=lambda x: quotes[x], item_id=I)

    # Promises the agents have not looked at yet: anything past due stays
    # "open" so the Collections agent is the one that finds it missed.
    promise_rows = [dict(p, status="open") if p["status"] == "missed" else p for p in h["promises"]]
    add("promises", KbPromise, promise_rows, party_id=P)

    bill_key = {b["id"]: (party_guid[b["party_id"]], b["bill_ref"]) for b in source.rows("bills")}
    from app.kb.models import KbBill

    db_bills = {(b.party_id, b.bill_ref): b.id for b in db.scalars(select(KbBill))}

    def B(gen_id):  # noqa: N802
        guid, ref = bill_key.get(gen_id, (None, None))
        return db_bills.get((parties.get(guid), ref))

    entity_map = {"quote": lambda x: quotes.get(x), "party": P, "bill": B}

    def remap(row: dict) -> dict:
        fn = entity_map.get(row["entity_type"]) if row.get("entity_type") else None
        return dict(row, entity_id=fn(row["entity_id"]) if fn else None)

    add("messages", KbMessage, [remap(m) for m in h["messages"]], party_id=P)
    links = [remap(link) for link in h["share_links"]]
    add("share_links", KbShareLink, [r for r in links if r["entity_id"]], party_id=P)
    rfqs = add("rfqs", KbRfq, h["rfqs"], item_id=I)
    add(
        "supplier_quotes",
        KbSupplierQuote,
        h["supplier_quotes"],
        rfq_id=lambda x: rfqs.get(x),
        supplier_id=P,
        item_id=I,
    )
    pos = add("purchase_orders", KbPurchaseOrder, h["purchase_orders"], supplier_id=P, purchase_voucher_id=V)
    add("po_lines", KbPoLine, h["po_lines"], po_id=lambda x: pos[x], item_id=I)

    known = {(r["agent"], r["key"]) for r in rules.all_rules(db)}
    for r in h["agent_rules"]:
        if (r["agent"], r["key"]) in known:
            rules.set_rule(db, r["agent"], r["key"], r["value"], None)

    have_alias = set(db.scalars(select(KbItemAlias.alias)))
    for a in h["item_aliases"]:
        if a["alias"] not in have_alias and I(a["item_id"]):
            have_alias.add(a["alias"])
            db.add(
                KbItemAlias(
                    organisation_id=org,
                    item_id=I(a["item_id"]),
                    alias=a["alias"],
                    source=a["source"],
                    hits=a["hits"],
                )
            )

    scope_fn = {"party": P, "item": I, "user": U, "org": lambda x: None}
    for m in h["memories"]:
        data = {
            k: v
            for k, v in m.items()
            if k in KbMemory.__table__.columns and k not in ("id", "organisation_id")
        }
        data["scope_id"] = scope_fn[m["scope_type"]](m["scope_id"])
        db.add(KbMemory(organisation_id=org, **data))
    docs = add("documents", KbDocument, h["documents"], party_id=P)
    add("document_chunks", KbDocumentChunk, h["document_chunks"], document_id=lambda x: docs[x])
    db.flush()
    logger.info("History loaded for org %s up to %s", org, today)
    return ids
