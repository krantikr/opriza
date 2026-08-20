"""The HTTP surface, and the approval path in particular.

The approve endpoint is the only route in the system that sends anything to a
customer, so most of what is asserted here is about what it refuses to do.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models import Approval, ApprovalAction, DraftStatus, QuotationDraft, QuotationStatus
from app.services.email.sender import LocalFileSender


@pytest.fixture()
def sent_dir(tmp_path, monkeypatch) -> Path:
    """Redirect outbound mail to a temporary folder."""
    outbox = tmp_path / "sent"
    monkeypatch.setattr(
        "app.services.quotations.approval.get_sender", lambda: LocalFileSender(outbox)
    )
    return outbox


@pytest.fixture()
def client(db, default_user, sent_dir) -> TestClient:
    """An authenticated client for the default desk.

    The session is overridden, but authentication is *not* faked: the client
    signs in with a real token, so these tests exercise the same dependency
    chain a browser does. Stubbing `current_user` instead would leave every
    route's auth untested.
    """
    from app.api.deps import tenant_db
    from app.core.security import issue_token

    app.dependency_overrides[get_db] = lambda: db
    # `tenant_db` is overridden because the test session is already bound by
    # the `db` fixture; re-binding it inside a TestClient request would open a
    # second transaction on the same session.
    app.dependency_overrides[tenant_db] = lambda: db

    token = issue_token(
        user_id=default_user.id,
        organisation_id=default_user.organisation_id,
        role=default_user.role.value,
        is_super_admin=False,
        token_version=default_user.token_version,
    )
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def drafted(db, quoted_quotation):
    """A quotation with a draft ready for review."""
    draft = QuotationDraft(
        quotation_request_id=quoted_quotation.id,
        version=1,
        is_current=True,
        subject="Re: Enquiry - IS 2062 E250 Plate 10mm",
        body="Dear Rajesh Kumar,\n\nRate: Rs 59,200.00 per MT for 20 MT.\n\nRegards,\nSales Team",
        status=DraftStatus.GENERATED,
        generated_by="fake/model",
    )
    db.add(draft)
    db.commit()
    db.refresh(quoted_quotation)
    return quoted_quotation


# --- Listings --------------------------------------------------------------


def test_health_is_reachable(client):
    assert client.get("/health").json()["status"] == "ok"


def test_quotation_list_returns_a_page(client, drafted):
    body = client.get("/api/v1/quotations").json()

    assert body["total"] == 1
    assert body["items"][0]["quotation_number"] == "Q-000001"
    assert body["items"][0]["headline_product"]
    assert body["items"][0]["total_suggested_value"] == "1220000.00000"


def test_quotation_list_filters_by_status(client, drafted):
    assert client.get("/api/v1/quotations", params={"status": "READY_FOR_REVIEW"}).json()["total"] == 1
    assert client.get("/api/v1/quotations", params={"status": "SENT"}).json()["total"] == 0


def test_quotation_detail_carries_the_whole_review_context(client, drafted):
    """Everything the reviewer needs on one screen (spec section 17)."""
    body = client.get(f"/api/v1/quotations/{drafted.id}").json()

    assert body["email"]["body_text"].startswith("Please quote 20 MT")
    line = body["line_items"][0]
    assert line["matched_stock_item_name"].startswith("E250 Plate")
    assert line["stock_availability"]["suggested_rate"] == "61000.00"
    assert line["stock_availability"]["available_qty_mt"] == "28.260"
    assert line["stock_availability"]["lot_count"] == 1
    assert body["current_draft"]["version"] == 1


def test_missing_quotation_is_a_404(client):
    assert client.get("/api/v1/quotations/9999").status_code == 404


def test_stock_listing_reports_the_lot_on_hand(client, plate):
    body = client.get("/api/v1/stock").json()
    assert body["items"][0]["display_name"].startswith("E250 Plate")
    assert body["items"][0]["balance_qty_kg"] == "28260.000"


def test_customer_detail_is_served(client, customer):
    body = client.get(f"/api/v1/customers/{customer.id}").json()
    assert body["name"] == "Rajesh Kumar"
    assert body["company"] == "ABC Industries Pvt Ltd"


def test_ad_hoc_stock_check_uses_the_same_service(client, plate, customer):
    """The dashboard's manual check must not be a second implementation."""
    response = client.post(
        "/api/v1/stock/check",
        json={"stock_item_id": plate.id, "quantity_mt": "20", "customer_id": customer.id},
    )

    body = response.json()
    assert body["suggested_rate"] == "61000"
    assert body["breakdown"][0]["id"] == "stock_lookup"
    assert "landed cost" in body["explanation"]


# --- Review actions --------------------------------------------------------


def test_editing_a_draft_saves_without_sending(client, drafted, sent_dir):
    response = client.put(
        f"/api/v1/quotations/{drafted.id}/draft",
        json={"subject": "Re: Our offer", "body": "Revised text.", "comments": "tightened wording"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "EDITED"
    assert not sent_dir.exists(), "editing must not send anything"


def test_approving_records_the_decision_then_sends(client, db, drafted, sent_dir, default_user):
    response = client.post(f"/api/v1/quotations/{drafted.id}/approve", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "SENT"

    db.refresh(drafted)
    assert drafted.status is QuotationStatus.SENT
    assert drafted.sent_at is not None
    assert drafted.sent_message_id

    approval = db.query(Approval).one()
    assert approval.action is ApprovalAction.APPROVE
    assert approval.user_id == default_user.id
    assert approval.final_body == drafted.current_draft.body

    assert len(list(sent_dir.glob("*.eml"))) == 1


def test_the_sent_message_threads_onto_the_original(client, drafted, sent_dir):
    """Without these headers the customer sees a disconnected new email."""
    client.post(f"/api/v1/quotations/{drafted.id}/approve", json={})
    raw = next(sent_dir.glob("*.eml")).read_text(encoding="utf-8")

    assert "In-Reply-To: <enquiry-1@sample.local>" in raw
    assert "References: <enquiry-1@sample.local>" in raw
    assert "To: rajesh@abcindustries.co.in" in raw


def test_approving_with_edits_sends_the_edited_text(client, db, drafted, sent_dir):
    client.post(
        f"/api/v1/quotations/{drafted.id}/approve",
        json={"subject": "Re: Final offer", "body": "Our final rate is Rs 59,200.00 per MT."},
    )

    approval = db.query(Approval).one()
    assert approval.was_edited is True
    assert approval.original_body != approval.final_body
    assert "final rate" in next(sent_dir.glob("*.eml")).read_text(encoding="utf-8")


def test_rejecting_closes_the_quotation_without_sending(client, db, drafted, sent_dir):
    response = client.post(
        f"/api/v1/quotations/{drafted.id}/reject", json={"reason": "Customer withdrew"}
    )

    assert response.json()["status"] == "REJECTED"
    db.refresh(drafted)
    assert drafted.status is QuotationStatus.REJECTED
    assert not sent_dir.exists()

    approval = db.query(Approval).one()
    assert approval.action is ApprovalAction.REJECT
    assert approval.comments == "Customer withdrew"


# --- Refusals --------------------------------------------------------------


def test_a_quotation_cannot_be_sent_twice(client, drafted):
    assert client.post(f"/api/v1/quotations/{drafted.id}/approve", json={}).status_code == 200
    second = client.post(f"/api/v1/quotations/{drafted.id}/approve", json={})

    assert second.status_code == 409
    assert "no longer be actioned" in second.json()["detail"]


def test_a_rejected_quotation_cannot_then_be_approved(client, drafted):
    client.post(f"/api/v1/quotations/{drafted.id}/reject", json={})
    assert client.post(f"/api/v1/quotations/{drafted.id}/approve", json={}).status_code == 409


def test_a_quotation_with_no_draft_cannot_be_approved(client, db, quoted_quotation, sent_dir):
    """Nothing to send is not the same as sending nothing."""
    response = client.post(f"/api/v1/quotations/{quoted_quotation.id}/approve", json={})

    assert response.status_code == 409
    assert "no draft to act on" in response.json()["detail"]
    assert not sent_dir.exists()


def test_processing_refuses_to_run_without_an_api_key(client, monkeypatch):
    monkeypatch.setattr("app.api.v1.pipeline.settings.openrouter_api_key", "")
    response = client.post("/api/v1/pipeline/process")

    assert response.status_code == 503
    assert "OPENROUTER_API_KEY" in response.json()["detail"]


# --- Metrics and audit -----------------------------------------------------


def test_dashboard_metrics_reflect_the_approval(client, drafted):
    client.post(f"/api/v1/quotations/{drafted.id}/approve", json={})
    body = client.get("/api/v1/dashboard/metrics").json()

    assert body["quotations"]["sent"] == 1
    assert body["approvals"]["approved"] == 1
    assert body["approvals"]["approval_rate"] == 1.0
    assert body["recent_activity"][0]["action"] == "APPROVED_AND_SENT"


def test_every_action_leaves_an_audit_trail(client, drafted):
    client.put(
        f"/api/v1/quotations/{drafted.id}/draft",
        json={"subject": "Re: Offer", "body": "Rate: Rs 59,200.00 per MT."},
    )
    client.post(f"/api/v1/quotations/{drafted.id}/approve", json={})

    actions = [entry["action"] for entry in client.get("/api/v1/audit-logs").json()["items"]]
    assert "DRAFT_EDITED" in actions
    assert "APPROVED_AND_SENT" in actions


def test_system_status_reports_what_is_configured(client, plate):
    body = client.get("/api/v1/system/status").json()

    assert body["auto_send_enabled"] is False
    assert body["rules_version"] == "1.0"
    assert body["stock_lots"] == 1
    assert "classify" in body["llm_models"]


def test_business_rules_are_inspectable(client):
    body = client.get("/api/v1/system/rules").json()
    assert body["stock_pricing"]["markup_pct"] == 8.0
    assert body["matching"]["accept_score"] == 80.0


def test_every_email_category_is_a_valid_filter(client):
    """The mailbox filters by category, so each one must be accepted.

    Regression: the UI sent `ORDER_CONFIRMATION` and `GENERAL_INQUIRY`, which
    are not members of the enum. Every folder using them 422'd.
    """
    from app.models import EmailCategory

    for category in EmailCategory:
        response = client.get("/api/v1/emails", params={"category": category.value})
        assert response.status_code == 200, f"{category.value} was rejected"


def test_an_unknown_category_is_refused_rather_than_ignored(client):
    """A typo must fail loudly, not silently return the whole mailbox."""
    response = client.get("/api/v1/emails", params={"category": "ORDER_CONFIRMATION"})
    assert response.status_code == 422


def test_an_email_carries_its_quotation_status(client, db, quoted_quotation):
    """The mailbox shows which enquiries still wait on a person."""
    body = client.get("/api/v1/emails").json()
    row = next(e for e in body["items"] if e["quotation_id"] == quoted_quotation.id)

    assert row["quotation_number"] == quoted_quotation.quotation_number
    assert row["quotation_status"] == "READY_FOR_REVIEW"
