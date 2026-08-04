# Load-test harness (M11 §7.4)

Locust harness for AC-11-3 (100 WS dashboards + 20 webhooks/sec) and AC-11-4
(50-user simultaneous L1 flatten), run against **local docker-compose with
`FakeBrokerAdapter`** (frozen decision §4.1).

## Files

| File | Purpose |
|---|---|
| `locustfile.py` | 3 scenarios: `WsDashboardUser`, `WebhookUser`, `FlattenUser` |
| `flatten_50.py` | server-side, deterministic 50-user L1 flatten measurement (AC-11-4) |
| `seed.py` | seed users + strategies + webhook configs + fake broker accounts; writes `fixtures.json` |
| `fake_broker_patch.py` | routes `build_adapter` → `FakeBrokerAdapter` (no app-code edit) |
| `sitecustomize.py` | auto-activates the seam on a dedicated stack via `Apps.populate` |
| `requirements.txt` | `locust`, `websocket-client`, `pyotp` |

`fixtures.json` is generated (contains per-user tokens + secrets) — do not commit
it; regenerate with `seed.py`.

## Quick start (dedicated stack)

```bash
export PROJECT=stp-load
docker compose -p "$PROJECT" up -d --build

# seed 100 users (fixtures.json lands in backend/loadtest/ via the bind mount)
docker compose -p "$PROJECT" exec -T backend \
  env STP_LOADTEST_FAKE_BROKER=1 PYTHONPATH=/app/loadtest \
  python /app/loadtest/seed.py --count 100 --with-broker

# host-side harness
python -m venv /tmp/lt && /tmp/lt/bin/pip install -r backend/loadtest/requirements.txt
export LT_FIXTURES=backend/loadtest/fixtures.json

/tmp/lt/bin/locust -f backend/loadtest/locustfile.py WsDashboardUser --headless -u 100 -r 20 -t 10m
/tmp/lt/bin/locust -f backend/loadtest/locustfile.py WebhookUser     --headless -u 20  -r 20 -t 10m --exit-code-on-error 1
docker compose -p "$PROJECT" exec -T backend \
  env STP_LOADTEST_FAKE_BROKER=1 STP_LOADTEST_FAKE_SEED_POSITION=1 PYTHONPATH=/app/loadtest \
  python /app/loadtest/flatten_50.py --users 50
```

## Seeding

`seed.py` (standalone Django script; run inside the backend container so
`FERNET_KEK`/`SECRET_KEY` and the DB host match the running stack):

```
--count N          number of users (default 100)
--prefix P         email namespace (default "loadtest+")   → loadtest+000@stp.local
--with-broker      seed a CONNECTED Alpaca paper account (default)
--no-broker        skip broker accounts (webhook-only; purges cleanly)
--purge            delete all matching users and exit
--base-url / --ws-url   written into fixtures.json for the host harness
```

Each user gets: verified account, verified `MFADevice` with a **known TOTP
secret** (so the L1 MFA step-up can be answered), a `Strategy`, a `WebhookConfig`
with a **known static `sig`**, an optional fake `BrokerAccount`, and a
freshly-minted access token (~15 min TTL — start the run promptly or re-seed).

`fixtures.json` shape:

```json
{ "base_url": "...", "ws_url": "...", "count": 100, "with_broker": true,
  "users": [ { "user_id": "...", "strategy_id": "...", "webhook_secret": "...",
               "totp_secret": "...", "access": "<jwt>", "email": "...", "password": "..." } ] }
```

## FakeBrokerAdapter seam

`build_adapter` has no built-in route to the fake adapter. The harness provides a
zero-touch monkeypatch (`fake_broker_patch.py`) activated by
`STP_LOADTEST_FAKE_BROKER=1` + `PYTHONPATH=/app/loadtest` on the
`backend`/`worker`/`streams` services of a **dedicated** stack. `sitecustomize.py`
applies it right after Django's app registry loads. `flatten_50.py` calls the
patch directly. **Never enable on the shared dev stack.** The equivalent
one-line production change (`BROKER_FORCE_FAKE`) is documented in
`docs/ops/load-test-results.md`.

## Env knobs (locustfile)

| Var | Meaning |
|---|---|
| `LT_FIXTURES` | path to `fixtures.json` (default: next to `locustfile.py`) |
| `LT_HOST` / `LT_WS_URL` | override the http / ws targets |
| `LT_WEBHOOK_WAIT` | seconds between a user's webhook posts (default 1.0 → ~1 rps/user) |
| `ENABLE_L1_FLATTEN=1` | arm the destructive `FlattenUser` REST scenario (off by default) |

## Metrics

- Ingest p50/p95/p99 + no-5xx: Locust client-side (WebhookUser fails on non-200/429).
- Ingest→submit (`ORDER_SUBMIT_LATENCY`) + `celery_queue_depth{queue}`: worker
  `:9101/metrics` (not host-published; scrape from inside the network).
- WS reconnect rate: the `WS connect`/`WS reconnect`/`WS event` rows.
- DB/Redis: `postgres-exporter` (:9187) / `redis-exporter` (:9121).
- Do **not** assert on `process_*`/`django_db_*` (disabled under multiproc gunicorn).
