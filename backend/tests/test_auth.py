"""Sign-in, invitations, and the crawl window.

The authentication tests here concentrate on the cases that are quiet when
they break: a token that outlives a password change, an invitation that can be
used twice, an error message that tells an attacker which addresses exist.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.core.security import TokenError, read_token
from app.models import InviteStatus, Organisation, OrgStatus, User, UserRole
from app.services import auth as auth_service
from app.services.auth import AuthError
from app.services.crawl_window import decide, in_window, is_due


@pytest.fixture()
def desk(db, default_org) -> Organisation:
    return db.get(Organisation, default_org)


@pytest.fixture()
def owner(db, desk) -> User:
    user = User(
        organisation_id=desk.id,
        name="Desk Owner",
        email="owner@example.com",
        password_hash=auth_service.hash_password("a-good-long-password"),
        role=UserRole.OWNER,
    )
    db.add(user)
    db.commit()
    return user


# --- Sign in ---------------------------------------------------------------


def test_correct_details_return_a_usable_token(db, owner):
    user, token = auth_service.authenticate(db, "owner@example.com", "a-good-long-password")
    assert user.id == owner.id
    assert read_token(token)["org"] == owner.organisation_id


def test_the_address_is_matched_case_insensitively(db, owner):
    """People capitalise their own address inconsistently; that is not a failure."""
    user, _ = auth_service.authenticate(db, "OWNER@Example.com", "a-good-long-password")
    assert user.id == owner.id


def test_a_wrong_password_and_an_unknown_address_are_indistinguishable(db, owner):
    """Different messages would let someone enumerate who has an account."""
    with pytest.raises(AuthError) as wrong:
        auth_service.authenticate(db, "owner@example.com", "not-the-password")
    with pytest.raises(AuthError) as unknown:
        auth_service.authenticate(db, "nobody@example.com", "not-the-password")

    assert str(wrong.value) == str(unknown.value)


def test_a_deactivated_user_cannot_sign_in(db, owner):
    auth_service.deactivate_user(db, owner)
    with pytest.raises(AuthError):
        auth_service.authenticate(db, "owner@example.com", "a-good-long-password")


def test_a_suspended_desk_cannot_sign_in(db, desk, owner):
    desk.status = OrgStatus.SUSPENDED
    db.commit()
    with pytest.raises(AuthError, match="suspended"):
        auth_service.authenticate(db, "owner@example.com", "a-good-long-password")


# --- Token invalidation ----------------------------------------------------


def test_changing_a_password_invalidates_tokens_already_issued(db, owner):
    """The point of `token_version`: a stolen token dies with the password."""
    _, old_token = auth_service.authenticate(db, "owner@example.com", "a-good-long-password")
    issued_version = read_token(old_token)["ver"]

    auth_service.change_password(db, owner, "a-good-long-password", "a-different-password")

    # The token still verifies cryptographically - it is the version check in
    # `current_user` that rejects it, which is why that check must exist.
    assert read_token(old_token)["ver"] == issued_version
    assert owner.token_version != issued_version


def test_deactivating_someone_invalidates_their_tokens(db, owner):
    before = owner.token_version
    auth_service.deactivate_user(db, owner)
    assert owner.token_version > before


def test_a_short_password_is_refused(db, owner):
    with pytest.raises(AuthError, match="at least"):
        auth_service.change_password(db, owner, "a-good-long-password", "short")


def test_an_expired_token_is_rejected():
    import jwt

    from app.core.config import settings

    expired = jwt.encode(
        {"sub": "1", "exp": datetime.now(UTC) - timedelta(hours=1)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(TokenError, match="expired"):
        read_token(expired)


def test_a_token_signed_with_another_key_is_rejected():
    """Guards the classic forgery: signing your own token."""
    import jwt

    forged = jwt.encode(
        {"sub": "1", "org": 999, "exp": datetime.now(UTC) + timedelta(hours=1)},
        "not-the-real-secret",
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        read_token(forged)


# --- Invitations -----------------------------------------------------------


def test_an_invitation_creates_an_account_on_the_right_desk(db, desk):
    _, token = auth_service.invite_user(
        db, organisation_id=desk.id, email="colleague@example.com", role=UserRole.MEMBER
    )
    user, access = auth_service.accept_invite(
        db, token=token, name="A Colleague", password="another-long-password"
    )

    assert user.organisation_id == desk.id
    assert user.role is UserRole.MEMBER
    assert read_token(access)["org"] == desk.id


def test_an_invitation_cannot_be_used_twice(db, desk):
    """Otherwise a forwarded link is an open door onto the desk."""
    _, token = auth_service.invite_user(
        db, organisation_id=desk.id, email="colleague@example.com", role=UserRole.MEMBER
    )
    auth_service.accept_invite(
        db, token=token, name="A Colleague", password="another-long-password"
    )

    with pytest.raises(AuthError, match="no longer valid"):
        auth_service.accept_invite(
            db, token=token, name="Impostor", password="yet-another-password"
        )


def test_an_expired_invitation_is_refused(db, desk):
    from app.core.db import utcnow

    invite, token = auth_service.invite_user(
        db, organisation_id=desk.id, email="colleague@example.com", role=UserRole.MEMBER
    )
    invite.expires_at = utcnow() - timedelta(days=1)
    db.commit()

    with pytest.raises(AuthError, match="expired"):
        auth_service.accept_invite(
            db, token=token, name="Late", password="another-long-password"
        )


def test_re_inviting_supersedes_the_previous_link(db, desk):
    """Two live links for one address is one more than anybody intended."""
    first, first_token = auth_service.invite_user(
        db, organisation_id=desk.id, email="colleague@example.com", role=UserRole.MEMBER
    )
    auth_service.invite_user(
        db, organisation_id=desk.id, email="colleague@example.com", role=UserRole.VIEWER
    )
    db.refresh(first)

    assert first.status is InviteStatus.REVOKED
    with pytest.raises(AuthError):
        auth_service.accept_invite(
            db, token=first_token, name="Nope", password="another-long-password"
        )


def test_inviting_someone_already_on_the_team_is_refused(db, desk, owner):
    with pytest.raises(AuthError, match="already on this team"):
        auth_service.invite_user(
            db, organisation_id=desk.id, email="owner@example.com", role=UserRole.MEMBER
        )


def test_a_guessed_invite_token_does_not_work(db, desk):
    auth_service.invite_user(
        db, organisation_id=desk.id, email="colleague@example.com", role=UserRole.MEMBER
    )
    with pytest.raises(AuthError):
        auth_service.accept_invite(
            db, token="not-a-real-token", name="Guesser", password="another-long-password"
        )


# --- The crawl window ------------------------------------------------------


def test_an_ordinary_daytime_window(desk):
    assert in_window(time(9, 0), time(8, 0), time(22, 0)) is True
    assert in_window(time(23, 0), time(8, 0), time(22, 0)) is False
    # The boundaries: start is inside, end is not.
    assert in_window(time(8, 0), time(8, 0), time(22, 0)) is True
    assert in_window(time(22, 0), time(8, 0), time(22, 0)) is False


def test_a_window_that_crosses_midnight(desk):
    """`22:00-06:00` is a real answer, and must not read as "never"."""
    assert in_window(time(23, 0), time(22, 0), time(6, 0)) is True
    assert in_window(time(2, 0), time(22, 0), time(6, 0)) is True
    assert in_window(time(12, 0), time(22, 0), time(6, 0)) is False


def test_the_requested_schedule_polls_every_ten_minutes_in_hours(db, desk):
    """08:00-22:00 every 10 minutes, hourly overnight - as specified."""
    # 10:00 in Asia/Kolkata is 04:30 UTC.
    morning = datetime(2026, 8, 20, 4, 30, tzinfo=UTC)
    decision = decide(desk, morning)
    assert decision.active is True
    assert decision.interval_minutes == 10

    # 23:00 Kolkata is 17:30 UTC.
    night = datetime(2026, 8, 20, 17, 30, tzinfo=UTC)
    decision = decide(desk, night)
    assert decision.active is False
    assert decision.interval_minutes == 60


def test_the_window_is_read_in_the_desks_own_timezone(db, desk):
    """The same instant is working hours for one desk and night for another."""
    desk.timezone = "America/New_York"
    db.commit()

    # 04:30 UTC is 00:30 in New York - the middle of the night.
    moment = datetime(2026, 8, 20, 4, 30, tzinfo=UTC)
    assert decide(desk, moment).active is False


def test_an_unknown_timezone_falls_back_rather_than_crashing(db, desk):
    """Polling on the wrong clock beats a background job that dies."""
    desk.timezone = "Mars/Olympus_Mons"
    db.commit()
    assert decide(desk).should_poll is True


def test_switching_crawling_off_stops_it(db, desk):
    desk.crawl_enabled = False
    db.commit()
    decision = decide(desk)
    assert decision.should_poll is False
    assert "switched off" in decision.reason


def test_a_mailbox_never_polled_is_due_immediately(db, desk):
    """A desk that has just connected should not wait an hour for its first mail."""
    assert is_due(desk, None) is True


def test_a_mailbox_polled_recently_is_not_due(db, desk):
    morning = datetime(2026, 8, 20, 4, 30, tzinfo=UTC)
    assert is_due(desk, morning - timedelta(minutes=2), morning) is False
    assert is_due(desk, morning - timedelta(minutes=11), morning) is True


def test_the_reason_explains_the_wait_in_words(db, desk):
    """"Why has nothing arrived since 10pm" has to be answerable in the UI."""
    night = datetime(2026, 8, 20, 17, 30, tzinfo=UTC)
    reason = decide(desk, night).reason
    assert "Outside working hours" in reason
    assert "08:00" in reason


# --- Onboarding ------------------------------------------------------------
#
# These run on `platform_db` rather than `db`: creating an organisation is a
# cross-tenant act, and a desk-scoped session correctly cannot do it.


def test_onboarding_a_desk_creates_it_with_an_owner_invitation(platform_db):
    org, invite, token = auth_service.create_organisation(
        platform_db, name="Gamma Steel", owner_email="gamma@example.com"
    )

    assert org.slug == "gamma-steel"
    assert invite.role is UserRole.OWNER
    # The operator issues an invitation; they never set the owner's password,
    # so they cannot sign in as a customer.
    user, _ = auth_service.accept_invite(
        platform_db, token=token, name="Gamma Owner", password="a-long-enough-password"
    )
    assert user.organisation_id == org.id


def test_two_desks_with_the_same_name_get_distinct_handles(platform_db):
    first, _, _ = auth_service.create_organisation(
        platform_db, name="Steel Traders", owner_email="one@example.com"
    )
    second, _, _ = auth_service.create_organisation(
        platform_db, name="Steel Traders", owner_email="two@example.com"
    )
    assert first.slug != second.slug


def test_a_new_desk_can_price_on_day_one(platform_db):
    """Onboarding publishes a pricing rule set.

    Without one the Pricing screen has nothing to edit and every enquiry comes
    back unquotable, with no way to recover from inside the app - the desk
    cannot do the one thing it exists to do.
    """
    from app.models import PricingRuleSet

    org, _, _ = auth_service.create_organisation(
        platform_db, name="Epsilon Steel", owner_email="epsilon@example.com"
    )

    rule_set = platform_db.scalars(
        select(PricingRuleSet).where(PricingRuleSet.organisation_id == org.id)
    ).first()
    assert rule_set is not None
    assert rule_set.is_active
    assert rule_set.rules, "a rule set with no rules prices nothing"


def test_each_desk_numbers_its_pricing_versions_from_one(platform_db):
    """Version 1 is not the platform's to hand out once.

    A global unique on `version` meant the second desk onboarded could not be
    given a starting rule set at all.
    """
    from app.models import PricingRuleSet

    first, _, _ = auth_service.create_organisation(
        platform_db, name="Zeta Steel", owner_email="zeta@example.com"
    )
    second, _, _ = auth_service.create_organisation(
        platform_db, name="Eta Steel", owner_email="eta@example.com"
    )

    versions = {
        org.id: platform_db.scalars(
            select(PricingRuleSet.version).where(PricingRuleSet.organisation_id == org.id)
        ).all()
        for org in (first, second)
    }
    assert versions[first.id] == [1]
    assert versions[second.id] == [1]


def test_a_new_desk_starts_on_the_requested_schedule(platform_db):
    """The default is the schedule that was asked for: 8am-10pm, 10 minutes."""
    org, _, _ = auth_service.create_organisation(
        platform_db, name="Delta Metals", owner_email="delta@example.com"
    )
    assert org.crawl_active_from == time(8, 0)
    assert org.crawl_active_to == time(22, 0)
    assert org.crawl_active_minutes == 10
    assert org.crawl_quiet_minutes == 60


# --- What the schedule screen reports --------------------------------------


def test_crawl_status_names_the_server_switch_before_the_schedule(client, db, desk, monkeypatch):
    """A saved schedule is not a running one.

    The desk can hold a perfectly good 10-minute window while the poller is
    switched off server-wide, and the screen that shows the window is the one
    place a trader would look to find that out.
    """
    monkeypatch.setattr("app.api.v1.auth.settings.polling_enabled", False)

    body = client.get("/api/v1/organisation/crawl-status").json()

    assert body["poller_running"] is False
    # The schedule itself is still reported - it is saved and correct. Which
    # interval applies depends on the hour the suite runs at, so this asserts
    # that one of the desk's two configured cadences came back, not a
    # particular one.
    assert body["interval_minutes"] in {
        desk.crawl_active_minutes,
        desk.crawl_quiet_minutes,
    }


def test_crawl_status_reports_whether_a_mailbox_exists(client, db, desk, monkeypatch):
    """A schedule with nothing to poll will never fetch anything."""
    from app.models import Mailbox

    monkeypatch.setattr("app.api.v1.auth.settings.polling_enabled", True)

    body = client.get("/api/v1/organisation/crawl-status").json()
    assert body["mailbox_connected"] is False
    assert body["last_polled_at"] is None

    db.add(Mailbox(organisation_id=desk.id, email_address="desk@example.com"))
    db.commit()

    body = client.get("/api/v1/organisation/crawl-status").json()
    assert body["mailbox_connected"] is True
