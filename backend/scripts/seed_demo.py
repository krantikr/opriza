"""Seed a self-contained demo desk for the marketing screenshots.

Everything is fictional: the buyers, the mills, the tonnages, the prices.
It lives in its own organisation (id 5) so no real desk's data is read or
written at any point.

Idempotent: wipes and re-seeds the demo org's own rows each run.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.core.tenancy import bind_session
from app.models import (
    Customer,
    Email,
    EmailCategory,
    EmailSourceType,
    MailDirection,
    Organisation,
    PriorityProduct,
    ProcessingStatus,
    QuotationDraft,
    QuotationLineItem,
    QuotationPricing,
    QuotationRequest,
    QuotationStatus,
    StockItem,
    User,
)
from app.models.enums import DraftStatus
from app.models.ops import CustomerNote
from app.models.pricing import SalesInvoice

ORG = 5
random.seed(7)
NOW = datetime.now(UTC)

BUYERS = [
    ("Bharat Engineering Works", "purchase@bharatengg.co.in", "Rakesh Menon"),
    ("Sunrise Fabricators", "procurement@sunrisefab.in", "Anita Deshpande"),
    ("Deccan Structurals", "buying@deccanstructurals.com", "Vikram Rao"),
    ("Konkan Boilers", "stores@konkanboilers.in", "Sameer Joshi"),
    ("Godavari Infra", "materials@godavariinfra.com", "Priya Nair"),
    ("Trident Pressure Vessels", "scm@tridentpv.co.in", "Arun Kulkarni"),
]

MILLS = ["JSPL", "SAIL", "TATA", "ESSAR", "AMNS"]
LOCATIONS = ["Nagpur", "Jamshedpur", "Raipur", "Taloja", "Rourkela"]

# (product, grade, thk, width, length, mill, location, tonnes, cost/MT, age days)
STOCK = [
    ("Plate", "IS2062 E250BR", 8, 1250, 5800, "SAIL", "Nagpur", 62.4, 58200, 18),
    ("Plate", "IS2062 E250BR", 10, 1500, 6300, "TATA", "Nagpur", 48.9, 59100, 32),
    ("Plate", "IS2062 E250BR", 12, 2000, 6300, "SAIL", "Jamshedpur", 74.2, 58650, 11),
    ("Plate", "IS2062 E350", 16, 2000, 6300, "JSPL", "Jamshedpur", 55.1, 62400, 47),
    ("Plate", "IS2062 E350", 20, 2500, 6300, "JSPL", "Raipur", 39.7, 63100, 63),
    ("Plate", "IS2062 E350", 25, 2500, 6300, "AMNS", "Raipur", 28.3, 64250, 74),
    ("Plate", "SA516 Gr70", 12, 2200, 6300, "ESSAR", "Taloja", 33.6, 78400, 26),
    ("Plate", "SA516 Gr70", 16, 2200, 6300, "ESSAR", "Taloja", 41.2, 79100, 39),
    ("Plate", "SA516 Gr70", 20, 2500, 8000, "AMNS", "Taloja", 22.8, 80350, 92),
    ("Plate", "C-45", 8, 1250, 5800, "JSPL", "Nagpur", 19.4, 71800, 21),
    ("Plate", "C-45", 12, 1500, 6000, "JSPL", "Nagpur", 26.7, 72450, 44),
    ("Coil", "IS2062 E250", 3, 1250, None, "TATA", "Rourkela", 88.5, 55900, 15),
    ("Coil", "IS2062 E250", 4, 1500, None, "SAIL", "Rourkela", 71.3, 56300, 29),
    ("Coil", "IS2062 E250", 5, 1500, None, "TATA", "Nagpur", 64.8, 56850, 53),
    ("Coil", "IS2062 E350", 6, 1500, None, "JSPL", "Raipur", 52.6, 60200, 37),
    ("Angle", "IS2062 E250", 6, 65, 6000, "SAIL", "Nagpur", 17.9, 57400, 22),
    ("Angle", "IS2062 E250", 8, 75, 6000, "SAIL", "Jamshedpur", 23.5, 57900, 58),
    ("Beam", "IS2062 E250", None, 150, 12000, "JSPL", "Raipur", 46.2, 61300, 33),
    ("Beam", "IS2062 E250", None, 200, 12000, "JSPL", "Jamshedpur", 58.7, 61850, 19),
    ("Channel", "IS2062 E250", None, 100, 6000, "SAIL", "Nagpur", 31.4, 58750, 41),
]

# (buyer idx, product, grade, thk, w, l, tonnes, status, days ago, rate/MT)
DEALS = [
    (0, "Plate", "IS2062 E250BR", 12, 2000, 6300, 42.0, QuotationStatus.PAID, 34, 66800),
    (1, "Plate", "SA516 Gr70", 16, 2200, 6300, 28.5, QuotationStatus.PAID, 29, 89400),
    (2, "Coil", "IS2062 E250", 4, 1500, None, 55.0, QuotationStatus.PAID, 25, 63200),
    (3, "Plate", "IS2062 E350", 20, 2500, 6300, 31.2, QuotationStatus.PAID, 21, 71500),
    (4, "Beam", "IS2062 E250", None, 200, 12000, 38.6, QuotationStatus.PAYMENT_PENDING, 17, 69800),
    (5, "Plate", "SA516 Gr70", 12, 2200, 6300, 24.4, QuotationStatus.PAYMENT_PENDING, 14, 88100),
    (0, "Plate", "IS2062 E250BR", 8, 1250, 5800, 33.8, QuotationStatus.CUSTOMER_ACCEPTED, 11, 65400),
    (2, "Angle", "IS2062 E250", 8, 75, 6000, 18.2, QuotationStatus.CUSTOMER_ACCEPTED, 9, 64900),
    (1, "Plate", "IS2062 E350", 16, 2000, 6300, 44.5, QuotationStatus.NEGOTIATION, 8, 70200),
    (3, "Coil", "IS2062 E350", 6, 1500, None, 36.9, QuotationStatus.NEGOTIATION, 6, 67600),
    (4, "Plate", "C-45", 12, 1500, 6000, 21.3, QuotationStatus.SENT, 5, 81200),
    (5, "Plate", "IS2062 E250BR", 10, 1500, 6300, 29.7, QuotationStatus.SENT, 4, 66100),
    (0, "Channel", "IS2062 E250", None, 100, 6000, 26.1, QuotationStatus.SENT, 3, 65700),
    (2, "Plate", "SA516 Gr70", 20, 2500, 8000, 19.8, QuotationStatus.SENT, 2, 90300),
    (1, "Coil", "IS2062 E250", 5, 1500, None, 47.2, QuotationStatus.READY_FOR_REVIEW, 1, 63800),
    (3, "Plate", "IS2062 E350", 25, 2500, 6300, 22.6, QuotationStatus.READY_FOR_REVIEW, 0, 72400),
    (4, "Plate", "IS2062 E250BR", 12, 2000, 6300, 51.4, QuotationStatus.READY_FOR_REVIEW, 0, 66500),
]


def spec(p, g, t, w, l):
    dims = " x ".join(str(int(d)) for d in (t, w, l) if d)
    return f"{g} {p} {dims} mm" if dims else f"{g} {p}"


def wipe(db):
    """Clear the demo org only. Ordered so FKs never block."""
    q_ids = [
        r for r in db.scalars(
            select(QuotationRequest.id).where(QuotationRequest.organisation_id == ORG)
        )
    ]
    li_ids = [
        r for r in db.scalars(
            select(QuotationLineItem.id).where(
                QuotationLineItem.quotation_request_id.in_(q_ids or [-1])
            )
        )
    ]
    db.execute(delete(QuotationPricing).where(
        QuotationPricing.quotation_line_item_id.in_(li_ids or [-1])))
    db.execute(delete(QuotationDraft).where(QuotationDraft.organisation_id == ORG))
    db.execute(delete(QuotationLineItem).where(QuotationLineItem.organisation_id == ORG))
    # Emails first: they carry FKs both ways (a quotation owns its enquiry
    # mail, and a reply points back at the quotation), so the quotations
    # cannot go while any mail still references them.
    db.execute(delete(Email).where(Email.organisation_id == ORG))
    db.execute(delete(QuotationRequest).where(QuotationRequest.organisation_id == ORG))
    db.execute(delete(StockItem).where(StockItem.organisation_id == ORG))
    db.execute(delete(PriorityProduct).where(PriorityProduct.organisation_id == ORG))
    # Both hang off customers, so they clear before the customers do.
    db.execute(delete(SalesInvoice).where(SalesInvoice.organisation_id == ORG))
    db.execute(delete(CustomerNote).where(CustomerNote.organisation_id == ORG))
    db.execute(delete(Customer).where(Customer.organisation_id == ORG))
    db.commit()


def main():
    with SessionLocal() as db:
        bind_session(db, ORG)
        wipe(db)

        org = db.get(Organisation, ORG)
        org.name = "Meridian Steel Traders"
        org.slug = "meridian-steel"

        user = db.scalars(select(User).where(User.organisation_id == ORG)).first()
        if user:
            user.name = "Operations"
            user.email = "desk@meridiansteel.in"

        # --- Stock ---------------------------------------------------------
        for i, (p, g, t, w, l, mill, loc, tonnes, cost, age) in enumerate(STOCK):
            db.add(StockItem(
                organisation_id=ORG,
                product_type=p, grade=g,
                thickness_mm=t, width_mm=w, length_mm=l,
                make=mill, location=loc,
                coil_no=f"{mill[:2].upper()}-{4100 + i * 37}",
                qty_kg=Decimal(str(round(tonnes * 1000, 2))),
                balance_qty_kg=Decimal(str(round(tonnes * 1000, 2))),
                nop=max(1, int(tonnes / 2.4)),
                balance_nop=max(1, int(tonnes / 2.4)),
                purchase_rate_per_kg=Decimal(str(round(cost / 1000, 3))),
                landed_cost_per_kg=Decimal(str(round(cost / 1000, 3))),
                stock_date=(NOW - timedelta(days=age)).date(),
            ))

        db.add(PriorityProduct(organisation_id=ORG, grade="SA516 Gr70", make="ESSAR"))

        # --- Customers -----------------------------------------------------
        cust = {}
        for i, (name, email, contact) in enumerate(BUYERS):
            c = Customer(
                organisation_id=ORG, name=name, email=email,
                company=name, is_priority=(i == 0), is_verified=True,
                default_delivery_location=LOCATIONS[i % len(LOCATIONS)],
                payment_terms="30 days from receipt",
            )
            db.add(c)
            cust[i] = c
        db.flush()

        # --- Deals ---------------------------------------------------------
        for n, (bi, p, g, t, w, l, tonnes, status, days, rate) in enumerate(DEALS, start=1):
            name, email, contact = BUYERS[bi]
            raised = NOW - timedelta(days=days, hours=random.randint(1, 7))
            desc = spec(p, g, t, w, l)

            mail = Email(
                organisation_id=ORG,
                message_id=f"demo:enq-{n}",
                thread_id=f"demo-thread-{n}",
                source=EmailSourceType.LOCAL,
                sender_email=email, sender_name=contact,
                subject=f"Enquiry — {desc}",
                body_text=(
                    f"Dear Sir,\n\nKindly quote your best rate for the following, "
                    f"delivered to our {LOCATIONS[bi % len(LOCATIONS)]} works:\n\n"
                    f"  {desc}\n  Quantity: {tonnes} MT\n\n"
                    f"Please confirm material test certificates and delivery "
                    f"schedule along with your offer.\n\nRegards,\n{contact}\n{name}"
                ),
                snippet=f"Kindly quote your best rate for {desc}, quantity {tonnes} MT.",
                received_at=raised,
                processing_status=ProcessingStatus.PROCESSED,
                category=EmailCategory.QUOTATION_REQUEST,
                classification_confidence=round(random.uniform(0.91, 0.98), 2),
                classification_reason=(
                    "The email requests a price quotation for a specific "
                    "material, quantity and delivery location."
                ),
                direction=MailDirection.INBOUND,
                processing_ms=random.randint(74_000, 138_000),
            )
            db.add(mail)
            db.flush()

            sent_at = None
            if status not in (QuotationStatus.READY_FOR_REVIEW,):
                sent_at = raised + timedelta(hours=random.randint(2, 9))

            q = QuotationRequest(
                organisation_id=ORG,
                quotation_number=f"MS-{2400 + n:06d}"[:12],
                email_id=mail.id,
                customer_id=cust[bi].id,
                customer_name_raw=contact,
                customer_company_raw=name,
                customer_email=email,
                status=status,
                delivery_location=LOCATIONS[bi % len(LOCATIONS)],
                required_delivery_date="within 3 weeks",
                payment_terms="30 days from receipt of material",
                sent_at=sent_at,
                despatched_at=(
                    sent_at + timedelta(days=6)
                    if status in (QuotationStatus.PAID, QuotationStatus.PAYMENT_PENDING)
                    else None
                ),
                created_at=raised,
            )
            db.add(q)
            db.flush()

            item = QuotationLineItem(
                organisation_id=ORG,
                quotation_request_id=q.id,
                line_no=1,
                raw_text=desc,
                product_type=p, grade=g,
                thickness_mm=t, width_mm=w, length_mm=l,
                quantity=Decimal(str(tonnes)), quantity_unit="MT",
                quantity_mt=Decimal(str(tonnes)),
                match_status="MATCH_FOUND", match_score=97,
            )
            db.add(item)
            db.flush()

            cost = next(
                (s[8] for s in STOCK if s[1] == g and s[0] == p),
                58000,
            )
            db.add(QuotationPricing(
                organisation_id=ORG,
                quotation_line_item_id=item.id,
                basis="STOCK",
                base_rate=Decimal(str(cost)),
                total_cost=Decimal(str(round(cost * 1.031, 2))),
                margin_amount=Decimal(str(round(rate - cost * 1.031, 2))),
                quote_rate=Decimal(str(rate)),
                line_total=Decimal(str(round(rate * tonnes, 2))),
                quantity_mt=Decimal(str(tonnes)),
                currency="INR",
                rules_version=1,
                components=[
                    {"code": "base_price", "label": "Base purchase price",
                     "kind": "BASE_PRICE", "amount": f"{cost:.2f}",
                     "note": "Landed cost of the matched lot",
                     "applied": True, "overridden": False,
                     "computed_amount": None, "subtotal": None, "meta": {}},
                    {"code": "transport", "label": "Transportation",
                     "kind": "TRANSPORT", "amount": "780.00",
                     "note": f"Road freight to {LOCATIONS[bi % len(LOCATIONS)]}",
                     "applied": True, "overridden": False,
                     "computed_amount": None, "subtotal": None, "meta": {}},
                    {"code": "handling", "label": "Loading / unloading",
                     "kind": "HANDLING", "amount": "300.00",
                     "note": "Standard handling at both ends",
                     "applied": True, "overridden": False,
                     "computed_amount": None, "subtotal": None, "meta": {}},
                    {"code": "finance", "label": "Financing cost",
                     "kind": "FINANCE", "amount": f"{cost * 0.0128:.2f}",
                     "note": "30 days credit at 15.5% per annum",
                     "applied": True, "overridden": False,
                     "computed_amount": None, "subtotal": None, "meta": {}},
                    {"code": "risk", "label": "Other / risk buffer",
                     "kind": "RISK", "amount": "200.00",
                     "note": "Rolling tolerance and weighbridge variance",
                     "applied": True, "overridden": False,
                     "computed_amount": None, "subtotal": None, "meta": {}},
                    {"code": "target_margin", "label": "Target margin",
                     "kind": "TARGET_MARGIN",
                     "amount": f"{rate - cost * 1.031:.2f}",
                     "note": "Desk target of 6% on landed cost",
                     "applied": True, "overridden": False,
                     "computed_amount": None, "subtotal": None, "meta": {}},
                ],
                warnings=[],
            ))

            if sent_at:
                db.add(QuotationDraft(
                    organisation_id=ORG,
                    quotation_request_id=q.id, version=1, is_current=True,
                    subject=f"Quotation {q.quotation_number} — {desc}",
                    body=(
                        f"Dear {contact},\n\nThank you for your enquiry. We are "
                        f"pleased to quote as follows:\n\n"
                        f"  Material : {desc}\n  Quantity : {tonnes} MT\n"
                        f"  Rate     : Rs {rate:,}/MT\n"
                        f"  Delivery : FOR {LOCATIONS[bi % len(LOCATIONS)]}, "
                        f"within 3 weeks\n  Payment  : 30 days from receipt\n\n"
                        f"Material test certificates will accompany the "
                        f"despatch.\n\nRegards,\nMeridian Steel Traders"
                    ),
                    status=DraftStatus.SENT,
                ))

                # A reply on some threads, so the follow-up board has life.
                if n % 3 == 0:
                    db.add(Email(
                        organisation_id=ORG,
                        message_id=f"demo:reply-{n}",
                        thread_id=mail.thread_id,
                        source=EmailSourceType.LOCAL,
                        sender_email=email, sender_name=contact,
                        subject=f"Re: Quotation {q.quotation_number}",
                        body_text=(
                            "Thank you for the offer. Can you improve the rate "
                            "slightly if we take the full quantity in one lot? "
                            "Also confirm the delivery schedule."
                        ),
                        snippet="Can you improve the rate slightly if we take the full quantity?",
                        received_at=sent_at + timedelta(days=random.randint(1, 3)),
                        processing_status=ProcessingStatus.PROCESSED,
                        category=EmailCategory.PRICE_NEGOTIATION,
                        classification_confidence=0.94,
                        direction=MailDirection.INBOUND,
                        replied_to_quotation_id=q.id,
                        awaiting_us=True,
                    ))

        db.commit()
        print("Seeded demo org:", org.name)
        print("  stock lots :", len(STOCK))
        print("  customers  :", len(BUYERS))
        print("  quotations :", len(DEALS))


if __name__ == "__main__":
    main()
