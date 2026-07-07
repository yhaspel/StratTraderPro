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

## M05 — Order Lifecycle + TradeStation (descoped)

- **Branch:** `feature/m05-order-lifecycle` (merged + deleted)
- **PR / merge:** [#23](https://github.com/yhaspel/StratTraderPro/pull/23) — ✅ **Merged** (squash, admin) — merge commit `73128b3`. All 5 CI checks green. Self-review recorded; the one blocking MEDIUM (orders strategy-filter 500) + L2/L4/N3 fixed in `58fe52e`.
- **Release tag (local, unpushed):** `v0.5.0-tradestation` → `73128b3`
- **Descope (per plan 2026-07-05 review note):** TradeStation API access is approval-gated and could not be obtained. The broker-agnostic order-lifecycle half is built in full; the TradeStation adapter + OAuth2/PKCE ship behind `BROKER_TRADESTATION_ENABLED=false` with stubbed/recorded tests; **live TS OAuth + real sim fills are deferred.**

### AC coverage
| AC | Status | Evidence |
|----|--------|----------|
| AC-05-1 TS OAuth flow | **Met (stubbed) / Deferred-live** | `TSOAuthViewTests` (start behind flag, callback creates account via stubbed exchange), PKCE + single-use state tested; live handshake needs TS access |
| AC-05-2 route to chosen broker | **Met** | `BrokerRoutingTests` (alert `broker` override + default fallback) |
| AC-05-3 both brokers connected | **Met** | model supports multiple accounts; routing test connects ALPACA + TRADESTATION |
| AC-05-4 MKT/LMT/STP/STP_LMT round-trip | **Met** | `ExtendedOrderTypeTests`; Alpaca mapping (Stop/StopLimit request models) |
| AC-05-5 options both / futures TS-only | **Met (fake+alpaca) / Deferred-live** | `AssetClassTests` (option accepted, future rejected on Alpaca); real options fills live-deferred |
| AC-05-6 reconciliation drift + heal | **Met** | `ReconciliationTests` (drift → 2nd-cycle heal; no-drift no-event) |
| AC-05-7 Orders page pagination/filters/CSV | **Met** | `OrdersApiTests` (pagination, broker filter, detail+fills, CSV, recon events) + `/orders` frontend |
| AC-05-8 LIVE mode rejected | **Met** | `LiveModeGateTests` (LIVE → 403 LIVE_TRADING_DISABLED; PAPER ok) |
| AC-05-9 flatten one broker only | **Met** | M04 flatten is per-BrokerAccount (user+account scoped) |
| AC-05-10 multi-broker parallel fills | **Met (fake)** | routing + per-account isolation; real dual-broker demo live-deferred (TS) |
| AC-05-11 TS WS reconnect storm no dup | **Met (logic) / Deferred-live** | backoff + `broker_exec_id` dedup reused from M04; live TS WS deferred |

### New surface
- **Models/migrations:** `orders.0003` (extended order types, asset/option/future descriptors, `ReconEvent`), `brokers.0002` (TradeStation + LIVE mode + OAuth token fields).
- **Adapters/services:** `apps/brokers/tradestation/` (adapter, `TSClient`, mapping, oauth, views); Alpaca STP/STP_LMT + TIF mapping; `apps/orders/reconcile.py`.
- **Tasks/beat:** `reconcile_positions_task` (5-min `reconcile-positions` beat entry).
- **Endpoints:** `/api/v1/brokers/tradestation/oauth/{start,callback}/`, `POST /api/v1/brokers/{id}/mode/`, `GET /api/v1/orders/{id}/`, `GET /api/v1/orders/export.csv`, `GET /api/v1/reconciliation/events/`, paginated `GET /api/v1/orders/`.
- **Flags (defaults):** `BROKER_TRADESTATION_ENABLED=false`, `ENABLE_LIVE_TRADING=false`.
- **Metrics:** reconcile drifts/heals, oauth refresh, order state transitions, ws reconnects.
- **Frontend:** `/orders` page + broker mode control + Connect TradeStation.

### Local gauntlet
- ruff ✓ · bandit ✓ · pytest (M04+M05, all pass) ✓ · makemigrations --check ✓ · prod-import ✓ · frontend ngc + build _(close-out)_.

### Decisions logged (autonomous)
- **`TradeStation` symbology** (options OCC→"AAPL 240119C150", futures ES+YYYY-MM→"ESZ26") is documented + unit-tested but **live-unverified** (approval-gated); ADR-050 records the canonical format.
- **Reconcile heal** never places corrective orders (position-snap only); per plan §6.3.
- **`decrypt_key` returns "" for empty blobs** so TradeStation accounts (OAuth, no api-key pair) build cleanly.
- **default webhook JSON schema** enum extended to include `STP_LMT` + `asset_class` (M05 supported types).
- Migration numbering: `orders.0003` (plan named `0002_extended_order_types`, but M04 already used `orders.0002`).

## M06 — Market Data + Regime Classifier

- **Branch:** `feature/m06-market-data-regime` (merged + deleted)
- **PR / merge:** [#24](https://github.com/yhaspel/StratTraderPro/pull/24) — ✅ **Merged** (squash, admin) — merge commit `5fb9de4`. All 5 CI checks green **(incl. Trivy on the new numpy/scipy/hmmlearn deps — no HIGH/CRITICAL CVE)**. Self-review recorded; the blocking HIGH (FMP transport-outage resilience) + M1/M2/L1/L2 fixed in `5f7e2eb`.
- **Release tag (local, unpushed):** `v0.6.0-regime` → `5fb9de4`

### AC coverage
| AC | Status | Evidence |
|----|--------|----------|
| AC-06-1 FMP daily bars, idempotent | **Met (fixtures) / Deferred-live** | `BarStoreTests.test_upsert_idempotent`; real 10y backfill needs FMP key |
| AC-06-2 intraday features ≤10 min | **Deferred-live** | beat task wired; needs live FMP feed on staging |
| AC-06-3 rule classifier + explainable | **Met** | `RuleClassifierTests` (buckets + top features) |
| AC-06-4 nightly HMM, non-regression swap | **Met (seeded) / Deferred-live** | `test_retrain_task_trains_and_activates`, `test_activate_model_swap_guard`; real overnight retrain deferred |
| AC-06-5 online decode + Viterbi | **Met** | `HMMTests.test_serialize_roundtrip_and_decode` |
| AC-06-6 deterministic ensemble | **Met** | `EnsembleTests` (decision table + determinism) |
| AC-06-7 dashboard badge + chart | **Met** | regime-badge component + 90-day strip |
| AC-06-8 model >48h → rule-only warning | **Met** | `test_compute_observation_rule_only_when_no_model`; UI degraded chip |
| AC-06-9 FMP rate-limit → backoff + cache, no 5xx | **Met** | `FMPClientTests` (retry, rate-limit fallback, circuit breaker) |
| AC-06-10 reproducible features (hash) | **Met** | `FeatureTests.test_reproducible` |

### New surface
- **Apps/models:** `marketdata.{Bar, MacroSeries}`, `regime.{FeatureVectorSnapshot, HMMModel, RegimeObservation}`. Migrations `marketdata.0001`, `regime.0001`.
- **Modules:** marketdata `{fmp, fred, services, metrics}`; regime `{features, rule_classifier, hmm_model, ensemble, services, metrics}`.
- **Tasks/beat:** `regime.retrain_hmm` (nightly ~03:00 ET), `regime.compute_features_daily`.
- **Commands:** `backfill_bars`.
- **Endpoints:** `/api/v1/regime/{current,history,model}/`, `/symbol/{sym}/` (501).
- **Flags:** `ENABLE_REGIME_UI` (default on). **Deps:** numpy/pandas/hmmlearn/tenacity.
- **Metrics:** 6 (marketdata + regime); **Data Pipelines** Grafana JSON committed.

### Local gauntlet
- ruff ✓ · bandit ✓ · pytest (M04–M06, all pass) ✓ · makemigrations --check ✓ · prod-import ✓ · frontend ngc+build _(close-out)_.

### Decisions logged (autonomous)
- **Bar Postgres month-partitioning deferred** — implemented as a plain indexed table (SQLite-testable, correct at MVP scale); ADR-061 documents the deferral. Avoided the `django-postgres-partition` dep.
- **FRED over plain httpx** (not `fredapi`) to avoid a heavier pandas-datareader stack.
- **HMM training seeded** (`REGIME_HMM_SEED`) for deterministic CI; tests train on synthetic seeded data.
- **Regime endpoints MFA-enforced** (consistent with `/api/v1/*`) despite being public market data — they're only consumed by the authenticated dashboard.

### Deferred (need externals)
- FMP premium key + FRED key; the 10-year `backfill_bars` run; the real overnight HMM retrain + intraday freshness on staging; Data Pipelines dashboard "live" verification.

## M07 — Sentiment Pipeline

- **Branch:** `feature/m07-sentiment` (merged + deleted)
- **PR / merge:** [#25](https://github.com/yhaspel/StratTraderPro/pull/25) — ✅ **Merged** (squash, admin) — merge commit `ee81f63`. All 5 CI checks green (Trivy confirms the feedparser-only base stayed lean). Self-review recorded; the blocking MEDIUM (aggregation double-count) + M2/M3/LOW fixed in `062e9a0`.
- **Release tag (local, unpushed):** `v0.7.0-sentiment` → `ee81f63`

### AC coverage
| AC | Status | Evidence |
|----|--------|----------|
| AC-07-1 fetchers + dedup | **Met (fixtures) / Deferred-live** | `IngestTests.test_dedup`; live feeds need ToS review |
| AC-07-2 tagger precision/recall | **Met (representative) / Deferred-full** | `TaggerTests` (registry/cashtag/alias + stopword precision); full 200-article eval deferred |
| AC-07-3 FinBERT within 60s | **Met (fake) / Deferred-live** | `score_pending_articles`; real FinBERT latency needs weights |
| AC-07-4 Tier-2 routing + structured output | **Met (fake)** | `RoutingTests` (material + low-conf → Llama); JSON-schema-validated |
| AC-07-5 EWMA per-symbol + market | **Met** | `AggregationTests` (half-life + aggregate) |
| AC-07-6 dashboard market score + history | **Met** | sentiment-panel component |
| AC-07-7 per-symbol drill-down + articles | **Met** | `/sentiment/symbol` + `/articles` + `test_end_to_end` |
| AC-07-8 Llama 200/day no lag | **Deferred-live** | benchmark on real worker deferred |
| AC-07-9 queue backlog alert | **Met** | `queue_backlog()` + `sentiment_queue_depth` |
| AC-07-10 LLM down → FinBERT-only | **Met** | `test_degraded_finbert_only` + UI degraded chip |
| AC-07-11 retention policy | **Deferred** | documented; rollup job is a follow-up |
| AC-07-12 no article text logged | **Met** | `LogScanTests.test_no_article_text_at_info` |

### New surface
- **Models/migration:** `sentiment.{NewsArticle, ArticleScore, SentimentScore, TickerRegistry, AliasTable, LLMInferenceLog}`; `sentiment.0001`.
- **Modules:** `fetchers`, `tagger`, `scorers` (Fake + lazy real), `routing`, `aggregator`, `services`, `metrics`, `views`; `prompts/v1.md`.
- **Tasks/beat:** `ingest_news` (15 min), `score_pending_articles` (2 min), `aggregate_sentiment` (5 min).
- **Endpoints:** `/api/v1/sentiment/{market,symbol/{sym},articles}/`.
- **Flags:** `SENTIMENT_ENABLED` (on), `LLM_WORKER_ENABLED`/`FINBERT_ENABLED` (off), `SENTIMENT_FAKE_SCORERS` (on).
- **Metrics:** 6. **Deps:** `feedparser` (base); heavy stacks in `requirements/ml-worker.txt`.

### Local gauntlet
- ruff ✓ · bandit ✓ · pytest (M04–M07, all pass) ✓ · makemigrations --check ✓ · prod-import ✓ · frontend ngc+build _(close-out)_.

### Decisions logged (autonomous)
- **Heavy model deps kept OUT of the base image** (`requirements/ml-worker.txt`, volume-mounted per plan §5). CI/local score with canned `FakeFinBert`/`FakeLlama` behind `SENTIMENT_FAKE_SCORERS`, so torch/llama-cpp never bloat the backend image or the Trivy scan — the same reason M06's ML deps passed Trivy.
- **`symbols_text` denormalization** — SQLite has no JSONField `contains` lookup, so a space-padded text column powers a cross-DB exact-symbol filter (CI runs SQLite).
- **spaCy NER is lazy + flag-gated** (`SENTIMENT_SPACY_NER` off); the regex/registry/alias tagger is the deterministic default.
- **Data Pipelines Grafana sentiment panels** — metrics emit; adding the panels to the existing dashboard JSON is a documented follow-up.

### Deferred (need externals)
- Download `ProsusAI/finbert` + the gated Meta-Llama-3.1-8B-Q4_K_M GGUF (HF/Meta license); the Day-1 tokens/sec benchmark on the real Railway worker (if p95 >5s/article → FinBERT-only fallback the plan already specifies); per-source ToS review (Benzinga/Finnhub/Yahoo); the full 200-article tagger precision/recall eval; the retention rollup job (AC-07-11).

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
