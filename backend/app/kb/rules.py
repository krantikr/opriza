"""The owner's rules: what each agent may do without asking.

Defaults live here; a desk's own values live in `kb_agent_rules` and are
edited on the Agents & rules screen. `gate()` in app.kb.runtime reads these
and nothing else to decide whether an action goes out or waits in Approvals.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.kb import clock
from app.kb.models import KbAgentRule


@dataclass(frozen=True)
class Rule:
    agent: str
    key: str
    default: object
    label: str
    kind: str  # number | percent | money | bool | time | text | choice
    help: str = ""
    choices: tuple[str, ...] = ()


RULES: tuple[Rule, ...] = (
    Rule(
        "sales",
        "margin_floor_pct",
        3.0,
        "Lowest margin I accept",
        "percent",
        "A quote below this waits for your approval.",
    ),
    Rule(
        "sales",
        "max_discount_pct",
        1.5,
        "Most discount off the customer's last rate",
        "percent",
        "Deeper discounts wait for your approval.",
    ),
    Rule("sales", "auto_send_in_band", True, "Send quotes inside these limits without asking", "bool"),
    Rule("sales", "nudge_after_hours", 24, "Nudge an unopened quote after", "number", "Hours."),
    Rule(
        "sales", "check_credit_limit", True, "Ask before quoting a customer over their credit limit", "bool"
    ),
    Rule("collect", "remind_days_before_due", 3, "Remind customers before the due date", "number", "Days."),
    Rule("collect", "language", "English", "Message language", "choice", choices=("English", "Hinglish")),
    Rule("collect", "statement_every_days", 7, "Send overdue customers a statement every", "number", "Days."),
    Rule("collect", "quiet_hours", "21:00-09:00", "Never message customers between", "text"),
    Rule("collect", "call_list_size", 8, "Calls on today's list", "number"),
    Rule("stock", "reorder_days", 12, "Reorder when stock covers fewer days than", "number"),
    Rule("stock", "rfq_suppliers", 3, "Ask this many suppliers for rates", "number"),
    Rule("stock", "po_limit", 4500000, "Send POs up to this amount without asking", "money"),
    Rule("stock", "idle_days", 60, "Call stock idle after no sale for", "number", "Days."),
    Rule("cash", "horizon_weeks", 4, "Forecast this many weeks", "number"),
    Rule("cash", "alert_weeks_ahead", 3, "Warn me this many weeks before cash runs short", "number"),
    Rule("cash", "min_balance", 0, "Keep at least this much in the bank", "money"),
    Rule("brief", "send_at", "08:00", "Morning brief at", "time"),
    Rule("brief", "weekly_report", False, "Also send a weekly report on Monday", "bool"),
    Rule("score", "ask_before_lowering_limit", True, "Ask me before lowering a credit limit", "bool"),
    Rule("score", "raise_limit_alone", False, "Raise credit limits for A customers without asking", "bool"),
    Rule("ask", "read_only", True, "Ask Oprisa only reads; actions go to the agent that owns them", "bool"),
)

_BY_KEY = {(r.agent, r.key): r for r in RULES}


def get(db: Session, agent: str, key: str):
    row = db.scalars(select(KbAgentRule).where(KbAgentRule.agent == agent, KbAgentRule.key == key)).first()
    if row is not None:
        return row.value
    rule = _BY_KEY.get((agent, key))
    if rule is None:
        raise KeyError(f"No rule {agent}.{key}")
    return rule.default


def all_rules(db: Session) -> list[dict]:
    stored = {(r.agent, r.key): r for r in db.scalars(select(KbAgentRule))}
    out = []
    for r in RULES:
        row = stored.get((r.agent, r.key))
        out.append(
            {
                "agent": r.agent,
                "key": r.key,
                "label": r.label,
                "kind": r.kind,
                "help": r.help,
                "choices": list(r.choices),
                "value": row.value if row else r.default,
                "default": r.default,
                "updated_at": row.updated_at if row else None,
            }
        )
    return out


def set_rule(db: Session, agent: str, key: str, value, user_id: int | None) -> None:
    rule = _BY_KEY.get((agent, key))
    if rule is None:
        raise KeyError(f"No rule {agent}.{key}")
    if rule.kind in ("number", "percent", "money"):
        value = float(value)
        if value < 0:
            raise ValueError("Must not be negative")
    elif rule.kind == "bool":
        value = bool(value)
    elif rule.kind == "choice" and value not in rule.choices:
        raise ValueError(f"Choose one of {', '.join(rule.choices)}")
    row = db.scalars(select(KbAgentRule).where(KbAgentRule.agent == agent, KbAgentRule.key == key)).first()
    if row is None:
        row = KbAgentRule(agent=agent, key=key, value=value)
        db.add(row)
    row.value = value
    row.updated_by = user_id
    row.updated_at = clock.now(db)
    db.flush()


def in_quiet_hours(db: Session) -> bool:
    spec = str(get(db, "collect", "quiet_hours"))
    try:
        start, end = spec.split("-")
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except ValueError:
        return False
    t = clock.now(db)
    minutes = t.hour * 60 + t.minute
    a, b = sh * 60 + sm, eh * 60 + em
    return (minutes >= a or minutes < b) if a > b else a <= minutes < b
