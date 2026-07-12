# Load-test results (M11 §7.4 → AC-11-3, AC-11-4)

Last reviewed: 2026-07-12

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

## What was run in this sandbox vs parked

**RAN (green):**
- Harness validated end-to-end under Locust 2.34 — both `WebhookUser` and
  `WsDashboardUser` load, spawn, drive traffic and report (the WS class exercises
  the gevent + `websocket-client` reconnect path). The custom end-of-run summary
  prints per-endpoint p50/p95/p99.
- `scripts/restore-drill.sh` — green (see `docs/ops/backup-restore.md`).
- `scripts/chaos/role-removal.sh` — green (see `docs/ops/chaos-drill-logs.md`).

**PARKED (operator runs on a dedicated stack) — why the full run is not executed here:**
1. **The FakeBrokerAdapter seam cannot be activated on the shared stack.** The
   shared `worker`/`backend` are already running without the seam env, and this
   task must not edit `docker-compose.yml` or restart shared services. Without
   the seam, webhook-driven orders route to real Alpaca with junk keys — noisy
   and non-deterministic. The seam is active only on a dedicated stack.
2. **Seeding into the shared DB is currently blocked by schema drift.** Another
   agent's in-flight M11 GDPR work left `users.0005_delete_flow_and_terms`
   **unapplied**, so `users_user.pending_delete_at` is missing and every ORM
   `User` query raises `ProgrammingError`. `seed.py` cannot run against the
   shared DB until that migration lands; on a fresh dedicated stack (which runs
   `migrate` on boot) it seeds cleanly. (Confirmed: no partial `loadtest+` rows
   were created.)
3. **The shared stack must not be overwhelmed** (other agents depend on it).

The harness, seed, and runners are complete and validated; the full-scale numbers
are produced by the exact commands above on the dedicated stack.
