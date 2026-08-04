# StratTraderPro — Plan Analysis, Cost Analysis & Business Model

> **Status: ❌ SCRAPPED 2026-07-14 — OSS pivot; do not implement.**
> Superseded by `project-plan/PIVOT-TO-OSS.md`. The Stripe / paid-SaaS business model is dead:
> distributing software is not an investment service, and vectorbt's Commons Clause forbids paid
> hosting/support anyway (D3). Kept as a record of what was deliberately **not** built (D8).
>
> **What carried over / was reconciled:**
> - **HIGH-05** (tearsheets carry no financial disclaimer) — still open → **WP-5** fixes it.
> - **MED-05** (broker-ToS credential storage) — *resolved by* self-hosting: the user holds their
>   own keys on their own instance.
> - **MED-09** (cross-user Kelly leak) — **verified not present:** the Kelly damper is deferred/
>   unimplemented and `backend/apps/risk/sizing.py` is a pure function with per-call inputs and no
>   shared cross-user state.
> - **CRITICAL-04** (HMM pickle-in-DB RCE) — **verified fixed:** `apps/regime/models.py` persists
>   the HMM as a `JSONField` (`params`/`state_labels`), not a pickle blob.
> - **CRITICAL-05** ("vectorbt is AGPL") — was factually wrong; vectorbt is Apache-2.0 + Commons
>   Clause (D3).

> **Date:** 2026-04-14
> **Author:** Software Architect / Market Analyst
> **Scope:** Full plan review (strat-trader-pro.md + M00–M12), monthly cost breakdown, and business model recommendation.

---

## Part 1 — Plan Review: Findings, Mistakes & Improvements

### 1.1 Critical Issues (must fix before implementation)

---

#### ❌ CRITICAL-01 — IBKR Gateway architecture is broken at multi-user scale

**What the plan says:** "IB Gateway runs as a sidecar on the worker service; per-user credentials decrypted into env of a per-user Gateway process; processes pooled by Celery worker; serialised by Redis lock per user."

**What's wrong:** IBKR Gateway is a ~500 MB Java process. For 50 users you would need up to 50 concurrent Gateway instances simultaneously. Railway worker containers are not designed to run dozens of long-lived child processes. The lock-per-user approach serialises trading for all users on the same gateway, destroying concurrency. Additionally, IBC GUI auto-login breaks every time IBKR updates the login UI (typically several times per year), which is a maintenance time-bomb.

**Fix:** Switch to the **IBKR Client Portal API (CPAPI)** — IBKR's newer REST + WebSocket gateway that requires no Java process, no GUI automation, and works with OAuth2-style sessions. Per-user sessions are managed via HTTPS. This is the recommended path for cloud deployments. Update ADR-040 accordingly.

- Replace `ib_insync` with direct CPAPI HTTP calls using `httpx`.
- Each user's session is an authenticated HTTP client, not a TCP socket to a sidecar.
- Eliminates the IBC dependency entirely.
- Downside: CPAPI has some limitations on order types vs TWS; document these.

---

#### ❌ CRITICAL-02 — Webhook HMAC canonicalisation fragility

**What the plan says:** HMAC is computed over "body without sig field". TradingView sends JSON. Server strips `sig` from the body and recomputes.

**What's wrong:** JSON is not canonically ordered. TradingView may format the alert body differently than the user typed it (e.g., escaping, whitespace, key order). If the server strips `sig` via key deletion and re-serialises (e.g., `json.dumps(body_without_sig)`), the resulting bytes may not match what was signed. This will cause intermittent HMAC failures that are very hard to debug.

**Fix:** Define a precise canonicalisation rule in ADR-041:
1. On the **user side**: instruct them to put `sig` as the **last key** in the JSON template. Most JSON parsers preserve insertion order. Provide a copy-paste template with `sig` as the final key.
2. On the **server side**: extract `sig` by removing only the last top-level key; verify the raw bytes of the body **before** JSON parsing against the HMAC — this means storing the raw `request.body` bytes and computing HMAC on those bytes without any re-serialisation.
3. Treat this as a known fragility; log a warning whenever body parsing succeeds but HMAC fails; show the raw body in the webhook debug UI so users can diagnose.

---

#### ❌ CRITICAL-03 — `order` is a reserved SQL keyword

**What the plan says:** `CREATE TABLE "order" (...)`.

**What's wrong:** `order` is a reserved keyword in SQL. While Postgres accepts it with quoting, it requires `"order"` everywhere in queries, migrations, and ORM calls. This is error-prone and produces confusing bugs when a developer forgets the quotes.

**Fix:** Rename to `trade_order` or `trading_order` in both the model and migration. Update all Appendix B SQL, API references, and model classes before any migration is written.

---

#### ❌ CRITICAL-04 — HMM model stored as a pickle in the database

**What the plan says:** "Model artifacts stored in DB (pickled + SHA-256)."

**What's wrong:** Python pickles are executable code. An attacker with DB write access (or a DB backup leak) could replace the pickle with malicious code that runs at model load time. Additionally, pickle format is not stable across Python versions or `hmmlearn` versions — a dependency upgrade can silently break model loading.

**Fix:**
- Use **joblib** with a fixed `compress=3` and version-pinned environment (same as training).
- Store the model as a file in **object storage** (R2), not the DB. Store only the `object_url`, `sha256`, `trained_at`, and `version` in the DB.
- Verify SHA-256 before loading. If verification fails, fall back to the previous active model.
- Consider exporting to ONNX format for maximum portability (hmmlearn doesn't support ONNX natively, so joblib is the practical choice here — just handle versioning explicitly).

---

#### ❌ CRITICAL-05 — vectorbt AGPL licence in a web service

**What the plan says:** "vectorbt AGPL for community edition — acceptable for our internal use."

**What's wrong:** AGPL requires that if you run a modified (or even unmodified) AGPL-licensed program as a network service and users interact with it over the network, you must offer the corresponding source code. A SaaS trading platform where users trigger backtests is arguably "network use" under AGPL. This could require disclosing your entire backend codebase to users who request it.

**Fix (choose one):**
1. Purchase the **vectorbt Pro commercial licence** (available; contact vectorbt author). Explicitly budget this in the cost model.
2. Replace vectorbt with a permissively licensed alternative: **bt** (MIT), **backtesting.py** (AGPL — same problem), **PyAlgoTrade** (Apache), or write a custom vectorised backtester using pure pandas/numpy (~3–4 days work for the sweep stage given our limited strategy set).
3. Fence vectorbt behind a subprocess boundary and argue the AGPL obligation doesn't propagate to your backend (legally uncertain — don't do this without counsel).

**Recommended:** Budget for the commercial licence. The time saved by using vectorbt is worth the licensing cost.

---

#### ❌ CRITICAL-06 — No subscription/billing system in any milestone

**What the plan says:** Nothing about billing, subscription management, or payment processing anywhere in the 13 milestone files.

**What's wrong:** You are building a paid SaaS. Without Stripe integration, you cannot charge users, enforce plan limits, handle upgrades/downgrades, issue invoices, or run a trial. This is not a minor omission — it touches authentication (plan-gated features), the database (plan tier per user), and the frontend (upgrade flows, billing portal).

**Fix:** Add **M03.5 — Billing & Subscription** as a new half-milestone between M03 and M04, covering:
- Stripe Checkout + Billing Portal.
- `Subscription` model: `user`, `plan` (FREE/TRADER/PRO), `stripe_subscription_id`, `trial_ends_at`, `current_period_end`, `status`.
- Stripe webhooks (`customer.subscription.updated`, `invoice.payment_failed`, etc.).
- Feature-gate middleware checking `user.subscription.plan`.
- Frontend: upgrade CTA, plan badge, billing portal link.

---

### 1.2 High-Priority Issues (fix in the same milestone they affect)

---

#### ⚠️ HIGH-01 — Daily P&L kill switch uses potentially stale marks

**Issue:** The daily-loss watcher runs every 30s and reads `unrealised P&L from broker adapter live cache`. If the broker connection is down, this cache could be several minutes stale, causing the kill switch to trigger too late or not at all during a fast move.

**Fix:** On each daily-loss-watcher tick, attempt a fresh broker position pull with a 5s timeout. If the pull fails, use the cache but flag a `STALE_MARKS` event and reduce the threshold to `daily_loss_pct × 0.8` as a conservative backstop. Log all mark sources.

---

#### ⚠️ HIGH-02 — Celery Beat has no distributed leader election

**Issue:** `beat` is a single replica (correct), but Railway will restart it on crash without delay, causing duplicate task executions during the restart window. `django-celery-beat` has no built-in idempotency for scheduled tasks.

**Fix:** Replace `django-celery-beat` with **Redbeat** (`celery-redbeat`), which uses Redis to implement distributed leader election. If the beat process crashes, the next instance picks up the schedule from Redis without duplicating in-flight tasks. Add to requirements in M00.

---

#### ⚠️ HIGH-03 — Postgres connection exhaustion with 6 services

**Issue:** 6 Railway services × Django's default pool = potentially 6 × 10 = 60 concurrent connections. Railway Postgres has a max-connection limit depending on plan (typically 25–100 for lower tiers). Under burst conditions (deploy + traffic) all services open max pools simultaneously.

**Fix:**
- Add **PgBouncer** as a 7th Railway service (or use Railway's PgBouncer plugin) in transaction-pooling mode.
- Set `MAX_CONN_NUM` explicitly per service: backend 10, worker 5, beat 2, llm-worker 2, frontend none.
- Add `django-db-connection-pool` with explicit pool sizing.
- Monitor `pg_stat_activity` connections in Grafana.

---

#### ⚠️ HIGH-04 — Benzinga and Yahoo Finance RSS scraping may violate ToS

**Issue:** M07 lists Benzinga RSS and Yahoo Finance RSS as news sources. Yahoo Finance blocks RSS/scraping programmatically and their ToS prohibits automated scraping. Benzinga has paid API tiers.

**Fix:**
- **Remove Yahoo Finance** from the ingestion sources entirely.
- **Replace Benzinga RSS with Benzinga API** (paid, ~$50/mo for basic tier) or drop it and rely on FMP + SEC EDGAR + Nasdaq.
- **Add Alpha Vantage News API** as a free-tier fallback (50 requests/day — enough for material news top-up).
- Update M07 ingestion sources accordingly.

---

#### ⚠️ HIGH-05 — Walk-forward backtest tearsheets lack required financial disclaimers

**Issue:** PDF tearsheets show historical performance metrics with no disclaimer that past performance does not predict future results. This is a compliance requirement and a courtesy to users who may interpret backtests as predictive.

**Fix:** Hardcode the following disclaimer block on every tearsheet PDF (non-removable, in the footer of every page):
> "IMPORTANT: The results shown are based on simulated historical backtests and are provided for informational purposes only. Past performance is not indicative of future results. Backtests have inherent limitations: they are based on historical data that cannot reliably predict future conditions, do not account for liquidity risk, and may reflect survivorship or look-ahead bias. Trading involves substantial risk of loss."

Also add a `PBO_WARNING` overlay when `pbo > 0.5`: "⚠ This strategy shows signs of overfit (PBO = {X}%). Use with extreme caution."

---

#### ⚠️ HIGH-06 — Pine→Python strategy adapter gap is a silent maintenance burden

**Issue:** The backtester requires a Python adapter (`_backtest.py`) for each system strategy, separate from the `.pine` file. Any time a Pine strategy is updated, its Python adapter must also be updated. There is no automated check that the two are in sync.

**Fix:**
- Add a `strategy_versions` table: `strategy_id`, `pine_sha256`, `python_adapter_sha256`, `verified_at`, `verified_by`.
- Add a CI check that fails if a `.pine` file changes without a corresponding `_backtest.py` change.
- Document the adapter contract explicitly in ADR-092 with a type-checked interface.
- In the backtest launcher, display a warning badge "Python adapter may be outdated" when `pine_sha256` changed after the adapter's `verified_at`.

---

#### ⚠️ HIGH-07 — FRED rate limits not accounted for in regime feature computation

**Issue:** FRED API free tier allows 120 requests/minute. The regime feature pipeline pulls credit spread data (HY OAS, IG OAS, yield spread) from FRED. With a nightly HMM retrain pulling 10 years of daily data plus intraday feature ticks every 5 minutes, the cumulative request count could exceed FRED limits.

**Fix:**
- Cache FRED data aggressively: daily series cached for 24h; weekly series for 7 days.
- Use FRED's bulk download for the initial historical pull (CSV endpoint, not API).
- Add a Prometheus metric `fred_api_requests_total`; alert at 80% of daily limit.
- Set a `FRED_API_KEY` env var (FRED provides free keys with higher limits).

---

### 1.3 Medium-Priority Issues (should address before public launch)

---

#### 🔶 MED-01 — `sig` field HMAC caveat not in user-facing copy

The reveal-once UX for the webhook secret doesn't tell users *where* to put the sig field in their TradingView alert template. The Copy TradingView Alert Template button should enforce a specific field ordering (sig as last key) and display an explicit warning if the user reorders fields in the editor.

---

#### 🔶 MED-02 — No email rate-limit budget specified for Resend

With 50 users, common flows (register, password reset, MFA alerts, kill-switch notifications, backtest completion) can generate hundreds of emails/day. Resend's free tier (100/day) will be exhausted immediately after launch. Budget the Starter plan ($20/mo, 50k/mo) from day 1.

---

#### 🔶 MED-03 — Backtest resource caps not enforced in M09

M09 mentions "per-user concurrent limit of 2" but doesn't define a CPU/wall-clock hard cap. A user running a 10-year sweep with a dense parameter grid on 5 symbols could consume the backtest worker for hours, starving other users.

**Fix:** Add `BacktestRun.cpu_seconds_budget` (default 1800s = 30 min). A Celery soft-time-limit raises a recoverable `SoftTimeLimitExceeded`; hard limit at 1900s. On breach, mark run `TIMEOUT`, clean up, notify user.

---

#### 🔶 MED-04 — No database transaction isolation specified for critical paths

For order creation, kill-switch state write, and daily-loss check, the plan doesn't specify isolation level. PostgreSQL defaults to `READ COMMITTED`, which can cause anomalies under concurrent writes.

**Fix:** Specify `SERIALIZABLE` for the daily-loss watcher and kill-switch toggle; use `SELECT FOR UPDATE` on the kill-switch state row to prevent concurrent toggles.

---

#### 🔶 MED-05 — No mention of how IBKR / TradeStation ToS restricts automated trading via third parties

Both IBKR and TradeStation have Terms of Service that restrict sharing API credentials with third-party services and rules around automated order submission. The current plan has users enter their API credentials into StratTraderPro, which may or may not be permitted under those ToS.

**Fix:** Before v0.2 live-trading launch, get legal opinion on whether our credential-storage model is permissible. Alternatively, explore IBKR's official third-party integration programme and TradeStation's partner programme. Add to the legal open-items list.

---

#### 🔶 MED-06 — Missing: Subscription feature gating across the codebase

Without a billing system, the plan has no description of what happens when a user exceeds limits: how many strategies, webhooks, brokers, and backtests are allowed per plan. This means any free-tier user can use all features indefinitely.

**Fix:** Define the feature gate matrix in the business model section (see Part 3), then add a `PlanEnforcer` middleware that checks limits on every relevant endpoint write. Return 402 with an upgrade CTA link when limits are exceeded.

---

#### 🔶 MED-07 — IB Gateway (CPAPI) sessions expire and need re-authentication

Even with the CPAPI fix (CRITICAL-01), IBKR CPAPI sessions expire after ~24 hours and require re-authentication via browser (the user must click a link). This will interrupt overnight trading. Plan needs a re-auth notification flow.

**Fix:** Monitor session expiry in the adapter; send a push notification (email + in-app banner) 2 hours before expiry with a one-click re-auth link; on expiry, set per-user kill switch L1 to prevent stale orders from being submitted on a dead session.

---

#### 🔶 MED-08 — Missing: Notification system (in-app + push)

The plan mentions email-only notifications. For a trading bot, critical events (kill switch fired, position flatttened, daily loss breach, broker disconnected) need to be surfaced *immediately*. Email is too slow.

**Fix:** Add a `Notification` model and a multi-channel delivery system by M10:
- **In-app:** WebSocket push + notification bell on dashboard.
- **Email:** Resend transactional.
- **Telegram bot (optional):** One-click setup in settings; a personal bot token approach is cheap and reliable for solo operators. High user demand for this feature based on competitor research.
- Budget a small Notification service (or use a Celery task + channel routing).

---

#### 🔶 MED-09 — Sizing algorithm exposes strategy fill rates to the sizing module without privacy controls

The Kelly damper reads `TradeHistory.objects.filter(strategy=alert.strategy).count()`. For system strategies, this aggregates across all users' trades — a user's sizing is influenced by other users' trading of the same strategy. This could be seen as a privacy issue or a market information leakage.

**Fix:** Kelly damper uses only the requesting user's own trade history: `filter(strategy=alert.strategy, user=user)`.

---

#### 🔶 MED-10 — No dead-letter queue strategy for failed webhook tasks

The plan mentions `autoretry_for` + `max_retries` but doesn't specify what happens to tasks that exhaust retries. They'll silently disappear from the queue.

**Fix:** Configure a Dead Letter Queue in Redis (or use a `FailedTask` DB table) for tasks that exhaust retries. Emit a Sentry alert + audit log entry for any dead-lettered order task. User sees a "Failed to process alert" notification.

---

### 1.4 Minor Improvements

| # | Issue | Suggested Fix |
|---|-------|---------------|
| MIN-01 | `strategy_file.content BYTEA` vs `object_url` — no clear rule on when to use each. | Use object storage for ALL files (even small ones) and always set `object_url`. Remove the `content BYTEA` column. DB stores metadata + URL only. Consistent, avoids the dual-path complexity. |
| MIN-02 | No mention of how the frontend handles expired access tokens *while the user is mid-form* (e.g., editing risk profile). | Add a token-expiry overlay (not a redirect) that says "Session expires soon, continue?" with a one-click refresh button. |
| MIN-03 | Dashboard route `/dashboard` is the default landing, but post-login the user is redirected to `/dashboard`. Consider a state-aware landing: if no broker connected, land on `/settings/brokers` with a wizard. | Add an `onboarding state machine` that tracks setup completion and routes new users through broker connection before showing the dashboard. |
| MIN-04 | M01 uses `djangorestframework-simplejwt` but M03 uses `drf-spectacular` for OpenAPI. Neither milestone calls out that `simplejwt` requires a `drf-spectacular` extension (`drf-spectacular[sidecar]`) to document auth endpoints correctly. | Add `drf-spectacular[jwt]` to M01 tech stack notes. |
| MIN-05 | Celery beat schedule runs `marketdata.sync_bars_intraday` every 1 min during market hours but doesn't define "market hours" explicitly. Pre/post market? Weekends? | Define a `is_market_hours()` utility function that accounts for US market hours (9:30–16:00 ET Mon–Fri, excluding NYSE holidays). Use a `trading_calendars` library (`exchange_calendars`) which has NYSE/NASDAQ calendar support. |
| MIN-06 | HMM uses 4 states but the naming (`BULL/CHOP/BEAR/CRISIS`) is assigned *post-hoc* based on mean feature inspection. If the HMM learns a different cluster structure after retraining, the labels flip silently. | Add a `state_labeling_check` step that asserts the learned states satisfy expected feature orderings (e.g., BULL state must have `pct_above_200sma` > BEAR state). Alert if the assignment flips. |
| MIN-07 | The `backtest` worker is on a shared queue `backtest` but nothing prevents a very large task from blocking smaller ones. | Use task priority: `celery_queues['backtest'] = Queue('backtest', routing_key='backtest', queue_arguments={'x-max-priority': 10})`. Small params grids get priority 8; large ones get priority 3. |
| MIN-08 | No mention of how to handle a user who connects the same IBKR account from two StratTraderPro accounts. | Add a constraint: a `(broker, account_id)` pair is unique per platform, not per user. Attempting to connect the same account_id twice shows an error. |

---

## Part 2 — Monthly Cost Analysis

All prices are approximate 2026 figures. Costs are per environment (staging and production are separate Railway projects).

### 2.1 Railway Infrastructure (Production)

Railway charges are usage-based (RAM × GB + CPU × vCPU-hours). Estimates below assume the minimum adequate sizing for 10–50 users.

| Service | Min RAM | Min vCPU | Est. monthly cost |
|---------|---------|----------|-------------------|
| `backend` (Django, 1 replica autoscale to 3) | 512 MB | 0.5 | $12–$30 |
| `worker` (Celery, 2 replicas) | 512 MB × 2 | 0.5 × 2 | $20–$30 |
| `beat` (Redbeat, 1 replica) | 256 MB | 0.25 | $4 |
| `llm-worker` (FinBERT + Llama CPU, **the expensive one**) | 8 GB | 4 | $60–$90 |
| `frontend` (nginx, 1 replica) | 128 MB | 0.25 | $3 |
| Postgres 16 (Railway plugin) | 1 GB RAM, 10 GB storage | — | $15–$25 |
| Redis 7 (Railway plugin) | 256 MB | — | $7 |
| PgBouncer (7th service) | 128 MB | 0.25 | $3 |
| **Railway Subtotal** | | | **$124–$192/mo** |

**Staging** (smaller sizing, llm-worker optional on staging): ~$50–$70/mo.

**Railway total (prod + staging): ~$175–$262/mo**

> Note: Railway bills usage-based from their $20 Pro plan credits. These estimates assume no auto-scaling events; peak traffic bursts add ~$10–20/mo in practice.

---

### 2.2 External Services (Production)

| Service | Purpose | Plan | Monthly cost |
|---------|---------|------|-------------|
| FinancialModelingPrep | Market data + news (bars, quotes, news endpoint) | Business/Enterprise plan required for intraday + news | $49–$199/mo |
| Cloudflare | WAF, CDN, DDoS, DNS | Pro plan (WAF rules) | $20/mo |
| Sentry | Error tracking (backend + frontend) | Team plan (50k errors/mo) | $26/mo |
| Grafana Cloud | Metrics + logs + traces | Free tier (10k series, 14d retention) | $0 (free tier sufficient early) |
| Resend | Transactional email | Starter (50k emails/mo) | $20/mo |
| Cloudflare R2 | Backtest PDFs + strategy files | ~10 GB storage + operations | ~$2–$5/mo |
| GitHub Actions | CI (beyond free 2,000 min/mo) | ~3,000 min/mo for dual pipeline | $8/mo |
| ngrok (dev) | Local dev tunnels for webhook testing | Personal plan (reserved subdomains) | $10/mo |
| Better Stack / UptimeRobot | External uptime monitor | Free tier | $0 |
| vectorbt Pro licence | Commercial licence to avoid AGPL compliance issue | One-time or annual | ~$50–$150/mo (annualised) |
| **External Subtotal** | | | **$185–$438/mo** |

> FMP plan range is the biggest variable. The $49/mo "Growth" plan covers daily bars and limited intraday. For 1-min bars + news + sector you likely need the $179–$199/mo plan. Start at Growth and upgrade when needed.

---

### 2.3 Total Monthly Operating Cost

| Scale | Railway infra | External services | **Total** |
|-------|--------------|-------------------|-----------|
| Pre-launch / 0 users | $175 | $185 | **$360/mo** |
| 10 users | $200 | $210 | **$410/mo** |
| 50 users | $265 | $240 | **$505/mo** |
| 100 users | $380 | $270 | **$650/mo** |
| 250 users (needs DB scale) | $600 | $310 | **$910/mo** |

These costs exclude developer time (solo dev) and legal/accounting costs.

### 2.4 Break-Even Analysis

| Tier | Monthly subscribers needed to break even (infra only) |
|------|--------------------------------------------------------|
| $49/mo product price | 8–9 paying subscribers cover infra at 0 users scale |
| At 50 users (50% paying = 25 subs) | 25 × $49 = $1,225 MRR → profitable after infra (~$500/mo profit) |
| Target MRR for comfortable solo operation | 50 paying subscribers × $59 avg = $2,950/mo |
| Sustainable full-time income threshold | 150 paying subscribers × $65 avg = ~$9,750/mo |

**Key insight:** With the proposed pricing, you need ~100–150 paying users to generate a meaningful full-time revenue. The infrastructure is lean enough to get there without external investment. FMP is your biggest variable cost lever.

---

### 2.5 Cost Optimisation Tips

1. **Defer FMP upgrade** — Start on the $49/mo Growth plan; fall back to `yfinance` for non-critical daily bars. Only upgrade when intraday precision is needed for live users.
2. **LLM worker CPU tuning** — The Llama 3.1-8B Q4_K_M can be replaced by **Llama 3.2-3B-Instruct** (much smaller, acceptable for headline sentiment) to halve the LLM worker RAM to 4 GB → saves ~$30/mo.
3. **Grafana Cloud** — The free tier is generous. Only upgrade when you exceed 10k Prometheus series, which won't happen until 100+ active users.
4. **Batch regime + sentiment** — Computing features every 5 min is expensive in CPU-time. Coarsen to every 15 min for the HMM decode; keep 5-min for the rule-based score only. This halves the worker CPU allocation.
5. **R2 vs S3** — Cloudflare R2 has no egress fees. Stay on R2; it saves ~$10–30/mo vs AWS S3 once PDFs accumulate.

---

## Part 3 — Business Model & Pricing Recommendation

### 3.1 Competitive Landscape Summary

Based on research of the 2026 trading bot SaaS market:

| Platform | Main price point | Free tier | Annual discount |
|----------|-----------------|-----------|-----------------|
| TradersPost | $49/mo | No (7-day trial) | Not standard |
| Composer | $40/mo | No (14-day trial) | 20% |
| 3Commas | $37–$99/mo | No (7-day trial) | 25–30% |
| WunderTrading | Free + paid $5–$90/mo | Yes (limited) | Standard |
| Zignaly | Free + 30% profit share | Yes | N/A |
| Vestinda | Tiered pricing | 14-day trial | Standard |

Key insight: **StratTraderPro has materially superior features** (HMM regime, AI sentiment, walk-forward backtesting with PBO, four-level kill switch, multi-broker) versus all of the above. Pricing above $49/mo is justified — but not by too much, since the market anchor is $49.

---

### 3.2 The Problem with Your Proposed Model

| Your proposal | Issue |
|---|---|
| 7-day free trial | Too short for algo trading. Users need 1–2 weeks to set up TradingView alerts, backtest, and see meaningful paper-trading results. 7 days is the fastest competitors go; 14 days converts significantly better. |
| $49/mo single tier | Leaves money on table from power users who would pay $79–129 for unlimited features. Single tier also means no upsell path. |
| 20% annual discount | Below the market standard of 25–30%. At 20% you give away only $117/year vs the $147–177 that 25–30% would give. The annual discount matters more as a churn-reduction tool than as a revenue driver — go to 25% to get users on annual plans. |
| No free tier | A free paper-only tier dramatically widens your top-of-funnel. Competitors with free tiers convert at 3–5× the rate of trial-only competitors. |

---

### 3.3 Recommended Pricing Model: Three Tiers + Freemium

#### 🆓 Free — "Paper Pilot"

**$0/month forever. No credit card required.**

Designed for: discovering the platform, building confidence in paper trading.

| Feature | Limit |
|---------|-------|
| Trading mode | Paper only (never live) |
| System strategies | 3 (read-only, pre-selected by us) |
| User-uploaded strategies | 0 |
| Broker connections | 1 (paper/simulator only) |
| Webhook alerts/day | 10 |
| Walk-forward backtests | 1 per day, max 1-year history, 1 symbol |
| Regime badge | ✅ current only (no history) |
| Sentiment | ✅ market-wide only (no per-symbol) |
| Kill switch | ✅ per-user global only |
| Risk profile | ✅ basic (no Kelly, no sentiment sizing) |
| Support | Community Discord |
| Data retention | 30 days |

**Why this works:** Paper-only means zero regulatory and financial risk. Users set up TradingView, try strategies, and hit the webhook limit within a week. Upgrade CTA is triggered naturally. Free users are also your word-of-mouth engine in trader communities.

---

#### 📈 Trader — "Live Ready"

**$69/month | $52/month billed annually ($624/year) — saves 25%**

14-day free trial. No credit card required for trial.

Designed for: individual active traders automating 1–3 strategies live.

| Feature | Limit |
|---------|-------|
| Trading mode | Paper + **Live** |
| System strategies | All (full catalogue) |
| User-uploaded strategies | 5 |
| Broker connections | 2 (any combination of IBKR, TradeStation) |
| Webhook alerts/day | 200 |
| Walk-forward backtests | 3 simultaneous, 5-year history, 5 symbols |
| Regime badge | ✅ full history (90 days) |
| Sentiment | ✅ market + per-symbol (S&P 1500) |
| Kill switch | ✅ all 4 levels |
| Risk profile | ✅ full (Kelly, sentiment sizing, soft/hard stop) |
| Sizing algorithm | ✅ full (regime-scaled, ATR, sentiment) |
| Notifications | Email + in-app |
| Support | Email (48h SLA) |
| Data retention | 1 year |

**Why $69 not $49:** You have features that TradersPost ($49) doesn't have at all — HMM regime, AI sentiment, walk-forward PBO, four-level kill switches. $69 is a ~40% premium that's defensible on features. Users who trade live are spending real money and will pay for a more sophisticated tool.

---

#### 🚀 Pro — "Full Automation"

**$129/month | $97/month billed annually ($1,164/year) — saves 25%**

14-day free trial. Card required.

Designed for: serious traders and small prop accounts running multiple strategies across multiple brokers.

| Feature | Limit |
|---------|-------|
| Everything in Trader, plus: | |
| User-uploaded strategies | Unlimited |
| Broker connections | Unlimited (all supported brokers) |
| Webhook alerts/day | Unlimited |
| Walk-forward backtests | 10 simultaneous, full history, unlimited symbols |
| Backtest report retention | 1 year |
| Regime badge | ✅ 2-year history + per-symbol regime |
| Sentiment | ✅ enhanced (Tier 2 Llama reports, impact scores, news archive) |
| Strategy auto-selector | ✅ ("Auto" mode — system selects best strategy by current regime) |
| Telegram/Discord alerts | ✅ real-time push |
| API access | ✅ read-only REST API (positions, fills, regime, sentiment) |
| Priority webhook execution | ✅ front-of-queue |
| Priority support | 24h SLA |
| Data retention | 3 years |
| Early access | ✅ (new brokers, new strategies) |

**Why $129:** $129 is the Goldilocks point for power users. It's comparable to 3Commas Expert ($99) but our feature set justifies the premium. The unlimited webhook alerts are the key unlock — a serious multi-strategy trader can easily run 500+ alerts/day on TradingView.

---

#### 🏢 Studio — Enterprise (Custom, post-v0.2)

Designed for: prop firms, family offices, hedge fund managers.

- Custom contract / per-seat.
- White-label option (your domain, your branding).
- Dedicated infra (isolated DB + workers).
- Custom strategy integration (we write the Python adapter).
- SLA: 4h response, 99.9% uptime.
- Compliance packaging: audit export, SOC 2 readiness.

**Target price:** $500–$2,000/month depending on users + assets under automation.

---

### 3.4 Feature Gate Matrix

| Feature | Free | Trader | Pro |
|---------|------|--------|-----|
| Paper trading | ✅ | ✅ | ✅ |
| Live trading | ❌ | ✅ | ✅ |
| System strategies | 3 | All | All |
| User-uploaded strategies | 0 | 5 | Unlimited |
| Broker connections | 1 (paper) | 2 | Unlimited |
| Webhook alerts/day | 10 | 200 | Unlimited |
| Regime (history) | Current only | 90d | 2y + per-symbol |
| Sentiment | Market only | Market + symbol | Enhanced (Llama reports) |
| Sizing algorithm | Basic | Full | Full + Kelly |
| Kill switches | L1 only | All 4 | All 4 + Platform |
| Walk-forward backtest | 1/day, 1y, 1 symbol | 3, 5y, 5 symbols | 10, full, unlimited |
| API access | ❌ | ❌ | ✅ |
| Telegram/Discord alerts | ❌ | ❌ | ✅ |
| Auto strategy selector | ❌ | ❌ | ✅ |
| Data retention | 30d | 1y | 3y |
| Support | Community | Email 48h | Priority 24h |

---

### 3.5 Revenue Projections

Assumptions: 5% monthly churn, 8% free-to-paid conversion, 40/50/10 split across Trader/Pro/Free paying.

| Month | Free users | Paying users | Trader | Pro | Est. MRR |
|-------|-----------|-------------|--------|-----|---------|
| 1 (beta) | 5 | 0 | 0 | 0 | $0 |
| 3 | 30 | 5 | 3 | 2 | $465 |
| 6 | 100 | 20 | 12 | 8 | $1,860 |
| 9 | 250 | 50 | 30 | 20 | $4,680 |
| 12 | 500 | 110 | 65 | 45 | $10,340 |
| 18 | 1,200 | 280 | 165 | 115 | $26,310 |

Break-even on infrastructure: ~month 4–5 (25 paying users).
**Full-time sustainable revenue (>$10k MRR): month 12.**

---

### 3.6 Annual Plan Mechanics

Annual plan discount: **25%** (vs your proposed 20%).

Mechanics:
- Billed upfront; Stripe subscription with annual interval.
- Annual subs reduce churn dramatically (3–6% monthly → 0.5–1% monthly for annual).
- Stripe checkout shows "Save $207/year" callout (Pro) and "Save $204/year" (Trader) — concrete dollar savings are more compelling than percentages.
- Allow annual → monthly downgrade at renewal only; no mid-cycle downgrade (customer keeps access to year end).

---

### 3.7 Additional Revenue Levers (post-v0.2)

| Lever | Mechanism | Est. uplift |
|-------|-----------|-------------|
| **Strategy Marketplace** | Community-tested strategies listed; authors earn 20% of plan upgrade attributed to their strategy. | Acquisition + retention |
| **Managed Backtesting** | User pays $19 per ad-hoc backtest beyond their plan quota | $500–$2k MRR at scale |
| **Affiliate Programme** | $50 one-time bonus per referred annual subscriber | Acquisition |
| **Broker Referral** | Revenue share agreements with IBKR and TradeStation for new account referrals | $50–$200 per referred activated account |
| **Data exports** | $9.99 one-time fee for extended strategy + trade data exports (beyond plan retention) | Low friction upsell |

---

### 3.8 Positioning & Messaging Recommendation

Most competitors position as "easy automation for crypto." StratTraderPro's differentiators are:

1. **Regime awareness** — "The only trading bot that knows if the market is in a bull, bear, or crisis regime before placing your order."
2. **AI sentiment filter** — "Reads the news so your bot doesn't trade into a disaster."
3. **Walk-forward backtesting** — "Know if your edge is real or overfitted before risking capital."
4. **Four-level risk engine** — "Institutional-grade risk controls for retail traders."

Target copywriting angle: **"Systematic edge, institutional safety net."**

Homepage hero: *"Your TradingView strategies, automated — with an AI layer that knows when not to trade."*

---

### 3.9 Go-to-Market Channels (cost-efficient for solo founder)

| Channel | Effort | Expected outcome |
|---------|--------|-----------------|
| TradingView community forums + Pine Script community | Low | High — your core user is already there, looking for automation |
| r/algotrading, r/trading subreddits | Low | Moderate — educational posts drive signups |
| YouTube tutorials (set up TV alert → StratTraderPro) | High (upfront) | High (compounding) — evergreen content |
| X/Twitter trader community (post regime charts + sentiment snaps) | Medium | Moderate — builds credibility |
| Product Hunt launch | One-time | Burst of 50–200 signups for paper tier |
| TradingView App Store (if applicable) | Research needed | Potentially very high — direct access to TV user base |

---

## Part 4 — Summary Scorecard

### Plan health

| Category | Rating | Notes |
|----------|--------|-------|
| Architecture completeness | 8/10 | Strong, with IBKR Gateway and multi-user broker session being the main gap |
| Security posture | 9/10 | Well thought out; fix pickle models |
| Compliance readiness | 6/10 | Risk R8 needs more action; CFTC CTA question not sufficiently addressed |
| Test coverage design | 9/10 | Excellent pyramid; chaos drills are a highlight |
| Observability | 9/10 | Comprehensive; Redbeat recommendation strengthens this |
| Timeline realism | 7/10 | Solo developer doing 13 weeks with Llama deployment + 2 broker integrations + HMM is aggressive |
| **Missing: Billing system** | ❌ | Needs a new milestone or expansion of M03 |
| i18n readiness | 9/10 | Excellent scaffolding |
| Cost management | 7/10 | FMP is a wildcard; LLM worker is the biggest fixed cost |

### Top 5 actions before writing code

1. **Add a billing milestone** (Stripe integration) before M04.
2. **Switch IBKR to CPAPI** and update ADR-040.
3. **Resolve vectorbt licence** (buy commercial or replace).
4. **Rename `order` table** to `trade_order` everywhere.
5. **Secure legal opinion** on CTA registration risk before live trading (not just EULA).

---

_End of analysis._
