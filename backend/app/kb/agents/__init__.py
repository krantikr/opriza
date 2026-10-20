"""The seven agents. Each reads the shared knowledge base, reacts to events,
and proposes actions that the runtime gates against the owner's rules."""

from app.kb.agents.ask import AskAgent
from app.kb.agents.brief import BriefAgent
from app.kb.agents.cash import CashAgent
from app.kb.agents.collect import CollectAgent
from app.kb.agents.sales import SalesAgent
from app.kb.agents.score import ScoreAgent
from app.kb.agents.stock import StockAgent

AGENTS = {
    a.name: a
    for a in (SalesAgent(), CollectAgent(), StockAgent(), CashAgent(), BriefAgent(), ScoreAgent(), AskAgent())
}

__all__ = ["AGENTS"]
