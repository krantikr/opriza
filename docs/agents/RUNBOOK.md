# Oprisa agents — runbook

How to run the agent product, and what to change to move a desk from the sample books to a customer's real Tally. Architecture: see the "Oprisa agents architecture" doc and `docs/agents/schema.sql`.

## What's where

| Piece | Where |
|---|---|
| Knowledge base (39 `kb_*` tables, row-level security) | `backend/app/kb/models.py`, migration `k1b00base01` |
| Where the books come from | `backend/app/kb/sources/` — `mock.py` (sample books), `tally_xml.py` (real Tally) |
| Sync, facts, events, rules, clock | `backend/app/kb/{sync,facts,events,rules,clock}.py` |
| Agent runtime (LangGraph, approvals as interrupts) | `backend/app/kb/runtime.py` |
| The seven agents | `backend/app/kb/agents/` — sales, collect, stock, cash, score, brief, ask |
| Brain (rules or LLM) | `backend/app/kb/brain/` |
| Sending (outbox, email, SMS) and customer links | `backend/app/kb/{channels,links}.py` |
| Scheduling | `backend/app/kb/jobs.py`, `scripts/agents_tick.py` |
| API | `/api/v1/app/*` (`api/v1/oprisa.py`), public `/api/v1/links/{token}` (`api/v1/links.py`) |
| Screens | `frontend/src/product/` — desk at `/app`, phone layout under 1100 px, customer links at `/l/:token` |

## Run it locally on the sample books

```bash
uv run alembic upgrade head            # adds the kb_* tables with their RLS policies
uv run python scripts/oprisa_seed.py   # three sample desks; prints the sign-ins
uv run uvicorn app.main:app --app-dir backend --port 8000
cd frontend && npm run dev             # http://localhost:5173/sign-in, then /app
```

Sign in as `kranti@shree-balaji-steels.demo` / `oprisa-demo-1` (owner). Other people on the same desk: `pooja@…` (sales), `rohan@…` (accounts), `priya@…` (purchase). The other two desks are `patel-build-mart` (building materials, Ahmedabad) and `sai-pharma-distributors` (pharma, Nagpur).

A sample desk holds its clock at 19 Oct 2026, 10:30 IST. That's the day the planted situations are built around. **Settings → Try it** posts a receipt, answers an RFQ or moves the clock. These go through the same code a live desk uses.

Re-running `oprisa_seed.py <slug>` rebuilds that desk from scratch.

## Settings (`.env`)

| Variable | Default | What it does |
|---|---|---|
| `AGENT_BRAIN` | `auto` | `rules` makes no model calls. `llm` uses OpenRouter, with the rules as fallback and as the check on every answer. `auto` means `llm` when `OPENROUTER_API_KEY` is a real key. |
| `OPENROUTER_API_KEY` | — | Already used by the email copilot. The agents use the same key. |
| `AGENT_MODEL_FAST` / `AGENT_MODEL_WRITE` | `LLM_MODEL_CLASSIFY` / `LLM_MODEL_DRAFT` | FAST reads enquiries and picks the tool for a question. WRITE words messages and answers. |
| `AGENT_CHANNEL` | `outbox` | `outbox` stores every message and writes it to `data/sent/agents/`; nothing leaves. `live` sends email through the existing sender and SMS through the webhook. |
| `SMS_WEBHOOK_URL`, `SMS_WEBHOOK_TOKEN` | — | Live SMS. The agents POST `{"to", "text"}` with a Bearer token. Adapt `SmsWebhookChannel.send` in `channels.py` for your gateway. |
| `APP_PUBLIC_URL` | `http://localhost:5173` | Base address for the `/l/<token>` links inside messages. |
| `AGENTS_SCHEDULER` | `off` | `on` runs due jobs and events every 5 minutes inside the API. Leave it off if cron runs `scripts/agents_tick.py`. |

The header shows **AI** or **Rules** so you can see which brain is running. Each run's brain, LLM calls and tokens are in **Agents & rules → Run log**.

`AUTO_SEND_ENABLED` belongs to the older email copilot only. The agents follow their own rule: within the owner's rules they act (send a quote inside the margin band, a reminder, a statement). Anything outside the rules waits in **Inbox → Approvals**. Keep a desk on `outbox` until its owner has set the rules in **Agents & rules → Your rules**.

## Going live: swap the sample books for a real Tally

Only the source changes. The sync hands every source's data to the same `apply_batch`, so facts, agents, API and screens don't know where the books came from.

1. **Make Tally reachable.** On the office PC, in TallyPrime, go to **F1 Help → Settings → Connectivity**. Set **TallyPrime acts as** to *Server* on port 9000. The backend must reach that address. Either run the connector on the same LAN and expose it, or use a tunnel. `TallyXmlSource` POSTs standard XML export requests to it.
2. **Check the three go-live TODOs** in `backend/app/kb/sources/tally_xml.py` against the customer's Tally:
   - the AlterID filter form, which differs between TallyPrime and ERP 9;
   - which ledgers count as bank;
   - godown-wise closing stock.

   `parse_envelope()` is covered by tests against a sample export. Save one real export (`curl -d @request.xml http://tally:9000`) and run it through `parse_envelope` first.
3. **Connect the desk.** The organisation and its users already exist through the normal sign-up and invite flow.

   ```bash
   uv run python scripts/oprisa_connect.py <org-slug> --tally-url http://192.168.1.20:9000 \
       --city Pune --language Hinglish
   uv run python scripts/oprisa_connect.py <org-slug> --role rohan@firm.in accounts
   ```

   The connect step does four things:
   - creates `kb_business` with `source="tally_xml"` and the real-time clock;
   - gives every user a desk role (the owner becomes owner, everyone else sales until you change it);
   - runs the first full sync, then builds the facts;
   - runs one agent cycle.

   If Tally is offline, the desk is still created and every tick retries.
4. **Keep it in step.** Do one of these:
   - set `AGENTS_SCHEDULER=on`;
   - add cron: `*/5 * * * * cd /srv/oprisa && uv run python scripts/agents_tick.py`.

   Each tick does three things for every desk:
   - syncs vouchers changed since the last AlterID (every 15 minutes);
   - runs the scheduled jobs that are due (8 am brief, 9 am reminders, quote nudges…);
   - dispatches events to the agents.
5. **Turn on sending.** Set `AGENT_CHANNEL=live` and `APP_PUBLIC_URL=https://<your domain>`. Before that, check the drafts under **Agents & rules → Messages sent**.
6. **Write-back to Tally.** Approved sales orders, purchase orders and credit-limit changes queue in `kb_tally_postings` (**Agents & rules → Back to Tally**). The connector should poll these and import them as vouchers or masters. Nothing writes into Tally directly.

`MockTallySource` stays available for demos and tests. A desk on sample books refuses `oprisa_connect.py`. Create the real desk separately rather than mixing the two.

## Checks

```bash
uv run pytest backend/tests/test_agents_scenarios.py backend/tests/test_oprisa_api.py \
              backend/tests/test_agent_brain_and_sources.py backend/tests/test_kb_connect.py
uv run python scripts/rls.py check     # every tenant table, kb_* included, has its policy
```

- **Scenario tests:** every planted situation on all three sample desks is found by the agent that owns it. Examples: the cold quote, the below-margin quote, the missed promise, the PO at the best rate, the slipping regular, the grade drop, the idle stock, the cash gap, the duplicate ledger.
- **Ask tests:** the Ask agent's answers match the golden answers.
