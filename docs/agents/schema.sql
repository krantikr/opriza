-- =============================================================================
-- Oprisa agents: the shared knowledge base (planned schema)
--
-- One database, one set of facts, seven agents. Every table below is
-- tenant-scoped by organisation_id; in the real migration each one gets the
-- same row-level-security policy as today's tables (scripts/rls.py).
--
-- Five layers, in the order data flows through them:
--   A. Tally mirror      what the books say. Written only by Tally Sync.
--   B. Business facts    what the numbers mean. Computed by code, not by an LLM.
--   C. Work state        what the agents and the team are doing about it.
--   D. Memory            events, learned aliases and notes, documents.
--   E. Runs and audit    what each agent did, what it cost, who approved.
--
-- This file is a plan: it lives in its own schema (kb) so it can be loaded
-- next to the current tables, explored and seeded with the mock data in
-- data/mock_business/. Names marked "maps to" show how it meets an existing
-- table when it becomes real Alembic migrations.
--
-- Needs PostgreSQL 15+ and pgvector 0.8+ (CREATE EXTENSION vector).
-- Embedding size 1536 is a placeholder; set it to the chosen model's size.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DROP SCHEMA IF EXISTS kb CASCADE;
CREATE SCHEMA kb;
SET search_path = kb, public;

-- -----------------------------------------------------------------------------
-- 0. Tenancy and people (stand-ins for the existing organisations / app_users)
-- -----------------------------------------------------------------------------

CREATE TABLE organisations (                       -- maps to: organisations
    id              integer PRIMARY KEY,
    slug            text NOT NULL UNIQUE,
    name            text NOT NULL,
    trade           text NOT NULL,                 -- steel, building, pharma ... (demo industry ids)
    city            text NOT NULL,
    tally_version   text NOT NULL DEFAULT 'TallyPrime',
    fy_start        date NOT NULL,                 -- financial year start, usually 1 April
    language        text NOT NULL DEFAULT 'English',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (                               -- maps to: app_users
    id              integer PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    name            text NOT NULL,
    role            text NOT NULL CHECK (role IN ('owner', 'accounts', 'sales', 'purchase', 'viewer')),
    email           text,
    phone           text
);

-- -----------------------------------------------------------------------------
-- A. Tally mirror: written only by Tally Sync, read by every agent
-- -----------------------------------------------------------------------------

CREATE TABLE tally_sync_runs (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    started_at      timestamptz NOT NULL,
    finished_at     timestamptz,
    status          text NOT NULL CHECK (status IN ('running', 'ok', 'partial', 'failed')),
    last_alter_id   bigint,                        -- Tally's change counter: next sync asks for alter_id > this
    objects_read    integer NOT NULL DEFAULT 0,
    error           text
);

CREATE TABLE godowns (
    id              integer PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    tally_guid      text NOT NULL,
    name            text NOT NULL,
    UNIQUE (organisation_id, tally_guid)
);

-- Customers and suppliers are both ledgers in Tally (Sundry Debtors / Creditors).
CREATE TABLE parties (                             -- maps to: customers (+ new suppliers)
    id              integer PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    tally_guid      text NOT NULL,
    name            text NOT NULL,
    kind            text NOT NULL CHECK (kind IN ('customer', 'supplier')),
    tally_group     text NOT NULL,                 -- 'Sundry Debtors' / 'Sundry Creditors'
    contact_name    text,
    phone           text,
    email           text,
    gstin           text,
    city            text,
    area            text,
    credit_days     integer NOT NULL DEFAULT 30,
    credit_limit    numeric(14, 2),                -- what Tally holds; the agent's suggestion lives in customer_profiles
    salesperson_id  integer REFERENCES users(id),
    brand           text,                          -- suppliers: the brand they sell
    since           date,
    UNIQUE (organisation_id, tally_guid)
);
CREATE INDEX parties_name_trgm ON parties USING gin (name gin_trgm_ops);

CREATE TABLE items (                               -- maps to: stock_items (steel desk keeps its lot detail there)
    id              integer PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    tally_guid      text NOT NULL,
    name            text NOT NULL,
    stock_group     text NOT NULL,
    unit            text NOT NULL,                 -- MT, bag, pc, can, box ...
    hsn             text,
    gst_rate        numeric(5, 2) NOT NULL,
    standard_cost   numeric(14, 2) NOT NULL,
    standard_rate   numeric(14, 2) NOT NULL,
    reorder_level   numeric(14, 3),
    UNIQUE (organisation_id, tally_guid)
);
CREATE INDEX items_name_trgm ON items USING gin (name gin_trgm_ops);

CREATE TABLE vouchers (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    tally_guid      text NOT NULL,
    alter_id        bigint NOT NULL,
    voucher_type    text NOT NULL CHECK (voucher_type IN
                      ('sales', 'purchase', 'receipt', 'payment', 'credit_note', 'debit_note', 'journal')),
    number          text NOT NULL,
    date            date NOT NULL,
    party_id        integer REFERENCES parties(id),
    amount          numeric(14, 2) NOT NULL,       -- total including tax
    tax_amount      numeric(14, 2) NOT NULL DEFAULT 0,
    narration       text,
    UNIQUE (organisation_id, tally_guid)
);
CREATE INDEX vouchers_party_date ON vouchers (organisation_id, party_id, date);
CREATE INDEX vouchers_type_date  ON vouchers (organisation_id, voucher_type, date);

CREATE TABLE voucher_lines (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    voucher_id      bigint NOT NULL REFERENCES vouchers(id),
    line_no         smallint NOT NULL,
    item_id         integer NOT NULL REFERENCES items(id),
    godown_id       integer REFERENCES godowns(id),
    qty             numeric(14, 3) NOT NULL,
    rate            numeric(14, 2) NOT NULL,
    amount          numeric(14, 2) NOT NULL        -- qty x rate, before tax
);
CREATE INDEX voucher_lines_item ON voucher_lines (organisation_id, item_id);

-- Bill-wise outstanding, both ways: what customers owe us and what we owe suppliers.
CREATE TABLE bills (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    party_id        integer NOT NULL REFERENCES parties(id),
    direction       text NOT NULL CHECK (direction IN ('receivable', 'payable')),
    bill_ref        text NOT NULL,
    bill_date       date NOT NULL,
    due_date        date NOT NULL,
    amount          numeric(14, 2) NOT NULL,
    pending_amount  numeric(14, 2) NOT NULL,
    voucher_id      bigint REFERENCES vouchers(id),
    UNIQUE (organisation_id, party_id, bill_ref)
);
CREATE INDEX bills_open ON bills (organisation_id, direction, due_date) WHERE pending_amount > 0;

-- Which receipt or payment settled which bill.
CREATE TABLE bill_allocations (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    bill_id         bigint NOT NULL REFERENCES bills(id),
    voucher_id      bigint NOT NULL REFERENCES vouchers(id),
    amount          numeric(14, 2) NOT NULL,
    date            date NOT NULL
);

-- Stock on hand per item and godown, as of a date (today, plus month ends for history).
CREATE TABLE stock_balances (
    organisation_id integer NOT NULL REFERENCES organisations(id),
    item_id         integer NOT NULL REFERENCES items(id),
    godown_id       integer NOT NULL REFERENCES godowns(id),
    as_of           date NOT NULL,
    qty             numeric(14, 3) NOT NULL,
    value           numeric(14, 2) NOT NULL,
    PRIMARY KEY (organisation_id, item_id, godown_id, as_of)
);

-- -----------------------------------------------------------------------------
-- B. Business facts: computed by deterministic jobs after every sync.
--    Agents read these instead of re-deriving numbers, so they always agree.
-- -----------------------------------------------------------------------------

CREATE TABLE customer_profiles (
    party_id               integer PRIMARY KEY REFERENCES parties(id),
    organisation_id        integer NOT NULL REFERENCES organisations(id),
    grade                  char(1) NOT NULL CHECK (grade IN ('A', 'B', 'C', 'D')),
    previous_grade         char(1),
    avg_days_late          numeric(6, 1) NOT NULL,      -- weighted by amount, last 12 months
    usual_pay_day          integer NOT NULL,            -- days after bill date they typically pay
    promises_made          integer NOT NULL DEFAULT 0,
    promises_kept          integer NOT NULL DEFAULT 0,
    sales_12m              numeric(14, 2) NOT NULL,
    sales_90d              numeric(14, 2) NOT NULL,
    outstanding            numeric(14, 2) NOT NULL,
    overdue                numeric(14, 2) NOT NULL,
    oldest_overdue_days    integer NOT NULL DEFAULT 0,
    last_order_on          date,
    avg_order_gap_days     numeric(6, 1),
    trend                  text NOT NULL CHECK (trend IN ('up', 'flat', 'down')),
    suggested_credit_limit numeric(14, 2),
    reasons                jsonb NOT NULL DEFAULT '[]', -- plain-language reasons shown in the app
    computed_at            timestamptz NOT NULL
);

CREATE TABLE item_metrics (
    item_id         integer PRIMARY KEY REFERENCES items(id),
    organisation_id integer NOT NULL REFERENCES organisations(id),
    sold_7d         numeric(14, 3) NOT NULL,
    sold_28d        numeric(14, 3) NOT NULL,
    per_day         numeric(14, 3) NOT NULL,       -- 28-day velocity
    stock_qty       numeric(14, 3) NOT NULL,
    stock_value     numeric(14, 2) NOT NULL,
    days_left       numeric(8, 1),                 -- null when nothing sells
    last_sale_on    date,
    idle_days       integer NOT NULL DEFAULT 0,
    reorder_qty     numeric(14, 3),                -- 30 days of sales, rounded to pack size
    status          text NOT NULL CHECK (status IN ('reorder', 'watch', 'ok', 'idle')),
    computed_at     timestamptz NOT NULL
);

-- Every rate we have seen: sold, bought, quoted, offered by a supplier.
-- The Sales agent prices from it; the Stock agent compares suppliers with it.
CREATE TABLE price_points (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    item_id         integer NOT NULL REFERENCES items(id),
    party_id        integer REFERENCES parties(id),
    source          text NOT NULL CHECK (source IN ('sale', 'purchase', 'quote', 'supplier_quote')),
    date            date NOT NULL,
    rate            numeric(14, 2) NOT NULL,
    qty             numeric(14, 3)
);
CREATE INDEX price_points_lookup ON price_points (organisation_id, item_id, party_id, date DESC);

CREATE TABLE cash_forecast (
    organisation_id integer NOT NULL REFERENCES organisations(id),
    week_start      date NOT NULL,
    scenario        text NOT NULL DEFAULT 'base',
    opening_balance numeric(14, 2) NOT NULL,       -- week 1: today's bank balance from Tally
    inflow          numeric(14, 2) NOT NULL,
    outflow         numeric(14, 2) NOT NULL,
    closing_balance numeric(14, 2) NOT NULL,       -- the number the Cash agent watches
    detail          jsonb NOT NULL DEFAULT '{}',   -- which bills and payments make up each side
    computed_at     timestamptz NOT NULL,
    PRIMARY KEY (organisation_id, week_start, scenario)
);

-- Daily headline numbers, so the brief can say what changed since yesterday.
CREATE TABLE kpi_snapshots (
    organisation_id integer NOT NULL REFERENCES organisations(id),
    day             date NOT NULL,
    metric          text NOT NULL,                 -- sales, collections, overdue, receivable, stock_value, dso ...
    value           numeric(16, 2) NOT NULL,
    PRIMARY KEY (organisation_id, day, metric)
);

-- -----------------------------------------------------------------------------
-- C. Work state: what the agents and the team are doing
-- -----------------------------------------------------------------------------

CREATE TABLE enquiries (                           -- maps to: emails + quotation_requests (enquiry side)
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    party_id        integer REFERENCES parties(id), -- null until matched
    channel         text NOT NULL CHECK (channel IN ('email', 'whatsapp_paste', 'phone_note', 'link', 'chat')),
    raw_text        text NOT NULL,
    received_at     timestamptz NOT NULL,
    parsed          jsonb,                         -- items, quantities, site, date the Sales agent understood
    status          text NOT NULL CHECK (status IN ('new', 'quoted', 'ignored')),
    assigned_to     integer REFERENCES users(id)
);

CREATE TABLE quotes (                              -- maps to: quotation_requests (quote side)
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    number          text NOT NULL,
    party_id        integer NOT NULL REFERENCES parties(id),
    enquiry_id      bigint REFERENCES enquiries(id),
    status          text NOT NULL CHECK (status IN
                      ('draft', 'pending_approval', 'sent', 'opened', 'negotiating', 'won', 'lost', 'expired')),
    created_at      timestamptz NOT NULL,
    sent_at         timestamptz,
    opened_at       timestamptz,
    decided_at      timestamptz,
    valid_until     date,
    subtotal        numeric(14, 2) NOT NULL,
    freight         numeric(14, 2) NOT NULL DEFAULT 0,
    tax             numeric(14, 2) NOT NULL,
    total           numeric(14, 2) NOT NULL,
    margin_pct      numeric(5, 2) NOT NULL,
    lost_reason     text,
    owner_id        integer REFERENCES users(id),
    sales_voucher_id bigint REFERENCES vouchers(id), -- the Tally sale it became, when won
    UNIQUE (organisation_id, number)
);

CREATE TABLE quote_lines (                         -- maps to: quotation_line_items
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    quote_id        bigint NOT NULL REFERENCES quotes(id),
    item_id         integer NOT NULL REFERENCES items(id),
    qty             numeric(14, 3) NOT NULL,
    rate            numeric(14, 2) NOT NULL,
    last_rate       numeric(14, 2),                -- what this customer last paid
    margin_pct      numeric(5, 2) NOT NULL
);

CREATE TABLE promises (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    party_id        integer NOT NULL REFERENCES parties(id),
    amount          numeric(14, 2) NOT NULL,
    made_on         date NOT NULL,
    due_date        date NOT NULL,
    source          text NOT NULL CHECK (source IN ('link', 'call', 'chat')),
    status          text NOT NULL CHECK (status IN ('open', 'kept', 'part_kept', 'missed')),
    settled_amount  numeric(14, 2) NOT NULL DEFAULT 0
);

-- Every message that leaves the building, whichever agent drafted it.
CREATE TABLE messages (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    party_id        integer REFERENCES parties(id),
    agent           text NOT NULL,
    purpose         text NOT NULL CHECK (purpose IN
                      ('reminder', 'statement', 'quote', 'nudge', 'rfq', 'offer', 'early_payment', 'payment_delay')),
    channel         text NOT NULL CHECK (channel IN ('sms', 'email', 'shared')), -- shared = a team member forwarded the link from their own phone
    language        text NOT NULL DEFAULT 'English',
    body            text NOT NULL,
    status          text NOT NULL CHECK (status IN ('draft', 'queued', 'sent', 'delivered', 'read', 'failed')),
    created_at      timestamptz NOT NULL,
    sent_at         timestamptz,
    entity_type     text,
    entity_id       bigint
);

-- Links customers and suppliers open without an account: quote, statement, rate request, offer.
CREATE TABLE share_links (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    token_hash      text NOT NULL UNIQUE,          -- only the hash is stored
    purpose         text NOT NULL CHECK (purpose IN ('quote', 'statement', 'rfq', 'offer')),
    party_id        integer NOT NULL REFERENCES parties(id),
    entity_type     text NOT NULL,
    entity_id       bigint NOT NULL,
    created_at      timestamptz NOT NULL,
    expires_at      timestamptz NOT NULL,
    first_opened_at timestamptz,
    responded_at    timestamptz,
    response        jsonb                          -- {"accepted": true} / {"pay_on": "...", "amount": ...} / {"rate": ...}
);

CREATE TABLE rfqs (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    item_id         integer NOT NULL REFERENCES items(id),
    qty             numeric(14, 3) NOT NULL,
    created_at      timestamptz NOT NULL,
    status          text NOT NULL CHECK (status IN ('open', 'closed'))
);

CREATE TABLE supplier_quotes (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    rfq_id          bigint REFERENCES rfqs(id),
    supplier_id     integer NOT NULL REFERENCES parties(id),
    item_id         integer NOT NULL REFERENCES items(id),
    rate            numeric(14, 2) NOT NULL,
    delivery_days   integer NOT NULL,
    received_at     timestamptz NOT NULL,
    valid_until     date
);

CREATE TABLE purchase_orders (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    number          text NOT NULL,
    supplier_id     integer NOT NULL REFERENCES parties(id),
    status          text NOT NULL CHECK (status IN ('draft', 'pending_approval', 'sent', 'received', 'cancelled')),
    created_at      timestamptz NOT NULL,
    total           numeric(14, 2) NOT NULL,
    purchase_voucher_id bigint REFERENCES vouchers(id),
    UNIQUE (organisation_id, number)
);

CREATE TABLE po_lines (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    po_id           bigint NOT NULL REFERENCES purchase_orders(id),
    item_id         integer NOT NULL REFERENCES items(id),
    qty             numeric(14, 3) NOT NULL,
    rate            numeric(14, 2) NOT NULL
);

-- The Inbox: everything waiting for a person, from every agent, in one table.
CREATE TABLE tasks (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    agent           text NOT NULL,
    kind            text NOT NULL,                 -- call_customer, review_quote, reorder, missed_promise ...
    title           text NOT NULL,
    detail          text,
    entity_type     text,
    entity_id       bigint,
    amount          numeric(14, 2),                -- money at stake, for sorting
    priority        smallint NOT NULL DEFAULT 2,   -- 1 high .. 3 low
    assignee_role   text NOT NULL,
    status          text NOT NULL CHECK (status IN ('open', 'done', 'dismissed', 'snoozed')),
    created_at      timestamptz NOT NULL,
    due_at          timestamptz,
    done_at         timestamptz
);
CREATE INDEX tasks_open ON tasks (organisation_id, assignee_role, priority) WHERE status = 'open';

-- Anything above the rules waits here. graph_thread_id lets the agent resume
-- exactly where it paused (LangGraph interrupt -> resume).
CREATE TABLE approvals (                           -- maps to: approvals (generalised)
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    agent           text NOT NULL,
    action_type     text NOT NULL,                 -- send_quote, send_po, change_credit_limit, send_offer ...
    title           text NOT NULL,
    reason          text NOT NULL,                 -- the rule it crossed, in plain words
    amount          numeric(14, 2),
    payload         jsonb NOT NULL,                -- exactly what will happen on approve
    requested_by    integer REFERENCES users(id),
    requested_at    timestamptz NOT NULL,
    status          text NOT NULL CHECK (status IN ('waiting', 'approved', 'rejected', 'expired')),
    decided_by      integer REFERENCES users(id),
    decided_at      timestamptz,
    graph_thread_id text
);

-- The rules the owner sets in Agents & rules. One row per setting.
CREATE TABLE agent_rules (
    organisation_id integer NOT NULL REFERENCES organisations(id),
    agent           text NOT NULL,
    key             text NOT NULL,                 -- remind_days_before_due, margin_floor_pct, po_limit ...
    value           jsonb NOT NULL,
    updated_by      integer REFERENCES users(id),
    updated_at      timestamptz NOT NULL,
    PRIMARY KEY (organisation_id, agent, key)
);

-- -----------------------------------------------------------------------------
-- D. Memory: the business timeline, what the agents have learned, documents
-- -----------------------------------------------------------------------------

-- Every business event, in order. Also the outbox agents subscribe to.
CREATE TABLE events (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    occurred_at     timestamptz NOT NULL,
    type            text NOT NULL,                 -- receipt.posted, quote.opened, promise.missed ...
    entity_type     text NOT NULL,
    entity_id       bigint NOT NULL,
    source          text NOT NULL CHECK (source IN ('tally_sync', 'agent', 'user', 'link', 'schedule')),
    actor           text,                          -- agent name or user id
    payload         jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX events_type_time ON events (organisation_id, type, occurred_at);
CREATE INDEX events_entity    ON events (organisation_id, entity_type, entity_id);

-- Which agent has handled which event: each consumer processes each event once.
CREATE TABLE event_deliveries (
    event_id        bigint NOT NULL REFERENCES events(id),
    consumer        text NOT NULL,                 -- agent name
    status          text NOT NULL CHECK (status IN ('pending', 'done', 'failed', 'skipped')),
    attempts        smallint NOT NULL DEFAULT 0,
    processed_at    timestamptz,
    PRIMARY KEY (event_id, consumer)
);

-- Words customers use for items: "saria" -> TMT 12mm. Learned from corrections.
CREATE TABLE item_aliases (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    item_id         integer NOT NULL REFERENCES items(id),
    alias           text NOT NULL,
    source          text NOT NULL CHECK (source IN ('tally', 'learned', 'user')),
    hits            integer NOT NULL DEFAULT 0,
    UNIQUE (organisation_id, alias)
);

-- What the agents should remember beyond the numbers: preferences, standing
-- instructions, facts from conversations. Searched by meaning (pgvector).
CREATE TABLE memories (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    scope_type      text NOT NULL CHECK (scope_type IN ('org', 'party', 'item', 'user')),
    scope_id        bigint,
    kind            text NOT NULL CHECK (kind IN ('preference', 'instruction', 'fact', 'note')),
    content         text NOT NULL,
    embedding       vector(1536),                  -- filled by the embedding job
    source          text NOT NULL,                 -- chat, call note, email, user
    confidence      numeric(3, 2) NOT NULL DEFAULT 0.8,
    valid_from      timestamptz NOT NULL,
    valid_to        timestamptz,                   -- set when a newer fact replaces it; never deleted
    created_by      text NOT NULL
);
CREATE INDEX memories_scope ON memories (organisation_id, scope_type, scope_id) WHERE valid_to IS NULL;
CREATE INDEX memories_embedding ON memories USING hnsw (embedding vector_cosine_ops);

CREATE TABLE documents (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    kind            text NOT NULL CHECK (kind IN ('email', 'pdf', 'po', 'invoice', 'mtc', 'note')),
    title           text NOT NULL,
    party_id        integer REFERENCES parties(id),
    received_at     timestamptz NOT NULL,
    storage_url     text,
    text            text
);

CREATE TABLE document_chunks (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    document_id     bigint NOT NULL REFERENCES documents(id),
    chunk_no        integer NOT NULL,
    content         text NOT NULL,
    embedding       vector(1536),
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
);
CREATE INDEX document_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX document_chunks_tsv ON document_chunks USING gin (tsv);

-- Chat threads in the app. The conversation itself is LangGraph's checkpoint
-- (tables created by langgraph-checkpoint-postgres); this row ties it to a person.
CREATE TABLE chat_threads (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    user_id         integer NOT NULL REFERENCES users(id),
    agent           text NOT NULL,
    langgraph_thread_id text NOT NULL UNIQUE,
    created_at      timestamptz NOT NULL,
    last_message_at timestamptz
);

-- -----------------------------------------------------------------------------
-- E. Runs and audit
-- -----------------------------------------------------------------------------

CREATE TABLE agent_runs (
    id              bigint PRIMARY KEY,
    organisation_id integer NOT NULL REFERENCES organisations(id),
    agent           text NOT NULL,
    trigger_type    text NOT NULL CHECK (trigger_type IN ('event', 'schedule', 'chat', 'manual')),
    trigger_ref     text,
    started_at      timestamptz NOT NULL,
    finished_at     timestamptz,
    status          text NOT NULL CHECK (status IN ('running', 'ok', 'waiting_approval', 'failed')),
    llm_calls       integer NOT NULL DEFAULT 0,
    tokens_in       integer NOT NULL DEFAULT 0,
    tokens_out      integer NOT NULL DEFAULT 0,
    cost_inr        numeric(10, 2) NOT NULL DEFAULT 0,
    outcome         jsonb,
    error           text
);
CREATE INDEX agent_runs_recent ON agent_runs (organisation_id, agent, started_at DESC);
-- audit_logs and llm_calls already exist and stay as they are.

-- -----------------------------------------------------------------------------
-- Views agents read most: one place for "what is overdue" and "last rate"
-- -----------------------------------------------------------------------------

CREATE VIEW overdue_bills AS
SELECT b.*, p.name AS party_name, (CURRENT_DATE - b.due_date) AS days_late
FROM bills b JOIN parties p ON p.id = b.party_id
WHERE b.direction = 'receivable' AND b.pending_amount > 0 AND b.due_date < CURRENT_DATE;

CREATE VIEW last_sale_rate AS
SELECT DISTINCT ON (organisation_id, party_id, item_id)
       organisation_id, party_id, item_id, date, rate
FROM price_points
WHERE source = 'sale'
ORDER BY organisation_id, party_id, item_id, date DESC;
