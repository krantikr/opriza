"""The quotation PDF that goes out attached to the email.

A customer forwards a quotation to whoever has to act on it, and an email body
does not survive that journey - it gets re-wrapped, stripped of its HTML, pasted
into another message. The PDF is what arrives intact, so these tests pin two
things: that it carries the same figures as the body, and that a host without
the rendering libraries degrades the mail instead of blocking the send.
"""

from __future__ import annotations

import email as email_lib
from decimal import Decimal

import pytest

from app.models import DraftStatus, QuotationDraft, QuotationPricing
from app.services.email.sender import Attachment, build_reply
from app.services.quotations import pdf as quotation_pdf
from app.services.quotations.table import build_rows


@pytest.fixture()
def drafted(db, quoted_quotation):
    """A quotation with a draft ready for review."""
    db.add(
        QuotationDraft(
            quotation_request_id=quoted_quotation.id,
            version=1,
            is_current=True,
            subject="Re: Enquiry - IS 2062 E250 Plate 10mm",
            body="Dear Rajesh Kumar,\n\nRate: Rs 59,200.00 per MT for 20 MT.\n\nRegards,\nSales Team",
            status=DraftStatus.GENERATED,
            generated_by="fake/model",
        )
    )
    db.commit()
    db.refresh(quoted_quotation)
    return quoted_quotation


def _price(db, quotation, *, cost: str = "50000", quote: str = "55000",
           qty: str = "20") -> None:
    item = quotation.line_items[0]
    db.add(
        QuotationPricing(
            quotation_line_item_id=item.id,
            quantity_mt=Decimal(qty),
            total_cost=Decimal(cost),
            quote_rate=Decimal(quote),
            line_total=Decimal(quote) * Decimal(qty),
            rules_version=1,
        )
    )
    db.commit()
    db.refresh(quotation)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def test_the_pdf_page_carries_the_same_table_as_the_email(db, quoted_quotation, default_user):
    """One definition of what a quotation looks like, not two."""
    _price(db, quoted_quotation)
    rows = build_rows(quoted_quotation)

    html = quotation_pdf.build_html(quoted_quotation, rows)

    assert quoted_quotation.quotation_number in html
    # The grade and the quoted rate both reach the page.
    assert "E250" in html
    assert "55,000" in html or "55000" in html


def test_the_page_names_the_customer_and_the_reference(db, quoted_quotation, default_user):
    _price(db, quoted_quotation)
    rows = build_rows(quoted_quotation)

    html = quotation_pdf.build_html(quoted_quotation, rows)

    assert "Quotation no." in html
    assert "Authorised signatory" in html
    assert "Terms" in html


def test_the_filename_is_the_quotation_number(db, quoted_quotation, default_user):
    assert quotation_pdf.filename(quoted_quotation) == (
        f"{quoted_quotation.quotation_number}.pdf"
    )


def test_a_quotation_with_no_priced_lines_produces_no_pdf(db, quoted_quotation, default_user):
    """A PDF of an empty table tells the customer nothing."""
    assert quotation_pdf.build(quoted_quotation, []) is None


def test_a_host_without_the_rendering_libraries_still_sends(
    db, quoted_quotation, default_user, monkeypatch
):
    """Missing Pango must degrade the mail, never block the send."""
    _price(db, quoted_quotation)
    rows = build_rows(quoted_quotation)

    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("libpango not found")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)

    assert quotation_pdf.build(quoted_quotation, rows) is None


def test_a_rendering_failure_is_swallowed_rather_than_raised(
    db, quoted_quotation, default_user, monkeypatch
):
    _price(db, quoted_quotation)
    rows = build_rows(quoted_quotation)
    monkeypatch.setattr(
        quotation_pdf, "build_html", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
    )

    assert quotation_pdf.build(quoted_quotation, rows) is None


# ---------------------------------------------------------------------------
# The MIME message
# ---------------------------------------------------------------------------


def test_an_attachment_keeps_the_text_and_html_parts_intact():
    """Attaching must not demote the body to a sibling of the file."""
    message = build_reply(
        to_address="buyer@example.com",
        subject="Quotation KK-000001",
        body="Please find our quotation below.",
        html_body="<p>Please find our quotation below.</p>",
        attachments=[Attachment(filename="KK-000001.pdf", content=b"%PDF-1.7 fake")],
    )

    parsed = email_lib.message_from_bytes(message.as_bytes())
    types = {part.get_content_type() for part in parsed.walk()}

    assert parsed.get_content_type() == "multipart/mixed"
    assert "text/plain" in types
    assert "text/html" in types
    assert "application/pdf" in types


def test_the_attachment_arrives_with_its_filename_and_bytes():
    payload = b"%PDF-1.7 pretend document"
    message = build_reply(
        to_address="buyer@example.com",
        subject="Quotation",
        body="body",
        attachments=[Attachment(filename="KK-000042.pdf", content=payload)],
    )

    parsed = email_lib.message_from_bytes(message.as_bytes())
    files = [p for p in parsed.walk() if p.get_filename()]

    assert len(files) == 1
    assert files[0].get_filename() == "KK-000042.pdf"
    assert files[0].get_payload(decode=True) == payload


def test_a_message_with_no_attachment_is_unchanged():
    """The common path must not become multipart/mixed for nothing."""
    message = build_reply(
        to_address="buyer@example.com",
        subject="Quotation",
        body="body",
        html_body="<p>body</p>",
    )

    assert email_lib.message_from_bytes(message.as_bytes()).get_content_type() == (
        "multipart/alternative"
    )


# ---------------------------------------------------------------------------
# End to end, through the approve route
# ---------------------------------------------------------------------------


def test_approving_sends_the_quotation_with_its_pdf(client, db, drafted, sent_dir):
    _price(db, drafted)

    response = client.post(f"/api/v1/quotations/{drafted.id}/approve", json={})
    assert response.status_code == 200

    sent = list(sent_dir.glob("*.eml"))
    assert len(sent) == 1

    parsed = email_lib.message_from_bytes(sent[0].read_bytes())
    files = [p for p in parsed.walk() if p.get_filename()]

    # WeasyPrint may be absent on the host running the suite; the send must
    # succeed either way, and when it is present the PDF must be a real one.
    if files:
        assert files[0].get_filename().endswith(".pdf")
        assert files[0].get_payload(decode=True).startswith(b"%PDF")
    assert any(p.get_content_type() == "text/plain" for p in parsed.walk())


@pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("weasyprint") is None,
    reason="WeasyPrint not installed",
)
def test_when_rendering_works_the_customer_really_gets_a_pdf(client, db, drafted, sent_dir):
    """Guards the happy path: the earlier test tolerates a host without Pango,
    which would let a silently-missing attachment pass unnoticed."""
    _price(db, drafted)
    if quotation_pdf.build(drafted, build_rows(drafted)) is None:
        pytest.skip("rendering libraries unavailable on this host")

    client.post(f"/api/v1/quotations/{drafted.id}/approve", json={})
    parsed = email_lib.message_from_bytes(next(sent_dir.glob("*.eml")).read_bytes())
    files = [p for p in parsed.walk() if p.get_filename()]

    assert len(files) == 1
    assert files[0].get_filename() == f"{drafted.quotation_number}.pdf"
    assert files[0].get_payload(decode=True).startswith(b"%PDF")


# ---------------------------------------------------------------------------
# The reviewer's preview
# ---------------------------------------------------------------------------


def test_the_preview_serves_the_markup_the_pdf_is_built_from(client, db, drafted):
    """Not a second rendering: a preview that could disagree with the file
    would be worse than no preview at all."""
    _price(db, drafted)

    response = client.get(f"/api/v1/quotations/{drafted.id}/attachment")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert drafted.quotation_number in response.text
    assert "Authorised signatory" in response.text


def test_the_preview_can_return_the_real_file(client, db, drafted):
    _price(db, drafted)

    response = client.get(f"/api/v1/quotations/{drafted.id}/attachment?fmt=pdf")

    # 503 when the host lacks the renderer, which is a stated outcome.
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        assert response.content.startswith(b"%PDF")
        assert drafted.quotation_number in response.headers["content-disposition"]


def test_a_quotation_with_no_rate_anywhere_has_nothing_to_preview(client, db, drafted):
    """A document that quotes nothing is not a quotation.

    A line carries a rate from its own pricing *or*, failing that, from the
    suggested rate on its stock availability - which is what the reviewer sees
    on screen. Only when neither exists is there nothing to attach.
    """
    item = drafted.line_items[0]
    if item.stock_availability is not None:
        item.stock_availability.suggested_rate = None
    db.commit()

    response = client.get(f"/api/v1/quotations/{drafted.id}/attachment")

    assert response.status_code == 404
    assert "no priced lines" in response.json()["detail"]


def test_a_suggested_rate_alone_is_enough_to_produce_the_document(client, db, drafted):
    """The document and the Pricing Calculator must not disagree about whether
    a rate exists."""
    response = client.get(f"/api/v1/quotations/{drafted.id}/attachment")

    assert response.status_code == 200
    assert drafted.quotation_number in response.text


# ---------------------------------------------------------------------------
# What counts as "there is a document to attach"
# ---------------------------------------------------------------------------


def test_a_rate_without_a_quantity_still_produces_a_document(db, quoted_quotation, default_user):
    """Quoting a rate against an unstated tonnage is an ordinary quotation.

    Regression: the gate used `TableRow.priced`, which means "has a line
    *amount*" and so needs a quantity. A customer who asks "what is your rate
    for 8mm plate?" gets a rate and no tonnage, and that quotation went out with
    no attachment at all.
    """
    from app.services.quotations.table import build_rows

    item = quoted_quotation.line_items[0]
    item.quantity_mt = None
    if item.stock_availability is not None:
        item.stock_availability.suggested_rate = Decimal("67000")
    db.commit()
    db.refresh(quoted_quotation)

    rows = build_rows(quoted_quotation)
    assert any(r.rate is not None for r in rows)
    assert not any(r.priced for r in rows), "no quantity, so no line amount"

    assert quotation_pdf.build(quoted_quotation, rows) is not None


def test_the_meta_pairs_read_as_label_then_value(db, quoted_quotation, default_user):
    """`Date: 23 Aug 2026`, not a label stranded from its value.

    The colon rides on the label and the label column collapses onto its own
    text, so the gap falls between the two pairs rather than inside either one.
    """
    from app.services.quotations.table import build_rows

    html = quotation_pdf.build_html(quoted_quotation, build_rows(quoted_quotation))

    assert "Quotation no.:" in html
    assert "Date:" in html
    assert "Delivery:" in html
    # The right-hand pair is pushed out by the left value column, not by
    # right-aligning the text - which would strand the value from its label.
    assert 'class="v v-left"' in html
    assert 'class="v v-right"' in html
