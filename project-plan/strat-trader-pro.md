# StratTraderPro — Project Plan

> **Status:** Draft v1.0
> **Author:** Software Architect / Market Analyst
> **Owner:** Yuval
> **Date:** 2026-04-14
> **Target MVP:** ~10–12 weeks
> **Hosting:** Railway (primary) + local-dev with ngrok bridge
> **Architecture baseline:** Django REST Framework (backend) + Angular 19+ signals (frontend), per the `django-angular-project-setup` and `frontend` skills.

---

## 1. Executive Summary

StratTraderPro is a cloud-hosted, always-on, multi-tenant trading bot platform that executes pre-defined quantitative strategies against live broker accounts in response to TradingView webhook alerts. It adds a regime-aware decision layer that conditions position sizing and strategy selection on:

- **Market Breadth & Regime** — Hidden Markov Model (HMM) plus a rule-based breadth classifier (advance/decline, NH/NL, % above 50/200 SMA, VIX, credit spreads).
- **Market Sentiment** — A small, locally-hosted LLM (FinBERT + a quantized Llama-class model) scoring breaking-news impact on the user's watchlist and the broad market.
- **User-defined Risk Envelope** — Daily-loss circuit breakers, per-strategy and per-user kill switches, and a platform-wide admin halt.

The system ships with a strict **paper-trading-first MVP** (using IBKR paper and TradeStation simulator endpoints), unlocks **live trading in a gated second release**, and is designed for a population of **10–50 concurrent users** at 6 months, with a clean horizontal-scale path to hundreds.

### 1.1 MVP Success Criteria

| # | Criterion | Measurement |
|---|-----------|-------------|
| 1 | A user can register, verify email, enable MFA, log in, and access the dashboard. | End-to-end e2e test passes. |
| 2 | A user can configure a TradingView webhook URL with per-strategy HMAC, receive a webhook, and see an order reflected in their paper broker account. | Measured via webhook → broker fill round-trip test. |
| 3 | The system auto-classifies market regime every bar-close and persists it. | HMM + rule classifier produce a regime label; dashboard shows current regime. |
| 4 | Sentiment pipeline ingests ≥ 5 news sources and produces per-symbol & market-wide scores every 15 min. | Background task runs at cadence; scores visible in dashboard. |
| 5 | Risk engine halts trading for a user when realized+unrealized daily loss ≥ configured threshold. | Integration test triggers breach; new orders rejected. |
| 6 | Walk-forward backtester produces a tearsheet (vectorbt + backtrader) on-demand for any strategy. | User clicks "Run backtest" → PDF + JSON report generated. |
| 7 | Global admin and per-user kill switches flatten positions within 5 seconds of trigger. | Kill-switch latency test. |
| 8 | All actions (login, order, kill-switch, config change) are written to an immutable audit log. | Audit rows exist and are queryable. |

---

## 2. Architecture Overview

StratTraderPro is a **3-tier multi-tenant monorepo**:

```
┌──────────────────────────────────────────────────────────────────────┐
│                    ANGULAR 19 (Presentation)                          │
│      Dashboard · Strategies · Backtest · Risk · Users · Admin         │
│   Signals-based state · 3-layer (Core → Abstraction → Presentation)   │
└────────────────────┬─────────────────────────────────────────────────┘
                     │ HTTPS / JWT (access + refresh) + MFA
┌────────────────────▼─────────────────────────────────────────────────┐
│                    DJANGO REST FRAMEWORK (API)                        │
│   Apps: users · strategies · webhooks · regime · sentiment ·          │
│          risk · brokers · backtest · orders · audit · admin           │
│   Channels / ASGI for live dashboard updates                          │
└─────────┬────────────────────┬───────────────────────────┬───────────┘
          │                    │                           │
┌─────────▼────────┐ ┌─────────▼──────────┐ ┌──────────────▼──────────┐
│   PostgreSQL     │ │  Redis  (cache +   │ │  Celery Workers +       │
│ (row-level RLS   │ │  Celery broker +   │ │  Beat (scheduled jobs)  │
│  isolation)      │ │  idempotency keys) │ │  GPU/CPU LLM worker     │
└──────────────────┘ └────────────────────┘ └─────────────────────────┘
          │                                      │           │
          │                                 ┌────▼─────┐ ┌──▼──────────┐
          │                                 │ Broker    │ │ Market Data │
          │                                 │ adapters  │ │ (FMP prem.) │
          │                                 │ (IBKR, TS)│ │             │
          │                                 └───────────┘ └─────────────┘
          │
 ┌────────▼─────────────┐
 │  Object storage       │
 │ (backtest PDFs,       │
 │  strategy uploads,    │
 │  pine/json/txt files) │
 └───────────────────────┘
```

### 2.1 Key architectural decisions (ADR summaries)

| # | Decision | Rationale |
|---|----------|-----------|
| ADR-001 | Monorepo, Django + Angular, signals-based frontend. | Matches the user's shared skills and reference implementation. |
| ADR-002 | Postgres (single tenant DB with `owner_id` scoped every row + Postgres RLS policies). | Simpler than schema-per-tenant for 10–50 users; RLS gives defense-in-depth. |
| ADR-003 | Celery + Redis for async & scheduled jobs. | Mature Python stack; Railway supports Redis natively. |
| ADR-004 | Local LLM sentiment worker (FinBERT + 7–8B quantized LLM). | Cost-predictable, private, scales with CPU; no per-token billing. |
| ADR-005 | Broker adapter abstraction with 2 concrete implementations (IBKR via **CPAPI** REST+WS, TradeStation via REST/WebSocket). | Enables per-user broker choice; easy to add Alpaca, Schwab later. CPAPI replaces the original `ib_insync`/IB-Gateway sidecar approach which does not scale past ~5 concurrent sessions. |
| ADR-006 | Walk-forward backtester: **vectorbt Pro** (commercial licence) for signal/param sweeps + **backtrader** for path-dependent validation. | Vectorbt is 50–500× faster for sweeps; backtrader's event loop validates realism. Commercial licence required because community edition is AGPL — AGPL requires source disclosure for network-accessible services. |
| ADR-007 | HMAC-signed webhooks with per-user, per-strategy secret; `sig` **must be the last JSON key** in the template; HMAC computed over the raw request bytes without re-serialisation. | Prevents spoofing; supports rotation. Placing `sig` last and hashing raw bytes avoids JSON canonicalisation fragility. |
| ADR-008 | Paper-trading MVP, feature-flag-gated live trading. | Risk containment; no real money until backtests + paper results validated. |
| ADR-009 | Audit log is append-only (no UPDATE/DELETE grants at DB level) with hash-chain. | Forensic evidence for disputes, regulator queries, and incident postmortems. |
| ADR-010 | Deploy to Railway: 1 web (Django), 1 worker, 1 beat, 1 LLM-worker, Postgres, Redis, PgBouncer. | Matches the available Railway skill; simplest path to always-on. PgBouncer prevents connection exhaustion across 6+ services. |
| ADR-011 | Market data via a **provider-abstraction layer** (`MarketDataProvider` protocol); active provider swappable by env var. FMP for dev/beta; **Polygon.io** for production live trading. | No single vendor covers all needs at all price points; the adapter pattern means switching costs are a config change, not a code change. See §3.4 for full provider comparison. |
| ADR-012 | Beat scheduler uses **`celery-redbeat`** (Redis leader-lock) instead of `django-celery-beat` (DB polling). | Redbeat survives crash-restart without duplicate task execution — a crash during beat dispatch doesn't re-fire in-flight tasks. |
| ADR-013 | Subscription billing via **Stripe Checkout + Billing Portal**; plan tiers enforced at API middleware (`PlanEnforcer`). | Industry-standard; excellent webhooks; handles trials, upgrades, proration, invoices. Plan-gating at middleware catches all paths including direct API calls. |

---

## 3. Technology Stack

### 3.1 Backend

| Layer | Choice | Notes |
|-------|--------|-------|
| Language | Python 3.12 | Latest stable w/ performance improvements. |
| Web framework | Django 5.x + DRF | Per `django-angular-project-setup` skill. |
| Async/Realtime | Django Channels 4 (ASGI, `daphne`/`uvicorn`) | For WebSocket dashboard push. |
| Auth | `djangorestframework-simplejwt` + `django-otp` (TOTP) | Access + refresh tokens; MFA enforcement middleware. |
| DB | Postgres 16 | Row-level security policies. |
| Cache/Queue | Redis 7 | Celery broker + cache + idempotency locks. |
| Task queue | Celery 5 + **`celery-redbeat`** (Redis leader-lock beat) | Scheduled jobs (regime, sentiment, eod recon). Redbeat replaces `django-celery-beat` to prevent duplicate task execution on beat restarts. |
| HTTP client | `httpx` (async) | Broker, news, market-data calls. |
| Brokers | **IBKR CPAPI** (Client Portal API, REST+WS, no Java sidecar) + TradeStation v3 REST+WS (custom thin client) | See §6.8. CPAPI scales to N concurrent user sessions without a Gateway process per user. |
| Market data | **Provider abstraction layer** (`MarketDataProvider` protocol). **Dev/beta:** FMP $49/mo Growth. **Production:** Polygon.io $79–199/mo. **Macro (free):** FRED API. Provider switched via `MARKET_DATA_PROVIDER` env var. See §3.4 and §6.13. | |
| Billing | **Stripe Checkout + Billing Portal**; `stripe-python`; plan webhooks. `Subscription` model + `PlanEnforcer` middleware. | Three tiers (Free/Trader/Pro). See §13. |
| News | FMP news endpoint (primary) + SEC EDGAR 8-K RSS + Nasdaq Trader halts RSS + Alpha Vantage News (free-tier backup) | Benzinga and Yahoo Finance RSS removed — ToS violations. Webhook-less pull every 15 min. |
| NLP | `transformers` + `FinBERT` + `llama-cpp-python` (GGUF-quantized 7–8B, e.g. Llama-3.1-8B-Instruct-Q4) | Runs on CPU (4–8 cores) acceptably for the use case; optional GPU later. |
| HMM | `hmmlearn` or `pomegranate` | Gaussian HMM on feature vector. |
| Backtester | `vectorbt` + `backtrader` + custom WF orchestrator | See §11. |
| Observability | `sentry-sdk`, `structlog`, OpenTelemetry (OTel → Grafana Cloud or Tempo) | Correlated traces from webhook → order fill. |
| Secrets | Railway env vars + `django-environ`; fernet-encrypted broker creds in DB | Per-user broker keys encrypted at rest. |

### 3.2 Frontend

| Concern | Choice | Notes |
|---------|--------|-------|
| Framework | Angular 19+ standalone components, signals | Per `frontend` skill. |
| State | Signals + `@ngrx/signalstore` (optional for larger stores) | Simple reactive state; no RxJS BehaviorSubjects soup. |
| Styling | Tailwind CSS 3 + Angular CDK + custom tokens | Fast iteration, accessible primitives. |
| Charts | `lightweight-charts` (TradingView OSS) + `plotly.js` | TV charts for live price/equity; plotly for tearsheets. |
| HTTP | `HttpClient` with typed response models + interceptors (JWT, error) | - |
| Realtime | `@stomp/stompjs` OR native `WebSocket` against Django Channels | Live positions, fills, regime changes. |
| Forms | Angular Reactive Forms + Zod-like validators | Strong typing on webhook JSON editor. |
| Routing | Standalone `Routes` with lazy-loaded feature areas | Dashboard, Strategies, Backtest, Risk, Admin. |
| Testing | Jest + Testing Library + Playwright e2e | Unit + component + e2e. |

### 3.3 Layer split (3-tier per `frontend` skill)

```
src/app/
├── core/                  # Singletons, HTTP, auth, interceptors, guards
│   ├── services/          # api/*.service.ts (one per domain)
│   ├── guards/            # auth, mfa, admin
│   ├── interceptors/      # jwt, refresh, error
│   └── models/            # Pure TS types, no deps
├── abstraction/           # Stores (signal stores), facades, selectors
│   ├── stores/            # positions.store.ts, regime.store.ts, …
│   └── facades/           # One per feature; presentation talks only to facade
└── presentation/          # Dumb components, smart pages, feature shells
    ├── features/
    │   ├── dashboard/
    │   ├── strategies/
    │   ├── backtest/
    │   ├── risk/
    │   ├── admin/
    │   └── auth/
    └── shared/            # Reusable UI primitives
```

**Rule:** Presentation components import only from `abstraction/facades`; facades import from `core/services` and `abstraction/stores`. No direct HTTP in components, ever.

### 3.4 Market Data Provider Comparison & Strategy

The market data layer is architected as a **swappable provider** (see ADR-011). This table covers all commercially viable options in the $0–$300/mo range:

| Provider | Dev/Beta fit | Production fit | Real-time WS | Intraday bars | 10y+ history | Options chains | Futures | News | Monthly cost (commercial) |
|----------|-------------|----------------|:----:|:----:|:----:|:----:|:----:|:----:|---|
| **FMP** (current) | ✅ Good | ⚠️ Marginal | ❌ Poll only | ✅ 1m–1d | ✅ | ⚠️ Limited | ❌ | ✅ | $49 (Growth) → $179 (Professional) |
| **Polygon.io** ⭐ recommended | ✅ | ✅ Excellent | ✅ <20ms | ✅ 1m–1d | ✅ 5y+ | ✅ Real-time OPRA | ✅ | ⚠️ via partner | $29 (Starter) → $79 (Dev) → $199 (Pro) |
| **Alpha Vantage** | ✅ | ⚠️ Moderate | ⚠️ Limited | ✅ 1m–60m | ✅ 20y+ | ❌ | ❌ | ✅ | $49.99 → $249.99 |
| **TwelveData** | ✅ | ✅ Good | ✅ WS | ✅ 1m–1d | ✅ | ⚠️ Limited | ❌ | ❌ | $29 → $99 |
| **EODHD** | ✅ | ⚠️ Check ToS | ❌ | ✅ 1m–1h | ✅ 50y+ | ✅ 6k symbols | ⚠️ | ✅ | Personal: $19.99 (⚠️ non-commercial). **Commercial SaaS requires €399+/mo enterprise licence** — not suitable at our scale. |
| **Intrinio** | ❌ | ✅ Best options | ✅ WS | ✅ | ✅ | ✅ Greeks + IV | ⚠️ | ❌ | $150–$250+ |
| **FRED API** | ✅ (macro only) | ✅ | ❌ | Daily only | ✅ | ❌ | ❌ | ❌ | **Free** (120 req/min) |
| **Alpaca Market Data** | ✅ | ✅ | ✅ WS | ✅ 1m–1d | ✅ | ⚠️ indicative | ❌ | ❌ | Free–$9/mo (Algo Trader Plus) |
| **Nasdaq Data Link** | ⚠️ | ✅ (macro/futures) | ❌ | ❌ | ✅ | ❌ | ✅ CME datasets | ❌ | Free–$50/mo (varies by dataset) |

**Decision matrix:**

| Phase | Provider | Cost | Notes |
|-------|----------|------|-------|
| **Development / Beta (paper only)** | FMP Growth | $49/mo | Adequate for bars, regime features, news. Not real-time. |
| **Production v0.1 (paper + live stocks/ETFs)** | Polygon.io Developer | $79/mo | Real-time WS, intraday bars, sufficient options data. Replace FMP. |
| **Production v0.2 (live options/futures)** | Polygon.io Pro + Nasdaq Data Link (futures) | $199 + $50/mo | Options chains real-time OPRA; CME futures via NDAQ. |
| **Macro data (all phases)** | FRED API | $0 | Yield spreads, credit spreads, VIX. Cache aggressively. |
| **News (fallback)** | Alpha Vantage free | $0 | 50 calls/day limit; supplementary to primary source. |

**Important commercial licensing note:**  
EODHD's low headline price ($19.99–$99.99) applies to **personal use only**. Commercial SaaS deployments require their enterprise licence at €399+/month, making it unsuitable for our cost model. Polygon.io and Alpha Vantage explicitly permit commercial SaaS at their standard paid tiers.

**Provider protocol (implementation sketch):**
```python
class MarketDataProvider(Protocol):
    def get_bars(self, symbol: str, tf: str, from_dt: datetime, to_dt: datetime) -> list[Bar]: ...
    def get_quote(self, symbol: str) -> Quote: ...
    def get_options_chain(self, symbol: str, expiry: date | None) -> list[OptionContract]: ...
    def stream_quotes(self, symbols: list[str]) -> AsyncIterator[Quote]: ...
    def get_news(self, symbol: str | None, from_dt: datetime) -> list[NewsArticle]: ...

# Active provider selected at startup:
# MARKET_DATA_PROVIDER=polygon  →  PolygonProvider(api_key=...)
# MARKET_DATA_PROVIDER=fmp      →  FMPProvider(api_key=...)
# MARKET_DATA_PROVIDER=twelvedata → TwelveDataProvider(api_key=...)
```

All providers share the same interface. Switching from FMP to Polygon is a one-line env var change and a `make migrate-bars` command to backfill any gaps in the new provider's format.

---

## 4. Repository Layout

```
StratTraderPro/
├── .github/workflows/         # CI: lint, test, build, deploy
├── backend/
│   ├── config/
│   │   ├── settings/          # base.py, dev.py, prod.py, test.py
│   │   ├── asgi.py            # Channels ASGI routing
│   │   ├── wsgi.py
│   │   └── urls.py
│   ├── apps/
│   │   ├── users/             # CustomUser, MFA, profiles
│   │   ├── billing/           # Stripe Checkout, Subscription, PlanEnforcer middleware
│   │   ├── strategies/        # Strategy, StrategyFile, WebhookConfig
│   │   ├── webhooks/          # Ingestion endpoint, HMAC verify, dedupe
│   │   ├── regime/            # HMM + rule classifier, features
│   │   ├── sentiment/         # FinBERT + LLM workers, news pipeline
│   │   ├── risk/              # Kill switches, daily loss, sizing
│   │   ├── brokers/           # Adapter abstraction + IBKR CPAPI + TradeStation
│   │   │   ├── ibkr/          # CPAPI REST+WS client (no Gateway sidecar)
│   │   │   └── tradestation/  # TS v3 REST+WS client
│   │   ├── orders/            # Order lifecycle, fills, reconciliation
│   │   ├── backtest/          # vectorbt Pro + backtrader orchestrator
│   │   │   └── strategies/    # Per-strategy Python adapters (_backtest.py)
│   │   ├── marketdata/        # Bar store, quote cache, provider router
│   │   │   └── providers/     # Pluggable provider implementations
│   │   │       ├── base.py    # MarketDataProvider Protocol
│   │   │       ├── fmp.py     # FinancialModelingPrep (dev/beta)
│   │   │       ├── polygon.py # Polygon.io (production ⭐)
│   │   │       ├── twelvedata.py
│   │   │       └── alphavantage.py
│   │   ├── audit/             # Append-only log, hash chain
│   │   └── admin_portal/      # Platform-wide admin endpoints
│   ├── requirements/          # base.txt, dev.txt, prod.txt
│   ├── manage.py
│   ├── pytest.ini
│   └── Dockerfile
├── frontend/
│   ├── src/app/core/
│   ├── src/app/abstraction/
│   ├── src/app/presentation/
│   ├── angular.json, tsconfig*.json
│   └── Dockerfile
├── strategies/                # Pre-loaded strategy artifacts (migrated from Trading Strategies project)
│   ├── <strategy_name>.pine
│   ├── <strategy_name>_Description.txt
│   └── <strategy_name>_Webhook.json
├── infra/
│   ├── railway/               # railway.toml, service defs
│   ├── nginx/                 # frontend nginx.conf
│   ├── docker-compose.yml     # Local dev (db, redis, backend, frontend, ngrok)
│   └── scripts/               # seed, loadstrategies, bootstrap
├── docs/
│   ├── adr/                   # Architecture Decision Records
│   ├── runbooks/              # On-call playbooks
│   └── api/                   # OpenAPI schema outputs
└── project-plan/
    └── strat-trader-pro.md    # THIS FILE
```

---

## 5. Domain Model (ER Summary)

**User** 1..N **BrokerAccount** (encrypted creds) 1..N **Position** 1..N **Fill**
**User** 1..N **Strategy** 1..N **StrategyFile** (pine/desc/webhook-json)
**User** 1..1 **RiskProfile** 1..N **RiskEvent** (breach history)
**User** 1..N **WebhookSecret** (per-strategy HMAC, rotatable)
**System** 1..N **RegimeObservation** (symbol-scoped or market-wide)
**System** 1..N **SentimentScore** (symbol- & market-wide)
**User** 1..N **BacktestRun** 1..1 **BacktestReport**
**System** 1..N **AuditLog** (append-only, hash-chained)

Full migration-level schema is in Appendix B.

---

## 6. Module Specifications

### 6.1 Users & Authentication (`apps/users`)

**Scope:** Registration, email verification, login (JWT), refresh rotation, TOTP MFA enrollment, password change, profile, account lockout.

**Models:**
- `User(AbstractUser)` — `email` (unique, primary login), `is_verified`, `mfa_enabled`, `role` (user/admin).
- `MFADevice` — TOTP secret (encrypted), verified, created_at.
- `UserProfile` — display name, timezone, default broker, default strategy mode (auto/manual).
- `EmailVerificationToken`, `PasswordResetToken` — single-use, TTL-bounded.

**API (DRF ViewSets):**
```
POST /api/v1/auth/register/           { email, password, display_name }
POST /api/v1/auth/verify-email/       { token }
POST /api/v1/auth/login/              { email, password }  → { access, refresh, mfa_required }
POST /api/v1/auth/mfa/enroll/         → { qr_b64, secret_backup_codes }
POST /api/v1/auth/mfa/verify/         { code } → { access, refresh }
POST /api/v1/auth/refresh/            { refresh }
POST /api/v1/auth/logout/             { refresh }
POST /api/v1/auth/password/reset/     { email }
POST /api/v1/auth/password/reset/confirm/  { token, new_password }
GET  /api/v1/users/me/                → profile
PATCH /api/v1/users/me/               → update profile
```

**Security:**
- Argon2id password hashing.
- Login rate limit: 5/min per email, 20/min per IP (django-ratelimit + Redis).
- Account lockout: 10 failed attempts → 15 min lock.
- Refresh tokens rotated on use; family revocation on reuse detection.
- MFA **required** before any broker connection or order-creation endpoint is accessible (middleware enforces).

### 6.2 Strategies (`apps/strategies`)

**Scope:** Manage the pre-loaded strategies migrated from the user's existing Trading Strategies project, plus accept user uploads.

**Upload contract (from spec):** User uploads exactly three files per strategy, matching filename patterns:
1. `<strategy_name>.pine` — Pine Script v5 code.
2. `<strategy_name>_Description.txt` — plain-text description (used for search, tooltips, tearsheet meta).
3. `<strategy_name>_Webhook.json` — JSON template of the TradingView webhook payload the strategy will emit.

**Validation rules:**
- Filenames must share the same `<strategy_name>` stem (regex: `^[A-Za-z0-9_\-]{3,64}$`).
- Pine file ≤ 64 KB, description ≤ 16 KB, webhook JSON ≤ 16 KB and must parse.
- Webhook JSON must contain top-level keys: `strategy`, `action`, `symbol`, `qty`, `order_type`, plus optional `price`, `stop`, `target`, `comment`. Unknown keys allowed but flagged.
- On upload, system computes a SHA-256 of each file; duplicates within a user's namespace rejected.

**Uploaded strategies are flagged `is_community_tested=false`.** UI shows a banner: "Uploaded strategies are not tested by StratTraderPro. You assume all risk. Review the Pine code and webhook JSON carefully before enabling."

**Models:**
- `Strategy` — `id`, `owner_id` (nullable for system-seeded), `name`, `slug`, `is_system`, `is_enabled`, `is_community_tested`, `created_at`.
- `StrategyFile` — `strategy_id`, `kind` (PINE/DESC/WEBHOOK_TEMPLATE), `filename`, `sha256`, `content_bytes` (or S3 URL for larger), `uploaded_at`.
- `WebhookConfig` — `strategy_id`, `user_id`, `secret` (encrypted), `allowed_ips` (optional), `json_schema` (jsonschema validated), `version`, `rotated_at`.

**API:**
```
GET    /api/v1/strategies/                     → list (system + user)
POST   /api/v1/strategies/                     → upload (multipart, 3 files)
GET    /api/v1/strategies/{id}/                → detail + files
PATCH  /api/v1/strategies/{id}/                → toggle enabled, rename
DELETE /api/v1/strategies/{id}/                → soft delete
GET    /api/v1/strategies/{id}/files/{kind}/   → download
POST   /api/v1/strategies/{id}/webhook-config/ → create/update JSON schema, rotate secret
POST   /api/v1/strategies/{id}/webhook-config/rotate/ → rotate secret (invalidates TradingView alerts until updated)
GET    /api/v1/strategies/{id}/webhook-config/url/    → signed webhook URL + current secret (one-time reveal)
```

**Pre-load migration:** A management command `python manage.py load_strategies /path/to/trading-strategies-project` walks the Trading Strategies project folder and seeds `Strategy` + `StrategyFile` rows with `is_system=true`.

### 6.3 Webhook Ingestion (`apps/webhooks`)

**Scope:** Public-facing HTTPS endpoint that TradingView alerts POST to, authenticates the alert, normalizes it, and dispatches to the order engine.

**URL shape:** `https://api.strattraderpro.com/hooks/v1/{user_uuid}/{strategy_uuid}/`

**Payload auth:**
- TradingView alert JSON is POSTed with an `X-StratTrader-Signature` header that TradingView cannot produce directly. **Workaround:** We include the HMAC inside the JSON body under a `sig` field. The PineScript `alert()` call includes `"sig": "{{TSP_SIG}}"` placeholder and the user pastes the secret into the alert body template via the dashboard when they copy-paste the generated alert template we provide.
- Server computes `hmac_sha256(secret, body_without_sig_field)` and compares constant-time to the `sig` field.
- Optional IP allowlist (TradingView IP ranges) as defense-in-depth; off by default (TV rotates IPs).

**Idempotency:** Each alert includes `"idempotency_key": "{{alert_id}}-{{time}}"` (user-replaceable via template). Ingestion Redis `SETNX` on key with 24h TTL; duplicate → 200 OK, noop.

**Dispatch:**
1. Verify signature → reject 401 if bad.
2. Validate against `WebhookConfig.json_schema` → reject 400 if invalid.
3. Check user's global kill switch and strategy kill switch.
4. Enqueue Celery task `process_alert(alert_id)` (low-latency queue).
5. Return 200 immediately (TradingView has a 3s timeout).

**Celery task `process_alert`:**
1. Hydrate alert and associated user/strategy.
2. Compute **regime** (cached, see §6.4).
3. Compute **sizing** (see §6.6) using risk profile + regime + sentiment.
4. Check **risk gates** (daily loss, margin, concentration).
5. Call **broker adapter** (see §6.8) to place order (paper in MVP, live when flag on).
6. Write **audit log** entries for every decision.
7. Push **WebSocket** event to dashboard.

### 6.4 Market Breadth & Regime Classifier (`apps/regime`)

**Scope:** Produce a market-wide regime label and a per-symbol regime label at configurable cadence (default: end-of-bar on 15m and 1d).

**Features (computed per bar-close):**
- **Breadth:** NYSE + Nasdaq advances/declines, advance/decline volume, new highs/lows, % of S&P 500 above 20/50/200 SMA, McClellan Oscillator.
- **Volatility/stress:** VIX level and term structure (VIX/VIX3M), MOVE index.
- **Credit:** HY OAS (FRED `BAMLH0A0HYM2`), IG OAS (`BAMLC0A0CM`).
- **Momentum:** Market SMA slopes (50, 200), RSI(14).
- **Macro:** 10Y–2Y spread (FRED `T10Y2Y`), DXY.

**Classifier stack:**
1. **Rule-based breadth score (0–100)** — weighted sum of standardized features → bins: `RISK_ON | NEUTRAL | RISK_OFF | PANIC`. Deterministic, always-available fallback.
2. **Gaussian HMM (hmmlearn)** — 3–4 hidden states trained offline nightly on 10y of features. Online, Viterbi-decodes the last state given new observations. Labels: `BULL | CHOP | BEAR | CRISIS`.
3. **Ensemble** — final regime = combine(rule_score, hmm_state) via a simple decision table, with rule_score as tiebreaker when HMM probability < 0.6.

**Training:**
- Nightly Celery beat job fetches fresh features (FMP + FRED) → fits HMM → validates against out-of-sample last-90-days → only swaps the production model if holdout log-likelihood improves OR is within 1% of prior.
- Model artifacts stored in DB (pickled + SHA-256) with version tag.

**Models:**
- `RegimeObservation(timestamp, scope, features_json, rule_score, hmm_state, hmm_probs_json, ensemble_label)` — scope ∈ {`MARKET`, `SYMBOL:XXX`}.
- `HMMModel(version, artifact_sha256, trained_at, trained_on, holdout_ll, active)`.

**API:**
```
GET /api/v1/regime/current/             → market regime + features snapshot
GET /api/v1/regime/history/?from&to     → time series
GET /api/v1/regime/symbol/{sym}/        → per-symbol regime (when available)
```

**Degradation:** If HMM stale > 48h, rule-based regime is used and a warning banner is shown.

### 6.5 Sentiment Analysis (`apps/sentiment`)

**Scope:** Ingest breaking news, score sentiment per-symbol and market-wide, feed sizing and risk modules.

**Ingestion sources (every 15 min):**
- FinancialModelingPrep news endpoint (primary).
- SEC EDGAR 8-K RSS (material events).
- Benzinga / Yahoo Finance RSS (redundancy).
- Nasdaq Trader halts RSS.

**Pipeline:**
1. **Fetch + dedupe** by URL + title-hash. Persist raw `NewsArticle` rows.
2. **Symbol tagging** — regex on tickers + NER (small spaCy model) to produce `symbols[]`.
3. **Score Tier 1 (FinBERT)** — `ProsusAI/finbert`, 3-class (positive/negative/neutral) with confidence. Runs on all articles.
4. **Score Tier 2 (local LLM)** — quantized Llama-3.1-8B GGUF via `llama-cpp-python`. Triggered **only** when FinBERT confidence < 0.7 OR the article is flagged material (SEC 8-K, halt, guidance change). Produces structured output: `{sentiment, impact_0_10, time_horizon_days, summary_80chars}`.
5. **Aggregate** — per-symbol EWMA over last 24h; market-wide weighted by S&P 500 cap weights.
6. **Publish** — upsert `SentimentScore` rows; emit Channels event.

**Sizing: LLM hardware.**
- **MVP:** CPU-only worker on Railway (4 vCPU, 8 GB RAM). Llama-3.1-8B Q4_K_M processes ~30 tok/s; at 80 tokens per article and ~50 "Tier 2" articles/day, total ~130s/day — comfortably fits on CPU.
- **Scale-up path:** Move LLM worker to a GPU pod (RTX 4000 / L4) once throughput > 500 Tier-2 articles/day.

**Models:**
- `NewsArticle(url, source, published_at, title, body, symbols_json, fetched_at, sha256)`.
- `SentimentScore(scope, symbol, window_minutes, positive, neutral, negative, impact, model_version, produced_at)`.

**API:**
```
GET /api/v1/sentiment/market/           → current market-wide score + history
GET /api/v1/sentiment/symbol/{sym}/     → per-symbol
GET /api/v1/sentiment/articles/?symbol  → recent articles + scores
```

### 6.6 Position Sizing & Allocation (`apps/risk` — sizing module)

**Inputs:**
- User's `RiskProfile` (max % risk per trade, max % per position, max concurrent positions, daily-loss threshold, leverage cap, permitted asset classes).
- Current regime (from §6.4).
- Current sentiment for the symbol + market (from §6.5).
- Strategy-suggested side (from webhook payload).
- Broker account equity + buying power (from broker adapter live cache).
- Instrument volatility (ATR-based).

**Algorithm (high-level):**
1. **Direction gate** — if `strategy.side == LONG` and regime ∈ {CRISIS, BEAR} and sentiment < -0.5, reduce size × 0.5 OR reject if user opted into strict mode.
2. **Risk-per-trade** — `dollar_risk = equity × risk_pct`, where `risk_pct` is regime-scaled:
   - BULL: user's base × 1.0
   - CHOP / NEUTRAL: × 0.6
   - BEAR: × 0.3
   - CRISIS: 0 (reject all new entries unless explicit override).
3. **Initial stop distance** = max(strategy stop, k × ATR14). k defaults to 1.5.
4. **Raw qty** = `dollar_risk / stop_distance_per_unit`.
5. **Clamps** — max % of equity per position; max concurrent positions; buying-power check; round-lot / tick-size rounding.
6. **Kelly damper (optional)** — if the strategy has ≥ 100 trades of history in our DB, apply `0.25 × kelly` to raw qty.
7. **Sentiment reinforcement** — if symbol sentiment > +0.7 and aligned with side, allow +10% size; if opposed, -30%.

All outputs recorded as a `SizingDecision` row for post-hoc review.

### 6.7 Risk Management & Kill Switches (`apps/risk`)

**Four-level kill switch hierarchy:**

| Level | Trigger | Action | Who |
|-------|---------|--------|-----|
| L0 — Per-strategy | User toggle in dashboard, OR auto (strategy drawdown > X%) | Reject new orders for that strategy; optionally flatten open positions tagged with that strategy. | User / system |
| L1 — Per-user global | User clicks "Halt my trading" OR daily-loss circuit breaker | Flatten ALL user's positions via broker market/DAY+IOC orders; reject new orders. | User / system |
| L2 — Daily-loss auto | (realized + unrealized) P&L ≤ `-max_daily_loss` for the user | Same as L1 but auto-triggered, unsettable until tomorrow UTC-05 (user configurable). | System |
| L3 — Platform admin | Admin clicks "Halt platform" | Reject all webhook processing & order placement globally; optionally flatten all. Emergency only. | Admin |

**Latency target:** ≤ 5s from trigger to all-positions-flattened submit (99p).

**Models:**
- `RiskProfile(user_id, max_risk_per_trade_pct, max_position_pct, max_concurrent, daily_loss_usd, daily_loss_pct, leverage_cap, permitted_asset_classes[], soft_stop_pct, hard_stop_pct)`.
- `KillSwitchState(scope, target_id, active, set_by_user_id, reason, active_from, active_to)`.
- `RiskEvent(user_id, event_type, details_json, created_at)`.

**Daily-loss watcher:** Celery task scheduled every 30s aggregates realized + unrealized per user (from broker adapter) and evaluates thresholds.

**Soft stop / Hard stop pattern:**
- Soft: reduce sizing by 50% once down `soft_stop_pct` intraday.
- Hard: L2 trigger.

### 6.8 Broker Connectors (`apps/brokers`)

**Interface (abstract):**
```python
class BrokerAdapter(Protocol):
    def connect(self, creds: EncryptedCreds) -> None: ...
    def get_account(self) -> Account: ...
    def list_positions(self) -> list[Position]: ...
    def place_order(self, req: OrderRequest) -> OrderAck: ...
    def cancel_order(self, broker_order_id: str) -> None: ...
    def flatten_all(self, reason: str) -> list[OrderAck]: ...  # kill switch
    def stream_fills(self) -> AsyncIterator[Fill]: ...
    def supports(self, asset_class: AssetClass) -> bool: ...
```

**IBKR Adapter (`brokers/ibkr/`)**
- Library: `ib_insync` over TWS/IBGateway.
- Deployment: **IB Gateway runs as a sidecar** on the worker service (Railway allows multi-process via start.sh). Authentication via IBKR's IBC + secure session, per-user credentials.
- Challenge: IBKR requires daily re-auth. Mitigation: IBC auto-restart + 2FA auto-confirm via IBKR mobile push (user must opt-in) OR use IBKR's paper account (no 2FA) for MVP paper phase.
- Supports: Stocks, options, futures, forex, ETFs. ✅ Meets spec.
- Fills: WebSocket-like via `ib_insync` event loop → push to Redis stream → persisted.

**TradeStation Adapter (`brokers/tradestation/`)**
- Library: wrap TradeStation v3 REST + WebSocket APIs (no mature SDK; we build a thin client).
- OAuth2 authorization_code flow; per-user refresh tokens stored encrypted.
- Supports: Stocks, options, futures, ETFs. ✅ Meets spec.
- Fills: stream via TS WebSocket → Redis stream.

**Paper vs live switch:** `BrokerAccount.mode ∈ {PAPER, LIVE}`, enforced by adapter endpoint selection. LIVE mode requires feature-flag `ENABLE_LIVE_TRADING` plus explicit user-accepted disclaimer versioned in DB.

**Reconciliation:** A beat job every 5 min compares our Position table to broker truth and emits a `ReconciliationEvent` on drift, auto-healing where safe.

### 6.9 Dashboard (Command Center)

**Routes (frontend):**
- `/dashboard` — default landing
  - Equity + PnL sparkline, today's P&L, open positions grid, recent fills, regime badge, sentiment heatmap, active strategies, kill-switch buttons.
- `/strategies` — list, enable/disable, upload, webhook config modal (see below), backtest launcher.
- `/backtest` — launch walk-forward runs, view reports, compare runs.
- `/risk` — configure `RiskProfile`, view `RiskEvent` log, set thresholds.
- `/brokers` — connect/disconnect broker, select default, toggle paper/live.
- `/admin` — (admin only) platform kill switch, user list, audit search.
- `/settings` — profile, change password, MFA.

**Webhook configuration modal (per spec point 7):**
- Opened from `/strategies` row → "Configure webhook".
- Fields:
  - **Webhook URL (read-only)** — generated per user+strategy.
  - **HMAC secret** — rotate button + copy-once reveal.
  - **JSON template editor** — Monaco editor with live JSON-schema validation, sample payload tester, "Copy TradingView alert" button that fills in placeholders for `{{strategy}}`, `{{ticker}}`, `{{close}}`, etc.
  - **Schema editor** — allow the user to redefine the accepted schema (always JSON, per spec). We ship a default schema but user can extend/override.
- Save persists `WebhookConfig` versioned; rotating invalidates old.

**Live updates:** WebSocket channel `ws://.../ws/dashboard/{user_id}/` streams `position.updated`, `fill.created`, `regime.changed`, `sentiment.updated`, `risk.breach`, `killswitch.state`.

**Performance:** Dashboard first render ≤ 1.5s on 4G. Signal-based stores avoid RxJS overhead; virtualized grids for fills.

### 6.10 Walk-Forward Backtester (`apps/backtest`)

**Purpose:** On-demand backtesting with a rolling/expanding window to reduce overfit and produce realistic out-of-sample performance.

**Design — two-stage engine:**

1. **Signal stage (vectorbt)** — ultra-fast parameter sweep over train window. Computes candidate parameter sets, ranks by Sharpe/MAR/PBO-adjusted score.
2. **Execution stage (backtrader)** — takes the chosen params and replays the test window bar-by-bar with realistic slippage, commissions, stop logic, partial fills. Produces the authoritative tearsheet.

**Walk-forward orchestrator:**
- User picks: symbol(s), strategy, `start`, `end`, `train_window` (e.g., 180d), `test_window` (e.g., 30d), `step` (e.g., 30d), `anchored | rolling`.
- Orchestrator iterates: train → select → test → collect fills + equity → advance window.
- Final report concatenates test segments into one continuous OOS equity curve.

**Metrics (report):**
- Total return, CAGR, Sharpe, Sortino, MAR (return / max DD), Max DD, % profitable, profit factor, avg win/loss, avg trade duration, exposure %, turnover, slippage estimate, per-window stability (variance of Sharpe across windows).
- PBO (Probability of Backtest Overfit, Bailey et al.) across the param sweep.

**Execution:**
- Long-running Celery task on a dedicated `backtest` queue (doesn't block order flow).
- Progress streamed to UI via WebSocket.
- Cancellable.

**Report outputs:**
- JSON (machine-readable), PDF tearsheet (WeasyPrint), Plotly-native HTML.
- Persisted in object storage; 90-day retention default, user-configurable.

**Models:**
- `BacktestRun(user_id, strategy_id, params_json, symbols[], start, end, train_w, test_w, step, status, progress_pct)`.
- `BacktestReport(run_id, metrics_json, equity_curve_json, trades_json, report_pdf_url, report_html_url, produced_at)`.

**API:**
```
POST /api/v1/backtest/runs/              → create + start
GET  /api/v1/backtest/runs/              → list
GET  /api/v1/backtest/runs/{id}/         → status + metrics
POST /api/v1/backtest/runs/{id}/cancel/
GET  /api/v1/backtest/runs/{id}/report/  → signed URL (PDF)
```

### 6.11 Audit Log (`apps/audit`)

Every privileged action writes an `AuditLog` row:
- `id`, `user_id`, `actor_id` (admin acting), `event_type`, `entity_type`, `entity_id`, `data_before`, `data_after`, `ip`, `ua`, `created_at`, `prev_hash`, `self_hash`.
- DB-level: app user has only INSERT + SELECT on `audit_log`. Nightly cron verifies hash chain and alerts on mismatch.

Events instrumented: login/logout, MFA enroll, password change, broker connect, webhook received, sizing decision, order placed/filled/canceled, kill-switch state change, risk breach, strategy upload, config change.

### 6.12 Admin Portal (`apps/admin_portal`)

**Beyond Django admin:**
- Platform-wide kill switch (L3).
- User list with last login, broker connected, mode (paper/live).
- Audit search (time range, event type, user).
- System health: queue depths, broker latencies, model freshness.

### 6.13 Market Data Provider Abstraction (`apps/marketdata/providers`)

**Scope:** A provider-agnostic data layer that allows the active market data vendor to be switched via a single environment variable (`MARKET_DATA_PROVIDER`). All upstream consumers (regime, sentiment, backtester, broker reconciliation) call the provider router; never a vendor SDK directly.

**Protocol:**
```python
class MarketDataProvider(Protocol):
    name: str
    supports_realtime: bool
    supports_options: bool
    supports_futures: bool

    def get_bars(self, symbol: str, tf: str,
                 from_dt: datetime, to_dt: datetime) -> list[Bar]: ...
    def get_quote(self, symbol: str) -> Quote: ...
    def get_options_chain(self, symbol: str,
                          expiry: date | None = None) -> list[OptionContract]: ...
    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[Quote]: ...
    def get_news(self, symbol: str | None,
                 from_dt: datetime) -> list[RawNewsArticle]: ...
    def get_breadth(self, date: date) -> BreadthSnapshot: ...   # A/D, NH/NL
    def health(self) -> ProviderHealth: ...
```

**Implemented providers (see §3.4 for cost/feature matrix):**

| Provider | `MARKET_DATA_PROVIDER` value | Phase | Real-time WS | Options | Futures |
|----------|------------------------------|-------|:---:|:---:|:---:|
| FinancialModelingPrep | `fmp` | Dev / Beta | ❌ (polling) | ⚠️ limited | ❌ |
| **Polygon.io** | `polygon` | **Production ⭐** | ✅ <20ms | ✅ OPRA | ✅ limited |
| TwelveData | `twelvedata` | Alternative | ✅ WS | ⚠️ limited | ❌ |
| Alpha Vantage | `alphavantage` | Fallback / news | ⚠️ limited | ❌ | ❌ |
| FRED | `fred` | Macro always-on (free) | ❌ | ❌ | ❌ |

**Provider router (`marketdata/router.py`):**
- Reads `MARKET_DATA_PROVIDER` (default: `fmp`).
- Instantiates the matching provider with its API key from env.
- Raises `ProviderCapabilityError` if a consumer requests a feature the active provider does not support (e.g., real-time WS on FMP) — forces explicit acknowledgement before fallback.

**Multi-provider composition (production):**
For production live trading you can run providers in composition:
```
MARKET_DATA_PROVIDER=polygon
MARKET_DATA_NEWS_PROVIDER=fmp          # FMP has better news coverage
MARKET_DATA_MACRO_PROVIDER=fred        # FRED for credit spreads, yield curve
MARKET_DATA_OPTIONS_PROVIDER=polygon   # Polygon OPRA feed
```
The router dispatches each data type to the appropriate provider. This keeps costs optimal: Polygon for speed-sensitive bar/quote data, FMP for news, FRED free for macro.

**Migration path: FMP → Polygon:**
1. Set `MARKET_DATA_PROVIDER=polygon` in staging Railway env.
2. Run `python manage.py backfill_bars --provider polygon --from 2015-01-01` to fill any gaps.
3. Verify regime features produce identical output on both providers for a 30-day overlap period.
4. Flip env var in production. No code changes required.

**Switching cost:** 0 code changes, 1 env var, ~30-minute backfill for gaps.

---

## 7. API Contract (high-level REST catalogue)

All endpoints JSON over HTTPS, JWT bearer, `Api-Version: 2026-04-01` header. OpenAPI 3.1 generated via `drf-spectacular` and served at `/api/schema/`.

| Resource | Methods |
|----------|---------|
| `/auth/*` | register, login, mfa, refresh, logout, password reset |
| `/users/me/` | GET, PATCH |
| `/strategies/` | GET, POST (upload) |
| `/strategies/{id}/` | GET, PATCH, DELETE |
| `/strategies/{id}/files/{kind}/` | GET |
| `/strategies/{id}/webhook-config/` | GET, PUT, rotate |
| `/risk/profile/` | GET, PUT |
| `/risk/killswitch/` | GET, POST (toggle) |
| `/brokers/` | GET, POST (connect), DELETE |
| `/brokers/{id}/test-connection/` | POST |
| `/brokers/{id}/flatten/` | POST |
| `/orders/` | GET (history) |
| `/positions/` | GET (live snapshot) |
| `/fills/` | GET |
| `/regime/current/`, `/regime/history/` | GET |
| `/sentiment/market/`, `/sentiment/symbol/{s}/` | GET |
| `/backtest/runs/`, `/backtest/runs/{id}/*` | CRUD |
| `/audit/search/` | GET (admin) |
| `/admin/killswitch/` | POST (admin) |
| `/hooks/v1/{user}/{strategy}/` | POST (webhook) |

---

## 8. Security Model

| Surface | Control |
|---------|---------|
| Transport | TLS 1.3 only; HSTS; CSP; no mixed content. |
| Authentication | Argon2 passwords; JWT short-lived access (15 min) + refresh (30 day rotating); MFA required for trading & broker endpoints. |
| Authorization | Per-row `owner_id` filter in every ViewSet + Postgres RLS as belt-and-suspenders. |
| Secrets | Railway env vars; per-user broker creds fernet-encrypted with a KEK stored in env. |
| Webhook auth | HMAC-SHA256 with per-user-per-strategy secret; constant-time compare; replay-protected via idempotency key. |
| CSRF | N/A for pure-JWT API, but CSRF tokens on cookie-based admin. |
| CORS | Strict allowlist: production frontend origin + `localhost:4444` in dev. |
| Rate limiting | Per-endpoint (webhook: 60/min/user; auth: 5/min/email; trade: 30/min/user). |
| Input validation | DRF serializers + jsonschema for webhook payloads. |
| Dependency security | `pip-audit` in CI; Dependabot PRs. |
| SAST/DAST | `bandit`, `ruff`, `semgrep` in CI. Trivy scan on Docker images. |
| Audit | Append-only hash-chained log (§6.11). |
| Disclaimer / consent | Versioned `TermsAcceptance` record per user before live trading is enabled. |

---

## 9. Observability & Monitoring

**Logging:**
- Structured JSON via `structlog`, correlation-id propagated from HTTP → Celery → broker call.
- Levels tuned; PII scrubbed; broker creds never logged (asserted via test).

**Metrics:**
- Prometheus endpoint exposed by Django + Celery + worker; scraped by Grafana Cloud.
- Key metrics: `webhook_latency_ms`, `order_submit_latency_ms`, `regime_freshness_s`, `sentiment_queue_lag`, `broker_reconnect_count`, `celery_queue_depth`, `killswitch_trigger_count`.

**Tracing:**
- OpenTelemetry SDK → Grafana Tempo; trace: webhook → sizing → risk → broker → fill.

**Error tracking:**
- Sentry for both backend and frontend; release + environment tagged.

**Uptime / healthchecks:**
- `GET /healthz` (process liveness), `GET /readyz` (DB, Redis, broker reachability).
- External pinger (UptimeRobot or Better Stack, free tier) hits `/healthz` every 60s.

**Alerts (PagerDuty or email/Telegram for MVP):**
- Webhook 5xx > 2% over 5 min.
- Broker disconnected > 2 min.
- Celery queue depth > 1000.
- Kill switch triggered.
- Sentiment pipeline lag > 30 min.
- HMM model age > 48h.
- DB CPU > 80% sustained 10 min.

**Dashboards (Grafana):**
1. Trading Ops — orders/min, fill latency, rejection reasons.
2. System Health — queues, DB, Redis, broker.
3. Data Pipelines — news ingest rate, sentiment throughput, regime updates.
4. Business — DAU, trades/user, P&L distribution.

---

## 10. CI/CD

**Pipeline (GitHub Actions):**

```yaml
# .github/workflows/ci.yml
on: [push, pull_request]
jobs:
  backend:
    steps:
      - checkout
      - setup-python 3.12
      - cache pip
      - install requirements/dev.txt
      - ruff check
      - bandit -r backend/apps
      - semgrep --config=auto
      - pytest --cov=apps --cov-fail-under=80
      - build docker image
      - trivy scan image

  frontend:
    steps:
      - checkout
      - setup-node 20
      - cache pnpm
      - pnpm install --frozen-lockfile
      - pnpm run lint
      - pnpm run test -- --watch=false --code-coverage
      - pnpm run build --configuration=production
      - build docker image
      - trivy scan image

  e2e:
    needs: [backend, frontend]
    steps:
      - docker compose up -d
      - pnpm run e2e

  deploy-staging:
    if: github.ref == 'refs/heads/main'
    needs: [e2e]
    steps:
      - railway up --service staging-backend
      - railway up --service staging-frontend
      - smoke tests

  deploy-prod:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: [deploy-staging]
    steps:
      - manual approval (GitHub env protection rule)
      - railway up --service prod-backend
      - railway up --service prod-frontend
      - canary smoke
```

**Release flow:**
- Trunk-based; every merge to `main` deploys to **staging** automatically.
- Production deploys on version tags (`v0.1.0` etc.) with required manual approval.
- Database migrations gate deploys; backwards-compatible migrations required; use Django's `RunPython` sparingly and wrap in separate release steps for destructive changes.

**Secrets management:** GitHub Actions `secrets` → Railway service variables via CLI. No secret in repo.

---

## 11. Local Development & ngrok bridge

**Local stack via `docker-compose`:**
- `postgres`, `redis`, `backend` (Django), `frontend` (ng serve), `celery-worker`, `celery-beat`, `llm-worker`, `ngrok`.

**ngrok bridge (for local TradingView testing):**
- `ngrok http 8777 --domain=<user-reserved-subdomain>` exposes the local webhook endpoint.
- A management command `python manage.py set_dev_webhook_host <ngrok-url>` updates the `WebhookConfig.url_base` for all user strategies in the local DB so TradingView alerts reach localhost.
- `.env.local.example` shipped with safe defaults.

**Broker sandboxes in local:** IBKR paper gateway and TradeStation simulator — both usable against the same code paths, switch via env.

---

## 12. Railway Deployment

**Services (6):**
1. `backend` — Django ASGI (daphne/uvicorn workers).
2. `worker` — Celery workers (queues: default, webhooks, orders, reconciliation).
3. `beat` — Celery beat scheduler (1 replica, crash-loop protected).
4. `llm-worker` — Separate service with higher RAM; consumes `sentiment` queue.
5. `frontend` — nginx serving built Angular SPA.
6. `postgres` + `redis` — managed by Railway.

**Config highlights:**
- Backend: min 1, max 3 replicas (autoscale on CPU).
- Worker: min 2.
- LLM worker: min 1 (sticky to prevent model cold-start thrash).
- Health checks on `/healthz`, `/readyz`.
- Rolling deploys with `preStop` graceful shutdown so Celery drains.

**Storage:** Railway's volume for `llm-worker` model cache; S3-compatible (Cloudflare R2 or Railway + minio side-car) for backtest PDFs + strategy files.

**Domains:** `api.strattraderpro.com`, `app.strattraderpro.com`. Cloudflare in front for DDoS + WAF.

**DB backups:** Railway automated daily + weekly; extra `pg_dump` to R2 weekly; test restore monthly.

---

## 13. Monetization

### 13.1 Positioning

StratTraderPro has materially stronger features than every direct competitor (TradersPost $49, Composer $40, 3Commas $49) — specifically: HMM-based regime filtering, AI news sentiment via a local LLM, walk-forward backtesting with PBO scoring, and a four-level institutional kill-switch hierarchy. This justifies pricing above the $49 commodity tier.

**Core positioning:** *"Systematic edge. Institutional safety net."*
**Hero copy:** *"Your TradingView strategies, automated — with an AI layer that knows when not to trade."*

Key differentiators to lead with:
- 🧠 **Regime-aware sizing** — the only bot that scales down in bear markets automatically.
- 📰 **AI sentiment filter** — reads breaking news so your bot doesn't trade into a disaster.
- 📊 **Walk-forward backtests** — know if your edge is real or overfit before risking capital.
- 🛡️ **Four-level risk engine** — from per-strategy pause to platform-wide emergency halt.

---

### 13.2 Tier Structure

#### 🆓 Free — "Paper Pilot"
**$0 / month — no credit card, forever.**

| Feature | Limit |
|---------|-------|
| Trading mode | Paper / simulator only |
| System strategies | 3 (curated selection) |
| User-uploaded strategies | ❌ |
| Broker connections | 1 (paper only) |
| Webhook alerts/day | 10 |
| Walk-forward backtest | 1 run/day · 1-year history · 1 symbol |
| Regime badge | ✅ current label only (no history) |
| Sentiment | ✅ market-wide score only |
| Kill switches | L1 global halt only |
| Risk profile | Basic (no Kelly, no sentiment sizing) |
| Support | Community Discord |
| Data retention | 30 days |

**Purpose:** Frictionless discovery. A user with a TradingView subscription and a paper broker account can be live-testing in under 15 minutes. The 10 alert/day limit triggers a natural upgrade moment within the first trading week. Free users are also the primary word-of-mouth channel in trader communities.

---

#### 📈 Trader — "Live Ready"
**$69 / month · $52 / month billed annually ($624/yr) — saves 25%**
14-day free trial, no credit card required for trial.

| Feature | Limit |
|---------|-------|
| Trading mode | Paper + **Live trading** |
| System strategies | All (full catalogue) |
| User-uploaded strategies | 5 |
| Broker connections | 2 (IBKR + TradeStation in any combination) |
| Webhook alerts/day | 200 |
| Walk-forward backtest | 3 simultaneous · 5-year history · 5 symbols |
| Regime | ✅ full history (90 days chart) |
| Sentiment | ✅ market + per-symbol (S&P 1500) |
| Kill switches | ✅ all 4 levels |
| Risk profile | ✅ full (Kelly damper, sentiment sizing, soft/hard stop) |
| Notifications | Email + in-app |
| Support | Email · 48h SLA |
| Data retention | 1 year |

**Why $69 not $49:** Competitors at $49 offer no regime awareness, no AI sentiment, and no walk-forward PBO backtesting. A $20 premium for those features is conservative; validated by competitor pricing and customer interviews in beta.

---

#### 🚀 Pro — "Full Automation"
**$129 / month · $97 / month billed annually ($1,164/yr) — saves 25%**
14-day free trial, card required.

| Feature | Limit |
|---------|-------|
| Everything in Trader, plus: | |
| User-uploaded strategies | Unlimited |
| Broker connections | Unlimited (all supported brokers) |
| Webhook alerts/day | Unlimited |
| Walk-forward backtest | 10 simultaneous · full history · unlimited symbols |
| Backtest report retention | 1 year |
| Regime | ✅ 2-year history + per-symbol regime |
| Sentiment | ✅ enhanced: Llama structured reports, impact scores, news archive |
| **Auto strategy selector** | ✅ system selects optimal strategy for current regime |
| **Telegram + Discord alerts** | ✅ real-time push |
| **Read-only REST API** | ✅ positions, fills, regime, sentiment (for your own tooling) |
| Priority webhook execution | ✅ front-of-queue |
| Support | Priority · 24h SLA |
| Data retention | 3 years |
| Early access | ✅ new brokers, new strategies |

---

#### 🏢 Studio — Enterprise (Post-v0.2, custom)
Designed for prop firms, family offices, hedge fund operators.
- Custom per-seat contract.
- White-label option (your domain, your branding).
- Isolated tenant infrastructure (dedicated DB + workers).
- Custom strategy Python adapter written by us.
- SLA: 4h response, 99.9% uptime guarantee.
- Target: $500–$2,000/month.

---

### 13.3 Annual Plan Mechanics

- Discount: **25%** (not 20% — the additional 5% is primarily a churn-reduction tool).
- Annual plans billed upfront via Stripe one-time invoice for 12 months.
- Display savings as a **concrete dollar amount** ("Save $204/year") in checkout — dollar savings outperform percentage discount labels in A/B tests.
- Annual → monthly downgrade allowed at renewal only; mid-cycle changes are not.
- Annual churn rate target: ≤1%/month vs 4–6%/month for monthly.

---

### 13.4 Feature Gate Implementation

The `PlanEnforcer` middleware (wired into DRF `permission_classes` globally) checks plan limits on every write endpoint:

```python
class PlanLimits:
    FREE  = PlanConfig(max_strategies_upload=0,  max_webhooks_day=10,  max_brokers=1,  live_trading=False, ...)
    TRADER = PlanConfig(max_strategies_upload=5, max_webhooks_day=200, max_brokers=2,  live_trading=True,  ...)
    PRO   = PlanConfig(max_strategies_upload=-1, max_webhooks_day=-1,  max_brokers=-1, live_trading=True,  ...)
```

On limit breach → `HTTP 402 Payment Required` with body:
```json
{ "code": "PLAN_LIMIT_REACHED", "limit": "webhooks_per_day",
  "current": 200, "allowed": 200,
  "upgrade_url": "https://app.strattraderpro.com/settings/billing/upgrade" }
```

Frontend intercepts 402 → shows an upgrade modal with plan comparison and Stripe Checkout CTA.

---

### 13.5 Trial Flow

1. User registers (Free).
2. User connects a broker → system detects intent to go live → prompts "Start your 14-day Trader trial".
3. Trial: all Trader features enabled; `subscription.trial_ends_at` set.
4. Day 12: email reminder "2 days left on your trial" + usage summary (how many alerts fired, positions taken, backtest runs).
5. Day 14: auto-downgrade to Free unless card added and Stripe subscription confirmed.
6. Pro trial: presented to Trader users who hit a Trader limit (e.g., 6th strategy upload).

---

### 13.6 Billing Stack

| Component | Technology |
|-----------|-----------|
| Checkout + Billing Portal | Stripe Checkout (hosted) + Stripe Customer Portal |
| Subscription model | Stripe Subscriptions with `MARKET_DATA_PROVIDER` analogy — `plan` field on `Subscription` |
| Webhooks | `/api/v1/billing/stripe-webhook/` — `customer.subscription.updated`, `invoice.payment_failed`, `invoice.paid`, `customer.subscription.deleted` |
| Trial | `subscription.trial_ends_at`; Stripe trial period |
| Invoices | Stripe auto-invoicing; PDF invoice download via Stripe Customer Portal |
| Currency | USD only at launch |
| Tax | Stripe Tax (automated for SaaS); disable for MVP, enable at 100+ users |
| DB model | `Subscription(user, stripe_customer_id, stripe_subscription_id, plan, status, trial_ends_at, current_period_end)` |

---

### 13.7 Revenue Model & Projections

Assumptions: 5% monthly churn (monthly plans), 1% (annual plans), 8% free-to-paid conversion rate, 40% Trader / 60% Pro split among paying users (Pro ratio is higher because Pro users self-select for high engagement).

| Month | Free users | Paying users | Est. MRR |
|-------|-----------|-------------|---------|
| 1 (beta) | 5 | 0 | $0 |
| 3 | 30 | 5 | ~$450 |
| 6 | 100 | 20 | ~$1,900 |
| 9 | 250 | 55 | ~$5,500 |
| 12 | 500 | 115 | ~$11,500 |
| 18 | 1,200 | 290 | ~$29,000 |

**Infrastructure break-even:** ~$360–505/mo (see §13.8). Reached at ~8 paying users.
**Comfortable solo-operation threshold:** 80–100 paying users (~month 10).
**Full-time sustainable income:** 150+ paying users (~month 12–14).

---

### 13.8 Monthly Infrastructure Cost at Scale

| Scale | Railway infra | External services | **Total** |
|-------|--------------|-------------------|-----------|
| Pre-launch | $175 | $185 | **$360** |
| 10 users | $200 | $210 | **$410** |
| 50 users | $265 | $240 | **$505** |
| 100 users | $380 | $270 | **$650** |
| 250 users | $600 | $310 | **$910** |

Key costs by line item (production):
- Railway (llm-worker 8GB): $60–90/mo (largest single item).
- Market data — Polygon.io Pro: $199/mo (replaces FMP at ~100 users).
- Market data — FMP Growth: $49/mo (dev/beta / fallback news).
- Cloudflare Pro: $20/mo.
- Sentry Team: $26/mo.
- Resend Starter (50k emails): $20/mo.
- Stripe: 2.9% + $0.30 per transaction (no fixed monthly fee).

**Cost optimisation levers:**
- Downgrade Llama to 3B model → halves llm-worker RAM → saves $30/mo.
- Stay on FMP Growth until live-trading user count justifies Polygon upgrade.
- Coarsen regime compute to 15-min intervals → reduces worker CPU by ~40%.

---

### 13.9 Additional Revenue Levers (post-v0.2)

| Lever | Mechanism | Notes |
|-------|-----------|-------|
| Strategy Marketplace | Community authors list strategies; 20% of upgrades attributed to their strategy go back as credits | Acquisition + retention flywheel |
| On-demand backtest credits | $9/extra run beyond plan quota | Low-friction upsell |
| Broker referrals | Revenue-share with IBKR ($50–200/activated account) + TradeStation partner programme | Passive income |
| API data exports | $9.99 one-time for extended data beyond retention period | Long-tail upsell |
| Affiliate programme | $50 cash per referred annual subscriber | Community-driven acquisition |
| Studio / white-label | $500–2,000/mo custom contract | High-ACV, low-volume |

---

### 13.10 Regulatory & Legal Checklist

| Item | Status | Action required |
|------|--------|----------------|
| Investment Advisor / CTA registration | ⚠️ Risk | Legal opinion before v0.2 live trading. EULA must state platform provides no investment advice and user owns all strategy logic. |
| CFTC / NFA (futures automation) | ⚠️ Research | Webhook-delivery model (not discretionary) has lower risk; still needs counsel review. |
| IBKR / TradeStation ToS re: credential storage | ⚠️ Research | Both have restrictions on third-party credential storage; review with counsel before v0.2. |
| Backtest disclaimers | ✅ Plan'd | "Past performance is not indicative…" disclaimer on every PDF tearsheet page. |
| GDPR / CCPA (data export + delete) | ✅ Plan'd | M11 implements export + soft delete. |
| Terms of Service + Privacy Policy | ✅ Plan'd | Drafted in M11; counsel review before v0.2. |
| PCI DSS | ✅ N/A | Stripe handles card data; we never touch raw card numbers. |

---

## 14. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | IBKR daily 2FA auth interrupts trading | High | High | Use paper gateway in MVP; for live, require user to enable IB mobile push; monitor auth state and page. |
| R2 | TradingView webhook spoof → unauthorized trades | Low | Critical | HMAC + idempotency + IP allowlist option + audit. |
| R3 | Walk-forward overfit → unrealistic live results | Medium | High | Enforce PBO reporting; require OOS Sharpe > 1 before enabling for live. |
| R4 | LLM worker OOM with spiky news | Medium | Medium | Queue caps + circuit breaker to FinBERT-only; autoscale RAM. |
| R5 | Broker API outage | Medium | High | Read-only positions cached; kill switch continues to work via cached state; status banner. |
| R6 | Market data vendor (FMP) rate limit | Medium | Medium | Local cache + long TTLs on bars; secondary source (yfinance) fallback for non-critical data. |
| R7 | User uploads malicious Pine file | Low | Low (Pine doesn't execute server-side, but displayed) | Sanitize on render; scan for XSS; file size cap. |
| R8 | Compliance: unregistered investment advisor concerns | Low | High | EULA explicitly states platform does NOT provide investment advice; all strategies are user-owned. Legal review before public launch. |
| R9 | Secret leak in logs | Low | Critical | Structlog processor strips keys; automated tests assert. |
| R10 | Runaway Celery retry storm | Medium | Medium | `autoretry_for` + exponential backoff + max retries + dead-letter queue. |
| R11 | HMM drift during regime shift | Medium | Medium | Nightly retrain + rule-based fallback + alerting on freshness. |
| R12 | Kill switch latency too high | Low | Critical | Pre-warm broker session; `flatten_all` uses market orders; dedicated priority queue; load test. |

---

## 15. Phased Delivery Plan (10–12 Weeks)

Assumption: 1 senior full-stack engineer (you), ~35 focused hrs/week. Scope is tight but achievable. Buffer week at the end.

### Week 0 — Scoping & Setup (pre-week)
- Finalize plan (this doc).
- Provision Railway project + Postgres + Redis + staging domain.
- Create GitHub repo + branch protection + CI skeleton.
- Bootstrap Django + Angular per `django-angular-project-setup` & `frontend` skills.
- **Exit gate:** `/healthz` returns 200 on staging; Angular "hello" deployed.

### Week 1 — Auth foundation
- `users` app: register, email verify, login, JWT, refresh rotation.
- Frontend: auth routes, guards, interceptors, login/register pages.
- Argon2, rate limits, lockout.
- Unit + e2e tests.
- **Exit gate:** A new user can sign up, verify, log in, see a protected dashboard stub.

### Week 2 — MFA + User Profile
- TOTP enrollment, QR, backup codes.
- MFA enforcement middleware.
- Profile page, password change.
- **Exit gate:** MFA can be enabled; required before any broker-related route.

### Week 3 — Strategies & Webhook Plumbing + Billing Foundation
- `strategies` app + upload endpoint + validation.
- Seed command: import from Trading Strategies project folder.
- `WebhookConfig` + rotate, reveal-once UI.
- Webhook modal (Monaco editor + schema test).
- **Billing (M03.5):** Stripe integration — `Subscription` model, Stripe Checkout, Billing Portal, `PlanEnforcer` middleware, plan-gated 402 responses, upgrade modal in frontend.
- **Exit gate:** Strategies list shows seeded strategies + user can upload + configure webhook. Stripe test-mode checkout completes and grants Trader plan in DB.

### Week 4 — Webhook Ingest + Broker Adapter Interface + IBKR paper
- `/hooks/v1/...` endpoint: HMAC verify, idempotency, Celery dispatch.
- Broker adapter Protocol + fake adapter for tests.
- IBKR paper adapter: connect, positions, place_order, flatten_all.
- **Exit gate:** End-to-end: TradingView alert → IBKR paper order → position visible in dashboard.

### Week 5 — TradeStation paper + Order lifecycle
- TradeStation OAuth + REST + WS.
- `orders` app: unified Order/Fill/Position models + reconciliation.
- Order history UI.
- **Exit gate:** Same e2e flow works with TradeStation paper; reconciliation corrects drift.

### Week 6 — Market Data Provider Layer + Regime classifier (rule-based + HMM)
- `marketdata/providers/` abstraction layer: `MarketDataProvider` protocol + FMP + Polygon.io implementations.
- `MARKET_DATA_PROVIDER` env var routing; `MARKET_DATA_NEWS_PROVIDER`, `MARKET_DATA_MACRO_PROVIDER` composition.
- Bar store with idempotent upserts; gap detection; FRED client for macro.
- `regime` app: features, rule-based classifier.
- HMM training + online decode; nightly beat job (using Redbeat).
- Regime badge + history chart in dashboard.
- **Exit gate:** Regime visible in dashboard; switching `MARKET_DATA_PROVIDER=polygon` produces identical regime output; FRED macro features fetching correctly.

### Week 7 — Sentiment pipeline (FinBERT + LLM)
- News fetchers (FMP, EDGAR, Benzinga).
- FinBERT worker.
- Local LLM worker (Llama-3.1-8B GGUF on CPU).
- Aggregation + Channels push.
- Sentiment UI (market + per-symbol).
- **Exit gate:** Fresh sentiment in dashboard; worker handles 200 articles/hr without lag.

### Week 8 — Risk engine + Sizing + Kill switches
- `RiskProfile` CRUD + UI.
- Sizing algorithm with regime + sentiment inputs.
- Per-strategy + global + daily-loss kill switches.
- Pre-warm broker session; `flatten_all` load test ≤ 5s.
- **Exit gate:** All four kill-switch levels pass integration tests with measured latency.

### Week 9 — Walk-Forward Backtester
- vectorbt param sweep.
- backtrader execution replay.
- WF orchestrator + cancel + progress.
- PDF tearsheet (WeasyPrint) + HTML export.
- **Exit gate:** Run a 3-year WF on a seeded strategy; PDF produced; metrics sensible.

### Week 10 — Admin Portal + Audit + Observability polish
- Platform kill switch UI.
- Audit search.
- Sentry + Prometheus + Grafana dashboards wired.
- Alert rules.
- **Exit gate:** Admin can query audit log; every key metric is on a Grafana panel.

### Week 11 — Hardening, Security, Load test, Docs
- pentesting checklist (OWASP ASVS L2 subset).
- Load test: 100 concurrent users, 10 webhooks/sec, kill-switch latency.
- User docs (getting started, strategy upload, TradingView alert setup, risk thresholds).
- Runbooks (on-call, broker outage, HMM retrain failure).
- **Exit gate:** Load test passes; docs reviewed.

### Week 12 — Beta, bugfix, sign-off
- Private beta with 3–5 users (paper).
- Collect feedback, fix critical.
- Final sign-off against §1.1 success criteria.
- **Exit gate:** All MVP success criteria green; release `v0.1.0` → prod.

### Post-MVP (v0.2+, outside 12 weeks)
- Gated live trading rollout (separate ADR + legal review).
- Additional brokers (Alpaca, Schwab).
- Options-aware sizing, IV rank filters.
- Mobile-friendly responsive polish.
- Strategy marketplace (community-tested flag promotion flow).
- GPU-backed LLM worker.

---

## 16. Testing Strategy

**Pyramid:**
- **Unit (60%):** DRF serializers, sizing math, HMM wrapper, HMAC verify, risk gates. `pytest` + `hypothesis` for property tests on sizing.
- **Integration (25%):** Webhook → Celery → fake broker → DB assertions. `pytest-django` with Postgres container.
- **Contract (5%):** OpenAPI schema → frontend types via `openapi-typescript`; contract tests run nightly.
- **E2E (10%):** Playwright flows: signup → MFA → connect paper broker → receive webhook → see fill → flatten → logout. Run against ephemeral staging every deploy.

**Load tests (Locust):**
- 100 concurrent WebSocket dashboards.
- 20 webhooks/sec for 10 min.
- Kill-switch under load (latency p99 ≤ 5s).

**Chaos drills (manual, once before launch):** kill Redis for 30s; kill worker; simulate broker 5xx storm.

---

## 17. Data Retention & Compliance

| Entity | Retention | Notes |
|--------|-----------|-------|
| AuditLog | 7 years | Financial norm; hash-chained; never deleted. |
| Orders/Fills | 7 years | Immutable history. |
| NewsArticle | 90 days | De-duped; can be re-fetched from source. |
| SentimentScore | 1 year rolling | Aggregates retained; raw rolled up after 30 days. |
| RegimeObservation | Indefinite (small) | Small rows, valuable for later research. |
| BacktestReport | User-configurable (default 90 days) | PDFs in object storage; LRU evict. |
| User PII | While account active + 30 days post-deletion | GDPR/CCPA export + delete endpoints. |

---

## 18. Open Questions / Assumptions (flagged for confirmation before Week 3)

1. **Legal / EULA.** Plan assumes StratTraderPro is a tool, not an advisor. Before live rollout we will draft a legal-reviewed EULA clarifying (a) user takes all trading risk, (b) platform makes no investment recommendation, (c) strategy outcomes are historical and not indicative. Additionally a legal opinion on CFTC/NFA CTA registration risk is needed before v0.2 given futures automation. ❓ Confirm we engage fintech counsel before v0.2.
2. **Trading Strategies project path.** The import command needs the absolute path to the existing Cowork "Trading Strategies Project." ❓ Please provide access / path in Week 3.
3. **Live-trading gate.** The plan assumes paper-only in MVP. Enabling live is a v0.2 story with additional checklist (KYC disclaimer, TermsAcceptance v2, per-user soft-cap on notional, IBKR/TS ToS review). ❓ Confirm alignment.
4. **Market data provider + tier.** Dev/beta uses FMP Growth ($49/mo). Production live-trading phase requires Polygon.io Developer ($79/mo) minimum for real-time WebSocket. Upgrade triggered when first user goes live, or when FMP poll latency becomes a user complaint. ❓ Confirm FMP current plan/limits so rate-limit sizing can be set accurately in M06.
5. **Polygon.io commercial licence.** Polygon explicitly permits commercial SaaS use on paid plans. ❓ Confirm sign-up and store API key in Railway env before M06.
6. **vectorbt Pro licence.** Community edition is AGPL — not suitable for a SaaS web service (requires source disclosure). ❓ Purchase commercial licence before M09 (backtester milestone). Alternative: replace sweep stage with a custom pandas/numpy vectorised engine (~3–4 days work); viable if licence cost is prohibitive.
7. **Stripe account.** Billing milestone (M03.5) requires a Stripe account in test mode. ❓ Create account before Week 3; confirm USD is the launch currency.
8. **Timezone.** All displayed times default to user's IANA tz; internal storage is always UTC. ❓ Confirm OK.
9. **Mobile.** Responsive but **not** a native app in MVP. ❓ Confirm.
10. **Notifications.** Email + in-app for MVP; Telegram/Discord in Pro tier (v0.1); SMS deferred. ❓ Confirm.
11. **IBKR CPAPI access.** CPAPI requires enrollment through IBKR's developer programme. ❓ Apply for CPAPI access before M04 (IBKR milestone). Note: paper accounts can use CPAPI directly for testing without special approval.

---

## Appendix A — Pine Webhook JSON Default Schema (shipped)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "StratTraderPro TradingView Webhook Payload",
  "type": "object",
  "required": ["strategy", "action", "symbol", "qty", "order_type", "sig", "idempotency_key"],
  "properties": {
    "strategy": { "type": "string", "maxLength": 64 },
    "action":   { "enum": ["ENTER_LONG", "ENTER_SHORT", "EXIT_LONG", "EXIT_SHORT", "FLATTEN"] },
    "symbol":   { "type": "string", "maxLength": 16 },
    "asset_class": { "enum": ["STOCK", "ETF", "OPTION", "FUTURE"], "default": "STOCK" },
    "qty":      { "type": "number", "exclusiveMinimum": 0 },
    "qty_type": { "enum": ["SHARES", "CONTRACTS", "RISK_PCT"], "default": "SHARES" },
    "order_type": { "enum": ["MKT", "LMT", "STP", "STP_LMT"] },
    "price":    { "type": "number" },
    "stop":     { "type": "number" },
    "target":   { "type": "number" },
    "time_in_force": { "enum": ["DAY", "GTC", "IOC"], "default": "DAY" },
    "comment":  { "type": "string", "maxLength": 256 },
    "sig":      { "type": "string", "pattern": "^[a-f0-9]{64}$" },
    "idempotency_key": { "type": "string", "maxLength": 128 }
  },
  "additionalProperties": true
}
```

## Appendix B — Key Postgres Tables (selected)

```sql
CREATE TABLE "user" (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  is_verified BOOL NOT NULL DEFAULT false,
  mfa_enabled BOOL NOT NULL DEFAULT false,
  role TEXT NOT NULL DEFAULT 'user',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE strategy (
  id UUID PRIMARY KEY,
  owner_id UUID NULL REFERENCES "user"(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  is_system BOOL NOT NULL DEFAULT false,
  is_enabled BOOL NOT NULL DEFAULT true,
  is_community_tested BOOL NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner_id, slug)
);

CREATE TABLE strategy_file (
  id UUID PRIMARY KEY,
  strategy_id UUID NOT NULL REFERENCES strategy(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('PINE','DESC','WEBHOOK_TEMPLATE')),
  filename TEXT NOT NULL,
  sha256 CHAR(64) NOT NULL,
  content BYTEA,        -- for small; else object storage URL
  object_url TEXT,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE webhook_config (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  strategy_id UUID NOT NULL REFERENCES strategy(id) ON DELETE CASCADE,
  secret_encrypted BYTEA NOT NULL,
  json_schema JSONB NOT NULL,
  version INT NOT NULL DEFAULT 1,
  allowed_ips INET[] NULL,
  rotated_at TIMESTAMPTZ,
  UNIQUE (user_id, strategy_id)
);

CREATE TABLE broker_account (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  broker TEXT NOT NULL CHECK (broker IN ('IBKR','TRADESTATION')),
  mode TEXT NOT NULL CHECK (mode IN ('PAPER','LIVE')),
  creds_encrypted BYTEA NOT NULL,
  nickname TEXT,
  is_default BOOL DEFAULT false,
  last_connected_at TIMESTAMPTZ
);

CREATE TABLE risk_profile (
  user_id UUID PRIMARY KEY REFERENCES "user"(id) ON DELETE CASCADE,
  max_risk_per_trade_pct NUMERIC(5,2) NOT NULL DEFAULT 0.50,
  max_position_pct NUMERIC(5,2) NOT NULL DEFAULT 10.00,
  max_concurrent INT NOT NULL DEFAULT 5,
  daily_loss_usd NUMERIC(14,2),
  daily_loss_pct NUMERIC(5,2) DEFAULT 3.0,
  leverage_cap NUMERIC(5,2) DEFAULT 1.0,
  soft_stop_pct NUMERIC(5,2) DEFAULT 1.5,
  hard_stop_pct NUMERIC(5,2) DEFAULT 3.0,
  permitted_asset_classes TEXT[] NOT NULL DEFAULT ARRAY['STOCK','ETF']
);

CREATE TABLE kill_switch_state (
  id UUID PRIMARY KEY,
  scope TEXT NOT NULL CHECK (scope IN ('STRATEGY','USER','DAILY_LOSS','PLATFORM')),
  target_id UUID NULL,
  active BOOL NOT NULL,
  reason TEXT,
  set_by_user_id UUID NULL,
  active_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  active_to TIMESTAMPTZ NULL
);

-- NOTE: Named trade_order (not "order") because ORDER is a reserved SQL keyword.
CREATE TABLE trade_order (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES "user"(id),
  broker_account_id UUID NOT NULL REFERENCES broker_account(id),
  strategy_id UUID NOT NULL REFERENCES strategy(id),
  client_order_id TEXT UNIQUE NOT NULL,
  broker_order_id TEXT UNIQUE,
  symbol TEXT NOT NULL,
  asset_class TEXT NOT NULL,
  side TEXT NOT NULL,
  qty NUMERIC(14,4) NOT NULL,
  order_type TEXT NOT NULL,
  limit_price NUMERIC(14,4),
  stop_price NUMERIC(14,4),
  tif TEXT NOT NULL,
  status TEXT NOT NULL,
  submitted_at TIMESTAMPTZ,
  filled_qty NUMERIC(14,4) DEFAULT 0,
  avg_fill_price NUMERIC(14,4),
  sizing_decision_id UUID,
  webhook_alert_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_id UUID,
  actor_id UUID,
  event_type TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT,
  data_before JSONB,
  data_after JSONB,
  ip INET,
  ua TEXT,
  prev_hash CHAR(64),
  self_hash CHAR(64) NOT NULL
);
REVOKE UPDATE, DELETE ON audit_log FROM app_user;
```

## Appendix C — Celery beat schedule (selected)

| Task | Cadence | Queue |
|------|---------|-------|
| `marketdata.sync_bars_daily` | 18:00 ET | default |
| `marketdata.sync_bars_intraday` | every 1 min (market hours) | default |
| `regime.compute_features` | every 5 min (market hours) | default |
| `regime.retrain_hmm` | 03:00 ET daily | default |
| `sentiment.ingest_news` | every 15 min | sentiment |
| `sentiment.score_batch` | triggered by ingest | sentiment |
| `risk.daily_loss_watcher` | every 30 s (market hours) | priority |
| `brokers.reconcile_positions` | every 5 min | default |
| `audit.verify_hash_chain` | 04:00 ET daily | default |
| `cleanup.evict_old_backtest_pdfs` | 04:30 ET daily | default |

## Appendix D — Acceptance test matrix (sample)

| Scenario | Inputs | Expected |
|----------|--------|----------|
| Register + MFA + login | new email | User lands on dashboard, MFA verified |
| Webhook happy path | valid HMAC, paper IBKR connected | Order placed; fill reflected; audit row |
| Webhook bad HMAC | invalid sig | 401; no order; audit row (rejected) |
| Duplicate alert | same idempotency key within 24h | 200; no second order |
| Daily loss breach | P&L falls below threshold | L2 trigger; flatten within 5s; new orders rejected |
| Strategy kill switch | user toggles off | Orders for that strategy rejected; others continue |
| Regime = CRISIS | webhook enters long | Sizing returns 0; order rejected with reason |
| Backtest run | strategy + 3y range, 180/30 WF | PDF produced; metrics present; PBO < 0.5 |
| Platform halt | admin toggles platform switch | All webhooks 503; no orders processed |
| LLM worker down | queue grows | Pipeline falls back to FinBERT-only; banner shown |

---

_End of plan._
