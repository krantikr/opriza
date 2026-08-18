# AI Sales Quotation Copilot

An AI-assisted quotation workflow for a steel trading business. It reads inbound
enquiry email, works out what the customer is asking for, prices it against the
company's own price list and invoice history, drafts a reply, and puts the whole
thing in front of a human who decides whether it goes out.

The organising principle, and the reason the code is shaped the way it is:

> **Language models read and write. Deterministic services price. A human commits.**

Margins in steel trading are thin — the default rules here floor at 2% — and
prices move daily. A hallucinated rate is not a bad user experience, it is a
loss-making order. So no model is ever asked for a number that matters.

---

## What it does

```
Gmail ─► ingest ─► classify ─► extract ─► match product ─► price ─► draft ─► REVIEW ─► send
         (dedupe)   (AI)        (AI)      (deterministic)  (det.)   (AI)     (human)
```

| Stage | Who decides | What happens when it is unsure |
|---|---|---|
| Classify | AI | Anything not a quotation request is recorded and left alone |
| Extract | AI | Missing details are reported, never invented |
| Match product | **Deterministic** | Ambiguous or unknown → a human chooses |
| Convert units | **Deterministic** | Cannot convert → a human decides the tonnage |
| Price | **Deterministic** | Below margin floor → corrected *and* flagged |
| Draft | AI | Figures are verified after generation; altered ones trigger a rewrite |
| Send | **Human** | There is no other code path that sends |

---

## Quick start

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
# 1. Install and configure
uv sync
cp .env.example .env

# 2. Generate sample steel data and enquiry emails
uv run python scripts/generate_sample_data.py

# 3. Create the database and import the master data
uv run python scripts/init_db.py --reset

# 4. Ingest the sample enquiries
uv run python scripts/poll_once.py

# 5. Run the API
uv run uvicorn app.main:app --reload

# 6. Run the dashboard (in a second terminal)
cd frontend && npm install && npm run dev
```

Dashboard: <http://localhost:5173> · API docs: <http://localhost:8000/docs>

Everything above works **without any credentials**. The AI stages need an
OpenRouter key; see below.

---

## Configuration

All behaviour is environment-driven — see [`.env.example`](.env.example) for the
annotated list. The two placeholders you need to fill in:

### 1. OpenRouter API key

```bash
OPENROUTER_API_KEY=sk-or-...
```

Models are routed **per task**, because classification runs on every inbound
email while extraction and drafting run only on the quotation subset. At a
thousand emails a day, pointing all three at the same model multiplies the bill
by the volume of the cheapest step.

```bash
LLM_MODEL_CLASSIFY=openai/gpt-4o-mini          # every email
LLM_MODEL_EXTRACT=anthropic/claude-sonnet-4.5  # quotation requests only
LLM_MODEL_DRAFT=anthropic/claude-sonnet-4.5    # quotation requests only
```

Any OpenRouter model works. Structured-output support varies between them, so
the extractor degrades through three modes — strict JSON schema, JSON mode,
then prompt-only — with a repair attempt at each. If all of them fail, the
enquiry goes to a human; it never proceeds on partially parsed data.

### 2. Gmail OAuth

```bash
GMAIL_CREDENTIALS_FILE=data/secrets/gmail_credentials.json
```

1. Create a Google Cloud project and enable the Gmail API.
2. Create OAuth client credentials of type **Desktop app**.
3. Save the downloaded JSON to the path above.
4. Authorise once:

```bash
uv run python scripts/gmail_auth.py
```

Only `gmail.readonly` and `gmail.send` are requested. The system never needs to
modify or delete a customer's mail, so it never asks for permission to.

Then switch the source over:

```bash
EMAIL_SOURCE=gmail
GMAIL_QUERY="in:inbox -in:chats newer_than:7d"
```

Until you do, `EMAIL_SOURCE=local` reads `.eml` files from
`data/sample/emails/`, and "sending" writes to `data/sent/` instead of mailing a
real customer.

---

## Project layout

```
.
├── ai/                    Pure language layer — no database, no HTTP, no business rules
│   ├── llm/               Client interface, OpenRouter adapter, strict-schema handling
│   ├── prompts/           classify · extract · normalize · draft (editable .md files)
│   ├── schemas.py         Typed contracts for every model output
│   └── guards.py          Verifies a draft reproduced the figures it was given
│
├── backend/app/
│   ├── config/            business_rules.yaml — every commercial number lives here
│   ├── core/              settings, database, rules loader, logging
│   ├── models/            SQLAlchemy ORM (15 tables)
│   ├── services/
│   │   ├── email/         source port · Gmail · local files · attachments · sending
│   │   ├── products/      weight & unit conversion · normaliser · matcher
│   │   ├── pricing/       history · engine · confidence
│   │   ├── quotations/    assembly · drafting · approval
│   │   └── ingestion/     Excel importers with tolerant column mapping
│   ├── workflows/         The LangGraph quotation graph
│   └── api/v1/            REST endpoints
│
├── frontend/src/          Vite + React + TypeScript dashboard
├── scripts/               generate_sample_data · init_db · gmail_auth · poll_once
└── data/                  sample files, SQLite database, secrets (gitignored)
```

Two structural decisions worth knowing:

**`ai/` never imports from `backend/`.** It is pure typed functions — testable
with recorded fixtures, no database, no network. The LangGraph workflow lives in
the backend because it must reach the database and the pricing engine; putting
it in `ai/` would collapse the separation. When individual stages later become
agents (spec §26), that is a rewiring, not a rewrite.

**Email input and output are ports.** `EmailSource` has Gmail and local-file
implementations, as does the sender. That is why the entire pipeline is
developable, testable and demonstrable before any credential exists — and why a
demo cannot be derailed by a network problem.

---

## Business rules

Nothing commercial is hard-coded, and nothing in
[`backend/app/config/business_rules.yaml`](backend/app/config/business_rules.yaml)
is ever shown to a model as something to compute with. The engine reads these
values and does the arithmetic in `Decimal`.

The pricing chain, in order:

| Step | What it does |
|---|---|
| `base_price` | The price in force today, from the effective-dated price master |
| `target_margin` | Lifts cost to a quotable selling price (default 3.5%) |
| `historical_anchor` | Blends in the average of recent comparable sales (default 40%) |
| `quantity_slab` | Volume pricing by tonnage band |
| `customer_tier` | A/B/C commercial adjustment |
| `freight` | Per-MT rate by delivery location — added *after* the percentage steps, because a tier discount should reduce the material rate, not the lorry |
| `margin_floor` | Clamps up to the minimum margin **and flags that it happened** |
| `rounding` | To a quotable figure, never back down through the floor |

Each step returns its adjustment **and the sentence explaining it**, so the
stored explanation is a by-product of the calculation rather than a model asked
to justify a number afterwards:

```
Base price for PLT-E250-10X1500X6000 effective 2026-08-09: INR 56,500.00/MT.
Applied the standard 3.5% margin over base cost: INR 58,477.50.
Blended 40% of the average of 9 comparable sale(s) in the last 30 days
  (INR 58,162.00) with the base price: INR 58,351.30.
Quantity 20 MT falls in the 5-25 MT slab: no adjustment.
Customer tier A applies a 0.5% discount: INR 58,059.55.
Freight to Patna: INR 1,200.00 per MT added.
Price clears the minimum of INR 58,830.00 (2% over base plus freight).
Rounded to the nearest INR 50: INR 59,250.00.
```

Product matching is scored out of 100 across the fields the enquiry actually
states, renormalised over those. A candidate must clear `accept_score` **and**
beat the runner-up by `ambiguity_delta`, otherwise the result is
`MULTIPLE_MATCHES` and a human picks. Thickness tolerance is 0% on purpose: a
12 mm plate is not a near miss for a 10 mm one, it is a different product.

Change a number, restart, done — `GET /api/v1/system/rules` shows what is
currently in force, and every recommendation stores the rules version that
produced it.

---

## Importing your own data

Excel is an input, never the running store. Replace the files in `data/sample/`
and re-import:

```bash
uv run python scripts/init_db.py --data-dir /path/to/your/files
```

Expected files: `products.xlsx`, `customers.xlsx`, `price_master.xlsx`,
`sales_history.xlsx`. Missing files are skipped rather than treated as errors.

Column headers are matched tolerantly — `Thickness (mm)`, `THICKNESS`, `Thk.`
and `thickness_mm` all resolve to the same field — so you should not have to
reshape your spreadsheets. A bad row is counted and recorded with its row number
and reason; the import continues. Every row written carries an `ImportBatch` id
holding the file name, a content hash and the validation errors, so any figure
can be traced back to the file it came from.

---

## Testing

```bash
uv run pytest                      # 161 tests
uv run pytest backend/tests/test_pricing.py -v
uv run ruff check .
cd frontend && npm run typecheck
```

The suite covers what actually carries risk:

- **`test_pricing.py`** — the chain asserted against hand-worked figures, plus
  the floor, outlier rejection, window widening, and every refusal path.
- **`test_matcher.py`** — the confident matches and, more importantly, the two
  cases where the system declines to choose.
- **`test_weights.py`** — conversions checked against published sectional
  weights, so 20 MT and 40 pieces of the same material agree.
- **`test_llm_structured.py`** — the three-stage structured-output fallback,
  with a scripted transport.
- **`test_drafting.py`** — the guardrail that catches a model rounding ₹59,200
  to ₹59,000.
- **`test_workflow.py`** — routing end to end, including everything that must
  *not* produce a quotation.
- **`test_api.py`** — the review actions, and the refusals: no double send, no
  send without a draft, no send after rejection.

---

## Safety properties

These are enforced structurally, not by configuration:

1. **No automatic sending.** `approve_and_send` is the only function that sends,
   and it cannot be reached without writing an `Approval` row first. No
   scheduled job or config value routes to it. `AUTO_SEND_ENABLED` exists so the
   intent is auditable and is asserted against, not consulted.
2. **No invented prices.** The pricing engine reads the price master and invoice
   history. A model never sees pricing rules and is never asked for a figure.
3. **No invented products.** Matching is deterministic. Ambiguity produces a
   shortlist for a human, not a choice.
4. **No invented quantities.** A quantity with no unit is an unknown order
   value, and the conversion refuses rather than guessing.
5. **Drafts are verified.** Every price, quantity and total handed to the model
   is checked for presence in what it wrote. A draft that alters one is
   regenerated; one that fails twice is stored and flagged, never sent quietly.
6. **Unknown senders are not auto-created as customers.** A first-time enquiry
   loses its tier adjustment and its HIGH confidence, and reaches a human.
7. **Everything is audited.** Every state change writes an `AuditLog` row, and
   every approval stores both the model's text and the text actually sent.

---

## Current limitations

Stated plainly, because they matter for planning:

- **Single mailbox.** One Gmail account, one company.
- **No authentication.** The dashboard has no login; actions are attributed to a
  seeded default user. The `users` table and every `user_id` foreign key already
  exist, so adding auth is a login endpoint and a dependency — not a migration
  through the audit trail.
- **SQLite.** Fine for the MVP at this volume. All SQL goes through SQLAlchemy
  with no SQLite-specific syntax, so PostgreSQL is a connection-string change
  plus a migration tool.
- **No migrations.** `init_db.py --reset` is the honest workflow while the data
  is regenerable. Alembic goes in at the PostgreSQL transition.
- **Scanned PDFs are not read.** Attachment extraction covers text PDFs, Excel,
  CSV and plain text. A scanned image RFQ records "no extractable text" and
  reaches a human intact; OCR is out of scope.
- **Candidate matching scans the product master in Python.** Correct and fast at
  a few hundred products; a master in the tens of thousands wants the scoring
  pushed into SQL.
- **Not built yet, by design:** ERP integration, inventory, negotiation replies,
  WhatsApp, multi-company, auto-send policies. The ports and interfaces are
  positioned for them.

---

## Command reference

| Command | What it does |
|---|---|
| `uv run python scripts/generate_sample_data.py` | Regenerate sample steel data and enquiries |
| `uv run python scripts/init_db.py --reset` | Recreate the schema, seed the user, import master data |
| `uv run python scripts/init_db.py --no-import` | Schema and user only |
| `uv run python scripts/gmail_auth.py` | One-time Gmail authorisation |
| `uv run python scripts/poll_once.py` | Ingest new mail |
| `uv run python scripts/poll_once.py --process` | Ingest, then run the quotation workflow |
| `uv run uvicorn app.main:app --reload` | Run the API |
| `uv export --no-hashes --no-emit-project --no-dev -o requirements.txt` | Refresh `requirements.txt` from `uv.lock` |

Set `POLLING_ENABLED=true` to run the ingest-and-process cycle on a timer
instead. It is off by default: polling a real mailbox is a decision to make
deliberately, not something that should start happening because someone ran the
server.

---

## API

`GET /docs` for the full interactive reference. The endpoints the dashboard uses:

```
GET    /api/v1/quotations                      list, filter, search
GET    /api/v1/quotations/{id}                 full review context
PUT    /api/v1/quotations/{id}/draft           save edits (does not send)
POST   /api/v1/quotations/{id}/regenerate      new draft from the same figures
POST   /api/v1/quotations/{id}/approve         record approval, then send
POST   /api/v1/quotations/{id}/reject          close without sending

GET    /api/v1/emails                          inbound mail, any category
GET    /api/v1/products  /customers            master data
POST   /api/v1/pricing/recommend               price a product directly
GET    /api/v1/dashboard/metrics               KPIs, quality signals, model spend
GET    /api/v1/audit-logs                      every state change
GET    /api/v1/system/status  /system/rules    what is configured, what is in force

POST   /api/v1/pipeline/ingest  /process  /run manual triggers
```
