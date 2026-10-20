"""The Oprisa product API: the desk screens, the agent chat and approvals.

Every route runs on a session bound to the caller's desk (`TenantDb`), so
row-level security keeps each business's knowledge base to itself. Reads come
from `app.kb.views`; changes go through `app.kb.actions`, which hands the
resulting events to the agents before responding.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, MemberUser, TenantDb
from app.kb import actions, jobs, rules, sync, views
from app.kb.actions import ActionError
from app.kb.agents import AGENTS
from app.kb.models import KbBusiness

router = APIRouter(prefix="/app", tags=["oprisa"])


def _desk(db: TenantDb) -> KbBusiness:
    biz = db.scalars(select(KbBusiness)).first()
    if biz is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This account has no Oprisa desk yet. Load or connect one first."
        )
    return biz


Desk = Annotated[KbBusiness, Depends(_desk)]


def _fail(exc: ActionError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# ------------------------------------------------------------------ reads


@router.get("/me")
def me(user: CurrentUser, db: TenantDb) -> dict:
    return views.me(db, user)


@router.get("/home")
def home(_: Desk, db: TenantDb, role: str = "owner") -> dict:
    return views.home(db, role)


@router.get("/inbox")
def inbox(
    _: Desk, db: TenantDb, role: str | None = None, status_: str = Query("open", alias="status")
) -> dict:
    return {"tasks": views.inbox(db, role, status=status_), "approvals": views.approvals(db, "waiting")}


@router.get("/approvals")
def approvals(_: Desk, db: TenantDb, status_: str = Query("waiting", alias="status")) -> list[dict]:
    return views.approvals(db, status_)


@router.get("/sales")
def sales(_: Desk, db: TenantDb) -> dict:
    return views.sales(db)


@router.get("/quotes/{quote_id}")
def quote(quote_id: int, _: Desk, db: TenantDb) -> dict:
    out = views.quote(db, quote_id)
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quote not found")
    out["links"] = views.link_status(db, "quote", quote_id)
    return out


@router.get("/collections")
def collections(_: Desk, db: TenantDb) -> dict:
    return views.collections(db)


@router.get("/customers")
def customers(_: Desk, db: TenantDb, q: str | None = None, grade: str | None = None) -> list[dict]:
    return views.customers(db, q, grade)


@router.get("/customers/{party_id}")
def customer(party_id: int, _: Desk, db: TenantDb) -> dict:
    out = views.customer(db, party_id)
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return out


@router.get("/stock")
def stock(_: Desk, db: TenantDb) -> dict:
    return views.stock(db)


@router.get("/items/{item_id}")
def item(item_id: int, _: Desk, db: TenantDb) -> dict:
    out = views.item_detail(db, item_id)
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return out


@router.get("/cash")
def cash(_: Desk, db: TenantDb) -> dict:
    return views.cash(db)


@router.get("/reports")
def reports(_: Desk, db: TenantDb) -> dict:
    return views.reports(db)


@router.get("/agents")
def agents(_: Desk, db: TenantDb) -> dict:
    return views.agents(db)


@router.get("/outbox")
def outbox(_: Desk, db: TenantDb) -> list[dict]:
    return views.outbox(db)


@router.get("/search")
def search(_: Desk, db: TenantDb, q: str = Query(min_length=1)) -> dict:
    return views.search(db, q)


@router.get("/chat")
def chat_threads(_: Desk, db: TenantDb) -> list[dict]:
    return views.chat_threads(db)


@router.get("/chat/{thread}")
def chat_thread(thread: str, _: Desk, db: TenantDb, user: CurrentUser) -> dict:
    if thread not in views.THREADS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such chat")
    msgs = views.chat_messages(db, thread)
    actions.mark_read(db, thread)
    db.commit()
    return {"thread": thread, "messages": msgs}


# ----------------------------------------------------------------- changes


class EnquiryIn(BaseModel):
    party_id: int | None = None
    text: str = Field(min_length=3, max_length=4000)
    channel: str = Field("whatsapp_paste", pattern="^(email|whatsapp_paste|phone_note|chat|link)$")


@router.post("/enquiries")
def new_enquiry(body: EnquiryIn, _: Desk, db: TenantDb, user: MemberUser) -> dict:
    try:
        out = actions.new_enquiry(
            db, party_id=body.party_id, text=body.text, channel=body.channel, user_id=user.id
        )
    except ActionError as exc:
        raise _fail(exc) from exc
    db.commit()
    return out


class QuoteEdit(BaseModel):
    rates: dict[int, float]


@router.post("/quotes/{quote_id}/rates")
def edit_quote(quote_id: int, body: QuoteEdit, _: Desk, db: TenantDb, user: MemberUser) -> dict:
    try:
        out = actions.edit_quote(db, quote_id, body.rates, user_id=user.id)
    except ActionError as exc:
        raise _fail(exc) from exc
    db.commit()
    return out


class QuoteOutcome(BaseModel):
    outcome: str = Field(pattern="^(won|lost)$")
    reason: str | None = Field(None, max_length=200)


@router.post("/quotes/{quote_id}/outcome")
def quote_outcome(quote_id: int, body: QuoteOutcome, _: Desk, db: TenantDb, user: MemberUser) -> dict:
    try:
        out = actions.mark_quote(db, quote_id, body.outcome, body.reason, user.id)
    except ActionError as exc:
        raise _fail(exc) from exc
    db.commit()
    return out


class PartyIds(BaseModel):
    party_ids: list[int] = Field(min_length=1, max_length=200)


@router.post("/collections/remind")
def remind(body: PartyIds, _: Desk, db: TenantDb, user: MemberUser) -> dict:
    out = actions.remind(db, body.party_ids, user.id)
    db.commit()
    return out


@router.post("/customers/{party_id}/statement")
def statement(party_id: int, _: Desk, db: TenantDb, user: MemberUser) -> dict:
    out = actions.statement(db, party_id, user.id)
    db.commit()
    return out


class PromiseIn(BaseModel):
    party_id: int
    amount: float = Field(gt=0)
    due_date: date
    source: str = Field("call", pattern="^(call|chat|link)$")


@router.post("/promises")
def promise(body: PromiseIn, _: Desk, db: TenantDb, user: MemberUser) -> dict:
    try:
        out = actions.log_promise(db, body.party_id, body.amount, body.due_date, body.source, user.id)
    except ActionError as exc:
        raise _fail(exc) from exc
    db.commit()
    return out


class TaskUpdate(BaseModel):
    status: str = Field(pattern="^(open|done|dismissed|snoozed)$")


@router.post("/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate, _: Desk, db: TenantDb, user: MemberUser) -> dict:
    try:
        out = actions.update_task(db, task_id, body.status)
    except ActionError as exc:
        raise _fail(exc) from exc
    db.commit()
    return out


class Decision(BaseModel):
    approve: bool
    note: str | None = Field(None, max_length=500)
    payload: dict[str, Any] | None = None


@router.post("/approvals/{approval_id}")
def decide(approval_id: int, body: Decision, _: Desk, db: TenantDb, user: AdminUser) -> dict:
    try:
        out = actions.decide(db, approval_id, body.approve, user.id, note=body.note, payload=body.payload)
    except ActionError as exc:
        raise _fail(exc) from exc
    db.commit()
    return out


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.post("/chat/{thread}")
def chat_send(thread: str, body: ChatIn, _: Desk, db: TenantDb, user: CurrentUser) -> dict:
    if thread not in views.THREADS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such chat")
    try:
        actions.chat_send(db, thread, body.text, user.id)
    except ActionError as exc:
        raise _fail(exc) from exc
    db.commit()
    return {"thread": thread, "messages": views.chat_messages(db, thread)}


class ChatAction(BaseModel):
    action_id: str = Field(min_length=1, max_length=60)


@router.post("/chat/messages/{message_id}/action")
def chat_action(message_id: int, body: ChatAction, _: Desk, db: TenantDb, user: CurrentUser) -> dict:
    try:
        out = actions.chat_action(db, message_id, body.action_id, user.id, bool(user.can_administer))
    except ActionError as exc:
        raise _fail(exc) from exc
    db.commit()
    return out


class RuleIn(BaseModel):
    value: Any


@router.put("/rules/{agent}/{key}")
def set_rule(agent: str, key: str, body: RuleIn, _: Desk, db: TenantDb, user: AdminUser) -> dict:
    try:
        rules.set_rule(db, agent, key, body.value, user.id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return {"agent": agent, "key": key, "value": rules.get(db, agent, key)}


@router.post("/agents/{agent}/run")
def run_agent(agent: str, _: Desk, db: TenantDb, user: MemberUser) -> dict:
    if agent not in AGENTS or not AGENTS[agent].jobs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such agent job")
    job = next(iter(AGENTS[agent].jobs))
    results = jobs.run_job(db, agent, job, trigger="manual", user_id=user.id)
    jobs.dispatch_events(db)
    db.commit()
    return {
        "agent": agent,
        "job": job,
        "runs": len(results),
        "approvals": sum(len(r.get("approvals") or []) for r in results),
    }


@router.post("/tick")
def tick(_: Desk, db: TenantDb, user: MemberUser) -> dict:
    out = jobs.tick(db)
    db.commit()
    return out


@router.post("/sync")
def run_sync(_: Desk, db: TenantDb, user: MemberUser) -> dict:
    run = sync.run_sync(db)
    jobs.dispatch_events(db)
    db.commit()
    return {"status": run.status, "objects": run.objects_read, "error": run.error}


class SimIn(BaseModel):
    kind: str = Field(pattern="^(receipt|enquiry|advance|supplier_rate)$")
    party_id: int | None = None
    amount: float | None = None
    text: str | None = None
    hours: float | None = None
    rate: float | None = None


@router.post("/simulate")
def simulate(body: SimIn, _: Desk, db: TenantDb, user: MemberUser) -> dict:
    try:
        out = actions.simulate(db, body.kind, body.model_dump(exclude_none=True))
    except (ActionError, KeyError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return out


class LinkIn(BaseModel):
    purpose: str = Field(pattern="^(quote|statement)$")
    entity_type: str = Field(pattern="^(quote|party)$")
    entity_id: int


@router.post("/links")
def make_link(body: LinkIn, _: Desk, db: TenantDb, user: MemberUser) -> dict:
    try:
        url = actions.link_for(db, body.purpose, body.entity_type, body.entity_id)
    except ActionError as exc:
        raise _fail(exc) from exc
    db.commit()
    return {"url": url}
