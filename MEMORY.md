# MEMORY.md — working rules for StratTraderPro

> Instructions for any Claude session or developer working in this repo.
> Read this before touching code. Last updated: 2026-07-05.

## 1. Status discipline

- **`project-plan/PROGRESS.md` is the canonical status file. Update it with every development milestone**: phase start/close, acceptance-criteria pass, tag push, scope change, broker/provider decision. One dated line in the right section is enough; don't let it rot.
- `project-plan/plan-progress-tracker.md` holds the detailed per-task tables — update it when closing a phase, but PROGRESS.md wins on conflict.
- **Never report milestone status from the trackers alFFone.** They have lagged reality before. Verify against code, migrations, tests, ADRs, and runbooks first (PROGRESS.md bottom section has the verification commands).

## 2. Broker state (as of 2026-07-05)

- **First execution broker: Alpaca** (paper). Decision + verified API facts: `docs/adr/041-alpaca-over-ibkr.md`. Spec: `project-plan/04-webhook-ingest-and-ibkr.md` (rewritten for Alpaca; filename is historical).
- **IBKR is parked, do not build on it.** The scrapped M04A spec lives at `project-plan/archived/04A-IBKR-Web-API.md`. Parked artifacts kept for reference: ADR-040, `docker/ib-gateway/`, `docs/runbooks/ib-gateway-reauth.md`, `scripts/spike_ibkr_smoke.py`.
- Paper trading only through the M12 beta. `ENABLE_LIVE_TRADING` stays **false**, and CI now *enforces* it (`block-live-trading-enabled`, M13 AC-13-16): arming live trading is an operator act on a deployed env, never a commit.
- **Alpaca live eligibility: CONFIRMED (2026-07-13).** An Israeli national can open and fund an Alpaca **live** account. *(This supersedes the old "unconfirmed — check with Alpaca support" note. It was the cheapest gate on live trading and it is now closed.)*
- **M13 (paper⇄live switch) is WRITTEN but NOT YET MERGED** — it sits uncommitted in the working tree, and **its test suite has never been executed** (the Cowork sandbox can't run pytest). Run the gauntlet in `project-plan/ONE-SHOT-M11-OPERATOR-TAIL.prompt.md` before trusting it. Once merged: the Alpaca adapter **no longer hard-codes paper** — execution mode comes from `BrokerAccount.mode` (`PAPER`|`LIVE`) via `BrokerContext.mode` → `TradingClient(paper=...)` **and** `TradingStream(paper=...)`. `ENABLE_LIVE_TRADING` is *permission to create* a live account — **it is not a mode**, and must never be read as one (flipping it must not migrate existing paper accounts onto the live endpoint).
- **Never read the live flag directly.** Use `apps.brokers.live_gate.live_trading_permitted()` = `settings.ENABLE_LIVE_TRADING` **AND** `is_enabled("ENABLE_LIVE_TRADING")`. The flag is `mutable=True`, so `is_enabled()` resolves a **DB override** first: reading only `settings` makes the admin-portal OFF switch inert (it reports success and keeps trading real money); reading only `is_enabled()` lets a DB write alone arm real money. Hard to arm, instant to revoke.
- Live trading is **built but NOT enabled**. Spec + the six enablement gates: `project-plan/13-live-trading-switch.md` §6. Still open: the load test / chaos drills (so kill-switch flatten p99 ≤5s on a LIVE account is *unproven*), and counsel-approved ToS (the ToS in force still says "PAPER TRADING ONLY").

## 3. Test / dev credentials & secrets

**Never commit secrets. Never print them in logs, test output, or PR text.**

| What | Where it lives |
|---|---|
| Local dev env | `.env` (repo root, gitignored) + `backend/.env.example` documents the shape |
| Staging overrides | `.env.staging.local` (gitignored) |
| Grafana agent (local) | `.env.grafana.local` (gitignored) |
| Staging/prod runtime env | Railway dashboard → project `17060567-b194-4926-a7c0-7f339e306bdf`, per service per environment |
| CI secrets | GitHub Actions secrets (`yhaspel/StratTraderPro`) |
| **Alpaca paper keys (M04+)** | Generated self-service in the Alpaca dashboard (Paper section). Platform-level dev keys go in `.env` as `ALPACA_*`; end-user keys are entered via the UI and stored Fernet-encrypted (`BrokerAccount`). Regenerating keys on Alpaca invalidates the old pair. |
| Fernet KEK | `FERNET_KEK` env — wraps MFA secrets, webhook secrets, and (M04+) broker keys. Rotation runbook: `docs/runbooks/mfa-kek-rotation.md` |
| IBKR paper account | `DUN167649` — **parked**. `TWS_USERID`/`TWS_PASSWORD` are slated for removal from all env stores during M04 §6.9, followed by password rotation at IBKR. Don't re-add. |
| Google OAuth | Client ID/secret in Railway env (both environments); GCP console app still in *Testing* mode with `yuval3000@gmail.com` as test user. Setup runbook: `docs/runbooks/google-oauth-setup.md` |
| Staging URLs | backend `backepnd-staging-4b6d.up.railway.app`, frontend `frontend-staging-9011.up.railway.app`; prod `backend-production-f3e8` / `frontend-production-c977f` |

## 4. The local CI gauntlet — run before claiming "ready to push"

CI runs more than pytest. Match it locally or CI will catch you:

```bash
# Backend (from backend/)
python -m pytest -q                                   # 128 passing at last verification
ruff check .
bandit -r apps/ config/ -x tests -q --severity-level medium

# Frontend (from frontend/) — pnpm, NOT npm; lockfile drift fails CI
pnpm install --frozen-lockfile
npx ngc --noEmit -p tsconfig.app.json                  # catches NG5002/NG9 template errors tsc misses
pnpm build
```

## 5. Gotchas that have already burned this project once

- **Settings star-import drops `_private` names**: `from .base import *` in `dev.py`/`prod.py` skips underscore-prefixed helpers — import them explicitly or prod crashes with `NameError` (tests won't catch it; `test.py` never loads `prod.py`).
- **`tsc --noEmit` is not enough** for Angular templates — run `ngc` (see gauntlet).
- **Monaco editor**: npm import breaks `ng build` (esbuild has no `.ttf` loader for codicon CSS). Textarea fallback shipped in M03; use the CDN AMD loader if Monaco UX is ever wanted.
- **Railway Postgres Data UI silently swallows INSERT/UPDATE errors** — use `psycopg2` via the Public Network connect string for data surgery.
- **`railway up` (CLI) doesn't inject `RAILWAY_GIT_COMMIT_SHA`** — deploy via `git push` so `/healthz` reports the real SHA.
- **Multi-process gunicorn Prometheus**: `process_*` collectors are disabled by design; `django_db_*` metrics need the `django_prometheus` engine wrapper (`_wrap_db_engines_for_prometheus` — see gotcha #1 about importing it).
- **`/metrics` + Sentry noise**: a `before_send` filter in `prod.py` suppresses a known allauth/ASGI `AttributeError` on scrapes; the durable fix (mount `/metrics` outside Django) is M10 §6.5a — remove the filter when that lands.
- **TradingView webhooks can't compute HMACs** — the `sig` field is the static per-user-per-strategy secret. Design/verify accordingly (M04 §6.3, ADR-042 when written).

## 6. Working conventions

- Milestone specs in `project-plan/` are authoritative; amend the milestone file (not the master plan) when scope changes mid-week, and record architectural decisions as ADRs in `docs/adr/` (next free number; 041 is the Alpaca pivot; 042 is reserved for webhook secret semantics).
- **Scrapped plans move to `project-plan/archived/`** with a SCRAPPED banner (why + what carried over) and all living references updated to the archived path. Never leave a dead plan in the top-level `project-plan/` folder.
- Exit-gate checklists gate milestone advancement; renegotiated ACs must be documented in the plan file + tag annotation (M00 set the precedent).
- Tags: `v0.<milestone>.0-<slug>` on `main`; CHANGELOG entry under `[Unreleased]` before tagging. Reminder: `v0.1.1-auth-metrics` is still awaiting push.
- Repo hygiene: don't commit `.DS_Store`, `_tmp_*`, screenshots, or `db.sqlite3` refreshes; two tracked `_tmp_14_*` files + three `gateway-*.png` are queued for removal in M04 §6.9.
