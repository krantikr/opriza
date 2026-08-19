"""Delivery channels for notifications, behind one port.

Same shape as the email source and sender: an interface plus swappable
implementations, so the whole notification path is developable, testable and
demonstrable before any provider account exists. `LocalChannel` writes to disk
and is what runs until Twilio is configured - a demo cannot be derailed by a
network problem, and a test never sends a real message.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.models import NotificationChannel

logger = get_logger(__name__)


@dataclass(slots=True)
class DeliveryResult:
    sent: bool
    destination: str | None = None
    provider_message_id: str | None = None
    error: str | None = None


class Channel(ABC):
    """One way of reaching a person."""

    kind: NotificationChannel

    @abstractmethod
    def send(self, *, destination: str, title: str, body: str) -> DeliveryResult: ...

    @abstractmethod
    def describe(self) -> str: ...

    def is_available(self) -> bool:
        return True


class InAppChannel(Channel):
    """The dashboard bell. Delivery is the database row itself."""

    kind = NotificationChannel.IN_APP

    def send(self, *, destination: str, title: str, body: str) -> DeliveryResult:
        return DeliveryResult(sent=True, destination=destination or "dashboard")

    def describe(self) -> str:
        return "in-app"


class EmailChannel(Channel):
    """Reuses the existing email sender, so local mode still writes to disk."""

    kind = NotificationChannel.EMAIL

    def send(self, *, destination: str, title: str, body: str) -> DeliveryResult:
        from app.services.email.sender import build_reply, get_sender

        sender = get_sender()
        try:
            message = build_reply(to_address=destination, subject=title, body=body or title)
            result = sender.send(message)
        except Exception as exc:  # noqa: BLE001 - a failed notice must not break the pipeline
            logger.warning("Email notification failed: %s", exc)
            return DeliveryResult(sent=False, destination=destination, error=str(exc))
        return DeliveryResult(
            sent=result.sent,
            destination=result.destination or destination,
            provider_message_id=result.message_id,
            error=result.error,
        )

    def describe(self) -> str:
        from app.services.email.sender import get_sender

        return f"email via {get_sender().describe()}"


class LocalChannel(Channel):
    """Writes messages to `data/notifications/` instead of sending them.

    The default for WhatsApp and SMS until credentials are configured, so the
    rules, the queue and the UI are all exercisable without a Twilio account.
    """

    def __init__(self, kind: NotificationChannel) -> None:
        self.kind = kind
        self.directory = Path(settings.data_dir) / "notifications"

    def send(self, *, destination: str, title: str, body: str) -> DeliveryResult:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = self.directory / f"{stamp}-{self.kind.value.lower()}.json"
        path.write_text(
            json.dumps(
                {"channel": self.kind.value, "to": destination, "title": title, "body": body},
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("%s notification written to %s", self.kind.value, path)
        return DeliveryResult(sent=True, destination=destination, provider_message_id=path.name)

    def describe(self) -> str:
        return f"{self.kind.value.lower()} (local file)"


class TwilioChannel(Channel):
    """WhatsApp or SMS through Twilio.

    Imported lazily and failing soft: a notification that cannot be delivered
    is recorded as failed, never raised into the workflow that triggered it.
    Telling someone about an enquiry must not be able to stop the enquiry being
    processed.
    """

    def __init__(self, kind: NotificationChannel) -> None:
        self.kind = kind

    def is_available(self) -> bool:
        return bool(
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and self._from_number()
        )

    def _from_number(self) -> str | None:
        if self.kind is NotificationChannel.WHATSAPP:
            return settings.twilio_whatsapp_from
        return settings.twilio_sms_from

    def send(self, *, destination: str, title: str, body: str) -> DeliveryResult:
        if not self.is_available():
            return DeliveryResult(
                sent=False,
                destination=destination,
                error="Twilio is not configured (see TWILIO_* in .env).",
            )

        try:
            from twilio.rest import Client  # type: ignore[import-not-found]
        except ImportError:
            return DeliveryResult(
                sent=False,
                destination=destination,
                error="The twilio package is not installed.",
            )

        prefix = "whatsapp:" if self.kind is NotificationChannel.WHATSAPP else ""
        from_number = self._from_number() or ""
        try:
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            message = client.messages.create(
                from_=f"{prefix}{from_number}",
                to=f"{prefix}{destination}",
                body=f"{title}\n\n{body}" if body else title,
            )
        except Exception as exc:  # noqa: BLE001 - provider errors are recorded, not raised
            logger.warning("%s notification failed: %s", self.kind.value, exc)
            return DeliveryResult(sent=False, destination=destination, error=str(exc))

        return DeliveryResult(
            sent=True, destination=destination, provider_message_id=getattr(message, "sid", None)
        )

    def describe(self) -> str:
        return f"{self.kind.value.lower()} via Twilio" if self.is_available() else (
            f"{self.kind.value.lower()} (Twilio not configured)"
        )


def get_channel(kind: NotificationChannel) -> Channel:
    """The implementation currently in force for a channel."""
    if kind is NotificationChannel.IN_APP:
        return InAppChannel()
    if kind is NotificationChannel.EMAIL:
        return EmailChannel()

    provider = (settings.notification_provider or "local").lower()
    if provider == "twilio":
        channel = TwilioChannel(kind)
        if channel.is_available():
            return channel
        logger.warning("Twilio selected but not configured; falling back to local files.")
    return LocalChannel(kind)


__all__ = [
    "Channel",
    "DeliveryResult",
    "get_channel",
    "InAppChannel",
    "EmailChannel",
    "LocalChannel",
    "TwilioChannel",
]
