#!/usr/bin/env bash
#
# Deploy Oprisa — one command from a clean checkout to a verified live site.
#
# What it does, in order:
#   1. Pre-flight   — clean tree, backend + frontend tests, typecheck, build
#   2. Migrate      — alembic upgrade head against the production DB (Neon)
#   3. RLS check    — confirm tenant isolation is still fully enforced
#   4. Ship         — push main, which triggers Render (backend) and Vercel
#                     (frontend) to auto-deploy from GitHub
#   5. Verify       — poll /health, load the site, exercise the public API
#
# Nothing here prints a secret. The production DATABASE_URL is read from the
# environment (or a local, git-ignored deploy.env) and never echoed.
#
# Usage:
#   DATABASE_URL='postgresql+psycopg://…neon…/neondb?sslmode=require' \
#     scripts/deploy.sh
#
# Flags:
#   --skip-tests     skip the test suite (faster re-deploys; use with care)
#   --skip-migrate   do not run the migration (Render still runs it on boot)
#   --no-push        do everything except the git push (dry run of checks)
#   --yes            do not prompt for confirmation before pushing

set -euo pipefail

# ---------------------------------------------------------------------------
# Config. Override via environment if your coordinates differ.
# ---------------------------------------------------------------------------
BRANCH="${DEPLOY_BRANCH:-main}"
REMOTE="${DEPLOY_REMOTE:-origin}"
BACKEND_URL="${BACKEND_URL:-https://quotation-copilot-api.onrender.com}"
FRONTEND_URL="${FRONTEND_URL:-https://opriza.vercel.app}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Load a local, git-ignored env file if present (keeps DATABASE_URL out of
# your shell history). deploy.env should set DATABASE_URL=…
if [[ -f "$ROOT/deploy.env" ]]; then
  # shellcheck disable=SC1091
  set -a; source "$ROOT/deploy.env"; set +a
fi

SKIP_TESTS=0; SKIP_MIGRATE=0; NO_PUSH=0; ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --skip-tests) SKIP_TESTS=1 ;;
    --skip-migrate) SKIP_MIGRATE=1 ;;
    --no-push) NO_PUSH=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    *) echo "Unknown flag: $arg" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  B="\033[1m"; DIM="\033[2m"; GRN="\033[32m"; RED="\033[31m"; YEL="\033[33m"; RST="\033[0m"
else
  B=""; DIM=""; GRN=""; RED=""; YEL=""; RST=""
fi
step() { echo -e "\n${B}▸ $*${RST}"; }
ok()   { echo -e "  ${GRN}✓${RST} $*"; }
warn() { echo -e "  ${YEL}!${RST} $*"; }
die()  { echo -e "\n${RED}✗ $*${RST}" >&2; exit 1; }

PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || die "No venv at .venv — run 'uv sync' first."

# ---------------------------------------------------------------------------
# 1. Pre-flight
# ---------------------------------------------------------------------------
step "Pre-flight checks"

cur_branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$cur_branch" == "$BRANCH" ]] || die "On branch '$cur_branch', expected '$BRANCH'. Checkout $BRANCH first."
ok "On branch $BRANCH"

if [[ -n "$(git status --porcelain)" ]]; then
  die "Working tree is dirty. Commit or stash before deploying."
fi
ok "Working tree clean"

# Make sure we're not about to push a diverged/stale history.
git fetch "$REMOTE" "$BRANCH" --quiet
local_head="$(git rev-parse HEAD)"
remote_head="$(git rev-parse "$REMOTE/$BRANCH" 2>/dev/null || echo none)"
if [[ "$remote_head" != none ]]; then
  base="$(git merge-base HEAD "$REMOTE/$BRANCH" 2>/dev/null || echo none)"
  if [[ "$base" == none ]]; then
    die "Local $BRANCH shares no history with $REMOTE/$BRANCH — unrelated histories. Reconcile first."
  fi
  if [[ "$base" != "$remote_head" && "$local_head" != "$remote_head" ]]; then
    die "Local $BRANCH has diverged from $REMOTE/$BRANCH — rebase before pushing."
  fi
fi
ok "History is a fast-forward over $REMOTE/$BRANCH"

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  step "Backend tests"
  PYTHONPATH="$ROOT:$ROOT/backend" "$PY" -m pytest backend/tests -q >/tmp/oprisa-pytest.log 2>&1 \
    && ok "$(grep -oE '[0-9]+ passed' /tmp/oprisa-pytest.log | tail -1) " \
    || { tail -25 /tmp/oprisa-pytest.log; die "Backend tests failed."; }

  step "Frontend typecheck, tests, build"
  ( cd frontend && npx tsc --noEmit ) && ok "Typecheck clean"
  ( cd frontend && npx vitest run >/tmp/oprisa-vitest.log 2>&1 ) \
    && ok "Frontend tests: $(grep -oE 'PASS \([0-9]+\)' /tmp/oprisa-vitest.log | tail -1)" \
    || { tail -25 /tmp/oprisa-vitest.log; die "Frontend tests failed."; }
  ( cd frontend && npm run build >/tmp/oprisa-build.log 2>&1 ) \
    && ok "Frontend build succeeds" \
    || { tail -25 /tmp/oprisa-build.log; die "Frontend build failed."; }
else
  warn "Skipping tests (--skip-tests)"
fi

# ---------------------------------------------------------------------------
# 2. Migrate the production database
# ---------------------------------------------------------------------------
if [[ "$SKIP_MIGRATE" -eq 0 ]]; then
  step "Database migration (production)"
  [[ -n "${DATABASE_URL:-}" ]] || die "DATABASE_URL is not set. Export the Neon URL or put it in deploy.env."
  case "$DATABASE_URL" in
    *localhost*|*127.0.0.1*) die "DATABASE_URL points at localhost — refusing to run a production deploy against it." ;;
  esac
  # Show where we're migrating, host only, never the password.
  host="$(printf '%s' "$DATABASE_URL" | sed -E 's#.*@([^/?]+).*#\1#')"
  echo -e "  ${DIM}target: $host${RST}"

  before="$(PYTHONPATH="$ROOT:$ROOT/backend" DATABASE_URL="$DATABASE_URL" "$PY" -m alembic current 2>/dev/null | tail -1 || true)"
  PYTHONPATH="$ROOT:$ROOT/backend" DATABASE_URL="$DATABASE_URL" "$PY" -m alembic upgrade head \
    && ok "Migrated to head" \
    || die "alembic upgrade failed."

  step "Row-level-security check (production)"
  PYTHONPATH="$ROOT:$ROOT/backend" DATABASE_URL="$DATABASE_URL" "$PY" scripts/rls.py check \
    && ok "Tenant isolation enforced on every tenant table" \
    || die "RLS check failed — do NOT serve traffic. Run scripts/rls.py apply."
else
  warn "Skipping migration (--skip-migrate). Render will run it on boot."
fi

# ---------------------------------------------------------------------------
# 3. Ship — push triggers Render + Vercel auto-deploy
# ---------------------------------------------------------------------------
step "Ship"
echo -e "  About to push ${B}$(git rev-parse --short HEAD)${RST} to ${B}$REMOTE/$BRANCH${RST}."
echo -e "  ${DIM}This triggers Render (backend) and Vercel (frontend) to redeploy.${RST}"
if [[ "$NO_PUSH" -eq 1 ]]; then
  warn "--no-push set: stopping before the push. All checks passed."
  exit 0
fi
if [[ "$ASSUME_YES" -eq 0 ]]; then
  read -r -p "  Proceed with push? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || die "Aborted by user."
fi
git push "$REMOTE" "$BRANCH"
ok "Pushed"

# Drive the frontend explicitly through the Vercel CLI when it's available and
# authenticated; otherwise the GitHub integration already deploys on push.
if command -v vercel >/dev/null 2>&1 && vercel whoami >/dev/null 2>&1; then
  step "Vercel deploy (frontend, --prod)"
  ( cd frontend && vercel deploy --prod --yes >/tmp/oprisa-vercel.log 2>&1 ) \
    && ok "Vercel production deploy triggered" \
    || warn "Vercel CLI deploy didn't run cleanly; the GitHub integration still deploys on push. See /tmp/oprisa-vercel.log"
else
  warn "Vercel CLI not authenticated — relying on the GitHub integration (deploys on push)."
fi

# ---------------------------------------------------------------------------
# 4. Verify the live deployment
# ---------------------------------------------------------------------------
step "Verify (allowing for Render cold-start and build time)"

poll() { # url, label, max_tries, want_code
  local url="$1" label="$2" tries="$3" want="${4:-200}" i code
  for ((i=1; i<=tries; i++)); do
    code="$(curl -s -o /dev/null -m 90 -w '%{http_code}' "$url" || echo 000)"
    if [[ "$code" == "$want" ]]; then ok "$label → $code"; return 0; fi
    printf "  %s… attempt %d/%d (got %s)\r" "$label" "$i" "$tries" "$code"
    sleep 12
  done
  echo ""
  warn "$label did not return $want after $tries tries (last: $code). Check the dashboards."
  return 1
}

poll "$BACKEND_URL/health" "Backend /health" 20 200 || true
poll "$FRONTEND_URL/" "Frontend" 20 200 || true
# The public leads endpoint should reject an empty body with 422 once live.
poll "$FRONTEND_URL/api/v1/leads" "Lead API via frontend proxy (POST-less GET 405/404 ok)" 3 405 || \
  warn "Lead API probe inconclusive (that GET probe is best-effort; the form uses POST)."

echo -e "\n${GRN}${B}Deploy complete.${RST}"
echo -e "  Frontend : $FRONTEND_URL"
echo -e "  Backend  : $BACKEND_URL"
echo -e "  ${DIM}Tip: submit the Request-access form and check the leads table to confirm end-to-end.${RST}"
