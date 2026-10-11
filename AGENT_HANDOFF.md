# Agent Handoff — Setup & Deployment

One file that tells an AI agent (or a new developer) everything needed to run
this project locally and deploy it free. Written to be followed top to bottom
from a **fresh clone** of the repository.

> **What this app is.** An AI-assisted sales-quotation copilot for steel
> trading. A FastAPI backend reads enquiry emails, an LLM extracts and drafts,
> deterministic services price against stock, and a human approves before
> anything sends. A React (Vite) frontend is the dashboard. Multi-tenant:
> several trading desks share one deployment, isolated by PostgreSQL row-level
> security (RLS).

---

## 0. What transferred to the new repo, and what did NOT

When the code was copied to a new Git repo, **hidden/`.`-folders and ignored
files do not come across**. That is expected — most are regenerated. Here is the
full picture so nothing feels missing:

**Tracked in Git → present in a fresh clone (do not recreate):**
- `.github/workflows/email-sync-cron.yml` — the cron workflow
- `.dockerignore`, `.gitignore`, `.python-version`
- `.env.example` — the template for `.env`
- `Dockerfile`, `render.yaml` — deploy config
- `data/secrets/.gitkeep` — keeps the secrets dir present (empty)

**NOT transferred, and correctly so — regenerate locally (see §2):**
| Missing item | What it is | How to restore |
|---|---|---|
| `.venv/` | Python virtualenv | `uv sync` |
| `.env` | real secrets/config | `cp .env.example .env` then edit |
| `node_modules/` | frontend deps | `cd frontend && npm install` |
| `frontend/dist/` | built frontend | `npm run build` |
| `data/*.db`, `data/sample/*.xlsx` | local SQLite + sample data | the seed scripts in §2 |
| `.pytest_cache/`, `.ruff_cache/`, `__pycache__/` | tool caches | created automatically |
| `*service-account*.json` (Firebase) | push-notification key | only if you use push; obtain from Firebase |

**If a `.`-folder you expected is gone, check the table above before worrying —
almost everything is either tracked (so it's there) or regenerable.** The only
things that are genuinely gone and *not* regenerable are real secrets (`.env`
values, Firebase keys), which never belong in Git anyway.

---

## 1. Prerequisites

- **Python 3.12** (see `.python-version`)
- **uv** (Python package manager) — https://docs.astral.sh/uv/
- **Node 20+** and npm
- **PostgreSQL** — local for dev, or a free Neon project for deploy.
  NOTE: SQLite works for a quick local run (`DATABASE_URL=sqlite:///data/app.db`)
  but **multi-tenant RLS requires PostgreSQL**. Deploy must use Postgres.
- Optional: **Docker** (for building the deploy image locally)
- An **OpenRouter API key** for the AI steps (https://openrouter.ai)

---

## 2. Local setup from a fresh clone

```bash
# 1. Install backend deps and create your env file
uv sync
cp .env.example .env          # then edit .env — at minimum set OPENROUTER_API_KEY

# 2. Generate sample steel data + enquiry emails
uv run python scripts/generate_sample_data.py

# 3. Create the database and import master data
uv run python scripts/init_db.py --reset

# 4. (Postgres only) apply row-level-security policies
uv run python scripts/rls.py apply      # skip on SQLite; required on Postgres

# 5. Ingest the sample enquiries
uv run python scripts/poll_once.py

# 6. Run the API (terminal 1)
uv run uvicorn app.main:app --reload

# 7. Run the dashboard (terminal 2)
cd frontend && npm install && npm run dev
```

Backend: http://localhost:8000 (health at `/health`, docs at `/docs`).
Frontend: http://localhost:5173 (proxies `/api` → backend, see `vite.config.ts`).

**Tests:** `uv run pytest` (backend) · `cd frontend && npm test` (frontend).

---

## 3. Key config (`.env`)

All vars are documented in `.env.example`. The ones that matter most:

| Var | Purpose | Deploy value |
|---|---|---|
| `DATABASE_URL` | DB connection. **Must** start `postgresql+psycopg://` for Postgres. | Neon URL, app role (see §5) |
| `OPENROUTER_API_KEY` | LLM access; AI steps refuse to run without it | your key |
| `JWT_SECRET` | signs login sessions | random 48+ chars |
| `CREDENTIAL_KEY` | Fernet key; encrypts stored mailbox tokens | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` |
| `CRON_SECRET` | guards the external email-sync trigger | random 48+ chars; same value in GitHub secret |
| `CORS_ORIGINS` | allowed frontend origins (comma-sep) | the Vercel URL |
| `POLLING_ENABLED` | in-process mail poller | **`false`** in deploy — external cron drives sync instead |

---

## 4. Architecture of the deployment (free tier)

```
 Vercel (frontend, static)         GitHub Actions (cron, every ~5 min)
        │  /api/* rewrite                     │  POST /api/v1/pipeline/cron
        ▼                                     ▼
 Render (FastAPI backend, Docker) ◄───────────┘   also wakes the sleeping host
        │
        ▼
 Neon (PostgreSQL, free)   ← app connects as a NOSUPERUSER NOBYPASSRLS role
```

**Why email sync is an external cron, not the in-process scheduler:** the free
host spins down when idle, so a `BackgroundScheduler` cannot be trusted to keep
ticking. `POST /api/v1/pipeline/cron` (guarded by `CRON_SECRET`) runs one poll
across **all** desks and is called by GitHub Actions; the call also wakes the
host. Keep `POLLING_ENABLED=false` in production.

---

## 5. Deployment — step by step

### 5a. Neon (PostgreSQL)

1. Create a Neon project. Note the **host**, database name (`neondb`), and that
   the default role (`neondb_owner`) is privileged.
2. In the Neon **SQL Editor**, create a dedicated app role. **This is
   mandatory** — the app refuses to boot if it connects as a superuser or a
   BYPASSRLS role (see `app/core/tenancy.py::assert_rls_enforced`), because that
   silently disables tenant isolation:

   ```sql
   CREATE ROLE steeldesk_app LOGIN PASSWORD '<strong-password>'
     NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
   GRANT CONNECT ON DATABASE neondb TO steeldesk_app;
   GRANT USAGE, CREATE ON SCHEMA public TO steeldesk_app;
   GRANT ALL ON ALL TABLES IN SCHEMA public TO steeldesk_app;
   GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO steeldesk_app;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO steeldesk_app;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO steeldesk_app;
   ```

3. Build `DATABASE_URL`:
   ```
   postgresql+psycopg://steeldesk_app:<password>@<neon-host>/neondb?sslmode=require
   ```

### 5b. Render (backend)

1. Render → **New → Blueprint** → connect GitHub → pick this repo (branch
   `main`). It reads `render.yaml` and creates a free Docker web service.
2. Set env vars in the dashboard: `DATABASE_URL`, `CREDENTIAL_KEY`,
   `CRON_SECRET`, `OPENROUTER_API_KEY`, and `CORS_ORIGINS` (temporarily `*`,
   then the Vercel URL). `JWT_SECRET` can be auto-generated by the blueprint.
3. Deploy. First build is slow (installs WeasyPrint native libs). The container
   runs `alembic upgrade head` then starts uvicorn.
4. **After the first successful deploy, apply RLS policies once.** Migrations
   create tables; `scripts/rls.py apply` creates the per-table policies. Run it
   against the Neon DB from the Render **Shell** tab, or locally with
   `DATABASE_URL` pointed at Neon:
   ```bash
   uv run python scripts/rls.py apply
   ```
   Verify with `uv run python scripts/rls.py check` (should report no gaps).
5. Confirm `https://<render-url>/health` returns `{"status":"ok",...}`.

   > If logs say *"tenant isolation is not in force"* and the app exits, the
   > `DATABASE_URL` role is still superuser/BYPASSRLS — redo §5a.

### 5c. Vercel (frontend)

1. In `frontend/vercel.json`, replace `REPLACE-WITH-RENDER-HOST` with the Render
   host (host only, no `https://`, no trailing slash). Commit and push.
2. Vercel → import the repo, **root directory = `frontend`**. It auto-deploys on
   push. The rewrite sends `/api/*` to Render; everything else is the SPA.
3. Put the Vercel URL into Render's `CORS_ORIGINS` and redeploy Render.

### 5d. GitHub Actions (email-sync cron)

Repo → **Settings → Secrets and variables → Actions** → add:
- `API_BASE_URL` = the Render URL (e.g. `https://quotation-copilot-api.onrender.com`)
- `CRON_SECRET` = the same value as Render's `CRON_SECRET`

The workflow `.github/workflows/email-sync-cron.yml` then POSTs to
`/api/v1/pipeline/cron` every ~5 min. Trigger it once by hand from the
**Actions** tab (**Run workflow**) and confirm a `202`.

> Scheduled workflows auto-disable after 60 days with no repo commits — a
> periodic commit keeps it alive.

---

## 6. Agent task checklist

An agent completing the deployment should, in order:

1. ✅ Code is already prepared: `/api/v1/pipeline/cron` endpoint, `Dockerfile`,
   `render.yaml`, `frontend/vercel.json`, cron workflow. Do **not** re-create
   these; verify they exist.
2. ⛔ **Human-only steps** (cannot be done by an agent — ask the user):
   account sign-ins, GitHub OAuth grants (Render, Vercel), email verification,
   entering secret values into dashboards, and clicking final "Deploy".
3. 🔧 Agent-doable: generate secrets, write/patch config files, run the Neon
   role SQL (via the user's logged-in SQL editor), fill form fields, run
   `rls.py apply`/`check`, run the test suite, assemble `DATABASE_URL`, and
   update `vercel.json` with the Render host once known.
4. 🔁 Dependency order is strict: **Neon → Render (URL appears) → Vercel rewrite
   + GitHub secrets**. The Vercel `/api` rewrite and the GitHub `API_BASE_URL`
   both need the Render URL, which does not exist until Render is deployed.

---

## 7. Gotchas (learned the hard way)

- **RLS role.** The single most common deploy failure: connecting as a
  privileged DB role. Must be `NOSUPERUSER NOBYPASSRLS`. The app enforces this
  at boot on purpose.
- **Run `rls.py apply` after migrations.** Tables without policies = tenant
  leak. `rls.py check` is run by the test suite so a gap fails CI, but on a
  fresh DB you must apply once after the first migrate.
- **`DATABASE_URL` driver prefix.** Use `postgresql+psycopg://` (psycopg 3), not
  bare `postgresql://`, or SQLAlchemy may pick the wrong driver.
- **WeasyPrint PDFs.** Need Pango/Cairo/GDK-Pixbuf system libs — the `Dockerfile`
  installs them. Without them, PDF generation degrades gracefully (disables)
  rather than crashing.
- **Free host cold start.** First request after idle takes ~30–60s while the
  container wakes. The cron call absorbs this; for a live demo, hit the app a
  minute early.
- **Frontend talks to `/api` relatively.** There is no hardcoded backend URL in
  the frontend; the dev proxy (`vite.config.ts`) and the prod rewrite
  (`vercel.json`) are what point `/api` at the backend. Keep both in sync.
