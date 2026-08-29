"""The quotation table as a PDF attachment.

A customer forwards a quotation to somebody who has to act on it - a purchase
manager, an accounts department - and an email body does not survive that
journey intact. It gets quoted, re-wrapped, stripped of its HTML, pasted into
another mail. A PDF arrives as the same document every time, and it is what a
buyer prints and walks into a meeting with.

The page is rendered from the *same* `render_html` table the email body uses,
wrapped in a letterhead. Drawing it a second time in a PDF-specific layout
engine would create two definitions of what a quotation looks like, and they
would drift the first time a column changed.

WeasyPrint needs Pango and Cairo present on the host. When they are missing,
`build` returns None rather than raising: a quotation that reaches the customer
without its attachment is a much smaller failure than one that never sends at
all, and the caller records the reason.
"""

from __future__ import annotations

from datetime import date
from html import escape

from app.core.config import settings
from app.core.logging import get_logger
from app.models import QuotationRequest
from app.services.quotations.table import TableRow, render_html

logger = get_logger(__name__)

#: Print styling. The screen table is styled inline for Gmail's benefit; a PDF
#: has no such constraint, so page furniture lives in a stylesheet here.
STYLES = """
@page {
  size: A4;
  margin: 14mm 12mm 16mm;
  @bottom-center {
    content: "Page " counter(page) " of " counter(pages);
    font-family: Arial, sans-serif; font-size: 8pt; color: #64748B;
  }
}
body { font-family: Arial, Helvetica, sans-serif; font-size: 10pt; color: #111; margin: 0; }

/* On screen the same markup is shown as the sheet it will become: A4 wide,
   with the page margin drawn rather than implied. `@page` governs paper only,
   so without this the preview stretches to the window and the reviewer checks
   a layout the customer will never see. WeasyPrint ignores a `screen` block,
   so the PDF is unaffected. */
@media screen {
  body {
    background: #F1F5F9;
    padding: 24px 12px;
  }
  .page {
    width: 210mm;
    min-height: 297mm;
    margin: 0 auto;
    padding: 14mm 12mm 16mm;
    background: #FFFFFF;
    box-shadow: 0 1px 4px rgba(15, 23, 42, .18);
    box-sizing: border-box;
  }
}
.head { border-bottom: 2px solid #0F172A; padding-bottom: 8px; margin-bottom: 14px; }
.org { font-size: 15pt; font-weight: bold; letter-spacing: .2px; }
.tag { font-size: 9pt; color: #B45309; font-weight: bold; margin-top: 2px; }
.contact { font-size: 8pt; color: #475569; margin-top: 4px; }
/* Key and value stay together as a pair. Aligning the right-hand column to the
   page edge strands its value half a page from the label that names it, and the
   reader has to track across whitespace to pair them up again. */
/* `table-layout: auto` on a table with no set width still hands each column a
   share of the space, which reopens the gap between a label and its value.
   Fixing the label columns to 1% collapses them onto their own text, and the
   value columns absorb the remainder. */
.meta { width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 9pt; }
.meta td { padding: 2px 0; vertical-align: top; }
/* Label columns collapse onto their own text so the colon stays against its
   value. The *first* value column takes the slack, which pushes the second
   pair out to the right margin - the two pairs then sit at the page's edges
   with the gap between them rather than inside either one. */
.meta .k { width: 1%; }
.meta .v-left { width: 99%; }
.meta .v-right { width: 1%; text-align: left; }
/* `Label: value`, with the colon carried by the label so the pair reads as one
   phrase. The separation that matters is between *pairs*, not inside them - so
   the gap is spent on the value's right padding, not the label's. */
.meta .k { color: #64748B; padding-right: 1.5mm; white-space: nowrap; }
.meta .v { font-weight: bold; white-space: nowrap; }
h1 { font-size: 11pt; margin: 0 0 8px; text-transform: uppercase; letter-spacing: .08em; }
table { width: 100%; }
.terms { margin-top: 14px; font-size: 8.5pt; color: #475569; line-height: 1.5; }
.terms b { color: #111; }
.sign { margin-top: 18px; font-size: 9pt; }
.sign .for { font-weight: bold; }
.sign .rule { margin-top: 16mm; border-top: 1px solid #94A3B8; width: 55mm; padding-top: 3px;
  font-size: 8pt; color: #64748B; }
"""


def _reference(quotation: QuotationRequest) -> str:
    return quotation.quotation_number or f"Q-{quotation.id}"


def build_html(quotation: QuotationRequest, rows: list[TableRow]) -> str:
    """The printable page: letterhead, the same table, terms, signature."""
    customer = (
        quotation.customer_company_raw
        or quotation.customer_name_raw
        or quotation.customer_email
        or "—"
    )
    tagline = settings.company_tagline or ""
    table = render_html(rows)

    contact = " · ".join(
        part for part in (settings.company_email, settings.company_phone) if part
    )

    validity = quotation.payment_terms or ""
    delivery = quotation.delivery_location or ""

    meta_rows = [
        ("Quotation no.:", escape(_reference(quotation)), "Date:",
         date.today().strftime("%d %b %Y")),
        ("Customer:", escape(customer), "Delivery:", escape(delivery or "—")),
    ]
    meta = "".join(
        f'<tr><td class="k">{k1}</td><td class="v v-left">{v1}</td>'
        f'<td class="k">{k2}</td><td class="v v-right">{v2}</td></tr>'
        for k1, v1, k2, v2 in meta_rows
    )

    terms = [
        "Rates are per MT, ex-stock, and exclusive of GST unless stated otherwise.",
        "Material is subject to prior sale; availability is confirmed on order.",
    ]
    if validity:
        terms.insert(0, f"Payment terms: {escape(validity)}.")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{escape(_reference(quotation))}</title>
<style>{STYLES}</style></head><body>
<div class="page">
<div class="head">
  <div class="org">{escape(settings.company_name)}</div>
  {f'<div class="tag">{escape(tagline)}</div>' if tagline else ""}
  {f'<div class="contact">{escape(contact)}</div>' if contact else ""}
</div>

<h1>Quotation</h1>
<table class="meta">{meta}</table>

{table}

<div class="terms">
  <b>Terms</b><br>
  {"<br>".join(escape(t) if not t.startswith("Payment") else t for t in terms)}
</div>

<div class="sign">
  <div class="for">For {escape(settings.company_name)}</div>
  <div class="rule">Authorised signatory</div>
</div>
</div>
</body></html>"""


def build(quotation: QuotationRequest, rows: list[TableRow]) -> bytes | None:
    """Render the quotation to PDF bytes, or None if it cannot be produced.

    Returns None for a quotation with no priced lines - a PDF of an empty table
    tells the customer nothing - and when the rendering libraries are absent,
    so a missing system package degrades the mail rather than blocking it.
    """
    # A line with no rate still produces a row, so "has rows" is not the test.
    # But `priced` means "has a line *amount*", which needs a quantity - and a
    # quotation that states a rate against an unspecified tonnage is a perfectly
    # ordinary one to send. The test is therefore a rate, not an amount.
    if not any(row.rate is not None for row in rows):
        return None

    try:
        from weasyprint import HTML
    except Exception as exc:  # noqa: BLE001 - absence is a deployment state
        logger.warning("PDF attachment skipped, WeasyPrint unavailable: %s", exc)
        return None

    try:
        return HTML(string=build_html(quotation, rows)).write_pdf()
    except Exception as exc:  # noqa: BLE001 - never block a send on the attachment
        logger.error("PDF rendering failed for %s: %s", _reference(quotation), exc)
        return None


def filename(quotation: QuotationRequest) -> str:
    reference = _reference(quotation).replace("/", "-").replace(" ", "-")
    return f"{reference}.pdf"


__all__ = ["build", "build_html", "filename"]
