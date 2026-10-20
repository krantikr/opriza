"""The golden test: load each sample business, let the agents run their day,
and check they reach the result planted in `scenarios.json`.

Nothing in today's Inbox, Approvals or chat is copied from the generator:
every task and approval below was produced by an agent from the data. The
suite runs on the rules brain (no network); `test_llm_brain_*` covers the
model path with a fake client.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.tenancy import bind_session
from app.kb import runtime
from app.kb.agents.ask import answer
from app.kb.brain import RulesBrain
from app.kb.models import (
    KbApproval,
    KbCashWeek,
    KbChatMessage,
    KbCustomerProfile,
    KbItem,
    KbItemMetric,
    KbMessage,
    KbParty,
    KbPromise,
    KbPurchaseOrder,
    KbQuote,
    KbTask,
)
from app.kb.seed import seed_business
from app.kb.sources.mock import MockTallySource

KEYS = ["shree-balaji-steels", "patel-build-mart", "sai-pharma-distributors"]


@pytest.fixture(scope="module")
def desks(engine):
    """All three sample desks, seeded once for the module."""
    import os

    os.environ["AGENT_BRAIN"] = "rules"
    os.environ["AGENT_CHANNEL"] = "outbox"
    runtime.reset_graph_cache()
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    admin = Session()
    bind_session(admin, None, super_admin=True)
    names = ", ".join(f'"{t}"' for t in Base.metadata.tables)
    admin.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    admin.commit()
    out = {}
    for key in KEYS:
        s = Session()
        bind_session(s, None, super_admin=True)
        org = seed_business(s, key)
        s.commit()
        out[key] = org.id
        s.close()
    admin.close()
    yield Session, out


OPEN: list = []


@pytest.fixture(autouse=True)
def _close_sessions():
    """Close what `session_for` opened. Left open mid-transaction, they hold
    locks that the next module's TRUNCATE would wait on forever."""
    yield
    for s in OPEN:
        s.close()
    OPEN.clear()


def session_for(desks, key):
    Session, orgs = desks
    s = Session()
    bind_session(s, orgs[key])
    OPEN.append(s)
    return s


def scenarios(key):
    return {s["id"]: s for s in MockTallySource(key).scenarios()}


def party(db, name):
    return db.scalars(select(KbParty).where(KbParty.name == name)).one()


def item(db, name):
    return db.scalars(select(KbItem).where(KbItem.name == name)).one()


def approvals(db, action, status="waiting"):
    return list(
        db.scalars(select(KbApproval).where(KbApproval.action_type == action, KbApproval.status == status))
    )


@pytest.mark.parametrize("key", KEYS)
def test_cold_quote_is_nudged(desks, key):
    db = session_for(desks, key)
    exp = scenarios(key)["cold_quote"]["expect"]
    q = db.scalars(select(KbQuote).where(KbQuote.number == exp["quote"])).one()
    assert q.opened_at is None and q.nudged_at is not None
    assert (
        db.scalar(
            select(func.count())
            .select_from(KbMessage)
            .where(
                KbMessage.purpose == "nudge", KbMessage.entity_type == "quote", KbMessage.entity_id == q.id
            )
        )
        == 1
    )


@pytest.mark.parametrize("key", KEYS)
def test_below_margin_quote_waits_for_owner(desks, key):
    db = session_for(desks, key)
    exp = scenarios(key)["below_margin_quote"]["expect"]
    q = db.scalars(select(KbQuote).where(KbQuote.number == exp["quote"])).one()
    waiting = [a for a in approvals(db, "send_quote") if a.payload.get("quote_id") == q.id]
    assert len(waiting) == 1 and "below your" in waiting[0].reason
    assert q.sent_at is None


@pytest.mark.parametrize("key", KEYS)
def test_missed_promise_goes_to_the_top_of_calls(desks, key):
    db = session_for(desks, key)
    exp = scenarios(key)["missed_promise"]["expect"]
    p = party(db, exp["party"])
    promises = db.scalars(
        select(KbPromise).where(KbPromise.party_id == p.id, KbPromise.status == "missed")
    ).all()
    assert promises
    tasks = db.scalars(
        select(KbTask).where(
            KbTask.kind == "missed_promise",
            KbTask.status == "open",
            KbTask.entity_id.in_([x.id for x in promises]),
        )
    ).all()
    assert tasks and tasks[0].priority == 1


@pytest.mark.parametrize("key", KEYS)
def test_stock_out_gets_a_po_at_the_best_rate(desks, key):
    db = session_for(desks, key)
    sc = scenarios(key)
    exp, rate = sc["stock_out"]["expect"], sc["rate_drop"]["expect"]
    it = item(db, exp["item"])
    m = db.scalars(select(KbItemMetric).where(KbItemMetric.item_id == it.id)).one()
    assert m.status == "reorder" and m.days_left < exp["days_left_below"]
    pos = [a for a in approvals(db, "place_po") if a.payload["item_id"] == it.id]
    sent = db.scalars(
        select(KbPurchaseOrder).where(KbPurchaseOrder.status == "sent", KbPurchaseOrder.rfq_id.is_not(None))
    ).all()
    assert pos or sent
    if pos:
        pl = pos[0].payload
        assert party(db, exp["best_supplier"]).id == pl["supplier_id"]
        assert pl["rate"] == pytest.approx(rate["rate"], abs=0.01)
        assert pl["saving_pct"] == pytest.approx(3.0, abs=0.1)
        assert pl["total"] > exp["needs_approval_above"]


@pytest.mark.parametrize("key", KEYS)
def test_slipping_customer_gets_a_win_back_call(desks, key):
    db = session_for(desks, key)
    exp = scenarios(key)["slipping_customer"]["expect"]
    p = party(db, exp["party"])
    prof = db.scalars(select(KbCustomerProfile).where(KbCustomerProfile.party_id == p.id)).one()
    assert prof.trend == "down"
    assert (
        db.scalars(select(KbTask).where(KbTask.kind == "win_back", KbTask.entity_id == p.id)).first()
        is not None
    )


@pytest.mark.parametrize("key", KEYS)
def test_grade_drop_proposes_a_lower_limit(desks, key):
    db = session_for(desks, key)
    exp = scenarios(key)["grade_drop"]["expect"]
    p = party(db, exp["party"])
    prof = db.scalars(select(KbCustomerProfile).where(KbCustomerProfile.party_id == p.id)).one()
    assert (prof.previous_grade, prof.grade) == (exp["previous_grade"], exp["grade"])
    waiting = [a for a in approvals(db, "change_credit_limit") if a.payload["party_id"] == p.id]
    assert len(waiting) == 1 and waiting[0].payload["new_limit"] < waiting[0].payload["old_limit"]


@pytest.mark.parametrize("key", KEYS)
def test_idle_stock_is_offered_to_past_buyers(desks, key):
    db = session_for(desks, key)
    exp = scenarios(key)["idle_stock"]["expect"]
    it = item(db, exp["item"])
    assert db.scalars(select(KbItemMetric).where(KbItemMetric.item_id == it.id)).one().status == "idle"
    offer = [a for a in approvals(db, "send_offer") if a.payload["item_id"] == it.id]
    assert len(offer) == 1
    buyers = {db.get(KbParty, pid).name for pid in offer[0].payload["to"]}
    assert buyers == set(exp["past_buyers"])


@pytest.mark.parametrize("key", KEYS)
def test_cash_gap_is_caught_three_weeks_out(desks, key):
    db = session_for(desks, key)
    exp = scenarios(key)["cash_gap"]["expect"]
    weeks = db.scalars(select(KbCashWeek).order_by(KbCashWeek.week_start)).all()
    first_short = next(w for w in weeks if w.closing_balance < 0)
    assert str(first_short.week_start) == exp["short_week_start"]
    assert (
        db.scalars(select(KbTask).where(KbTask.kind == "cash_gap", KbTask.status == "open")).first()
        is not None
    )
    ask = approvals(db, "ask_early_payment")
    assert len(ask) == 1
    assert ask[0].payload["delay"]["name"] == exp["big_payment"]


@pytest.mark.parametrize("key", KEYS)
def test_duplicate_ledger_is_flagged(desks, key):
    db = session_for(desks, key)
    exp = scenarios(key)["duplicate_ledger"]["expect"]
    dup = party(db, exp["duplicate"])
    assert db.scalars(
        select(KbTask).where(KbTask.kind == "duplicate_ledger", KbTask.entity_id == dup.id)
    ).first()


@pytest.mark.parametrize("key", KEYS)
def test_ask_answers_match_the_books(desks, key):
    db = session_for(desks, key)
    brain = RulesBrain()
    for sid, s in scenarios(key).items():
        if not sid.startswith("ask_"):
            continue
        out = answer(db, s["title"], brain)
        r, e = out["result"], s["expect"]
        if "party" in e:
            assert r.get("party") == e["party"], (sid, out["tool"], r)
        if "amount" in e:
            assert r["amount"] == pytest.approx(e["amount"], rel=0.01, abs=1), (sid, out["tool"])
        if "items" in e:
            assert r["items"] == e["items"], sid
        if "rate" in e:
            assert r["rate"] == pytest.approx(e["rate"], abs=0.01) and str(r["date"]) == e["date"], sid
        if "count" in e:
            assert r["count"] == e["count"], sid


@pytest.mark.parametrize("key", KEYS)
def test_every_agent_ran_and_the_brief_went_out(desks, key):
    db = session_for(desks, key)
    from app.kb.models import KbAgentRun

    runs = db.scalars(select(KbAgentRun)).all()
    assert {r.agent for r in runs} >= {"sales", "collect", "stock", "cash", "score", "brief"}
    assert not [r for r in runs if r.status == "failed"], [
        (r.agent, r.error) for r in runs if r.status == "failed"
    ]
    brief = db.scalars(select(KbChatMessage).where(KbChatMessage.thread == "brief")).all()
    assert brief and brief[-1].card["kind"] == "brief"


def test_approving_a_po_resumes_the_paused_run(desks):
    db = session_for(desks, "shree-balaji-steels")
    ap = approvals(db, "place_po")[0]
    sup = ap.payload["supplier_id"]
    out = runtime.decide_approval(db, ap, True, None)
    db.commit()
    assert out["resumed"] and out["status"] == "ok"
    po = db.scalars(
        select(KbPurchaseOrder)
        .where(KbPurchaseOrder.supplier_id == sup, KbPurchaseOrder.status == "sent")
        .order_by(KbPurchaseOrder.id.desc())
    ).first()
    assert po is not None and float(po.total) == pytest.approx(ap.payload["total"])
    assert db.scalars(
        select(KbMessage).where(KbMessage.purpose == "po", KbMessage.entity_id == po.id)
    ).first()


def test_rejecting_a_quote_sends_it_back_for_repricing(desks):
    db = session_for(desks, "patel-build-mart")
    ap = next(a for a in approvals(db, "send_quote") if a.payload.get("quote_id"))
    runtime.decide_approval(db, ap, False, None, note="Too low")
    db.commit()
    q = db.get(KbQuote, ap.payload["quote_id"])
    assert q.status == "draft" and q.sent_at is None
    assert db.scalars(select(KbTask).where(KbTask.kind == "review_quote", KbTask.entity_id == q.id)).first()
