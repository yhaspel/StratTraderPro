# M04–M08 Execution Report

> Autonomous implementation run. Updated after each milestone so a partial
> report survives interruption. Two sections: **A — What was implemented**,
> **B — Manual user steps & follow-ups**.

---

# Section A — What was implemented

## M04 — Webhook Ingest + Broker Adapter + Alpaca Paper

- **Branch:** `feature/m04-webhook-alpaca-paper` (merged + deleted)
- **PR:** https://github.com/yhaspel/StratTraderPro/pull/22
- **Merge status:** ✅ **Merged** (squash, admin override) — merge commit `88e74a7`. All 5 CI checks green (Backend, Frontend, E2E smoke, block-legacy-ibkr-creds, Trivy). Self-review recorded on the PR; all MEDIUM+ review findings addressed in `aac97ee`.
- **Release tag (created locally, NOT pushed):** `v0.4.0-alpaca-paper` → `88e74a7`

### AC coverage

| AC | Status | Evidence |
|----|--------|----------|
| AC-04-1 accepted alert 200 | **Met** | `WebhookAcceptTests.test_valid_alert_accepted`; latency histogram `webhook_latency_seconds` |
| AC-04-2 wrong/missing sig → 401 + audit + rate limit | **Met** | `WebhookAuthTests` (wrong/missing sig, generic 401, rate-limit-before-body) |
| AC-04-3 bad schema → 400 + detail | **Met** | `WebhookSchemaTests.test_bad_schema_returns_400_with_detail` |
| AC-04-4 duplicate idempotency → duplicate=true, single order | **Met** | `WebhookIdempotencyTests` |
| AC-04-5 halt gate → rejected reason + audit | **Met** | `WebhookHaltTests` (user + strategy halt, released halt no-block) |
| AC-04-6 connect Alpaca paper / test-connection / live-key reject | **Met** | `BrokerConnectViewTests` (happy/no-secret/live-key/auth-fail/test-connection); frontend `/settings/brokers` |
| AC-04-7 equity DAY order placed, fill persisted | **Met (fake) / Deferred-live (Alpaca)** | e2e via FakeBroker (`WebhookEndToEndTests`); real Alpaca fill = §10.4 smoke (runbook) |
| AC-04-8 dashboard updates ≤2s via WS | **Met** | `DashboardConsumerTests.test_receives_position_update`; frontend ws client |
| AC-04-9 admin flatten → flat | **Met** | `BrokerFlattenTests` (admin-gated; reconcile_positions snaps flat) |
| AC-04-10 e2e send_webhook → position ≤5s (FakeBroker) | **Met** | `WebhookEndToEndTests.test_alert_to_position_under_5s` |
| AC-04-11 stream kill → supervised restart + REST catch-up, no lost/dup fill; DEGRADED status | **Met (logic) / Deferred-live** | `StreamCatchUpTests` (replay+dedup, backoff, DEGRADED/DOWN status); live reconnect = staging |
| AC-04-12 no secrets/keys/PII in logs/metrics | **Met** | `SecretHygieneTests` (no key fields in serializer/audit); `SENSITIVE_KEYS` scrubber; write-only serializers |
| AC-04-13 make up without ib-gateway; `--profile ibkr` works; TWS_ scrubbed; CI grep gate | **Met** | compose `ibkr` profile; `.env.example` scrub; `block-legacy-ibkr-creds` CI job (verified locally) |
| AC-04-14 OpenAPI documents webhook + new paths; types compile | **Met** | `apps/webhooks/schema.py` post-processor; regenerated `docs/openapi/openapi.json` + `schema.ts` |

### New surface
- **Apps/models:** `apps.dashboard` (new); `webhooks.AlertMessage`; `brokers.{BrokerAccount, TradingHalt, BrokerCallAudit}`; `orders.{Order, Fill, Position}`. Migrations: `webhooks.0001`, `brokers.0001` (incl. TradingHalt — see note), `orders.0001`+`0002`.
- **Adapters/services:** `BrokerAdapter` protocol + DTOs (`brokers/base.py`), `FakeBrokerAdapter`, `AlpacaAdapter` (+ `alpaca/{mapping,errors,streams,adapter}.py`), `brokers/services.py` (factory, halt gate, heartbeat), `brokers/streams.py` (supervisor + catch-up), `orders/services.ingest_fill_event`, `orders/fills.py` (transport).
- **Celery tasks:** `webhooks.tasks.process_alert`, `orders.tasks.fill_ingestor` (beat: `fill-ingestor` @5s). Celery app now imported in `config/__init__.py`.
- **Endpoints:** `POST /hooks/v1/{user}/{strategy}/`; `/api/v1/brokers/` (+ `{id}/`, `test-connection`, `status`, `flatten`); `/api/v1/orders/`, `/api/v1/positions/`, `/api/v1/fills/`.
- **WS:** `/ws/dashboard/` — `order.created`, `order.updated`, `fill.created`, `position.updated`, `broker.status`.
- **Management commands:** `run_broker_streams`, `alpaca_smoke`.
- **Feature flags (defaults):** `WEBHOOK_V1_ENABLED=true`, `BROKER_ALPACA_ENABLED=true`, `ENABLE_LIVE_TRADING=false`, `FILLS_INLINE=false` (true in tests).
- **Frontend routes/components:** `/settings/brokers`, `/dashboard`; `ws.service.ts`, brokers/dashboard facades+stores+api services.
- **Metrics:** `webhook_received_total`, `webhook_latency_seconds`, `order_submit_latency_seconds`, `broker_connect_total`, `broker_stream_disconnects_total`, `fills_ingested_total`, `broker_stream_heartbeat_age_seconds`.

### Docs / tracker
- ADR-042 (webhook secret-in-body) + ADR-031 amendment; runbooks `alpaca-paper-smoke.md`, `webhook-debug.md`; user help `alpaca-paper-connect.html` + refreshed `tradingview-alert-config.html`.
- CHANGELOG `[Unreleased]` M04 block; PROGRESS.md M04 row + truth updated.

### Local gauntlet result
- ruff ✓ · bandit (medium+) ✓ · pytest **191 passed** (SQLite) ✓ · makemigrations --check ✓ · prod-import smoke ✓ · CI grep gate ✓ · frontend `ngc` + `pnpm build` _(see close-out)_.

### Decisions logged (autonomous)
- **Channels was not actually configured** (plan claimed "since M00" — it wasn't). Added `channels`/`channels-redis`/`daphne`, an ASGI `ProtocolTypeRouter`, and a compose `ws` service. HTTP stays WSGI/gunicorn.
- **`TradingHalt` landed in `brokers.0001_initial`** (with `BrokerAccount`/`BrokerCallAudit`), not a separate `0002_tradinghalt` as the plan named it. Functionally identical; M08 extends via its own migration.
- **Reconnect catch-up:** exec-level replay for adapters exposing `recent_fills` (Fake → exact dedup); position-snap for Alpaca (no per-execution history endpoint in `alpaca-py` 0.43.5) — per-execution Fill backfill deferred to M05's reconciliation loop. Documented in `brokers/streams.py`.
- **Live-key detection:** reject `AK`/`BK` key-ID prefixes up front (Alpaca paper keys are `PK`) — the user-provided key confirms the `PK` prefix.
- **CI grep-gate allowlist** broadened beyond the plan's literal list to cover all current historical TWS_ references (docs/, project-plan/, MEMORY.md, docker-compose.yml) so no historical records are rewritten; the gate still protects active code (`backend/**`, `frontend/**`, `.github/**`, `.env.example`).

---

## M05 — Order Lifecycle + TradeStation
_Not started._

## M06 — Market Data + Regime
_Not started._

## M07 — Sentiment Pipeline
_Not started._

## M08 — Risk Engine & Kill Switches
_Not started._

---

# Section B — Manual user steps & follow-ups

### External accounts & API keys
- **Alpaca paper keys** — PROVIDED by user and stored in the gitignored `backend/.env` as `ALPACA_PAPER_KEY_ID` / `ALPACA_PAPER_SECRET_KEY` (key ID starts with `PK` = paper ✓). **Production users connect their own keys via the UI** (`/settings/brokers`); these env vars are local-smoke-only. **Recommend regenerating these keys after testing** — they were shared in-session (Alpaca dashboard → Paper → regenerate; note regenerating invalidates the old pair).
  - **Railway:** could not be set (no Railway access in this environment). Add `ALPACA_PAPER_KEY_ID`/`ALPACA_PAPER_SECRET_KEY` to the Railway backend service env **only if** you want the `alpaca_smoke` command available on staging; production per-user flow does not need them.

### Live verifications deferred to staging
- **M04 real-Alpaca-paper smoke** — run `docs/runbooks/alpaca-paper-smoke.md` (or `python manage.py alpaca_smoke --place AAPL 1`) during Regular Trading Hours; confirm order in Alpaca dashboard + fill ≤5s in ours (AC-04-7, §10.4).
- **Grafana Trading Ops dashboard** — JSON committed under `infra/grafana/`; import to Grafana Cloud + verify panels populate on staging (exit-gate "live" item).

### Security / ops actions (M04 carryover)
- **Rotate IBKR paper + live passwords** and **delete `TWS_*` from Railway + GitHub secrets** (04A carryover; the repo scrub is done, the secret stores are not reachable from here).
- **Confirm Alpaca live-trading eligibility for Israeli residents** with Alpaca support *before any live scope* (M12+). Paper is unaffected.

### Release tags created locally but NOT pushed (each vX push triggers prod deploy)
- `v0.4.0-alpaca-paper` — push when ready to deploy M04.

### PRs left open (if `--admin` merge was blocked)
- _(recorded at close-out)_
