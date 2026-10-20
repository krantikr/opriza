"""The shared knowledge base: one set of tables every agent reads.

Five layers, each with exactly one kind of writer (see docs/agents/schema.sql
and the "Oprisa Agents" plan doc):

    A  Tally mirror     written only by the sync (app.kb.sync)
    B  Business facts   computed by plain code (app.kb.facts), never by an LLM
    C  Work state       agents and people, through app.kb services
    D  Memory           events (the outbox), aliases, memories, documents, chat
    E  Runs             agent runs and sync runs

Every table carries `organisation_id` through `TenantMixin`, so
`scripts/rls.py` gives each one a row-level-security policy and a desk can
never read another desk's rows. Table names start with `kb_` to keep them
apart from the quotation copilot's tables, which keep working unchanged.

Money columns are floats on the Python side (`Numeric(asdecimal=False)`): the
agents do arithmetic on them constantly and the facts layer compares, ranks
and sums rather than prices, so the copilot's Decimal discipline would only
add conversions here.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.models.mixins import TenantMixin


def money():
    return Numeric(16, 2, asdecimal=False)


def qty():
    return Numeric(16, 3, asdecimal=False)


# ---------------------------------------------------------------------------
# The business itself: what the agents need to know about the desk
# ---------------------------------------------------------------------------


class KbBusiness(Base, TenantMixin):
    """One row per organisation: trade, language, Tally connection, clock.

    `as_of` freezes the business clock. Mock data is built around a fixed
    "today", so a desk running on mock data sets it and every agent sees the
    same day the scenarios were planted for. A live desk leaves it empty and
    the agents use the real time.
    """

    __tablename__ = "kb_business"
    __table_args__ = (UniqueConstraint("organisation_id", name="uq_kb_business_org"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trade: Mapped[str] = mapped_column(String(40), default="steel", nullable=False)
    city: Mapped[str | None] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(20), default="English", nullable=False)
    tally_version: Mapped[str] = mapped_column(String(40), default="TallyPrime", nullable=False)
    #: "mock" or "tally_xml" - which TallySource the sync uses for this desk.
    source: Mapped[str] = mapped_column(String(20), default="mock", nullable=False)
    #: For "tally_xml": the connector address, e.g. http://192.168.1.20:9000
    source_url: Mapped[str | None] = mapped_column(String(200))
    #: For "mock": which sample business to load (its slug in the generator).
    mock_key: Mapped[str | None] = mapped_column(String(60))
    as_of: Mapped[datetime | None] = mapped_column()
    bank_balance: Mapped[float] = mapped_column(money(), default=0, nullable=False)
    bank_balance_at: Mapped[datetime | None] = mapped_column()
    last_sync_at: Mapped[datetime | None] = mapped_column()
    last_alter_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fy_start: Mapped[date | None] = mapped_column(Date)


class KbMember(Base, TenantMixin):
    """Which desk role a user plays: owner, accounts, sales or purchase.

    Separate from the login role (OWNER/MEMBER/VIEWER) because that one is
    about permissions and this one is about whose Inbox a task lands in.
    """

    __tablename__ = "kb_members"
    __table_args__ = (UniqueConstraint("organisation_id", "user_id", name="uq_kb_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False)
    desk_role: Mapped[str] = mapped_column(String(20), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))


# ---------------------------------------------------------------------------
# A. Tally mirror
# ---------------------------------------------------------------------------


class KbSyncRun(Base, TenantMixin):
    __tablename__ = "kb_sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(12), default="running", nullable=False)
    last_alter_id: Mapped[int | None] = mapped_column(Integer)
    objects_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class KbGodown(Base, TenantMixin):
    __tablename__ = "kb_godowns"
    __table_args__ = (UniqueConstraint("organisation_id", "tally_guid", name="uq_kb_godown_guid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tally_guid: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class KbParty(Base, TenantMixin):
    """A Tally ledger under Sundry Debtors (customer) or Creditors (supplier)."""

    __tablename__ = "kb_parties"
    __table_args__ = (
        UniqueConstraint("organisation_id", "tally_guid", name="uq_kb_party_guid"),
        Index("ix_kb_parties_org_kind", "organisation_id", "kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tally_guid: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # customer | supplier
    tally_group: Mapped[str] = mapped_column(String(60), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(20), index=True)
    city: Mapped[str | None] = mapped_column(String(80))
    area: Mapped[str | None] = mapped_column(String(80))
    credit_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    credit_limit: Mapped[float | None] = mapped_column(money())
    salesperson_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    brand: Mapped[str | None] = mapped_column(String(80))
    since: Mapped[date | None] = mapped_column(Date)
    #: Suppliers: share of deliveries on time, from the purchase history.
    on_time_pct: Mapped[float | None] = mapped_column(Float)
    #: Suppliers: usual days from order to delivery.
    delivery_days: Mapped[int | None] = mapped_column(Integer)


class KbItem(Base, TenantMixin):
    __tablename__ = "kb_items"
    __table_args__ = (UniqueConstraint("organisation_id", "tally_guid", name="uq_kb_item_guid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tally_guid: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stock_group: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(12), nullable=False)
    hsn: Mapped[str | None] = mapped_column(String(12))
    gst_rate: Mapped[float] = mapped_column(Float, default=18, nullable=False)
    standard_cost: Mapped[float] = mapped_column(money(), nullable=False)
    standard_rate: Mapped[float] = mapped_column(money(), nullable=False)
    reorder_level: Mapped[float | None] = mapped_column(qty())


class KbVoucher(Base, TenantMixin):
    __tablename__ = "kb_vouchers"
    __table_args__ = (
        UniqueConstraint("organisation_id", "tally_guid", name="uq_kb_voucher_guid"),
        Index("ix_kb_vouchers_org_type_date", "organisation_id", "voucher_type", "date"),
        Index("ix_kb_vouchers_party", "party_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tally_guid: Mapped[str] = mapped_column(String(80), nullable=False)
    alter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    voucher_type: Mapped[str] = mapped_column(String(16), nullable=False)
    number: Mapped[str] = mapped_column(String(60), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("kb_parties.id", ondelete="SET NULL"))
    amount: Mapped[float] = mapped_column(money(), nullable=False)
    tax_amount: Mapped[float] = mapped_column(money(), default=0, nullable=False)
    narration: Mapped[str | None] = mapped_column(Text)


class KbVoucherLine(Base, TenantMixin):
    __tablename__ = "kb_voucher_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    voucher_id: Mapped[int] = mapped_column(
        ForeignKey("kb_vouchers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("kb_items.id"), nullable=False, index=True)
    godown_id: Mapped[int | None] = mapped_column(ForeignKey("kb_godowns.id"))
    qty: Mapped[float] = mapped_column(qty(), nullable=False)
    rate: Mapped[float] = mapped_column(money(), nullable=False)
    amount: Mapped[float] = mapped_column(money(), nullable=False)


class KbBill(Base, TenantMixin):
    """Bill-wise outstanding, as Tally keeps it."""

    __tablename__ = "kb_bills"
    __table_args__ = (
        UniqueConstraint("organisation_id", "party_id", "bill_ref", name="uq_kb_bill_ref"),
        Index("ix_kb_bills_open", "organisation_id", "direction", "pending_amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("kb_parties.id"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(12), nullable=False)  # receivable | payable
    bill_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(money(), nullable=False)
    pending_amount: Mapped[float] = mapped_column(money(), nullable=False)
    voucher_id: Mapped[int | None] = mapped_column(ForeignKey("kb_vouchers.id", ondelete="SET NULL"))


class KbBillAllocation(Base, TenantMixin):
    __tablename__ = "kb_bill_allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(
        ForeignKey("kb_bills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voucher_id: Mapped[int] = mapped_column(
        ForeignKey("kb_vouchers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(money(), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)


class KbStockBalance(Base, TenantMixin):
    __tablename__ = "kb_stock_balances"
    __table_args__ = (
        UniqueConstraint("organisation_id", "item_id", "godown_id", "as_of", name="uq_kb_stock_bal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("kb_items.id"), nullable=False, index=True)
    godown_id: Mapped[int] = mapped_column(ForeignKey("kb_godowns.id"), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    qty: Mapped[float] = mapped_column(qty(), nullable=False)
    value: Mapped[float] = mapped_column(money(), nullable=False)


# ---------------------------------------------------------------------------
# B. Business facts (computed by app.kb.facts; never typed by an LLM)
# ---------------------------------------------------------------------------


class KbCustomerProfile(Base, TenantMixin):
    __tablename__ = "kb_customer_profiles"
    __table_args__ = (UniqueConstraint("organisation_id", "party_id", name="uq_kb_profile_party"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("kb_parties.id", ondelete="CASCADE"), nullable=False)
    grade: Mapped[str] = mapped_column(String(1), nullable=False)
    previous_grade: Mapped[str | None] = mapped_column(String(1))
    avg_days_late: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    usual_pay_day: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    promises_made: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    promises_kept: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sales_12m: Mapped[float] = mapped_column(money(), default=0, nullable=False)
    sales_90d: Mapped[float] = mapped_column(money(), default=0, nullable=False)
    outstanding: Mapped[float] = mapped_column(money(), default=0, nullable=False)
    overdue: Mapped[float] = mapped_column(money(), default=0, nullable=False)
    oldest_overdue_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_order_on: Mapped[date | None] = mapped_column(Date)
    avg_order_gap_days: Mapped[float | None] = mapped_column(Float)
    trend: Mapped[str] = mapped_column(String(6), default="flat", nullable=False)
    suggested_credit_limit: Mapped[float | None] = mapped_column(money())
    reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)


class KbItemMetric(Base, TenantMixin):
    __tablename__ = "kb_item_metrics"
    __table_args__ = (UniqueConstraint("organisation_id", "item_id", name="uq_kb_metric_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("kb_items.id", ondelete="CASCADE"), nullable=False)
    sold_7d: Mapped[float] = mapped_column(qty(), default=0, nullable=False)
    sold_28d: Mapped[float] = mapped_column(qty(), default=0, nullable=False)
    per_day: Mapped[float] = mapped_column(qty(), default=0, nullable=False)
    stock_qty: Mapped[float] = mapped_column(qty(), default=0, nullable=False)
    stock_value: Mapped[float] = mapped_column(money(), default=0, nullable=False)
    days_left: Mapped[float | None] = mapped_column(Float)
    last_sale_on: Mapped[date | None] = mapped_column(Date)
    idle_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reorder_qty: Mapped[float | None] = mapped_column(qty())
    status: Mapped[str] = mapped_column(String(8), default="ok", nullable=False)
    computed_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)


class KbPricePoint(Base, TenantMixin):
    __tablename__ = "kb_price_points"
    __table_args__ = (Index("ix_kb_price_item_date", "organisation_id", "item_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("kb_items.id", ondelete="CASCADE"), nullable=False)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("kb_parties.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # sale|purchase|quote|supplier_quote
    date: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[float] = mapped_column(money(), nullable=False)
    qty: Mapped[float | None] = mapped_column(qty())


class KbCashWeek(Base, TenantMixin):
    __tablename__ = "kb_cash_forecast"
    __table_args__ = (UniqueConstraint("organisation_id", "week_start", "scenario", name="uq_kb_cash_week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    scenario: Mapped[str] = mapped_column(String(20), default="base", nullable=False)
    opening_balance: Mapped[float] = mapped_column(money(), nullable=False)
    inflow: Mapped[float] = mapped_column(money(), nullable=False)
    outflow: Mapped[float] = mapped_column(money(), nullable=False)
    closing_balance: Mapped[float] = mapped_column(money(), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)


class KbKpi(Base, TenantMixin):
    __tablename__ = "kb_kpi_snapshots"
    __table_args__ = (UniqueConstraint("organisation_id", "day", "metric", name="uq_kb_kpi"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    metric: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[float] = mapped_column(money(), nullable=False)


# ---------------------------------------------------------------------------
# C. Work state
# ---------------------------------------------------------------------------


class KbEnquiry(Base, TenantMixin):
    __tablename__ = "kb_enquiries"

    id: Mapped[int] = mapped_column(primary_key=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("kb_parties.id", ondelete="SET NULL"), index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    parsed: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(12), default="new", nullable=False
    )  # new|quoted|ignored|needs_review
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))


class KbQuote(Base, TenantMixin):
    __tablename__ = "kb_quotes"
    __table_args__ = (UniqueConstraint("organisation_id", "number", name="uq_kb_quote_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    party_id: Mapped[int] = mapped_column(ForeignKey("kb_parties.id"), nullable=False, index=True)
    enquiry_id: Mapped[int | None] = mapped_column(ForeignKey("kb_enquiries.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column()
    opened_at: Mapped[datetime | None] = mapped_column()
    decided_at: Mapped[datetime | None] = mapped_column()
    nudged_at: Mapped[datetime | None] = mapped_column()
    valid_until: Mapped[date | None] = mapped_column(Date)
    subtotal: Mapped[float] = mapped_column(money(), nullable=False)
    freight: Mapped[float] = mapped_column(money(), default=0, nullable=False)
    tax: Mapped[float] = mapped_column(money(), nullable=False)
    total: Mapped[float] = mapped_column(money(), nullable=False)
    margin_pct: Mapped[float] = mapped_column(Float, nullable=False)
    lost_reason: Mapped[str | None] = mapped_column(String(200))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    sales_voucher_id: Mapped[int | None] = mapped_column(ForeignKey("kb_vouchers.id", ondelete="SET NULL"))


class KbQuoteLine(Base, TenantMixin):
    __tablename__ = "kb_quote_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int] = mapped_column(
        ForeignKey("kb_quotes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("kb_items.id"), nullable=False)
    qty: Mapped[float] = mapped_column(qty(), nullable=False)
    rate: Mapped[float] = mapped_column(money(), nullable=False)
    last_rate: Mapped[float | None] = mapped_column(money())
    margin_pct: Mapped[float] = mapped_column(Float, nullable=False)


class KbPromise(Base, TenantMixin):
    __tablename__ = "kb_promises"

    id: Mapped[int] = mapped_column(primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("kb_parties.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(money(), nullable=False)
    made_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # link|call|chat
    status: Mapped[str] = mapped_column(String(10), default="open", nullable=False, index=True)
    settled_amount: Mapped[float] = mapped_column(money(), default=0, nullable=False)


class KbMessage(Base, TenantMixin):
    """Something sent to a customer or supplier (a link by email or SMS)."""

    __tablename__ = "kb_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("kb_parties.id", ondelete="SET NULL"), index=True)
    agent: Mapped[str] = mapped_column(String(12), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)  # sms|email|shared
    language: Mapped[str] = mapped_column(String(20), default="English", nullable=False)
    to_address: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # draft|queued|sent|delivered|read|failed
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column()
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class KbShareLink(Base, TenantMixin):
    """A secure link a customer or supplier opens without an account."""

    __tablename__ = "kb_share_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(12), nullable=False)  # quote|statement|rfq|offer|early_pay
    party_id: Mapped[int] = mapped_column(ForeignKey("kb_parties.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    first_opened_at: Mapped[datetime | None] = mapped_column()
    responded_at: Mapped[datetime | None] = mapped_column()
    response: Mapped[dict | None] = mapped_column(JSON)


class KbRfq(Base, TenantMixin):
    __tablename__ = "kb_rfqs"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("kb_items.id"), nullable=False)
    qty: Mapped[float] = mapped_column(qty(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="open", nullable=False)


class KbSupplierQuote(Base, TenantMixin):
    __tablename__ = "kb_supplier_quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int | None] = mapped_column(ForeignKey("kb_rfqs.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("kb_parties.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("kb_items.id"), nullable=False)
    rate: Mapped[float] = mapped_column(money(), nullable=False)
    delivery_days: Mapped[int] = mapped_column(Integer, nullable=False)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)


class KbPurchaseOrder(Base, TenantMixin):
    __tablename__ = "kb_purchase_orders"
    __table_args__ = (UniqueConstraint("organisation_id", "number", name="uq_kb_po_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("kb_parties.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    total: Mapped[float] = mapped_column(money(), nullable=False)
    rfq_id: Mapped[int | None] = mapped_column(ForeignKey("kb_rfqs.id", ondelete="SET NULL"))
    purchase_voucher_id: Mapped[int | None] = mapped_column(ForeignKey("kb_vouchers.id", ondelete="SET NULL"))


class KbPoLine(Base, TenantMixin):
    __tablename__ = "kb_po_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(
        ForeignKey("kb_purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("kb_items.id"), nullable=False)
    qty: Mapped[float] = mapped_column(qty(), nullable=False)
    rate: Mapped[float] = mapped_column(money(), nullable=False)


class KbTask(Base, TenantMixin):
    """One line in someone's Inbox."""

    __tablename__ = "kb_tasks"
    __table_args__ = (Index("ix_kb_tasks_open", "organisation_id", "status", "assignee_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent: Mapped[str] = mapped_column(String(12), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    amount: Mapped[float | None] = mapped_column(money())
    priority: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    assignee_role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    due_at: Mapped[datetime | None] = mapped_column()
    done_at: Mapped[datetime | None] = mapped_column()
    #: A stable key so a daily job never files the same task twice.
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)
    why: Mapped[list | None] = mapped_column(JSON)


class KbApproval(Base, TenantMixin):
    """An action outside the owner's rules, waiting for a yes or no.

    `graph_thread_id` is the paused LangGraph run; approving resumes it.
    """

    __tablename__ = "kb_approvals"
    __table_args__ = (Index("ix_kb_approvals_status", "organisation_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent: Mapped[str] = mapped_column(String(12), nullable=False)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float | None] = mapped_column(money())
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    requested_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="waiting", nullable=False)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column()
    decision_note: Mapped[str | None] = mapped_column(Text)
    graph_thread_id: Mapped[str | None] = mapped_column(String(200))
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[int | None] = mapped_column(Integer)


class KbAgentRule(Base, TenantMixin):
    __tablename__ = "kb_agent_rules"
    __table_args__ = (UniqueConstraint("organisation_id", "agent", "key", name="uq_kb_rule"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent: Mapped[str] = mapped_column(String(12), nullable=False)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[object] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)


class KbTallyPosting(Base, TenantMixin):
    """Something approved that goes back into Tally: a sales order, a PO,
    a receipt note or a credit limit. The connector picks these up."""

    __tablename__ = "kb_tally_postings"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # sales_order|purchase_order|receipt_note|credit_limit
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), default="pending", nullable=False
    )  # pending|posted|failed
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# D. Memory: events (the outbox), aliases, memories, documents, chat
# ---------------------------------------------------------------------------


class KbEvent(Base, TenantMixin):
    __tablename__ = "kb_events"
    __table_args__ = (Index("ix_kb_events_org_time", "organisation_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)  # tally_sync|agent|user|link|schedule
    actor: Mapped[str | None] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class KbEventDelivery(Base, TenantMixin):
    __tablename__ = "kb_event_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "consumer", name="uq_kb_delivery"),
        Index("ix_kb_deliveries_pending", "organisation_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("kb_events.id", ondelete="CASCADE"), nullable=False)
    consumer: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)


class KbItemAlias(Base, TenantMixin):
    __tablename__ = "kb_item_aliases"
    __table_args__ = (UniqueConstraint("organisation_id", "alias", name="uq_kb_alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("kb_items.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(80), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # tally|learned|user
    hits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class KbMemory(Base, TenantMixin):
    """A remembered preference, instruction or fact. Kept, not overwritten:
    a replaced fact gets `valid_to` and stays readable."""

    __tablename__ = "kb_memories"
    __table_args__ = (Index("ix_kb_memories_scope", "organisation_id", "scope_type", "scope_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)  # org|party|item|user
    scope_id: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # preference|instruction|fact|note
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column()
    created_by: Mapped[str] = mapped_column(String(60), nullable=False)


class KbDocument(Base, TenantMixin):
    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("kb_parties.id", ondelete="SET NULL"))
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    storage_url: Mapped[str | None] = mapped_column(String(500))
    text: Mapped[str | None] = mapped_column(Text)


class KbDocumentChunk(Base, TenantMixin):
    """Searchable text. Keyword search today (Postgres full text); a pgvector
    `embedding` column is added in build step 6 when the embedding job lands."""

    __tablename__ = "kb_document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class KbChatMessage(Base, TenantMixin):
    """One message in an agent's chat: text, a card, and tap buttons.

    The shape (`card`, `actions`, `chips`) is the one the app's chat
    components render, so an agent posts exactly what the owner sees.
    """

    __tablename__ = "kb_chat_messages"
    __table_args__ = (Index("ix_kb_chat_thread", "organisation_id", "thread", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    thread: Mapped[str] = mapped_column(String(12), nullable=False)  # agent id
    sender: Mapped[str] = mapped_column(String(8), nullable=False)  # agent|me|system
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    card: Mapped[dict | None] = mapped_column(JSON)
    actions: Mapped[list | None] = mapped_column(JSON)
    chips: Mapped[list | None] = mapped_column(JSON)
    chosen: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str | None] = mapped_column(String(120))
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: For an action button: what it acts on, e.g. {"approval_id": 4}.
    ref: Mapped[dict | None] = mapped_column(JSON)


# ---------------------------------------------------------------------------
# E. Runs
# ---------------------------------------------------------------------------


class KbAgentRun(Base, TenantMixin):
    __tablename__ = "kb_agent_runs"
    __table_args__ = (Index("ix_kb_runs_org_time", "organisation_id", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent: Mapped[str] = mapped_column(String(12), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(10), nullable=False)  # event|schedule|chat|manual
    trigger_ref: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(18), default="running", nullable=False)
    brain: Mapped[str] = mapped_column(String(10), default="rules", nullable=False)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    outcome: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    graph_thread_id: Mapped[str | None] = mapped_column(String(200))


class KbJobRun(Base, TenantMixin):
    """When each scheduled job last ran for a desk, so a tick runs it once a day."""

    __tablename__ = "kb_job_runs"
    __table_args__ = (UniqueConstraint("organisation_id", "job", name="uq_kb_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(40), nullable=False)
    last_run_on: Mapped[date | None] = mapped_column(Date)
    last_run_at: Mapped[datetime | None] = mapped_column()


__all__ = [name for name in dir() if name.startswith("Kb")]
