"""System push notifications via Firebase Cloud Messaging.

Push is the only channel that reaches a trader with the site closed, so the
properties that matter are about what happens when things go wrong rather than
when they go right:

* **An unconfigured desk never crashes.** A notification that cannot be
  delivered is recorded as failed and the workflow carries on - nobody loses a
  quotation because a phone was unreachable.
* **Dead tokens are retired, transient failures are not.** Leaving a dead one
  active burns a request per notification forever; deactivating on a timeout
  would silently stop a working phone.
* **One row per device.** A trader with a phone and a desk machine expects
  both to buzz.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import (
    NotificationChannel,
    NotificationKind,
    NotificationRule,
    PushDevice,
)
from app.services.notifications.channels import FcmChannel, LocalChannel, get_channel
from app.services.notifications.service import NotificationService


@pytest.fixture()
def device(db, default_user) -> PushDevice:
    row = PushDevice(
        user_id=default_user.id,
        token="tok-" + "a" * 32,
        label="Chrome on Android",
        is_active=True,
        last_seen_at=datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# The channel, unconfigured
# ---------------------------------------------------------------------------


def test_an_unconfigured_desk_falls_back_to_local_files():
    """The whole push path stays exercisable before any Firebase project."""
    channel = get_channel(NotificationChannel.PUSH)

    assert isinstance(channel, LocalChannel)


def test_sending_without_firebase_reports_why_rather_than_raising():
    result = FcmChannel().send(destination="tok", title="Hi", body="There")

    assert result.sent is False
    assert "not configured" in (result.error or "").lower()


def test_a_missing_token_is_refused_before_any_request():
    result = FcmChannel().send(destination="", title="Hi", body="There")

    assert result.sent is False
    assert result.error


# ---------------------------------------------------------------------------
# Dead tokens
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    ["UNREGISTERED", "NOT_FOUND", "SENDER_ID_MISMATCH", "INVALID_ARGUMENT · bad token"],
)
def test_permanent_failures_are_recognised(error):
    assert FcmChannel().is_dead_token(error) is True


@pytest.mark.parametrize(
    "error",
    ["UNAVAILABLE", "INTERNAL", "Read timed out", "QUOTA_EXCEEDED", None],
)
def test_transient_failures_are_not_treated_as_dead(error):
    """Deactivating on a timeout would silently stop a working phone."""
    assert FcmChannel().is_dead_token(error) is False


def test_a_rejected_device_is_deactivated_not_deleted(db, device, default_user):
    """Kept so "why did this phone stop buzzing" stays answerable."""
    service = NotificationService(db)
    service._retire_device(device.token, "UNREGISTERED")
    db.commit()

    db.refresh(device)
    assert device.is_active is False
    assert "UNREGISTERED" in (device.disabled_reason or "")
    # Still present, not removed.
    assert db.get(PushDevice, device.id) is not None


# ---------------------------------------------------------------------------
# Fan-out
# ---------------------------------------------------------------------------


def test_a_push_rule_reaches_every_active_device(db, device, default_user):
    """A trader with a phone and a desk machine expects both to buzz."""
    second = PushDevice(
        user_id=default_user.id, token="tok-" + "b" * 32, label="Chrome on Mac"
    )
    off = PushDevice(
        user_id=default_user.id,
        token="tok-" + "c" * 32,
        label="Old phone",
        is_active=False,
    )
    db.add_all([second, off])
    db.commit()

    rule = NotificationRule(
        label="push", kind=NotificationKind.NEW_ENQUIRY, channel=NotificationChannel.PUSH
    )
    db.add(rule)
    db.flush()

    recipients = NotificationService(db)._recipients(rule)
    tokens = {token for token, _ in recipients}

    assert tokens == {device.token, second.token}
    assert off.token not in tokens


def test_no_devices_means_no_recipients(db):
    """Silent rather than inventing a destination that cannot exist."""
    rule = NotificationRule(
        label="push", kind=NotificationKind.NEW_ENQUIRY, channel=NotificationChannel.PUSH
    )
    db.add(rule)
    db.flush()

    assert NotificationService(db)._recipients(rule) == []


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------


def test_registering_is_idempotent_on_the_token(client, db, default_user):
    """The frontend calls this on every load, because FCM rotates tokens."""
    payload = {"token": "tok-" + "d" * 32, "label": "Chrome on Mac"}

    first = client.post("/api/v1/push/devices", json=payload)
    second = client.post("/api/v1/push/devices", json=payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]


def test_re_registering_revives_a_retired_device(client, db, device):
    """Granting permission again should undo an earlier rejection."""
    device.is_active = False
    device.disabled_reason = "UNREGISTERED"
    db.commit()

    r = client.post("/api/v1/push/devices", json={"token": device.token})

    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True
    assert r.json()["disabled_reason"] is None


def test_status_separates_desk_setup_from_device_count(client, device):
    """So the UI can say "ask your administrator" rather than prompting for a
    permission that could never deliver anything."""
    r = client.get("/api/v1/push/status")

    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False  # no Firebase in tests
    assert body["devices"] == 1


def test_a_device_can_be_turned_off(client, db, device):
    r = client.delete(f"/api/v1/push/devices/{device.id}")

    assert r.status_code == 204
    db.refresh(device)
    assert device.is_active is False


def test_testing_without_a_device_says_so(client):
    r = client.post("/api/v1/push/test")

    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "no devices" in r.json()["detail"].lower()
