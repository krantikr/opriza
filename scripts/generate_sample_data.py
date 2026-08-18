"""Generate realistic sample steel data and enquiry emails.

Produces the four Excel files a steel trader would actually hand over, plus a
set of `.eml` enquiries that exercise every branch of the pipeline - clean
single-item, multi-item, missing quantity, ambiguous product, unknown product,
and the non-quotation categories the MVP must record but not answer.

Deterministic: the same seed produces the same files, so tests and demos are
reproducible.

    uv run python scripts/generate_sample_data.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

import pandas as pd

from app.core.paths import SAMPLE_DIR
from app.services.products.weights import Dimensions, weight_kg_per_piece

SEED = 20260816
EMAIL_DIR = SAMPLE_DIR / "emails"

# Standard sectional weights (kg/m) for rolled sections. No simple formula
# reproduces these, so they come from the standards and are stored on the
# product master for the weight service to use.
ISMC_KG_PER_M = {75: 7.14, 100: 9.56, 125: 13.1, 150: 16.8, 200: 22.3, 250: 30.6}
ISMB_KG_PER_M = {100: 11.5, 125: 13.3, 150: 14.9, 200: 25.4, 250: 37.3, 300: 44.2}

# Indicative INR/MT base prices by product form.
BASE_PRICE_BY_TYPE = {
    "Plate": 56500,
    "Sheet": 58500,
    "Coil": 55000,
    "Angle": 55500,
    "Channel": 56000,
    "Beam": 57000,
    "Round Bar": 57500,
    "TMT Bar": 52500,
    "Pipe": 64000,
    "Flat Bar": 56500,
}

GRADE_PREMIUM = {
    "E250": 0,
    "E350": 2500,
    "E410": 4200,
    "Fe500": 0,
    "Fe550": 900,
}


@dataclass
class ProductRow:
    product_code: str
    product_type: str
    grade: str | None
    standard: str | None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    diameter_mm: float | None = None
    unit: str = "MT"
    weight_per_piece_kg: float | None = None
    description: str = ""
    base_price: float = field(default=0.0)


def _thickness_premium(thickness: float | None) -> float:
    """Thin material costs more per tonne to roll and handle."""
    if thickness is None:
        return 0.0
    if thickness < 3:
        return 2200.0
    if thickness < 5:
        return 1400.0
    if thickness < 8:
        return 600.0
    if thickness >= 25:
        return -400.0
    return 0.0


def _price_for(product_type: str, grade: str | None, thickness: float | None) -> float:
    base = BASE_PRICE_BY_TYPE[product_type]
    base += GRADE_PREMIUM.get(grade or "", 0)
    base += _thickness_premium(thickness)
    return round(base / 50) * 50.0


def build_products() -> list[ProductRow]:
    rows: list[ProductRow] = []

    # --- Plates ----------------------------------------------------------
    for grade in ("E250", "E350"):
        for thickness in (6, 8, 10, 12, 16, 20, 25, 32):
            for width, length in ((1500, 6000), (2000, 6300)):
                rows.append(
                    ProductRow(
                        product_code=f"PLT-{grade}-{thickness:g}X{width}X{length}",
                        product_type="Plate",
                        grade=grade,
                        standard="IS 2062",
                        thickness_mm=float(thickness),
                        width_mm=float(width),
                        length_mm=float(length),
                        description=f"IS 2062 {grade} MS Plate {thickness:g} x {width} x {length} mm",
                    )
                )

    # --- Sheets ----------------------------------------------------------
    for thickness in (2.0, 2.5, 3.0, 4.0):
        rows.append(
            ProductRow(
                product_code=f"SHT-E250-{thickness:g}X1250X2500",
                product_type="Sheet",
                grade="E250",
                standard="IS 2062",
                thickness_mm=thickness,
                width_mm=1250.0,
                length_mm=2500.0,
                description=f"HR Sheet {thickness:g} x 1250 x 2500 mm",
            )
        )

    # --- Coils (no defined length) ---------------------------------------
    for thickness in (2.5, 3.0, 4.0, 5.0):
        for width in (1250, 1500):
            rows.append(
                ProductRow(
                    product_code=f"COL-E250-{thickness:g}X{width}",
                    product_type="Coil",
                    grade="E250",
                    standard="IS 2062",
                    thickness_mm=thickness,
                    width_mm=float(width),
                    description=f"HR Coil {thickness:g} mm x {width} mm",
                )
            )

    # --- Equal angles ----------------------------------------------------
    for leg, thickness in ((50, 5), (50, 6), (65, 6), (65, 8), (75, 6), (75, 8), (100, 8), (100, 10)):
        rows.append(
            ProductRow(
                product_code=f"ANG-E250-{leg}X{leg}X{thickness}",
                product_type="Angle",
                grade="E250",
                standard="IS 2062",
                thickness_mm=float(thickness),
                width_mm=float(leg),
                length_mm=6000.0,
                description=f"ISA {leg} x {leg} x {thickness} mm Equal Angle, 6 m",
            )
        )

    # --- Channels --------------------------------------------------------
    for depth, kg_per_m in ISMC_KG_PER_M.items():
        rows.append(
            ProductRow(
                product_code=f"CHN-E250-ISMC{depth}",
                product_type="Channel",
                grade="E250",
                standard="IS 2062",
                width_mm=float(depth),
                length_mm=6000.0,
                weight_per_piece_kg=round(kg_per_m * 6, 2),
                description=f"ISMC {depth} Channel, 6 m ({kg_per_m} kg/m)",
            )
        )

    # --- Beams -----------------------------------------------------------
    for depth, kg_per_m in ISMB_KG_PER_M.items():
        rows.append(
            ProductRow(
                product_code=f"BEM-E250-ISMB{depth}",
                product_type="Beam",
                grade="E250",
                standard="IS 2062",
                width_mm=float(depth),
                length_mm=6000.0,
                weight_per_piece_kg=round(kg_per_m * 6, 2),
                description=f"ISMB {depth} Beam, 6 m ({kg_per_m} kg/m)",
            )
        )

    # --- Round bars ------------------------------------------------------
    for diameter in (12, 16, 20, 25, 32, 40):
        rows.append(
            ProductRow(
                product_code=f"RND-E250-D{diameter}",
                product_type="Round Bar",
                grade="E250",
                standard="IS 2062",
                diameter_mm=float(diameter),
                length_mm=6000.0,
                description=f"MS Round Bar {diameter} mm dia, 6 m",
            )
        )

    # --- TMT bars --------------------------------------------------------
    for grade in ("Fe500", "Fe550"):
        for diameter in (8, 10, 12, 16, 20, 25):
            rows.append(
                ProductRow(
                    product_code=f"TMT-{grade.upper()}-D{diameter}",
                    product_type="TMT Bar",
                    grade=grade,
                    standard="IS 1786",
                    diameter_mm=float(diameter),
                    length_mm=12000.0,
                    description=f"TMT Bar {grade} {diameter} mm dia, 12 m",
                )
            )

    # --- Pipes -----------------------------------------------------------
    for od in (25, 32, 40, 50, 80, 100):
        for thickness in (2.9, 3.2):
            rows.append(
                ProductRow(
                    product_code=f"PIP-E250-OD{od}X{thickness:g}",
                    product_type="Pipe",
                    grade="E250",
                    standard="IS 1239",
                    diameter_mm=float(od),
                    thickness_mm=thickness,
                    length_mm=6000.0,
                    description=f"MS Pipe OD {od} mm x {thickness:g} mm, 6 m",
                )
            )

    # --- Flat bars -------------------------------------------------------
    for width, thickness in ((50, 6), (65, 8), (75, 10), (100, 10)):
        rows.append(
            ProductRow(
                product_code=f"FLT-E250-{width}X{thickness}",
                product_type="Flat Bar",
                grade="E250",
                standard="IS 2062",
                thickness_mm=float(thickness),
                width_mm=float(width),
                length_mm=6000.0,
                description=f"MS Flat Bar {width} x {thickness} mm, 6 m",
            )
        )

    # Fill in derived weights and prices.
    for row in rows:
        if row.weight_per_piece_kg is None:
            computed = weight_kg_per_piece(
                Dimensions(
                    product_type=row.product_type,
                    thickness_mm=row.thickness_mm,
                    width_mm=row.width_mm,
                    length_mm=row.length_mm,
                    diameter_mm=row.diameter_mm,
                )
            )
            if computed:
                row.weight_per_piece_kg = round(computed[0], 2)
        row.base_price = _price_for(row.product_type, row.grade, row.thickness_mm)

    return rows


CUSTOMERS = [
    ("CUST-001", "Rajesh Kumar", "rajesh@abcindustries.co.in", "ABC Industries Pvt Ltd", "Patna", "A"),
    ("CUST-002", "Sunil Agarwal", "sunil@bharatfab.co.in", "Bharat Fabricators", "Patna", "B"),
    ("CUST-003", "Meera Sinha", "meera@sinhaengineering.in", "Sinha Engineering Works", "Muzaffarpur", "B"),
    ("CUST-004", "Anil Verma", "anil@vermasteel.co.in", "Verma Steel Traders", "Gaya", "C"),
    ("CUST-005", "Prakash Jha", "prakash@jhaconstructions.in", "Jha Constructions", "Hajipur", "B"),
    ("CUST-006", "Vikram Singh", "vikram@ranchimetals.co.in", "Ranchi Metals Ltd", "Ranchi", "A"),
    ("CUST-007", "Deepak Mishra", "deepak@tatasuppliers.in", "Jamshedpur Structurals", "Jamshedpur", "A"),
    ("CUST-008", "Ravi Prasad", "ravi@dhanbadironworks.in", "Dhanbad Iron Works", "Dhanbad", "B"),
    ("CUST-009", "Sanjay Gupta", "sanjay@kolkatasteels.co.in", "Kolkata Steel Centre", "Kolkata", "A"),
    ("CUST-010", "Amit Roy", "amit@royengineers.co.in", "Roy Engineers", "Kolkata", "C"),
    ("CUST-011", "Neha Srivastava", "neha@varanasibuild.in", "Varanasi Buildcon", "Varanasi", "B"),
    ("CUST-012", "Manoj Tiwari", "manoj@tiwarienterprises.in", "Tiwari Enterprises", "Bhagalpur", "C"),
    ("CUST-013", "Kiran Yadav", "kiran@yadavinfra.co.in", "Yadav Infra Projects", "Patna", "B"),
    ("CUST-014", "Suresh Pandey", "suresh@pandeystructurals.in", "Pandey Structurals", "Ranchi", "B"),
    ("CUST-015", "Alok Chatterjee", "alok@chatterjeefab.co.in", "Chatterjee Fabrication", "Kolkata", "B"),
    ("CUST-016", "Nitin Sharma", "nitin@sharmaudyog.in", "Sharma Udyog", "Muzaffarpur", "C"),
    ("CUST-017", "Pooja Das", "pooja@dasengineering.co.in", "Das Engineering", "Jamshedpur", "B"),
    ("CUST-018", "Rakesh Ranjan", "rakesh@ranjanmetals.in", "Ranjan Metals", "Gaya", "C"),
    ("CUST-019", "Harish Modi", "harish@moditubes.co.in", "Modi Tubes & Pipes", "Dhanbad", "B"),
    ("CUST-020", "Sandeep Kaur", "sandeep@kaursteelworks.in", "Kaur Steel Works", "Patna", "A"),
]

PAYMENT_TERMS = ["Advance", "15 days credit", "30 days credit", "50% advance, balance on delivery"]


def build_customers() -> pd.DataFrame:
    records = []
    for code, name, email, company, city, tier in CUSTOMERS:
        records.append(
            {
                "Customer Code": code,
                "Customer Name": name,
                "Email": email,
                "Phone": f"+91 9{random.randint(100000000, 999999999)}",
                "Company": company,
                "Billing Address": f"{company}, Industrial Area, {city}",
                "Shipping Address": f"{company} Works, {city}",
                "City": city,
                "Tier": tier,
                "Payment Terms": random.choice(PAYMENT_TERMS),
                "Status": "ACTIVE",
            }
        )
    return pd.DataFrame(records)


def build_product_frame(products: list[ProductRow]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Product Code": p.product_code,
                "Product Type": p.product_type,
                "Grade": p.grade,
                "Standard": p.standard,
                "Thickness (mm)": p.thickness_mm,
                "Width (mm)": p.width_mm,
                "Length (mm)": p.length_mm,
                "Diameter (mm)": p.diameter_mm,
                "Unit": p.unit,
                "Weight per Piece (kg)": p.weight_per_piece_kg,
                "Description": p.description,
                "Status": "ACTIVE",
            }
            for p in products
        ]
    )


def build_price_master(products: list[ProductRow], effective_from: date) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Product Code": p.product_code,
                "Base Price": p.base_price,
                "Currency": "INR",
                "Unit": "MT",
                "Effective From": effective_from,
                "Effective To": None,
                "Source": "Mill price circular (sample)",
            }
            for p in products
        ]
    )


def build_sales_history(
    products: list[ProductRow], today: date, invoice_count: int = 650
) -> pd.DataFrame:
    """Generate invoices with 1-3 product lines each.

    Selling prices sit above base price by a tier- and quantity-dependent
    margin, with a mild upward market trend over the period and per-line noise,
    so the historical-anchor step in the pricing engine has something realistic
    to work with.

    Invoice dates are skewed toward the recent past, both because that is how a
    real order book looks and because the pricing engine's primary comparable
    window is only 30 days - a flat distribution would leave it starved.
    """
    # Weight the mix toward the products a trader actually moves.
    popular = [p for p in products if p.product_type in ("Plate", "TMT Bar", "Angle", "Channel")]
    weights = [6 if p in popular else 1 for p in products]

    tier_margin = {"A": 0.022, "B": 0.032, "C": 0.045}
    records: list[dict] = []

    for n in range(1, invoice_count + 1):
        code, _name, _email, _company, city, tier = random.choice(CUSTOMERS)
        # Exponent > 1 pulls the distribution toward recent dates.
        days_ago = max(1, int(180 * (random.random() ** 1.8)))
        sale_date = today - timedelta(days=days_ago)
        # Market drift: prices were slightly lower further back.
        trend = 1.0 - (days_ago * 0.00018)
        terms = random.choice(PAYMENT_TERMS)
        invoice_no = f"INV-{sale_date.year}-{n:04d}"

        for product in random.sample(
            random.choices(products, weights=weights, k=6), k=random.randint(1, 3)
        ):
            quantity = round(random.uniform(2, 90), 3)
            margin = tier_margin[tier]
            if quantity > 50:
                margin -= 0.008
            elif quantity < 5:
                margin += 0.012
            rate = product.base_price * trend * (1 + margin) * random.uniform(0.994, 1.006)
            records.append(
                {
                    "Invoice No": invoice_no,
                    "Invoice Date": sale_date,
                    "Customer Code": code,
                    "Product Code": product.product_code,
                    "Quantity": quantity,
                    "Unit": "MT",
                    "Rate": round(rate / 10) * 10,
                    "Currency": "INR",
                    "Delivery Location": city,
                    "Payment Terms": terms,
                }
            )

    frame = pd.DataFrame(records)
    # The (invoice, product) pair is unique in the schema; drop the rare clash.
    return frame.drop_duplicates(subset=["Invoice No", "Product Code"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Sample enquiry emails
# ---------------------------------------------------------------------------

SALES_INBOX = "sales@yoursteelcompany.co.in"


@dataclass
class SampleEmail:
    slug: str
    sender_name: str
    sender_email: str
    subject: str
    body: str
    days_ago: int = 0
    note: str = ""


SAMPLE_EMAILS: list[SampleEmail] = [
    SampleEmail(
        slug="01-clean-plate-enquiry",
        sender_name="Rajesh Kumar",
        sender_email="rajesh@abcindustries.co.in",
        subject="Enquiry - IS 2062 E250 Plate 10mm",
        body="""Dear Sir,

Please quote your best price for IS 2062 E250 plate, 10mm x 1500 x 6000, quantity 20 MT, delivery Patna.

Kindly confirm the delivery schedule along with your offer.

Regards,
Rajesh Kumar
ABC Industries Pvt Ltd
Patna
""",
        days_ago=0,
        note="Textbook case: exact product, clear quantity and location. Expect HIGH confidence.",
    ),
    SampleEmail(
        slug="02-tmt-enquiry",
        sender_name="Prakash Jha",
        sender_email="prakash@jhaconstructions.in",
        subject="Requirement of TMT bars Fe500",
        body="""Hello,

We need TMT bars Fe500, 16mm dia, 45 MT for our site at Hajipur.
Please share your rate and validity. Payment 30 days credit as usual.

Thanks,
Prakash Jha
Jha Constructions
""",
        days_ago=0,
        note="Known customer, quantity slab discount applies.",
    ),
    SampleEmail(
        slug="03-multi-item-enquiry",
        sender_name="Vikram Singh",
        sender_email="vikram@ranchimetals.co.in",
        subject="RFQ - structural steel requirement",
        body="""Dear Sales Team,

Kindly quote for the following requirement, delivery at Ranchi:

1. ISMC 100 Channel, 6 mtr - 12 MT
2. ISA 75 x 75 x 6 Angle, 6 mtr - 8 MT
3. IS 2062 E250 Plate 12mm x 1500 x 6000 - 25 MT

Material should be accompanied by mill test certificate.
Please send your offer by tomorrow.

Best regards,
Vikram Singh
Ranchi Metals Ltd
""",
        days_ago=1,
        note="Multi-line RFQ - exercises the line-item model end to end.",
    ),
    SampleEmail(
        slug="04-missing-quantity",
        sender_name="Anil Verma",
        sender_email="anil@vermasteel.co.in",
        subject="Price for E350 plate",
        body="""Sir,

Please send rate for IS 2062 E350 plate 16mm, size 2000 x 6300.
Delivery at Gaya.

Regards,
Anil Verma
Verma Steel Traders
""",
        days_ago=1,
        note="No quantity stated. Must route to NEEDS_INFORMATION, never assume a tonnage.",
    ),
    SampleEmail(
        slug="05-ambiguous-product",
        sender_name="Sunil Agarwal",
        sender_email="sunil@bharatfab.co.in",
        subject="MS plate requirement",
        body="""Dear Sir,

We need MS plate 10mm, around 15 MT, delivery Patna.
Please quote urgently.

Regards,
Sunil Agarwal
Bharat Fabricators
""",
        days_ago=2,
        note="10mm plate exists in two widths - expect MULTIPLE_MATCHES and a human decision.",
    ),
    SampleEmail(
        slug="06-pieces-unit",
        sender_name="Suresh Pandey",
        sender_email="suresh@pandeystructurals.in",
        subject="ISMB 200 requirement - 40 nos",
        body="""Hello,

Require ISMB 200 beam, 6 metre length, 40 nos, delivery Ranchi.
Please quote per MT basis.

Regards,
Suresh Pandey
Pandey Structurals
""",
        days_ago=2,
        note="Quantity in pieces - exercises the weight service's PCS conversion.",
    ),
    SampleEmail(
        slug="07-unknown-product",
        sender_name="Harish Modi",
        sender_email="harish@moditubes.co.in",
        subject="Enquiry for SS 304 sheet",
        body="""Dear Sir,

Please quote for stainless steel SS 304 sheet, 3mm thickness, 5 MT, delivery Dhanbad.

Regards,
Harish Modi
Modi Tubes & Pipes
""",
        days_ago=3,
        note="Stainless is not in the product master - expect NO_MATCH, not a fabricated price.",
    ),
    SampleEmail(
        slug="08-new-customer",
        sender_name="Imran Sheikh",
        sender_email="imran@newhorizonfab.co.in",
        subject="Quotation required - MS Angle",
        body="""Dear Sir,

We are a fabrication unit at Patna. Please quote your best rate for
ISA 65 x 65 x 6 angle, 6 metre, quantity 10 MT.

This is our first enquiry with you.

Regards,
Imran Sheikh
New Horizon Fabrication
""",
        days_ago=3,
        note="Unknown sender - customer resolution fails, confidence must drop below HIGH.",
    ),
    SampleEmail(
        slug="09-price-negotiation",
        sender_name="Sanjay Gupta",
        sender_email="sanjay@kolkatasteels.co.in",
        subject="Re: Quotation for 12mm plate",
        body="""Dear Sir,

Your price of Rs 59,200 per MT is on the higher side. We have an offer at
Rs 57,500 from another supplier. Please review and confirm your best rate,
otherwise we will have to place the order elsewhere.

Regards,
Sanjay Gupta
Kolkata Steel Centre
""",
        days_ago=4,
        note="PRICE_NEGOTIATION - recorded and shown as unsupported in the MVP.",
    ),
    SampleEmail(
        slug="10-order",
        sender_name="Deepak Mishra",
        sender_email="deepak@tatasuppliers.in",
        subject="Purchase Order PO-2026-0412",
        body="""Dear Sir,

Please find our confirmed order for 30 MT of IS 2062 E250 plate 12mm x 1500 x 6000
at the rate quoted. Delivery required at Jamshedpur within 10 days.
Formal PO is attached.

Regards,
Deepak Mishra
Jamshedpur Structurals
""",
        days_ago=4,
        note="ORDER - must not generate a quotation reply.",
    ),
    SampleEmail(
        slug="11-delivery-query",
        sender_name="Kiran Yadav",
        sender_email="kiran@yadavinfra.co.in",
        subject="Status of pending delivery",
        body="""Sir,

Our order placed last week for TMT bars has not yet arrived at the Patna site.
Please update on the dispatch status and expected delivery date.

Regards,
Kiran Yadav
Yadav Infra Projects
""",
        days_ago=5,
        note="DELIVERY_QUERY.",
    ),
    SampleEmail(
        slug="12-payment-query",
        sender_name="Alok Chatterjee",
        sender_email="alok@chatterjeefab.co.in",
        subject="Payment reconciliation for June invoices",
        body="""Dear Accounts Team,

Please share the outstanding statement for our account. We have made a payment
of Rs 12,50,000 on 5th against invoices INV-2026-0141 and INV-2026-0152 which is
not reflecting in your last statement.

Regards,
Alok Chatterjee
Chatterjee Fabrication
""",
        days_ago=5,
        note="PAYMENT_QUERY.",
    ),
    SampleEmail(
        slug="13-spam",
        sender_name="Marketing Team",
        sender_email="promo@bulkmailerdeals.com",
        subject="Boost your business 10x with our SEO package!!",
        body="""Hi there,

Limited time offer! Get first page Google ranking guaranteed. Reply now to claim
your 70% discount before it expires.

Unsubscribe here.
""",
        days_ago=6,
        note="SPAM - must be filtered out cheaply.",
    ),
    SampleEmail(
        slug="14-pipe-in-metres",
        sender_name="Pooja Das",
        sender_email="pooja@dasengineering.co.in",
        subject="MS Pipe requirement",
        body="""Dear Sir,

Kindly quote for MS Pipe IS 1239, OD 50mm x 3.2mm thickness, total 1200 running metres,
delivery at Jamshedpur.

Regards,
Pooja Das
Das Engineering
""",
        days_ago=6,
        note="Quantity in running metres - exercises the MTR conversion path.",
    ),
]


def write_emails(today: datetime) -> int:
    EMAIL_DIR.mkdir(parents=True, exist_ok=True)
    for existing in EMAIL_DIR.glob("*.eml"):
        existing.unlink()

    for sample in SAMPLE_EMAILS:
        msg = EmailMessage()
        msg["Message-ID"] = make_msgid(domain="sample.local")
        msg["From"] = f"{sample.sender_name} <{sample.sender_email}>"
        msg["To"] = SALES_INBOX
        msg["Subject"] = sample.subject
        msg["Date"] = format_datetime(today - timedelta(days=sample.days_ago, hours=3))
        # Not a standard header - a note to whoever reads the sample corpus.
        msg["X-Sample-Note"] = sample.note
        msg.set_content(sample.body)
        (EMAIL_DIR / f"{sample.slug}.eml").write_bytes(msg.as_bytes())

    return len(SAMPLE_EMAILS)


def _write_excel(frame: pd.DataFrame, path: Path, sheet_name: str) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name=sheet_name)


def main() -> None:
    random.seed(SEED)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    today = date.today()
    now = datetime.now(UTC)

    products = build_products()
    product_frame = build_product_frame(products)
    price_frame = build_price_master(products, effective_from=today - timedelta(days=7))
    customer_frame = build_customers()
    sales_frame = build_sales_history(products, today)

    _write_excel(product_frame, SAMPLE_DIR / "products.xlsx", "Products")
    _write_excel(price_frame, SAMPLE_DIR / "price_master.xlsx", "Price Master")
    _write_excel(customer_frame, SAMPLE_DIR / "customers.xlsx", "Customers")
    _write_excel(sales_frame, SAMPLE_DIR / "sales_history.xlsx", "Sales")

    email_count = write_emails(datetime.combine(today, datetime.min.time(), tzinfo=UTC))

    print(f"Sample data written to {SAMPLE_DIR}")
    print(f"  products.xlsx      {len(product_frame):5} rows")
    print(f"  price_master.xlsx  {len(price_frame):5} rows")
    print(f"  customers.xlsx     {len(customer_frame):5} rows")
    print(f"  sales_history.xlsx {len(sales_frame):5} rows")
    print(f"  emails/            {email_count:5} .eml files")
    print(f"  generated at       {now:%Y-%m-%d %H:%M:%S} UTC (seed {SEED})")


if __name__ == "__main__":
    main()
