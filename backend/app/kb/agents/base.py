"""What every agent provides. See app.kb.runtime for how the steps are run."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import select

from app.kb import clock, events, links
from app.kb.channels import deliver, pick_channel
from app.kb.models import KbApproval, KbEvent, KbMessage, KbParty
from app.kb.runtime import Ctx, Proposal, post


class Agent:
    name = "base"
    label = "Agent"
    #: Scheduled jobs: name -> (hour, minute) in the business's time zone.
    jobs: dict[str, tuple[int, int]] = {}

    # ---- the graph steps (override what you need) --------------------------

    def gather(self, ctx: Ctx, case: dict) -> dict:
        return {}

    def decide(self, ctx: Ctx, case: dict, data: dict) -> list[Proposal]:
        return []

    def check(self, ctx: Ctx, data: dict, proposals: list[Proposal]) -> list[Proposal]:
        return proposals

    def needs_approval(self, ctx: Ctx, p: Proposal) -> str | None:
        """None when the owner's rules allow it, else the reason in plain words."""
        return None

    def act(self, ctx: Ctx, p: Proposal) -> dict:
        handler: Callable | None = getattr(self, f"do_{p['kind']}", None)
        if handler is None:
            raise ValueError(f"{self.name} cannot do {p['kind']}")
        return handler(ctx, p.get("payload") or {}) or {}

    def on_approval_requested(self, ctx: Ctx, p: Proposal, approval: KbApproval) -> None:
        post(
            ctx,
            card={
                "kind": "alert",
                "tone": "warn",
                "title": f"Needs your OK: {p['title']}",
                "body": approval.reason,
            },
            actions=[
                {"id": "approve", "label": "Approve", "primary": True},
                {"id": "reject", "label": "Reject"},
                {"id": "go-approvals", "label": "Open Approvals"},
            ],
            ref={"approval_id": approval.id},
        )

    def on_rejected(self, ctx: Ctx, p: Proposal, approval: KbApproval | None) -> None:
        post(ctx, text=f"Okay, I won't go ahead with: {p['title']}.")

    # ---- reacting --------------------------------------------------------

    def on_event(self, ctx_factory, event: KbEvent) -> None:
        """Called by the dispatcher. `ctx_factory(case, ref)` runs a case."""

    def on_chat_action(self, db, message, action: dict, user_id: int | None) -> str | None:
        """A tap on one of this agent's chat buttons. Returns a reply to post."""
        return None

    def run_job(self, db, job: str) -> list[dict]:
        """A scheduled job: returns the cases to run."""
        return [{"job": job}]


# ---------------------------------------------------------------------------
# Messages to customers and suppliers
# ---------------------------------------------------------------------------


def send_message(
    ctx: Ctx,
    party: KbParty,
    purpose: str,
    facts: dict,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    link_purpose: str | None = None,
    link_entity: tuple[str, int] | None = None,
) -> KbMessage:
    """Write (brain), store and deliver one message, with a secure link when asked."""
    facts = dict(facts)
    facts.setdefault("name", (party.contact_name or party.name).split()[0])
    facts.setdefault("company", ctx.company)
    if link_purpose:
        etype, eid = link_entity or (entity_type or "party", entity_id or party.id)
        _, url = links.create(ctx.db, link_purpose, party.id, etype, eid)
        facts["link"] = url
    language = ctx.language
    body = ctx.brain.write(purpose, facts, language)
    channel, address = pick_channel(party)
    msg = KbMessage(
        organisation_id=ctx.org,
        party_id=party.id,
        agent=ctx.agent,
        purpose=purpose,
        channel=channel,
        language=language,
        to_address=address,
        body=body,
        status="queued",
        created_at=ctx.now,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    ctx.db.add(msg)
    ctx.db.flush()
    deliver(msg, party, ctx.company)
    events.publish(
        ctx.db,
        "message.sent",
        "message",
        msg.id,
        source="agent",
        actor=ctx.agent,
        purpose=purpose,
        party_id=party.id,
    )
    return msg


def already_messaged(
    ctx: Ctx, purpose: str, entity_type: str, entity_id: int, since_days: int | None = None
) -> bool:
    q = select(KbMessage.id).where(
        KbMessage.purpose == purpose, KbMessage.entity_type == entity_type, KbMessage.entity_id == entity_id
    )
    if since_days is not None:
        q = q.where(KbMessage.created_at >= clock.at(ctx.today, 0) - timedelta(days=since_days))
    return ctx.db.scalars(q.limit(1)).first() is not None
