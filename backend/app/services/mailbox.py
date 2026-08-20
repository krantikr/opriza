"""Connecting a desk's enquiry mailbox from the browser.

Previously this was `scripts/gmail_auth.py`, run in a terminal by whoever
deployed the system. That cannot work for a product: a trader onboarded this
morning has no terminal, and until a mailbox is connected the whole system
does nothing at all.

The flow is the standard OAuth authorisation-code exchange, with two details
that matter for a multi-tenant deployment:

* **The `state` parameter carries the organisation**, signed. Google hands it
  back on the callback, which is how a returning consent is attributed to the
  right desk. It is signed rather than a plain id because the callback is a
  public URL - anyone can invoke it with any value they like.
* **Only the refresh token is kept**, encrypted. Access tokens live an hour
  and are re-minted on use, so there is nothing worth storing.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import utcnow
from app.core.logging import get_logger
from app.core.security import encrypt_credential
from app.models import Mailbox, MailboxStatus

logger = get_logger(__name__)

#: Least privilege, unchanged from the original script: read mail and send
#: replies. Never modify or delete a customer's mailbox.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

#: The consent link is short-lived. It encodes which desk is connecting, so a
#: link left open in a tab overnight cannot attach a mailbox to a desk the
#: person has since stopped working for.
STATE_VALID_FOR = timedelta(minutes=30)


class MailboxError(RuntimeError):
    """Connecting failed, with a message safe to show a trader."""


def _client_config() -> dict:
    """Google's client id and secret - the same for every desk.

    These identify Steel Desk to Google. What differs per organisation is the
    refresh token, not the client.
    """
    import json

    path = settings.gmail_credentials_path
    if not path.exists():
        raise MailboxError(
            "Steel Desk is not set up to connect Google accounts yet. "
            "Ask your administrator to add the Google credentials file."
        )
    try:
        blob = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise MailboxError("The Google credentials file could not be read.") from exc

    client = blob.get("installed") or blob.get("web")
    if not client:
        raise MailboxError("The Google credentials file is not in a recognised format.")
    return client


def _sign_state(organisation_id: int) -> str:
    """A signed, expiring token naming the desk that started this flow."""
    import jwt

    now = utcnow()
    return jwt.encode(
        {"org": organisation_id, "iat": now, "exp": now + STATE_VALID_FOR},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def read_state(state: str) -> int:
    """The organisation a callback belongs to, or raise.

    The callback URL is public, so this value is never trusted as given - an
    unsigned or expired state means the flow did not start here.
    """
    import jwt

    try:
        payload = jwt.decode(
            state, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise MailboxError(
            "This connection link has expired. Start again from Settings."
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise MailboxError("This connection link is not valid.") from exc
    return int(payload["org"])


def check_redirect_registered(redirect_uri: str) -> str | None:
    """Whether Google will accept our callback, or a sentence saying what to fix.

    Google rejects a redirect it does not recognise with `redirect_uri_mismatch`
    on its own error page - after the trader has already clicked Connect and
    left the application. Catching it here turns a dead end into an
    instruction, and the instruction names the exact URI to paste.

    Returns None when everything is in order.
    """
    client = _client_config()
    registered = client.get("redirect_uris") or []

    if redirect_uri in registered:
        return None

    return (
        "Google has not been told to accept this address back. Add "
        f"{redirect_uri} to the authorised redirect URIs of the OAuth client "
        "in Google Cloud Console, using a client of type Web application."
    )


def consent_url(organisation_id: int, redirect_uri: str) -> str:
    """Where to send the trader to approve access to their mailbox."""
    from urllib.parse import urlencode

    client = _client_config()

    # Refused before the trader leaves rather than after: Google's own error
    # page tells them nothing they can act on.
    problem = check_redirect_registered(redirect_uri)
    if problem:
        raise MailboxError(problem)
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        # Without both of these Google returns no refresh token on a repeat
        # consent, and the mailbox silently stops working when the access
        # token expires an hour later.
        "access_type": "offline",
        "prompt": "consent",
        "state": _sign_state(organisation_id),
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def complete_connection(
    db: Session, *, organisation_id: int, code: str, redirect_uri: str
) -> Mailbox:
    """Exchange the code for a refresh token and store the mailbox.

    The address is read from Google rather than typed by the trader, so the
    stored mailbox is always the one that was actually authorised.
    """
    import requests

    client = _client_config()
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if not response.ok:
        logger.error("Google token exchange failed: %s", response.text[:400])
        detail = ""
        try:
            body = response.json()
            detail = body.get("error_description") or body.get("error") or ""
        except ValueError:
            pass
        raise MailboxError(
            f"Google did not accept the connection: {detail}"
            if detail
            else "Google did not accept the connection. Please try again."
        )

    payload = response.json()
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        # Happens when the user has consented before and `prompt=consent` was
        # not honoured. Without it the connection dies in an hour, so it is
        # refused now rather than appearing to work.
        raise MailboxError(
            "Google did not return a lasting connection. Remove Steel Desk "
            "from your Google account permissions and connect again."
        )

    address = _address_for(payload.get("access_token"))

    existing = db.scalars(
        select(Mailbox).where(Mailbox.email_address == address)
    ).first()
    mailbox = existing or Mailbox(
        organisation_id=organisation_id,
        provider="GMAIL",
        email_address=address,
    )
    mailbox.refresh_token_enc = encrypt_credential(refresh_token)
    mailbox.status = MailboxStatus.CONNECTED
    mailbox.last_error = None
    if existing is None:
        db.add(mailbox)
    db.commit()

    logger.info("Mailbox connected for org %s: %s", organisation_id, address)
    return mailbox


def _address_for(access_token: str | None) -> str:
    """Which mailbox was authorised, according to Google.

    Google's own message is passed through rather than replaced with a
    generic sentence. The two failures here have completely different fixes -
    the Gmail API not being enabled, versus a scope not being granted - and a
    message that cannot tell them apart leaves somebody guessing.
    """
    import requests

    if not access_token:
        raise MailboxError("Google did not return a usable connection.")

    response = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )

    if not response.ok:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = response.text[:200]
        logger.error(
            "Gmail profile lookup failed (%s): %s", response.status_code, detail
        )

        # The most common cause by far, and the one whose fix is a single
        # click, so it is named explicitly.
        if "has not been used in project" in detail or "is disabled" in detail:
            raise MailboxError(
                "The Gmail API is not enabled for this project. Enable it in "
                "Google Cloud Console (APIs & Services -> Library -> Gmail "
                "API), wait a minute, then connect again."
            )
        raise MailboxError(
            f"We could not read which mailbox was connected. Google said: {detail}"
            if detail
            else "We could not read which mailbox was connected."
        )

    address = response.json().get("emailAddress")
    if not address:
        raise MailboxError(
            "Google authorised the connection but did not say which mailbox "
            "it was. Try connecting again."
        )
    return address


def connect_local(db: Session, organisation_id: int) -> Mailbox:
    """Attach the sample mailbox, for trying the system without Google.

    Kept because a trader evaluating Steel Desk should be able to see it work
    before granting access to their real inbox.
    """
    existing = db.scalars(select(Mailbox).where(Mailbox.provider == "LOCAL")).first()
    if existing is not None:
        return existing

    mailbox = Mailbox(
        organisation_id=organisation_id,
        provider="LOCAL",
        email_address="sample@steeldesk.local",
        status=MailboxStatus.CONNECTED,
    )
    db.add(mailbox)
    db.commit()
    return mailbox


def disconnect(db: Session, mailbox: Mailbox) -> None:
    """Stop reading a mailbox and forget its credentials.

    The emails already ingested are kept: they are the desk's own records, and
    disconnecting a mailbox is not a request to delete its history.
    """
    mailbox.refresh_token_enc = None
    mailbox.status = MailboxStatus.DISCONNECTED
    mailbox.last_error = None
    db.commit()


__all__ = [
    "MailboxError",
    "complete_connection",
    "connect_local",
    "consent_url",
    "disconnect",
    "read_state",
]
