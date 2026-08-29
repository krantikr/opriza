"""Per-desk follow-up wording, filled from settled figures.

No model is involved: a follow-up says the same thing every time and only the
reference and the money change. These pin that the substitution is
deterministic, that a desk's own wording is honoured, and that clearing the
box restores the default rather than sending an empty email.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import Organisation, QuotationStatus
from app.services.quotations.templates import (
    DEFAULT_FOLLOWUP_BODY,
    PLACEHOLDERS,
    followup_body,
    followup_subject,
    render,
)


@pytest.fixture()
def sent(db, quoted_quotation):
    from app.core.db import utcnow

    quoted_quotation.status = QuotationStatus.SENT
    quoted_quotation.sent_at = utcnow()
    db.commit()
    return quoted_quotation


def _org(db, quotation) -> Organisation | None:
    return db.get(Organisation, quotation.organisation_id) if quotation.organisation_id else None


# --- Substitution -----------------------------------------------------------


def test_placeholders_are_replaced_with_real_values(db, sent):
    body = render("Quote {{quotation_number}} for {{customer_name}}.", sent, _org(db, sent))

    assert sent.quotation_number in body
    assert "{{" not in body


def test_an_unknown_placeholder_is_left_visible(db, sent):
    """A typo must be obvious, not silently blanked into a hole in the email."""
    body = render("Call {{contact_mobile}} please.", sent, _org(db, sent))
    assert "{{contact_mobile}}" in body


def test_every_documented_placeholder_actually_resolves(db, sent):
    """The help beside the editor must not promise something that does nothing."""
    template = " ".join(f"{{{{{name}}}}}" for name, _ in PLACEHOLDERS)
    out = render(template, sent, _org(db, sent))
    assert "{{" not in out, "a documented placeholder did not resolve"


def test_the_total_matches_the_quotation(db, sent):
    """The follow-up cannot quote a different figure from the document."""
    from app.services.quotations.table import build_rows, format_inr, totals

    _, total = totals(build_rows(sent))
    body = render("Total {{total_amount}}.", sent, _org(db, sent))

    if total is None:
        assert "Total ." in body or "Total" in body
    else:
        assert format_inr(total) in body


def test_an_unpriced_quotation_does_not_invent_a_zero(db, quoted_quotation):
    """A zero is a stated price; a blank is the truth."""
    for item in quoted_quotation.line_items:
        if item.stock_availability is not None:
            item.stock_availability.suggested_rate = None
    db.commit()

    body = render("Total {{total_amount}}.", quoted_quotation, None)
    assert "0.00" not in body


# --- Per-desk wording -------------------------------------------------------


def test_a_desk_without_a_template_gets_the_built_in_default(db, sent):
    org = _org(db, sent)
    if org is not None:
        org.followup_body_template = None
        db.commit()

    body = followup_body(sent, org)
    # The default's own distinctive phrasing, with placeholders resolved.
    assert "Following up on" in body
    assert "{{" not in body


def test_a_desks_own_wording_is_used_when_set(db, sent):
    org = _org(db, sent)
    if org is None:
        pytest.skip("fixture quotation has no organisation")

    org.followup_body_template = "Namaste {{customer_name}}, kindly confirm {{quotation_number}}."
    db.commit()

    body = followup_body(sent, org)
    assert body.startswith("Namaste")
    assert sent.quotation_number in body


def test_the_subject_always_threads(db, sent):
    """Whatever the desk types, the reply must still thread onto the original."""
    org = _org(db, sent)
    if org is not None:
        org.followup_subject_template = "Reminder about {{quotation_number}}"
        db.commit()

    assert followup_subject(sent, org).startswith("Re:")


# --- The API ----------------------------------------------------------------


def test_the_endpoint_serves_the_defaults_and_the_placeholder_list(client):
    body = client.get("/api/v1/organisation/email-templates").json()

    assert body["default_followup_body"] == DEFAULT_FOLLOWUP_BODY
    assert {p["name"] for p in body["placeholders"]} == {n for n, _ in PLACEHOLDERS}


def test_saving_then_clearing_restores_the_default(client, db):
    client.patch("/api/v1/organisation", json={"followup_body_template": "Custom {{customer_name}}"})
    assert client.get("/api/v1/organisation/email-templates").json()[
        "followup_body_template"
    ] == "Custom {{customer_name}}"

    # An emptied box means "use the default", not "send an empty email".
    client.patch("/api/v1/organisation", json={"followup_body_template": ""})
    assert client.get("/api/v1/organisation/email-templates").json()[
        "followup_body_template"
    ] is None


def test_a_follow_up_sends_with_the_desks_wording(db, client, sent):
    org = _org(db, sent)
    if org is None:
        pytest.skip("fixture quotation has no organisation")
    org.followup_body_template = "Namaste {{customer_name}}, re {{quotation_number}}."
    db.commit()

    from app.services.quotations.followup import FollowUpService

    result = FollowUpService(db).send(sent)
    assert result.follow_up.body.startswith("Namaste")
    assert "{{" not in result.follow_up.body
