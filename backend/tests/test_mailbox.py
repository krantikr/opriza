"""Connecting a desk's mailbox from the browser.

The `state` parameter is the security-relevant part: the OAuth callback is a
public URL, so what it claims about which organisation is connecting has to be
something the server signed. Most of these tests are about that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Mailbox, MailboxStatus, Organisation
from app.services.mailbox import (
    MailboxError,
    connect_local,
    consent_url,
    disconnect,
    read_state,
)


@pytest.fixture()
def desk(db, default_org) -> Organisation:
    return db.get(Organisation, default_org)


REDIRECT = "http://localhost:8000/api/v1/organisation/mailbox/callback"


# --- The consent link ------------------------------------------------------


@pytest.fixture()
def registered(monkeypatch):
    """A Google client with our callback registered, as a real one must be."""
    monkeypatch.setattr(
        "app.services.mailbox._client_config",
        lambda: {
            "client_id": "test-client",
            "client_secret": "test-secret",
            "redirect_uris": [REDIRECT],
        },
    )


def test_the_link_asks_only_for_read_and_send(desk, registered):
    """Least privilege. Steel Desk never needs to modify a customer's mail."""
    url = consent_url(desk.id, REDIRECT)
    assert "gmail.readonly" in url
    assert "gmail.send" in url
    assert "gmail.modify" not in url
    assert "mail.google.com" not in url  # the full-access scope


def test_the_link_asks_for_a_lasting_connection(desk, registered):
    """Without both of these Google returns no refresh token on a repeat
    consent, and the mailbox stops working an hour later for no visible
    reason."""
    url = consent_url(desk.id, REDIRECT)
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_the_link_carries_the_organisation_signed(desk, registered):
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(consent_url(desk.id, REDIRECT)).query)["state"][0]
    assert read_state(state) == desk.id


# --- The callback's claim about who is connecting --------------------------


def test_an_unsigned_state_is_refused(desk):
    """The callback is public, so anyone can call it with anything."""
    with pytest.raises(MailboxError):
        read_state("42")


def test_a_state_signed_with_another_key_is_refused(desk):
    """The attack this prevents: attaching your mailbox to somebody else's desk."""
    import jwt

    forged = jwt.encode(
        {"org": desk.id, "exp": datetime.now(UTC) + timedelta(minutes=10)},
        "not-the-real-secret",
        algorithm="HS256",
    )
    with pytest.raises(MailboxError):
        read_state(forged)


def test_an_expired_state_is_refused(desk):
    """A consent link left open overnight should not still attach a mailbox."""
    import jwt

    from app.core.config import settings

    stale = jwt.encode(
        {"org": desk.id, "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(MailboxError, match="expired"):
        read_state(stale)


# --- Setup problems, caught before the trader leaves -----------------------


def test_an_unregistered_redirect_is_refused_before_leaving(desk, monkeypatch):
    """Google would reject this on its own error page, after the trader has
    already left the application and with nothing they can act on."""
    monkeypatch.setattr(
        "app.services.mailbox._client_config",
        lambda: {"client_id": "x", "client_secret": "y", "redirect_uris": ["http://localhost"]},
    )
    with pytest.raises(MailboxError, match="authorised redirect URIs"):
        consent_url(desk.id, REDIRECT)


def test_the_message_names_the_exact_uri_to_register(desk, monkeypatch):
    """A setup instruction that makes somebody guess the value is no better
    than the error it replaced."""
    from app.services.mailbox import check_redirect_registered

    monkeypatch.setattr(
        "app.services.mailbox._client_config",
        lambda: {"client_id": "x", "redirect_uris": ["http://localhost"]},
    )
    problem = check_redirect_registered(REDIRECT)
    assert REDIRECT in problem


def test_a_registered_redirect_reports_no_problem(desk, monkeypatch):
    from app.services.mailbox import check_redirect_registered

    monkeypatch.setattr(
        "app.services.mailbox._client_config",
        lambda: {"client_id": "x", "redirect_uris": [REDIRECT]},
    )
    assert check_redirect_registered(REDIRECT) is None


# --- The sample mailbox ----------------------------------------------------


def test_the_sample_mailbox_lets_a_desk_try_the_system(db, desk):
    """A trader should see Steel Desk work before granting access to a real inbox."""
    mailbox = connect_local(db, desk.id)
    assert mailbox.provider == "LOCAL"
    assert mailbox.status is MailboxStatus.CONNECTED
    assert mailbox.organisation_id == desk.id


def test_connecting_the_sample_twice_does_not_duplicate_it(db, desk):
    first = connect_local(db, desk.id)
    second = connect_local(db, desk.id)
    assert first.id == second.id


# --- Disconnecting ---------------------------------------------------------


def test_disconnecting_forgets_the_credentials(db, desk):
    from app.core.security import encrypt_credential

    mailbox = Mailbox(
        organisation_id=desk.id,
        provider="GMAIL",
        email_address="sales@example.com",
        refresh_token_enc=encrypt_credential("a-refresh-token"),
        status=MailboxStatus.CONNECTED,
    )
    db.add(mailbox)
    db.commit()

    disconnect(db, mailbox)

    assert mailbox.refresh_token_enc is None
    assert mailbox.status is MailboxStatus.DISCONNECTED


def test_disconnecting_keeps_the_mail_already_received(db, desk, quoted_quotation):
    """Disconnecting a mailbox is not a request to delete the desk's records."""
    from sqlalchemy import func, select

    from app.models import Email

    mailbox = connect_local(db, desk.id)
    before = db.scalar(select(func.count()).select_from(Email))

    disconnect(db, mailbox)

    assert db.scalar(select(func.count()).select_from(Email)) == before


# --- Credentials at rest ---------------------------------------------------


def test_a_refresh_token_is_not_stored_in_plain_text(db, desk):
    """A database backup should not be a set of live Gmail credentials."""
    from app.core.security import decrypt_credential, encrypt_credential

    secret = "1//0abcdefghijklmnop"
    stored = encrypt_credential(secret)

    assert secret not in stored
    assert decrypt_credential(stored) == secret


def test_a_credential_encrypted_under_a_lost_key_reads_as_needing_reconnection(db):
    """A rotated key should present as "reconnect this mailbox", not as a crash."""
    from app.core.security import decrypt_credential

    assert decrypt_credential("not-a-valid-fernet-token") is None


# --- Isolation -------------------------------------------------------------


def test_a_mailbox_belongs_to_one_desk_only(db, two_desks):
    """A connected mailbox must not be visible to another organisation."""
    from sqlalchemy import select

    from app.core.tenancy import bind_session

    alpha, beta = two_desks

    bind_session(db, alpha.id)
    connect_local(db, alpha.id)
    db.commit()

    bind_session(db, beta.id)
    assert db.scalars(select(Mailbox)).all() == []
    db.commit()
