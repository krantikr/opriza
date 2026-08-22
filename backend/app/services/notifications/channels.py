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
    def send(
        self, *, destination: str, title: str, body: str, link: str | None = None
    ) -> DeliveryResult:
        """Deliver one message.

        `link` is where the notification should take the reader. Only push
        acts on it - a notification on a phone is tappable and has to land on
        the right screen - but it is part of the port so the service does not
        have to special-case one channel when dispatching.
        """

    @abstractmethod
    def describe(self) -> str: ...

    def is_available(self) -> bool:
        return True


class InAppChannel(Channel):
    """The dashboard bell. Delivery is the database row itself."""

    kind = NotificationChannel.IN_APP

    def send(
        self, *, destination: str, title: str, body: str, link: str | None = None
    ) -> DeliveryResult:
        return DeliveryResult(sent=True, destination=destination or "dashboard")

    def describe(self) -> str:
        return "in-app"


class EmailChannel(Channel):
    """Reuses the existing email sender, so local mode still writes to disk."""

    kind = NotificationChannel.EMAIL

    def send(
        self, *, destination: str, title: str, body: str, link: str | None = None
    ) -> DeliveryResult:
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

    def send(
        self, *, destination: str, title: str, body: str, link: str | None = None
    ) -> DeliveryResult:
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

    def send(
        self, *, destination: str, title: str, body: str, link: str | None = None
    ) -> DeliveryResult:
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


class FcmChannel(Channel):
    """System push via Firebase Cloud Messaging (HTTP v1).

    The only channel that reaches a trader with the site closed. The in-app
    bell needs the dashboard open and the browser Notification API needs the
    tab alive; a push goes to the operating system, which is the point.

    v1 rather than the deprecated legacy endpoint: legacy takes a static
    server key that Google has been switching off, v1 signs each request with
    a short-lived OAuth2 token minted from the service account. `google-auth`
    is already a dependency here (Gmail ingestion uses it), so this adds no
    new package.

    The credential is cached on the instance and refreshed by the library when
    it expires - minting a token per notification would add a round trip to
    Google before every single message.
    """

    kind = NotificationChannel.PUSH

    #: A token Firebase rejects for these reasons is dead for good: the app
    #: was uninstalled, or the registration was replaced. Anything else -
    #: a timeout, a 500, a quota - is transient and must not deactivate a
    #: device that is merely unreachable this minute.
    DEAD_TOKEN_ERRORS = frozenset(
        {"UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND", "SENDER_ID_MISMATCH"}
    )

    def __init__(self) -> None:
        self._credentials = None

    def is_available(self) -> bool:
        return settings.fcm_configured

    def describe(self) -> str:
        if not self.is_available():
            return "push (Firebase not configured)"
        return f"push via Firebase ({settings.fcm_project_id})"

    # -- credentials -------------------------------------------------------

    def _access_token(self) -> str:
        """A current OAuth2 token for the FCM scope."""
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        if self._credentials is None:
            self._credentials = service_account.Credentials.from_service_account_file(
                settings.fcm_credentials_file,
                scopes=["https://www.googleapis.com/auth/firebase.messaging"],
            )
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        return self._credentials.token

    # -- sending -----------------------------------------------------------

    def send(
        self,
        *,
        destination: str,
        title: str,
        body: str,
        link: str | None = None,
    ) -> DeliveryResult:
        """Deliver to one device token.

        Returns rather than raises on every provider failure, matching the
        other channels: a notification that cannot be delivered is recorded
        as failed and the workflow that triggered it carries on. Nobody
        should lose a quotation because a phone was unreachable.
        """
        if not self.is_available():
            return DeliveryResult(
                sent=False,
                destination=destination,
                error="Firebase is not configured (set FCM_PROJECT_ID and FCM_CREDENTIALS_FILE).",
            )
        if not destination:
            return DeliveryResult(sent=False, error="No device token.")

        import httpx

        payload = {
            "message": {
                "token": destination,
                # `notification` rather than a data-only message: the browser
                # and the OS render it themselves when the site is closed,
                # which a data-only message cannot do without the page alive.
                "notification": {"title": title, "body": body or ""},
                "webpush": {
                    "notification": {
                        "icon": "/favicon.svg",
                        "badge": "/favicon.svg",
                        # Collapse repeats of the same subject rather than
                        # stacking a column of near-identical buzzes.
                        "tag": link or "steel-desk",
                        "renotify": True,
                    },
                    # Where the notification takes them when tapped.
                    "fcm_options": {"link": link or "/"},
                },
                "android": {"priority": "high"},
                "apns": {"headers": {"apns-priority": "10"}},
            }
        }

        url = (
            f"https://fcm.googleapis.com/v1/projects/"
            f"{settings.fcm_project_id}/messages:send"
        )

        try:
            token = self._access_token()
            response = httpx.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
        except Exception as exc:  # noqa: BLE001 - provider errors are recorded, not raised
            logger.warning("Push notification failed: %s", exc)
            return DeliveryResult(sent=False, destination=destination, error=str(exc))

        if response.status_code == 200:
            return DeliveryResult(
                sent=True,
                destination=destination,
                provider_message_id=response.json().get("name"),
            )

        reason = _fcm_error(response)
        logger.warning("Push rejected (%s): %s", response.status_code, reason)
        return DeliveryResult(sent=False, destination=destination, error=reason)

    def is_dead_token(self, error: str | None) -> bool:
        """Whether this failure means the device is gone for good."""
        if not error:
            return False
        return any(code in error for code in self.DEAD_TOKEN_ERRORS)


def _fcm_error(response) -> str:
    """The provider's reason, in one line.

    FCM nests the useful code inside `error.details[].errorCode`; the top
    level `status` is often just INVALID_ARGUMENT. Both are kept so
    `is_dead_token` can match either.
    """
    try:
        error = response.json().get("error", {})
    except Exception:  # noqa: BLE001 - a non-JSON body is itself the diagnosis
        return f"HTTP {response.status_code}: {response.text[:200]}"

    parts = [error.get("status") or "", error.get("message") or ""]
    for detail in error.get("details") or []:
        code = detail.get("errorCode")
        if code:
            parts.append(code)
    return " · ".join(p for p in parts if p) or f"HTTP {response.status_code}"


def get_channel(kind: NotificationChannel) -> Channel:
    """The implementation currently in force for a channel."""
    if kind is NotificationChannel.IN_APP:
        return InAppChannel()
    if kind is NotificationChannel.EMAIL:
        return EmailChannel()
    if kind is NotificationChannel.PUSH:
        # Falls through to LocalChannel when Firebase is unconfigured, so the
        # whole push path stays exercisable before any project exists.
        channel = FcmChannel()
        return channel if channel.is_available() else LocalChannel(kind)

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
    "FcmChannel",
    "get_channel",
    "InAppChannel",
    "EmailChannel",
    "LocalChannel",
    "TwilioChannel",
]
