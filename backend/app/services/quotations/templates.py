"""Fixed email templates, filled from settled figures.

A follow-up says the same thing every time; only the quotation it chases and
the money at stake change. That makes it a template, not a writing task - and
running it through a language model would spend a call, introduce variation
the desk did not ask for, and put a figure in an email by a route nothing
verifies.

So the wording is stored per desk and the values are substituted here, in
code. The figures come from the same `build_rows`/`totals` pair that renders
the quotation table and the PDF, so a follow-up cannot quote a different total
from the document it is chasing.

Placeholders are `{{name}}`. An unknown placeholder is left untouched rather
than blanked: a desk that typed `{{contact_mobile}}` expecting it to work
should see the mistake, not send an email with a hole where a phone number
was meant to be.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.models import Organisation, QuotationRequest
from app.services.quotations.table import build_rows, format_inr, totals

#: `{{ name }}` with optional inner whitespace.
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}", re.IGNORECASE)

DEFAULT_FOLLOWUP_SUBJECT = "Re: {{original_subject}}"

DEFAULT_FOLLOWUP_BODY = """Dear {{customer_name}},

Following up on quotation {{quotation_number}}, sent on {{sent_date}}, for a
total of {{total_amount}}. Wanted to check if you had a chance to review it and
see if you have any questions, or would like to go ahead.

Happy to help with anything you need.

Regards,
{{signatory}}
{{company_name}}"""

#: Every placeholder a template may use, with a line of help. Drives both the
#: substitution below and the reference shown beside the editor - one list, so
#: the documentation cannot drift from what actually resolves.
PLACEHOLDERS: tuple[tuple[str, str], ...] = (
    ("customer_name", "Who the email is addressed to"),
    ("customer_company", "Their company, where one is known"),
    ("quotation_number", "This quotation's reference"),
    ("original_subject", "The subject line of their enquiry"),
    ("sent_date", "When the quotation went out"),
    ("total_amount", "Order total, e.g. INR 12,26,351.40"),
    ("total_weight", "Total tonnage, e.g. 20.00 MT"),
    ("item_count", "How many lines are on the quotation"),
    ("delivery_location", "Where it is going"),
    ("signatory", "Who signs off, from the desk's settings"),
    ("company_name", "The desk's own name"),
)


def _values(quotation: QuotationRequest, organisation: Organisation | None) -> dict[str, str]:
    """What each placeholder resolves to for this quotation."""
    from app.core.config import settings

    rows = build_rows(quotation)
    total_weight, total_amount = totals(rows)

    name = (
        quotation.customer_name_raw
        or quotation.customer_company_raw
        or "Sir/Madam"
    )
    original = quotation.email.subject if quotation.email else None
    signatory = (
        (organisation.company_signatory if organisation else None)
        or settings.company_signatory
    )
    company = (organisation.name if organisation else None) or settings.company_name

    return {
        "customer_name": name,
        "customer_company": quotation.customer_company_raw or "",
        "quotation_number": quotation.quotation_number,
        "original_subject": original or f"Quotation {quotation.quotation_number}",
        "sent_date": (
            quotation.sent_at.strftime("%d %b %Y") if quotation.sent_at else "recently"
        ),
        # Blank rather than "0.00" when nothing is priced: a zero is a stated
        # price, and a follow-up must not invent one.
        "total_amount": f"INR {format_inr(total_amount)}" if total_amount is not None else "",
        "total_weight": f"{total_weight} MT" if total_weight else "",
        "item_count": str(len(rows)),
        "delivery_location": quotation.delivery_location or "",
        "signatory": signatory,
        "company_name": company,
    }


def render(template: str, quotation: QuotationRequest,
           organisation: Organisation | None = None) -> str:
    """Substitute every known placeholder in `template`."""
    values = _values(quotation, organisation)

    def swap(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        # Unknown placeholders survive verbatim - see the module docstring.
        return values.get(key, match.group(0))

    text = _PLACEHOLDER.sub(swap, template or "")

    # A placeholder that resolved to nothing can leave a stranded blank line
    # ("sent on , for a total of ."). Tidy the spacing rather than the words.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def followup_subject(quotation: QuotationRequest,
                     organisation: Organisation | None = None) -> str:
    template = (
        (organisation.followup_subject_template if organisation else None)
        or DEFAULT_FOLLOWUP_SUBJECT
    )
    subject = render(template, quotation, organisation)
    # Threading depends on the Re: prefix surviving whatever the desk typed.
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    return subject[:500]


def followup_body(quotation: QuotationRequest,
                  organisation: Organisation | None = None) -> str:
    template = (
        (organisation.followup_body_template if organisation else None)
        or DEFAULT_FOLLOWUP_BODY
    )
    return render(template, quotation, organisation)


# --- The quotation reply ----------------------------------------------------
#
# The model writes the prose; the figures were never its to author. These two
# functions are the seam: `templatise` takes the text it produced and puts the
# money back behind placeholders, and `render_quotation_body` fills them from
# the calculator. A price change then re-renders in code, with no second
# generation and no wording lost.

#: Figures a quotation reply may legitimately state, in the order they are
#: substituted. Longest values first, so a line total is never partly matched
#: by a rate that happens to share its leading digits.
_QUOTATION_FIGURES = ("total_amount", "total_weight")


def _line_figures(quotation: QuotationRequest) -> dict[str, Decimal]:
    """Per-line rates and amounts, keyed by the placeholder that carries them."""
    figures: dict[str, Decimal] = {}
    for row in build_rows(quotation):
        if row.rate is not None:
            figures[f"line_{row.sr_no}_rate"] = Decimal(str(row.rate))
        if row.amount is not None:
            figures[f"line_{row.sr_no}_amount"] = Decimal(str(row.amount))
    return figures


def quotation_values(quotation: QuotationRequest,
                     organisation: Organisation | None = None) -> dict[str, str]:
    """Every placeholder a quotation reply may use, resolved."""
    values = _values(quotation, organisation)
    for key, figure in _line_figures(quotation).items():
        values[key] = format_inr(figure)
    return values


def templatise(body: str, quotation: QuotationRequest) -> str:
    """Put the money in `body` back behind placeholders.

    The model was handed the figures and told to reproduce them exactly, so
    the text it returns contains them verbatim. Swapping each one for the
    placeholder that produced it turns a fixed document back into a template -
    without touching a word of the prose, which is the part worth keeping.

    Matching is on the *rendered* form, because that is what the model was
    given and what it echoed. A figure it altered simply does not match and is
    left alone; `verify_draft_facts` is what catches that, and silently
    rewriting a wrong number into a right-looking placeholder would hide
    exactly the failure that check exists to surface.
    """
    if not body:
        return body

    rows = build_rows(quotation)
    _, total_amount = totals(rows)

    # Longest rendered figure first: "1,22,000.00" contains "22,000.00", and
    # substituting the shorter one first would leave a mangled prefix behind.
    candidates: list[tuple[str, str]] = []
    for key, figure in _line_figures(quotation).items():
        candidates.append((format_inr(figure), key))
    if total_amount is not None:
        candidates.append((format_inr(total_amount), "total_amount"))

    out = body
    for rendered, key in sorted(candidates, key=lambda c: len(c[0]), reverse=True):
        if not rendered or rendered == "-":
            continue
        out = out.replace(rendered, f"{{{{{key}}}}}")
    return out


def render_quotation_body(template: str, quotation: QuotationRequest,
                          organisation: Organisation | None = None) -> str:
    """Fill a stored draft template from the pricing as it now stands."""
    values = quotation_values(quotation, organisation)

    def swap(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        return values.get(key, match.group(0))

    return _PLACEHOLDER.sub(swap, template or "")


def preview_values(quotation: QuotationRequest,
                   organisation: Organisation | None = None) -> dict[str, str]:
    """What the placeholders resolve to, for the editor's live preview."""
    return _values(quotation, organisation)


__all__ = [
    "DEFAULT_FOLLOWUP_BODY",
    "DEFAULT_FOLLOWUP_SUBJECT",
    "PLACEHOLDERS",
    "followup_body",
    "followup_subject",
    "quotation_values",
    "render_quotation_body",
    "templatise",
    "preview_values",
    "render",
]
