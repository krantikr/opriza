"""The Oprisa API end to end: sign in as a sample desk, use the screens, and
watch the agents react. Also: one desk can never see another's knowledge base."""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.core.db import Base, get_db
from app.core.tenancy import bind_session
from app.kb import runtime
from app.kb.models import KbMessage, KbParty, KbPromise
from app.kb.seed import SAMPLE_PASSWORD, email_for, seed_business
from app.main import app


@pytest.fixture(scope="module")
def api(engine):
    os.environ["AGENT_BRAIN"] = "rules"
    os.environ["AGENT_CHANNEL"] = "outbox"
    runtime.reset_graph_cache()
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    admin = Session()
    bind_session(admin, None, super_admin=True)
    names = ", ".join(f'"{t}"' for t in Base.metadata.tables)
    admin.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    admin.commit()
    orgs = {}
    for key in ("shree-balaji-steels", "patel-build-mart"):
        s = Session()
        bind_session(s, None, super_admin=True)
        orgs[key] = seed_business(s, key).id
        s.commit()
        s.close()
    admin.close()

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    yield client, Session, orgs
    app.dependency_overrides.pop(get_db, None)


def login(client, key, first="Kranti"):
    names = {
        "shree-balaji-steels": {"owner": "Kranti", "sales": "Pooja", "accounts": "Rohan"},
        "patel-build-mart": {"owner": "Nirav", "sales": "Hetal", "accounts": "Dhaval"},
    }
    who = names[key].get(first, first)
    r = client.post("/api/v1/auth/login", json={"email": email_for(who, key), "password": SAMPLE_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_every_screen_loads(api):
    client, _, _ = api
    h = login(client, "shree-balaji-steels", "owner")
    for path in (
        "me",
        "home",
        "inbox",
        "approvals",
        "sales",
        "collections",
        "customers",
        "stock",
        "cash",
        "reports",
        "agents",
        "chat",
        "outbox",
        "chat/brief",
    ):
        r = client.get(f"/api/v1/app/{path}", headers=h)
        assert r.status_code == 200, (path, r.text)
    me = client.get("/api/v1/app/me", headers=h).json()
    assert me["business"]["mock"] and me["user"]["desk_role"] == "owner" and me["brain"] == "rules"
    home = client.get("/api/v1/app/home", headers=h).json()
    assert home["approvals_waiting"] >= 5 and home["cash"]["short"] is not None


def test_desks_cannot_see_each_other(api):
    client, _, _ = api
    steel = login(client, "shree-balaji-steels", "owner")
    build = login(client, "patel-build-mart", "owner")
    steel_quotes = {q["id"] for q in client.get("/api/v1/app/sales", headers=steel).json()["quotes"]}
    build_quotes = {q["id"] for q in client.get("/api/v1/app/sales", headers=build).json()["quotes"]}
    assert steel_quotes and build_quotes and not steel_quotes & build_quotes
    some = next(iter(steel_quotes))
    assert client.get(f"/api/v1/app/quotes/{some}", headers=build).status_code == 404
    steel_appr = client.get("/api/v1/app/approvals", headers=steel).json()[0]["id"]
    assert (
        client.post(f"/api/v1/app/approvals/{steel_appr}", json={"approve": True}, headers=build).status_code
        == 400
    )


def test_only_the_owner_approves(api):
    client, _, _ = api
    sales = login(client, "shree-balaji-steels", "sales")
    ap = client.get("/api/v1/app/approvals", headers=sales).json()[0]["id"]
    assert (
        client.post(f"/api/v1/app/approvals/{ap}", json={"approve": True}, headers=sales).status_code == 403
    )


def test_enquiry_is_priced_and_sent_or_held(api):
    client, _, _ = api
    h = login(client, "patel-build-mart", "sales")
    cust = client.get("/api/v1/app/customers", headers=h).json()
    small = next(c for c in cust if c["grade"] == "A" and c["outstanding"] < (c["credit_limit"] or 0) * 0.5)
    r = client.post(
        "/api/v1/app/enquiries",
        headers=h,
        json={
            "party_id": small["party_id"],
            "text": "Please quote 200 bags OPC 53 Cement, delivery Bopal",
            "channel": "email",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["quote"] or out["approval_id"]
    if out["quote"]:
        q = client.get(f"/api/v1/app/quotes/{out['quote_id']}", headers=h).json()
        assert (
            q["status"] == "sent" and q["lines"][0]["item"] == "OPC 53 Cement" and q["lines"][0]["qty"] == 200
        )
        assert q["messages"] and "/l/" in q["messages"][0]["body"]


def test_approving_in_chat_resumes_the_agent(api):
    client, Session, orgs = api
    h = login(client, "shree-balaji-steels", "owner")
    stock = client.get("/api/v1/app/chat/stock", headers=h).json()["messages"]
    card = next(m for m in stock if (m.get("ref") or {}).get("approval_id") and not m.get("chosen"))
    r = client.post(
        f"/api/v1/app/chat/messages/{card['id']}/action", json={"action_id": "approve"}, headers=h
    )
    assert r.status_code == 200 and r.json()["resumed"], r.text
    after = client.get("/api/v1/app/chat/stock", headers=h).json()["messages"]
    assert any(
        (m.get("card") or {}).get("kind") == "po" or "Offer for" in (m.get("text") or "") for m in after
    )


def test_customer_link_accept_and_promise(api):
    client, Session, orgs = api
    db = Session()
    bind_session(db, orgs["shree-balaji-steels"])
    msgs = db.scalars(
        select(KbMessage)
        .where(KbMessage.purpose.in_(("quote", "nudge", "statement")))
        .order_by(KbMessage.id.desc())
    ).all()
    tokens = {}
    for m in msgs:
        if found := re.search(r"/l/(\S+)", m.body):
            tokens.setdefault(m.purpose if m.purpose != "nudge" else "quote", found.group(1))
    db.close()
    q = client.get(f"/api/v1/links/{tokens['quote']}")
    assert q.status_code == 200 and q.json()["purpose"] == "quote"
    assert (
        client.post(f"/api/v1/links/{tokens['quote']}", json={"action": "accept"}).json()["status"] == "won"
    )
    s = client.get(f"/api/v1/links/{tokens['statement']}").json()
    r = client.post(
        f"/api/v1/links/{tokens['statement']}",
        json={"action": "promise", "date": s["statement"]["dates"][2], "amount": 50000},
    )
    assert r.status_code == 200 and r.json()["promise_id"]
    assert client.get("/api/v1/links/not-a-real-token-123456").status_code == 404


def test_receipt_from_tally_keeps_a_promise(api):
    client, Session, orgs = api
    h = login(client, "shree-balaji-steels", "owner")
    db = Session()
    bind_session(db, orgs["shree-balaji-steels"])
    promise = db.scalars(select(KbPromise).where(KbPromise.status == "missed")).first()
    party = db.get(KbParty, promise.party_id)
    amount = float(promise.amount)
    db.close()
    r = client.post(
        "/api/v1/app/simulate", headers=h, json={"kind": "receipt", "party_id": party.id, "amount": amount}
    )
    assert r.status_code == 200, r.text
    db = Session()
    bind_session(db, orgs["shree-balaji-steels"])
    assert db.get(KbPromise, promise.id).status in ("kept", "part_kept")
    db.close()
    chat = client.get("/api/v1/app/chat/collect", headers=h).json()["messages"]
    assert any("received from" in (m.get("text") or "") for m in chat)


def test_ask_in_chat(api):
    client, _, _ = api
    h = login(client, "patel-build-mart", "owner")
    r = client.post("/api/v1/app/chat/ask", headers=h, json={"text": "Who owes me the most?"})
    last = r.json()["messages"][-1]
    assert last["from"] == "agent" and "owes the most" in last["text"]


def test_rules_change_and_validation(api):
    client, _, _ = api
    h = login(client, "patel-build-mart", "owner")
    assert (
        client.put("/api/v1/app/rules/sales/margin_floor_pct", json={"value": 4}, headers=h).json()["value"]
        == 4
    )
    assert (
        client.put("/api/v1/app/rules/sales/margin_floor_pct", json={"value": -1}, headers=h).status_code
        == 400
    )
    assert client.put("/api/v1/app/rules/sales/nope", json={"value": 1}, headers=h).status_code == 400
    sales = login(client, "patel-build-mart", "sales")
    assert (
        client.put("/api/v1/app/rules/sales/margin_floor_pct", json={"value": 1}, headers=sales).status_code
        == 403
    )
