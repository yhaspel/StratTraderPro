# Load-test results (M11 §7.4 → AC-11-3, AC-11-4)

Last reviewed: 2026-07-14 — **AC-11-3 and AC-11-4 EXECUTED and PASSING** (see
"MEASURED RESULTS" below).

Harness: **Locust** under `backend/loadtest/`, run against **local docker-compose
with `FakeBrokerAdapter`** (frozen decision §4.1 — real Alpaca paper caps at
~200 req/min and cannot absorb 20 orders/sec).

## Scenarios

| # | Class / runner | Target | Measures |
|---|---|---|---|
| A | `WsDashboardUser` (`locustfile.py`) | 100 WS dashboards on `ws://…:8788/ws/dashboard/?token=<jwt>` | connect latency, event flow, **reconnect rate** |
| B | `WebhookUser` (`locustfile.py`) | 20 webhooks/sec → `POST /hooks/v1/{user}/{strategy}/`, 70/20/10 stock/ETF/option, unique `idempotency_key` | ingest p50/p95/p99; **no 5xx** |
| C | `flatten_50.py` (primary) + `FlattenUser` (HTTP variant) | 50-user simultaneous **L1** halt+flatten | flatten p50/p95/**p99** |

## AC targets

- **AC-11-3:** 100 WS + 20 rps sustained 10 min; **no 5xx**; p95 ingest→submit ≤ 1.5s.
- **AC-11-4:** 50-user L1 flatten — all submitted within 10s; **p99 ≤ 8s** (per-user ≤5s p99, AC-08-8).

## The `FakeBrokerAdapter` seam (READ THIS FIRST)

`apps.brokers.services.build_adapter` only knows `ALPACA` and `TRADESTATION` —
there is **no runtime seam** to route webhook-driven orders to the deterministic
in-memory `FakeBrokerAdapter`. The harness ships one that requires **zero edits
to tracked app/config code** (`backend/loadtest/fake_broker_patch.py` +
`sitecustomize.py`). Activate it on a **dedicated** stack by setting on the
`backend`, `worker` and `streams` services:

```yaml
environment:
  STP_LOADTEST_FAKE_BROKER: "1"
  PYTHONPATH: "/app/loadtest"
```

`sitecustomize.py` wraps Django's `Apps.populate` so `build_adapter` is rebound
to `FakeBrokerAdapter` the instant the app registry is ready, in every process
(gunicorn/daphne/celery/manage.py). The server-side runner `flatten_50.py` calls
the patch directly, so it needs only the env, not `sitecustomize`.

> The one-line production alternative M11's app owner may prefer instead is an
> env branch at the top of `build_adapter`:
> ```python
> if os.environ.get("BROKER_FORCE_FAKE") == "1":
>     from apps.brokers.base import BrokerContext
>     from apps.brokers.fake import FakeBrokerAdapter
>     return FakeBrokerAdapter(BrokerContext(account_id=str(account.id), user_id=str(account.user_id)))
> ```
> That change lives in `backend/apps/` (outside this harness's write scope); the
> zero-touch `sitecustomize` seam above is the delivered mechanism.

**Never enable the seam on the shared dev stack** — it changes order execution
globally.

## How to run the full test (dedicated stack)

```bash
export PROJECT=stp-load
docker compose -p "$PROJECT" up -d --build      # dedicated stack; seam env set on backend/worker/streams

# 1. seed 100 users + strategies + webhook configs + fake broker accounts
docker compose -p "$PROJECT" exec -T backend \
  env STP_LOADTEST_FAKE_BROKER=1 PYTHONPATH=/app/loadtest \
  python /app/loadtest/seed.py --count 100 --with-broker
#    -> writes backend/loadtest/fixtures.json (access tokens ~15 min TTL — run promptly)

# 2. install the harness on the host
python -m venv /tmp/lt && /tmp/lt/bin/pip install -r backend/loadtest/requirements.txt

# 3a. 100 WS dashboards, 10 min
LT_FIXTURES=backend/loadtest/fixtures.json \
  /tmp/lt/bin/locust -f backend/loadtest/locustfile.py WsDashboardUser \
  --headless -u 100 -r 20 -t 10m --csv=ws

# 3b. 20 webhooks/sec, 10 min  (20 users × ~1 rps; fail on any 5xx)
LT_FIXTURES=backend/loadtest/fixtures.json LT_WEBHOOK_WAIT=1.0 \
  /tmp/lt/bin/locust -f backend/loadtest/locustfile.py WebhookUser \
  --headless -u 20 -r 20 -t 10m --exit-code-on-error 1 --csv=hooks

# 3c. 50-user simultaneous L1 flatten (server-side, deterministic)
docker compose -p "$PROJECT" exec -T backend \
  env STP_LOADTEST_FAKE_BROKER=1 STP_LOADTEST_FAKE_SEED_POSITION=1 PYTHONPATH=/app/loadtest \
  python /app/loadtest/flatten_50.py --users 50
```

## Capturing metrics during the run

- **Ingest p50/p95/p99 + no-5xx:** Locust client-side stats (WebhookUser marks
  any non-200/429 as a failure; `--exit-code-on-error 1` fails the run on a 5xx).
- **Ingest→submit (worker-side `ORDER_SUBMIT_LATENCY`):** the histogram is
  recorded in the WORKER process, exposed on `TASK_METRICS_PORT` (9101), not on
  the host. Scrape it from inside the network:
  `docker compose -p "$PROJECT" exec worker wget -qO- localhost:9101/metrics | grep order_submit_latency`.
- **`celery_queue_depth{queue}`** (M10 gauge, refreshed by beat every 30s): same
  worker `:9101/metrics`. Do **not** assert on `process_*`/`django_db_*` (disabled
  under multiproc gunicorn).
- **WS reconnect rate:** the `WS reconnect` / `WS connect` / `WS event` rows in
  the Locust summary + CSV.
- **Infra (DB/Redis):** the `postgres-exporter` (:9187) and `redis-exporter`
  (:9121) services already in compose — scrape during the run. Host-level
  CPU/IOPS on Railway remains [LIVE].

## MEASURED RESULTS — executed 2026-07-14 (dedicated `stp-load` stack)

Run on the operator's machine with Docker, on a throwaway `-p stp-load` stack
(shared `strattraderpro` stack stopped for the duration, restored after). The
FakeBrokerAdapter seam was active; `CACHES` was Redis (not LocMem — verified).

### AC-11-3 — sustained load (100 WS + ~19 webhooks/s, 10 min) → **PASS**

**⚠️ Run on a PROD-SHAPED backend, not the default dev stack.** The committed
default (`SERVICE_ROLE=web-dev` = Django `runserver` + `DEBUG=True`) **cannot**
carry 20 req/s — it caps at ~5 rps with webhook-accept p50 ≈ 2.7 s / p95 ≈ 8.8 s
and the Celery queue grows unbounded. That is a harness limitation, not a
platform defect: `runserver` is a dev server. AC-11-3 was therefore measured with
the backend as the gunicorn `web` role (`config.settings.loadtest`, `DEBUG=False`,
3 workers × 4 threads) and `fill_ingestor` isolated to the `backtest` queue
(`worker-backtest`) so a fill sweep can't starve `process_alert`. See
"Harness changes required to run this" below.

| Assertion | Target | Measured | Verdict |
|---|---|---|---|
| a. Zero 5xx | 0 | **0 failures** / 11,420 webhooks @ 19.07 rps (`--exit-code-on-error 1` → exit 0) | ✅ |
| b. p95 ingest→submit (`order_submit_latency_seconds`, worker :9101) | ≤ 1.5 s | **p50 25 ms · p95 47.5 ms · p99 49.5 ms** (n=5,720) | ✅ |
| c. `celery_queue_depth{queue}` returns to ~0 (no unbounded backlog) | ~0 | **0.0 for the entire 10 min**, and 0.0 at +30 s post-load (celery AND backtest queues) | ✅ |
| d. WS reconnect not pathological | — | **100 connects, 0 failures, 0 reconnect events, 37,134 events delivered** | ✅ |

Webhook client-side accept latency (gunicorn): p50 48 ms · p95 65 ms · p99 84 ms.
All 5,720 submitted orders reached `FILLED` (`fills_ingested_total` = 5,891 on
`worker-backtest`); the fill→position→WS path was exercised end-to-end. Host CPU
after the run was near-idle (backend 0.1%) — the prod-shaped stack had large
headroom at 19 rps. The submit rate (~9.5/s) is ~half the webhook rate because
the 50/50 buy/sell mix runs against flat fake accounts, so SELLs don't submit —
correct behaviour, not a loss.

### AC-11-4 — 50-user simultaneous L1 halt+flatten → **PASS** (also M13 §6 gate 2)

Server-side (`flatten_50.py`), so unaffected by the web-tier limitation above.

| Mode | wall (all submitted) | p50 | p95 | **p99** | max (per-user) |
|---|---|---|---|---|---|
| PAPER | 0.260 s | 0.148 s | 0.196 s | **0.200 s** | 0.200 s |
| **LIVE** (M13 gate 2) | 0.173 s | 0.110 s | 0.164 s | **0.169 s** | 0.169 s |

**Flatten p99 = 0.169–0.200 s → AC-11-4 (≤ 8 s) PASS *and* `docs/slo.md` (≤ 5 s)
PASS *and* AC-13-10 (≤ 5 s) PASS** — all three thresholds cleared with ~25×
margin. All 50 flatten orders submitted well within 10 s; per-user max 0.200 s ≤
the AC-08-8 5 s budget. **Threshold reconciliation:** the three sources disagree
(AC-11-4 says ≤ 8 s; `docs/slo.md` and AC-13-10 say ≤ 5 s). The measured p99 of
0.2 s meets the *tighter* 5 s number with huge margin, so **AC-11-4 should be
tightened from ≤ 8 s to ≤ 5 s** to match the published SLO — see
`project-plan/11-hardening-and-load-test.md` (which is itself internally
inconsistent: line 14 cites AC-08-8's ≤ 5 s while the AC-11-4 row cites ≤ 8 s).

#### M13 gate 2 — what the LIVE run proves, and what it does NOT

The LIVE run set the seeded `BrokerAccount.mode = LIVE` and confirmed the mode
plumbing end-to-end: `BrokerAccount.mode → BrokerContext.mode = "LIVE"`
(`is_paper = False`) reaches the adapter, and the kill-switch flatten SLO holds
under load in LIVE mode.

- ✅ Proves: the flatten latency SLO holds under load, and the M13 mode plumbing
  does **not** break the kill-switch path.
- ❌ Does **NOT** prove anything about Alpaca's live endpoint. `fake_broker_patch`
  replaces `build_adapter` wholesale, so `AlpacaAdapter` — and therefore its live
  gate and key validation — **never executes**. Nothing here touches a real
  broker, by design. **AC-13-10's wording ("against a LIVE account") is
  misleading and has been tightened** — see `project-plan/13-live-trading-switch.md`.

  (Fidelity note: `_build_fake` originally dropped `mode`, so a "LIVE" run would
  have silently carried the PAPER default and proven nothing. The seam was fixed
  to thread `mode=account.mode`, mirroring the real `build_adapter`.)

## Harness changes required to run this (the harness had never been run)

The committed harness could not actually produce these numbers as-shipped; the
following defects were fixed to run it (all default-off / load-test-scoped):

- **`locustfile.py`** — `WsDashboardUser` had **no `@task`**, so under Locust 2.34
  it raised "No tasks defined" and every WS user died instantly (the WS half of
  AC-11-3 silently never ran). Added a keep-alive task.
- **`backend/loadtest/fake_broker_patch.py`** — (1) thread `mode=account.mode`
  into `BrokerContext` (M13 gate-2 fidelity); (2) `StreamSupervisor._build_stream`
  instantiates the **real `AlpacaStream` directly** and is NOT covered by the
  `build_adapter` patch, so `run_broker_streams` stormed real Alpaca (429s, 380%
  CPU) — added an `IdleStream` neutralization; (3) implemented the
  `STP_LOADTEST_FAKE_5XX` hook the Day-4 drill documents but was never wired up.
- **`config/settings/dev.py`** — env-gated `STP_LOADTEST_REDIS_CACHE` (dev
  hard-coded LocMem, which would make the AC-11-5 SETNX idempotency assertion
  per-process and meaningless) and `STP_LOADTEST_FAST_HASH` (Argon2 costs ~4.5 s
  per seeded user → seeding outlives the 15-min token TTL).
- **`config/settings/loadtest.py`** (new) + `docker-compose.loadtest.yml` /
  `docker-compose.ac113.yml` — the prod-shaped web tier + fill-queue isolation.
- **`.gitignore`** — `backend/loadtest/fixtures.json` (per-user tokens + TOTP
  secrets) was **not** ignored; now is.

## How to reproduce

```bash
export PROJECT=stp-load
# stop the shared stack first if it publishes the same host ports
docker compose -p stp-load -f docker-compose.yml -f docker-compose.loadtest.yml \
  -f docker-compose.ac113.yml up -d --build \
  postgres redis backend worker worker-backtest beat ws postgres-exporter redis-exporter
docker compose -p stp-load exec -T backend \
  env STP_LOADTEST_FAKE_BROKER=1 PYTHONPATH=/app/loadtest STP_LOADTEST_FAST_HASH=1 \
  python /app/loadtest/seed.py --count 100 --with-broker
python -m venv /tmp/lt && /tmp/lt/bin/pip install -r backend/loadtest/requirements.txt
export LT_FIXTURES=backend/loadtest/fixtures.json
/tmp/lt/bin/locust -f backend/loadtest/locustfile.py WsDashboardUser --headless -u 100 -r 20 -t 10m &
/tmp/lt/bin/locust -f backend/loadtest/locustfile.py WebhookUser --headless -u 20 -r 20 -t 10m --exit-code-on-error 1
# AC-11-4 (server-side; run flatten_50 with accounts in PAPER then mode=LIVE):
docker compose -p stp-load exec -T backend \
  env STP_LOADTEST_FAKE_BROKER=1 STP_LOADTEST_FAKE_SEED_POSITION=1 PYTHONPATH=/app/loadtest \
  python /app/loadtest/flatten_50.py --users 50
```
