"""How a message reaches a customer or supplier.

Customers never install the app: they get a short message with a secure link.

    AGENT_CHANNEL=outbox   (default) nothing leaves the building. Each message is
                           stored as sent and written to data/sent/agents/ so you
                           can read exactly what would have gone out.
    AGENT_CHANNEL=live     email through the configured sender (Gmail or local
                           files, see EMAIL_SOURCE), SMS through SMS_WEBHOOK_URL.

To plug in a real SMS provider, set SMS_WEBHOOK_URL (and SMS_WEBHOOK_TOKEN):
we POST {"to": "+91...", "text": "..."} with a Bearer token. Most Indian
gateways (MSG91, Gupshup, Kaleyra) accept this shape or need a few lines in
`SmsWebhookChannel.send`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from email.message import EmailMessage

import httpx

from app.core.logging import get_logger
from app.core.paths import DATA_DIR
from app.kb.models import KbMessage, KbParty

logger = get_logger(__name__)


def channel_mode() -> str:
    import ai.config  # noqa: F401 - loads .env

    return (os.getenv("AGENT_CHANNEL") or "outbox").strip().lower()


def pick_channel(party: KbParty | None) -> tuple[str, str | None]:
    """Email when we have an address, otherwise SMS."""
    if party is None:
        return "shared", None
    if party.email:
        return "email", party.email
    if party.phone:
        return "sms", party.phone
    return "shared", None


def deliver(msg: KbMessage, party: KbParty | None, company: str) -> None:
    """Send one stored message and update its status. Never raises."""
    mode = channel_mode()
    try:
        if mode != "live" or msg.channel == "shared":
            _outbox(msg, party)
            msg.status = "sent"
        elif msg.channel == "email":
            _email(msg, party, company)
            msg.status = "sent"
        elif msg.channel == "sms":
            _sms(msg)
            msg.status = "sent"
        msg.sent_at = msg.sent_at or msg.created_at
    except Exception as exc:  # noqa: BLE001 - a failed send is recorded, not raised
        logger.warning("Message %s to %s failed: %s", msg.id, msg.to_address, exc)
        msg.status = "failed"
        msg.error = str(exc)[:500]


def _outbox(msg: KbMessage, party: KbParty | None) -> None:
    folder = DATA_DIR / "sent" / "agents"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    path = folder / f"{stamp}-{msg.agent}-{msg.purpose}.txt"
    path.write_text(
        f"To: {party.name if party else '-'} <{msg.to_address or '-'}> via {msg.channel}\n"
        f"Purpose: {msg.purpose}\n\n{msg.body}\n",
        encoding="utf-8",
    )


def _email(msg: KbMessage, party: KbParty | None, company: str) -> None:
    from app.services.email.sender import get_sender

    em = EmailMessage()
    em["To"] = msg.to_address
    em["Subject"] = {
        "reminder": f"Payment reminder from {company}",
        "statement": f"Your statement from {company}",
        "quote": f"Quotation from {company}",
        "nudge": f"Your quotation from {company}",
        "rfq": f"Rate request from {company}",
        "po": f"Purchase order from {company}",
        "offer": f"A special offer from {company}",
        "early_payment": f"A request from {company}",
    }.get(msg.purpose, f"Message from {company}")
    em.set_content(msg.body)
    result = get_sender().send(em)
    if not result.sent:
        raise RuntimeError(result.error or "email not sent")


def _sms(msg: KbMessage) -> None:
    url = os.getenv("SMS_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("SMS is not configured (set SMS_WEBHOOK_URL)")
    headers = {"Authorization": f"Bearer {os.getenv('SMS_WEBHOOK_TOKEN', '')}"}
    r = httpx.post(url, json={"to": msg.to_address, "text": msg.body}, headers=headers, timeout=15)
    r.raise_for_status()
