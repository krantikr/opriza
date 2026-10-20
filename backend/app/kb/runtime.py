"""The agent runtime: one LangGraph graph shape shared by all seven agents.

    main run:    gather -> decide -> check -> gate -> act_auto
    approval:    wait (interrupt) -> act          one thread per approval

* gather / check / gate / act are plain code, written once here or in the
  agent; decide is where the brain (rules or LLM) does its part.
* gate reads the owner's rules. Proposals inside them go straight to
  act_auto. Each proposal outside them becomes a row in Approvals and is
  parked on its own LangGraph thread, paused with `interrupt()` and
  checkpointed in Postgres (`PostgresSaver`), so it can wait hours or days.
* approving or rejecting in the app calls `decide_approval()`, which resumes
  that thread with `Command(resume=...)` and acts on exactly what was
  approved (including any change the owner made to the payload).

Each run is recorded in `kb_agent_runs` with its trigger, brain, LLM usage
and outcome. LLM calls are also written to the existing `llm_calls` table.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.kb import clock, events, rules
from app.kb.brain import Brain, get_brain
from app.kb.models import KbAgentRun, KbApproval, KbChatMessage, KbTask
from app.models import Organisation

logger = get_logger(__name__)

AGENT_LABELS = {
    "sales": "Sales & Quote",
    "collect": "Collections",
    "stock": "Stock & Purchase",
    "cash": "Cash",
    "brief": "Business Manager",
    "score": "Customer Score",
    "ask": "Ask Oprisa",
}


# ---------------------------------------------------------------------------
# What an agent sees while it runs
# ---------------------------------------------------------------------------


@dataclass
class Ctx:
    db: Session
    org: int
    brain: Brain
    run: KbAgentRun
    agent: str
    user_id: int | None = None
    _now: datetime | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def now(self) -> datetime:
        return self._now or clock.now(self.db)

    @property
    def today(self) -> date:
        return self.now.date()

    def rule(self, key: str, agent: str | None = None):
        return rules.get(self.db, agent or self.agent, key)

    @property
    def company(self) -> str:
        org = self.db.get(Organisation, self.org)
        return org.name if org else "us"

    @property
    def language(self) -> str:
        return str(rules.get(self.db, "collect", "language") or clock.business(self.db).language)


class Proposal(TypedDict, total=False):
    kind: str
    title: str
    payload: dict
    amount: float | None
    entity_type: str | None
    entity_id: int | None
    reason: str | None
    approval_id: int | None


class State(TypedDict, total=False):
    agent: str
    case: dict
    data: dict
    proposals: list
    auto: list
    pending: list
    results: list
    decisions: dict


# ---------------------------------------------------------------------------
# Shared helpers every agent uses
# ---------------------------------------------------------------------------


def post(
    ctx: Ctx,
    *,
    thread: str | None = None,
    text: str | None = None,
    card: dict | None = None,
    actions: list[dict] | None = None,
    chips: list[dict] | None = None,
    ref: dict | None = None,
    status: str | None = None,
    sender: str = "agent",
    user_id: int | None = None,
) -> KbChatMessage:
    """Post into an agent's chat thread (what the owner sees)."""
    msg = KbChatMessage(
        organisation_id=ctx.org,
        thread=thread or ctx.agent,
        sender=sender,
        at=ctx.now,
        text=text,
        card=card,
        actions=actions,
        chips=chips,
        ref=ref,
        status=status,
        user_id=user_id,
    )
    ctx.db.add(msg)
    ctx.db.flush()
    return msg


def task(
    ctx: Ctx,
    *,
    kind: str,
    title: str,
    role: str,
    detail: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    amount: float | None = None,
    priority: int = 2,
    dedupe: str | None = None,
    why: list[str] | None = None,
    agent: str | None = None,
) -> KbTask | None:
    """Add a line to someone's Inbox, once."""
    if dedupe:
        existing = ctx.db.scalars(
            select(KbTask).where(KbTask.dedupe_key == dedupe, KbTask.status == "open")
        ).first()
        if existing is not None:
            existing.amount = amount if amount is not None else existing.amount
            existing.detail = detail or existing.detail
            return None
    t = KbTask(
        organisation_id=ctx.org,
        agent=agent or ctx.agent,
        kind=kind,
        title=title,
        detail=detail,
        entity_type=entity_type,
        entity_id=entity_id,
        amount=amount,
        priority=priority,
        assignee_role=role,
        status="open",
        created_at=ctx.now,
        due_at=clock.at(ctx.today, 18),
        dedupe_key=dedupe,
        why=why,
    )
    ctx.db.add(t)
    ctx.db.flush()
    return t


def close_tasks(
    ctx: Ctx,
    *,
    kind: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    dedupe: str | None = None,
) -> int:
    q = select(KbTask).where(KbTask.status == "open")
    if kind:
        q = q.where(KbTask.kind == kind)
    if entity_type:
        q = q.where(KbTask.entity_type == entity_type)
    if entity_id is not None:
        q = q.where(KbTask.entity_id == entity_id)
    if dedupe:
        q = q.where(KbTask.dedupe_key == dedupe)
    n = 0
    for t in ctx.db.scalars(q):
        t.status = "done"
        t.done_at = ctx.now
        n += 1
    return n


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


def _agent(state: State):
    from app.kb.agents import AGENTS

    return AGENTS[state["agent"]]


def _ctx(config) -> Ctx:
    return config["configurable"]["ctx"]


def n_gather(state: State, config) -> dict:
    return {"data": _agent(state).gather(_ctx(config), state["case"]) or {}}


def n_decide(state: State, config) -> dict:
    return {
        "proposals": list(_agent(state).decide(_ctx(config), state["case"], state.get("data") or {}) or [])
    }


def n_check(state: State, config) -> dict:
    agent = _agent(state)
    ok = agent.check(_ctx(config), state.get("data") or {}, state.get("proposals") or [])
    return {"proposals": list(ok)}


def n_gate(state: State, config) -> dict:
    ctx = _ctx(config)
    agent = _agent(state)
    auto, pending = [], []
    thread_id = config["configurable"]["thread_id"]
    for p in state.get("proposals") or []:
        reason = agent.needs_approval(ctx, p)
        if not reason:
            auto.append(p)
            continue
        ap = KbApproval(
            organisation_id=ctx.org,
            agent=state["agent"],
            action_type=p["kind"],
            title=p["title"],
            reason=reason,
            amount=p.get("amount"),
            payload=_plain(p.get("payload") or {}),
            requested_by=ctx.user_id,
            requested_at=ctx.now,
            status="waiting",
            graph_thread_id=thread_id,
            entity_type=p.get("entity_type"),
            entity_id=p.get("entity_id"),
        )
        ctx.db.add(ap)
        ctx.db.flush()
        events.publish(
            ctx.db,
            "approval.requested",
            "approval",
            ap.id,
            source="agent",
            actor=state["agent"],
            reason=reason,
            title=p["title"],
        )
        pending.append({**p, "reason": reason, "approval_id": ap.id})
    return {"auto": auto, "pending": pending}


def n_act_auto(state: State, config) -> dict:
    ctx = _ctx(config)
    agent = _agent(state)
    results = [agent.act(ctx, p) or {} for p in state.get("auto") or []]
    # Tell the owner about anything waiting only after the automatic part is
    # done, so the chat reads in order. This node never re-runs on resume.
    for p in state.get("pending") or []:
        ap = ctx.db.get(KbApproval, p["approval_id"])
        if ap is not None:
            agent.on_approval_requested(ctx, p, ap)
    return {"results": results}


class ApprovalState(TypedDict, total=False):
    agent: str
    proposal: dict
    decision: dict
    result: dict


def a_wait(state: ApprovalState, config) -> dict:
    """Pause until the owner decides this one approval."""
    decision = interrupt({"approval_id": state["proposal"]["approval_id"]})
    return {"decision": decision}


def a_act(state: ApprovalState, config) -> dict:
    ctx = _ctx(config)
    agent = _agent(state)
    p = state["proposal"]
    ap = ctx.db.get(KbApproval, p["approval_id"])
    if ap is not None and ap.status == "approved":
        return {"result": agent.act(ctx, {**p, "payload": ap.payload or p.get("payload") or {}}) or {}}
    agent.on_rejected(ctx, p, ap)
    return {"result": {"rejected": p["title"]}}


def _build():
    """The main run: gather, decide, check, gate, act on what the rules allow."""
    g = StateGraph(State)
    for name, fn in (
        ("gather", n_gather),
        ("decide", n_decide),
        ("check", n_check),
        ("gate", n_gate),
        ("act_auto", n_act_auto),
    ):
        g.add_node(name, fn)
    g.add_edge(START, "gather")
    g.add_edge("gather", "decide")
    g.add_edge("decide", "check")
    g.add_edge("check", "gate")
    g.add_edge("gate", "act_auto")
    g.add_edge("act_auto", END)
    return g


def _build_approval():
    """One approval: wait (interrupt, checkpointed) -> act on the decision.

    Each approval gets its own thread, so approving one PO does not wait for
    the owner to decide an unrelated offer proposed in the same run.
    """
    g = StateGraph(ApprovalState)
    g.add_node("wait", a_wait)
    g.add_node("act", a_act)
    g.add_edge(START, "wait")
    g.add_edge("wait", "act")
    g.add_edge("act", END)
    return g


_graph_lock = threading.Lock()
_compiled: dict[str, Any] = {}


def _dsn(db: Session) -> str:
    url = db.get_bind().url
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def graph(db: Session):
    """The compiled graph with a Postgres checkpointer for this database."""
    dsn = _dsn(db)
    with _graph_lock:
        if dsn not in _compiled:
            import psycopg
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row

            conn = psycopg.connect(dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row)
            saver = PostgresSaver(conn)
            saver.setup()
            _compiled[dsn] = (
                _build().compile(checkpointer=saver),
                conn,
                _build_approval().compile(checkpointer=saver),
            )
        return _compiled[dsn][0]


def approval_graph(db: Session):
    graph(db)
    return _compiled[_dsn(db)][2]


def reset_graph_cache() -> None:
    with _graph_lock:
        for _, conn, _a in _compiled.values():
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        _compiled.clear()


# ---------------------------------------------------------------------------
# Running and resuming
# ---------------------------------------------------------------------------


def _record_usage(ctx: Ctx) -> None:
    u = ctx.brain.usage
    ctx.run.brain = ctx.brain.name
    ctx.run.llm_calls = u.calls
    ctx.run.tokens_in = u.tokens_in
    ctx.run.tokens_out = u.tokens_out
    ctx.run.cost_usd = round(u.cost_usd, 6)
    if u.records:
        from app.services.telemetry import record_call

        for rec in u.records:
            record_call(ctx.db, rec)
        u.records.clear()


def run_case(
    db: Session,
    agent: str,
    case: dict,
    *,
    trigger: str = "manual",
    ref: str | None = None,
    user_id: int | None = None,
    brain: Brain | None = None,
) -> dict:
    """Run one case through the graph. Returns {"status", "results", "approvals"}."""
    org = db.info["organisation_id"]
    run = KbAgentRun(
        organisation_id=org,
        agent=agent,
        trigger_type=trigger,
        trigger_ref=(ref or "")[:120],
        started_at=clock.now(db),
        status="running",
    )
    db.add(run)
    db.flush()
    ctx = Ctx(db=db, org=org, brain=brain or get_brain(), run=run, agent=agent, user_id=user_id)
    thread_id = f"{agent}:{org}:run{run.id}"
    run.graph_thread_id = thread_id
    config = {"configurable": {"thread_id": thread_id, "ctx": ctx}, "recursion_limit": 25}
    try:
        with db.begin_nested():
            out = graph(db).invoke({"agent": agent, "case": _plain(case)}, config)
    except Exception as exc:
        logger.exception("Agent %s failed on %s", agent, ref)
        run.status = "failed"
        run.error = str(exc)[:2000]
        run.finished_at = clock.now(db)
        _record_usage(ctx)
        db.flush()
        return {"status": "failed", "error": str(exc), "results": [], "approvals": []}
    waiting = []
    for p in out.get("pending") or []:
        waiting.append(_start_approval(db, agent, p, ctx))
    run.status = "ok"
    run.outcome = _plain(
        {
            "results": out.get("results") or [],
            "approvals": waiting,
            "proposals": len(out.get("proposals") or []),
            "notes": ctx.notes,
        }
    )
    run.finished_at = clock.now(db)
    _record_usage(ctx)
    db.flush()
    return {
        "status": "waiting_approval" if waiting else "ok",
        "results": out.get("results") or [],
        "approvals": waiting,
        "run_id": run.id,
    }


def _start_approval(db: Session, agent: str, proposal: dict, parent: Ctx) -> int:
    """Park one approval on its own LangGraph thread (it pauses at once)."""
    org = db.info["organisation_id"]
    ap = db.get(KbApproval, proposal["approval_id"])
    run = KbAgentRun(
        organisation_id=org,
        agent=agent,
        trigger_type="approval",
        trigger_ref=f"approval {ap.id}"[:120],
        started_at=clock.now(db),
        status="waiting_approval",
    )
    db.add(run)
    db.flush()
    thread_id = f"{agent}:{org}:approval{ap.id}"
    ap.graph_thread_id = thread_id
    run.graph_thread_id = thread_id
    ctx = Ctx(db=db, org=org, brain=parent.brain, run=run, agent=agent, user_id=parent.user_id)
    config = {"configurable": {"thread_id": thread_id, "ctx": ctx}, "recursion_limit": 10}
    approval_graph(db).invoke({"agent": agent, "proposal": _plain(proposal)}, config)
    db.flush()
    return ap.id


def decide_approval(
    db: Session,
    approval: KbApproval,
    approve: bool,
    user_id: int | None,
    payload: dict | None = None,
    note: str | None = None,
) -> dict:
    """Record the owner's decision and, once every approval of that run is
    decided, resume the paused run so it acts on what was approved."""
    if approval.status != "waiting":
        return {"status": approval.status, "resumed": False}
    approval.status = "approved" if approve else "rejected"
    approval.decided_by = user_id
    approval.decided_at = clock.now(db)
    approval.decision_note = note
    if payload is not None and approve:
        approval.payload = payload
    db.flush()
    events.publish(
        db,
        "approval.decided",
        "approval",
        approval.id,
        source="user",
        actor=str(user_id or ""),
        status=approval.status,
    )
    for m in db.scalars(select(KbChatMessage).where(KbChatMessage.ref.is_not(None))):
        if (m.ref or {}).get("approval_id") == approval.id and not m.chosen:
            m.chosen = "Approve" if approve else "Reject"
    if not approval.graph_thread_id:
        return {"status": approval.status, "resumed": False}
    return resume(
        db, approval.graph_thread_id, {"approval_id": approval.id, "status": approval.status}, user_id=user_id
    )


def resume(db: Session, thread_id: str, decisions: dict, *, user_id: int | None = None) -> dict:
    org = db.info["organisation_id"]
    run = db.scalars(select(KbAgentRun).where(KbAgentRun.graph_thread_id == thread_id)).first()
    agent = thread_id.split(":")[0]
    if run is None:
        run = KbAgentRun(
            organisation_id=org,
            agent=agent,
            trigger_type="manual",
            started_at=clock.now(db),
            status="running",
            graph_thread_id=thread_id,
        )
        db.add(run)
        db.flush()
    ctx = Ctx(db=db, org=org, brain=get_brain(), run=run, agent=agent, user_id=user_id)
    config = {"configurable": {"thread_id": thread_id, "ctx": ctx}, "recursion_limit": 25}
    g = approval_graph(db)
    state = g.get_state(config)
    if not state.next:
        return {"status": "done", "resumed": False}
    try:
        with db.begin_nested():
            out = g.invoke(Command(resume=decisions), config)
    except Exception as exc:
        logger.exception("Resuming %s failed", thread_id)
        run.status = "failed"
        run.error = str(exc)[:2000]
        db.flush()
        return {"status": "failed", "resumed": False, "error": str(exc)}
    run.status = "ok"
    run.finished_at = clock.now(db)
    run.outcome = _plain({**(run.outcome or {}), "after_approval": out.get("result") or {}})
    _record_usage(ctx)
    db.flush()
    return {"status": "ok", "resumed": True, "result": out.get("result") or {}}


def _plain(value):
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
