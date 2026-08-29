"""The five working stages, and moving between them by hand.

The status machine records what happened; the stages are how a trader reads
the desk. These pin that the mapping is a derivation rather than a second
source of truth, and that moving a card never rewrites the account of what was
actually sent to the customer.
"""

from __future__ import annotations

import pytest

from app.core.db import utcnow
from app.models import QuotationStatus as Q
from app.services.quotations.stages import (
    COMMERCIAL_STAGES,
    STATUS_FOR_STAGE,
    stage_of,
)


class Fake:
    """Only what `stage_of` reads."""

    def __init__(self, status, despatched_at=None, paid_at=None):
        self.status = status
        self.despatched_at = despatched_at
        self.paid_at = paid_at


# --- The mapping ------------------------------------------------------------


def test_the_five_stages_are_in_working_order():
    assert [key for key, _, _ in COMMERCIAL_STAGES] == [
        "received", "sent", "negotiation", "delivery_pending", "payment_pending",
    ]


def test_everything_not_yet_sent_counts_as_received():
    """A quotation waiting on a missing address is as unanswered as a new one."""
    for status in (Q.NEW, Q.PROCESSING, Q.NEEDS_INFORMATION, Q.READY_FOR_REVIEW,
                   Q.EDITED, Q.APPROVED):
        assert stage_of(Fake(status)) == "received", status


def test_sent_means_awaiting_a_reply_not_everything_ever_sent():
    assert stage_of(Fake(Q.SENT)) == "sent"
    # Once the customer replies it has moved on, and must leave the stage.
    assert stage_of(Fake(Q.NEGOTIATION)) == "negotiation"
    assert stage_of(Fake(Q.CUSTOMER_ACCEPTED)) == "delivery_pending"


def test_despatched_goods_move_the_stage_without_a_status_change():
    """Otherwise a trader chases a lorry that left last week."""
    accepted = Fake(Q.CUSTOMER_ACCEPTED)
    assert stage_of(accepted) == "delivery_pending"

    accepted.despatched_at = utcnow()
    assert stage_of(accepted) == "payment_pending"


def test_settled_quotations_are_in_no_stage():
    """A board is a list of things to do, not an archive."""
    for status in (Q.PAID, Q.CUSTOMER_DECLINED, Q.REJECTED, Q.FAILED):
        assert stage_of(Fake(status)) is None, status


def test_every_stage_can_be_reached_by_hand():
    for key, _, _ in COMMERCIAL_STAGES:
        assert key in STATUS_FOR_STAGE
    # Plus the two endings, so a deal agreed on the phone can be recorded.
    assert "won" in STATUS_FOR_STAGE
    assert "lost" in STATUS_FOR_STAGE


# --- Moving by hand ---------------------------------------------------------


def test_a_trader_can_move_a_quotation_to_any_stage(client, quoted_quotation):
    for stage, expected in (
        ("negotiation", Q.NEGOTIATION),
        ("delivery_pending", Q.CUSTOMER_ACCEPTED),
        ("payment_pending", Q.PAYMENT_PENDING),
        ("sent", Q.SENT),
    ):
        response = client.post(
            f"/api/v1/quotations/{quoted_quotation.id}/stage", json={"stage": stage}
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == expected.value


def test_an_unknown_stage_is_refused_with_the_valid_ones(client, quoted_quotation):
    response = client.post(
        f"/api/v1/quotations/{quoted_quotation.id}/stage", json={"stage": "nonsense"}
    )
    assert response.status_code == 422
    assert "negotiation" in response.json()["detail"]


def test_moving_to_payment_records_the_despatch(db, client, quoted_quotation):
    client.post(
        f"/api/v1/quotations/{quoted_quotation.id}/stage",
        json={"stage": "payment_pending"},
    )
    db.expire_all()
    fresh = db.get(type(quoted_quotation), quoted_quotation.id)
    assert fresh.despatched_at is not None, "goods cannot be awaiting payment unsent"
    assert fresh.paid_at is None


def test_moving_back_to_delivery_clears_the_despatch(db, client, quoted_quotation):
    """A correction must not leave a despatch date for goods still on the floor."""
    client.post(
        f"/api/v1/quotations/{quoted_quotation.id}/stage",
        json={"stage": "payment_pending"},
    )
    client.post(
        f"/api/v1/quotations/{quoted_quotation.id}/stage",
        json={"stage": "delivery_pending"},
    )
    db.expire_all()
    fresh = db.get(type(quoted_quotation), quoted_quotation.id)
    assert fresh.despatched_at is None
    assert fresh.paid_at is None


def test_marking_won_records_both_dates(db, client, quoted_quotation):
    client.post(f"/api/v1/quotations/{quoted_quotation.id}/stage", json={"stage": "won"})
    db.expire_all()
    fresh = db.get(type(quoted_quotation), quoted_quotation.id)
    assert fresh.status is Q.PAID
    assert fresh.paid_at is not None


def test_moving_a_card_leaves_the_record_of_what_was_sent_alone(db, client, quoted_quotation):
    """The status is where it sits; the draft is what was actually said."""
    from app.models import DraftStatus, QuotationDraft

    draft = QuotationDraft(
        quotation_request_id=quoted_quotation.id, version=1, is_current=True,
        subject="Re: Enquiry", body="Our offer stands.",
        status=DraftStatus.APPROVED, generated_by="test",
    )
    db.add(draft)
    db.commit()

    client.post(
        f"/api/v1/quotations/{quoted_quotation.id}/stage", json={"stage": "negotiation"}
    )

    db.expire_all()
    kept = db.get(QuotationDraft, draft.id)
    assert kept.body == "Our offer stands."
    assert kept.status is DraftStatus.APPROVED


def test_the_move_is_recorded_against_the_quotation(db, client, quoted_quotation):
    client.post(
        f"/api/v1/quotations/{quoted_quotation.id}/stage",
        json={"stage": "negotiation", "reason": "customer rang about price"},
    )
    actions = [e["action"] for e in client.get("/api/v1/audit-logs").json()["items"]]
    assert "STAGE_CHANGED" in actions


# --- The dashboard ----------------------------------------------------------


def test_the_dashboard_reports_all_five_stages(client, quoted_quotation):
    body = client.get("/api/v1/dashboard/pipeline").json()
    assert [s["key"] for s in body["stages"]] == [
        "received", "sent", "negotiation", "delivery_pending", "payment_pending",
    ]


def test_a_moved_quotation_changes_which_stage_counts_it(client, quoted_quotation):
    def count(key: str) -> int:
        body = client.get("/api/v1/dashboard/pipeline").json()
        return next(s["count"] for s in body["stages"] if s["key"] == key)

    assert count("received") == 1
    assert count("negotiation") == 0

    client.post(
        f"/api/v1/quotations/{quoted_quotation.id}/stage", json={"stage": "negotiation"}
    )

    assert count("received") == 0
    assert count("negotiation") == 1


def test_the_interface_offers_exactly_the_stages_the_server_accepts():
    """The picker duplicates this list; a drift makes a button 422 on click."""
    import re
    from pathlib import Path

    # Anchored on this file, not the working directory: pytest is run from
    # the repo root and from `backend/`, and a relative path silently fails
    # under one of them.
    repo = Path(__file__).resolve().parents[2]
    panel = (repo / "frontend/src/components/QuotationDetailPanel.tsx").read_text()
    block = panel.split("const STAGES:", 1)[1].split("];", 1)[0]
    offered = re.findall(r'key: "([a-z_]+)"', block)

    for key in offered:
        assert key in STATUS_FOR_STAGE, f"the panel offers {key}, which the server rejects"

    # Every stage on the board must be reachable from the panel.
    for key, _, _ in COMMERCIAL_STAGES:
        assert key in offered, f"{key} is on the dashboard but not offered in the panel"


# --- Payment dates ----------------------------------------------------------
#
# Derived from the agreed terms and the despatch date, never typed in. A desk
# that waits to be told when money is due finds out late.


def test_the_credit_period_is_read_from_the_agreed_terms(db, quoted_quotation):
    from app.services.quotations.pipeline import payment_days

    for text, expected in (
        ("30 days", 30),
        ("Net 45 days from invoice", 45),
        ("60 DAYS", 60),
        ("100% advance", 0),
        ("Against delivery", 0),
    ):
        quoted_quotation.payment_terms = text
        assert payment_days(quoted_quotation) == expected, text


def test_unstated_terms_assume_a_month_rather_than_immediate(db, quoted_quotation):
    """Treating silence as "due today" reports every invoice overdue on ship."""
    from app.services.quotations.pipeline import DEFAULT_PAYMENT_DAYS, payment_days

    quoted_quotation.payment_terms = None
    if quoted_quotation.customer:
        quoted_quotation.customer.payment_terms = None
    assert payment_days(quoted_quotation) == DEFAULT_PAYMENT_DAYS == 30


def test_money_is_due_the_agreed_days_after_despatch(db, quoted_quotation):
    from datetime import date, timedelta

    from app.core.db import utcnow
    from app.services.quotations.pipeline import build

    quoted_quotation.status = Q.PAYMENT_PENDING
    quoted_quotation.despatched_at = utcnow() - timedelta(days=10)
    quoted_quotation.payment_terms = "30 days"
    db.commit()

    row = build(db).payments[0]
    assert row.due_on == (date.today() - timedelta(days=10)) + timedelta(days=30)
    assert row.days_overdue == 0, "twenty days still to run"


def test_an_invoice_past_its_terms_is_reported_overdue(db, quoted_quotation):
    from datetime import timedelta

    from app.core.db import utcnow
    from app.services.quotations.pipeline import build

    quoted_quotation.status = Q.PAYMENT_PENDING
    quoted_quotation.despatched_at = utcnow() - timedelta(days=45)
    quoted_quotation.payment_terms = "30 days"
    db.commit()

    pipeline = build(db)
    assert pipeline.payments[0].days_overdue == 15
    assert pipeline.overdue_count == 1


def test_a_paid_order_leaves_the_payment_table(db, quoted_quotation):
    from datetime import timedelta

    from app.core.db import utcnow
    from app.services.quotations.pipeline import build

    quoted_quotation.status = Q.PAYMENT_PENDING
    quoted_quotation.despatched_at = utcnow() - timedelta(days=45)
    db.commit()
    assert len(build(db).payments) == 1

    quoted_quotation.paid_at = utcnow()
    db.commit()
    assert build(db).payments == []


# --- Deliveries -------------------------------------------------------------


def test_a_won_order_shows_what_must_be_bought_to_ship_it(db, quoted_quotation):
    """The purchase decision, stated per order rather than left to arithmetic."""
    from app.services.quotations.pipeline import build

    quoted_quotation.status = Q.CUSTOMER_ACCEPTED
    quoted_quotation.despatched_at = None
    db.commit()

    row = build(db).deliveries[0]
    assert row.tonnes > 0
    assert row.in_stock_mt + row.to_buy_mt == row.tonnes


def test_a_despatched_order_leaves_the_delivery_table(db, quoted_quotation):
    from app.core.db import utcnow
    from app.services.quotations.pipeline import build

    quoted_quotation.status = Q.CUSTOMER_ACCEPTED
    quoted_quotation.despatched_at = None
    db.commit()
    assert len(build(db).deliveries) == 1

    quoted_quotation.despatched_at = utcnow()
    db.commit()
    assert build(db).deliveries == []


def test_the_pipeline_reports_tonnage_not_only_counts(db, client, quoted_quotation):
    """A steel desk runs on tonnage; twelve quotations is not a workload."""
    body = client.get("/api/v1/dashboard/pipeline").json()
    received = next(s for s in body["stages"] if s["key"] == "received")
    assert received["tonnes"] > 0
    assert "value" in received and "count" in received
