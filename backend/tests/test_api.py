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
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def drafted(db, priced_quotation):
    """A quotation with a draft ready for review."""
    draft = QuotationDraft(
        quotation_request_id=priced_quotation.id,
        version=1,
        is_current=True,
        subject="Re: Enquiry - IS 2062 E250 Plate 10mm",
        body="Dear Rajesh Kumar,\n\nRate: Rs 59,200.00 per MT for 20 MT.\n\nRegards,\nSales Team",
        status=DraftStatus.GENERATED,
        generated_by="fake/model",
    )
    db.add(draft)
    db.commit()
    db.refresh(priced_quotation)
    return priced_quotation


# --- Listings --------------------------------------------------------------


def test_health_is_reachable(client):
    assert client.get("/health").json()["status"] == "ok"


def test_quotation_list_returns_a_page(client, drafted):
    body = client.get("/api/v1/quotations").json()

    assert body["total"] == 1
    assert body["items"][0]["quotation_number"] == "Q-000001"
    assert body["items"][0]["headline_price"] == "59200.00"


def test_quotation_list_filters_by_status(client, drafted):
    assert client.get("/api/v1/quotations", params={"status": "READY_FOR_REVIEW"}).json()["total"] == 1
    assert client.get("/api/v1/quotations", params={"status": "SENT"}).json()["total"] == 0


def test_quotation_detail_carries_the_whole_review_context(client, drafted):
    """Everything the reviewer needs on one screen (spec section 17)."""
    body = client.get(f"/api/v1/quotations/{drafted.id}").json()

    assert body["email"]["body_text"].startswith("Dear Sir")
    line = body["line_items"][0]
    assert line["matched_product_code"] == "PLT-E250-10X1500X6000"
    assert line["pricing"]["recommended_price"] == "59200.00"
    assert line["pricing"]["comparable_count"] == 5
    assert body["current_draft"]["version"] == 1


def test_missing_quotation_is_a_404(client):
    assert client.get("/api/v1/quotations/9999").status_code == 404


def test_products_listing_includes_the_current_price(client, plate):
    body = client.get("/api/v1/products").json()
    assert body["items"][0]["current_price"] == "56500.00"
    assert body["items"][0]["display_name"].startswith("IS 2062 E250 Plate")


def test_customer_detail_reports_purchase_history(client, customer, comparable_sales):
    body = client.get(f"/api/v1/customers/{customer.id}").json()
    assert body["total_orders"] == 5
    assert len(body["recent_sales"]) == 5


def test_ad_hoc_pricing_uses_the_same_engine(client, plate, customer, comparable_sales):
    response = client.post(
        "/api/v1/pricing/recommend",
        json={
            "product_id": plate.id,
            "quantity_mt": "20",
            "customer_id": customer.id,
            "delivery_location": "Patna",
        },
    )

    body = response.json()
    assert body["recommended_price"] == "59200.00"
    assert body["breakdown"][0]["id"] == "base_price"
    assert "Freight to Patna" in body["explanation"]


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


def test_a_quotation_with_no_draft_cannot_be_approved(client, db, priced_quotation, sent_dir):
    """Nothing to send is not the same as sending nothing."""
    response = client.post(f"/api/v1/quotations/{priced_quotation.id}/approve", json={})

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
    assert body["pricing_rule_version"] == "1.0"
    assert body["products"] == 1
    assert "classify" in body["llm_models"]


def test_business_rules_are_inspectable(client):
    body = client.get("/api/v1/system/rules").json()
    assert body["pricing"]["margin_floor"]["minimum_margin_pct"] == 2.0
    assert body["matching"]["accept_score"] == 80.0
