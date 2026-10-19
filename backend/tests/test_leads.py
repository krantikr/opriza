"""Public lead capture: the Request-access form and live-demo sign-ups.

Both routes are unauthenticated and write to the platform-level `leads` table,
so the tests drive them through a plain TestClient on a platform session.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.api.v1.admin import LeadOut
from app.main import app
from app.models import Lead

DEMO = {
    "name": "Karan Mehta",
    "company": "KK Traders",
    "email": "karan@kktraders.in",
    "phone": "+91 98765 43210",
    "city": "Pune",
    "industry": "building",
    "industry_label": "Building materials",
    "revenue": "250-500",
    "team": "10–25",
    "tally": "TallyPrime",
    "problems": ["Slow quotes", "Late payments"],
}


@pytest.fixture()
def public(platform_db):
    """An anonymous client, as a prospect on the public site is."""
    app.dependency_overrides[get_db] = lambda: platform_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _leads(db):
    db.expire_all()
    return db.scalars(select(Lead).order_by(Lead.id)).all()


def test_a_demo_sign_up_is_stored_with_its_business_details(public, platform_db):
    res = public.post("/api/v1/leads/demo", json=DEMO)

    assert res.status_code == 201
    assert res.json() == {"received": True}
    [lead] = _leads(platform_db)
    assert lead.source == "demo"
    assert lead.status == "new"
    assert (lead.name, lead.company, lead.email, lead.phone) == (
        "Karan Mehta",
        "KK Traders",
        "karan@kktraders.in",
        "+91 98765 43210",
    )
    assert lead.details == {
        "city": "Pune",
        "industry": "building",
        "industry_label": "Building materials",
        "revenue": "250-500",
        "team": "10–25",
        "tally": "TallyPrime",
        "problems": ["Slow quotes", "Late payments"],
    }


def test_the_admin_list_shows_the_details(public, platform_db):
    public.post("/api/v1/leads/demo", json=DEMO)
    [lead] = _leads(platform_db)

    out = LeadOut.model_validate(lead)

    assert out.source == "demo"
    assert out.details is not None and out.details["industry_label"] == "Building materials"


def test_email_and_phone_are_required(public, platform_db):
    no_email = {k: v for k, v in DEMO.items() if k != "email"}
    bad_email = {**DEMO, "email": "not-an-email"}
    no_phone = {**DEMO, "phone": ""}
    short_phone = {**DEMO, "phone": "12-34"}

    for body in (no_email, bad_email, no_phone, short_phone):
        assert public.post("/api/v1/leads/demo", json=body).status_code == 422

    assert _leads(platform_db) == []


def test_empty_business_fields_are_left_out(public, platform_db):
    body = {"name": "A", "company": "B", "email": "a@b.co", "phone": "9876543210", "problems": []}

    assert public.post("/api/v1/leads/demo", json=body).status_code == 201

    [lead] = _leads(platform_db)
    assert lead.details is None


def test_a_filled_honeypot_is_accepted_but_not_stored(public, platform_db):
    res = public.post("/api/v1/leads/demo", json={**DEMO, "website": "http://spam.example"})

    assert res.status_code == 201
    assert _leads(platform_db) == []


def test_each_start_is_its_own_row(public, platform_db):
    """Leads are append-only: a second start with changed details adds a row and
    never edits the first."""
    public.post("/api/v1/leads/demo", json=DEMO)
    public.post(
        "/api/v1/leads/demo", json={**DEMO, "industry": "steel", "industry_label": "Steel and metals"}
    )

    first, second = _leads(platform_db)
    assert first.details["industry"] == "building"
    assert second.details["industry"] == "steel"


def test_the_contact_form_still_works_and_has_no_details(public, platform_db):
    res = public.post(
        "/api/v1/leads",
        json={"name": "Asha", "company": "Asha Steels", "email": "asha@example.com", "phone": "9876543210"},
    )

    assert res.status_code == 201
    [lead] = _leads(platform_db)
    assert lead.source == "marketing_site"
    assert lead.details is None
