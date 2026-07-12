# Chaos drill logs (M11 §7.5)

Last reviewed: 2026-07-12

Scripts: `scripts/chaos/` (each prints `[ASSERT]`/`[PASS]`/`[FAIL]` and exits
non-zero on failure). The five stop/kill/restart drills **run on a DEDICATED
throwaway stack, never the shared dev stack** (`_lib.sh` refuses
`PROJECT=strattraderpro`); the role-removal drill is non-destructive and was run
here. See `scripts/chaos/README.md` for the dedicated-stack setup + prerequisites
(Redis cache backend, seeded fixtures, FakeBrokerAdapter seam).

Status summary: **scripts delivered for all six; Day-6 executed here; Days 1–5
execute on a dedicated stack.**

---

## Day 1 — Redis kill (→ AC-11-5) · `redis-kill.sh`

**Procedure:** fire a repeated `idempotency_key`, `docker compose kill redis` for
~90s, restart, wait ≤60s for Celery to reconnect.

**Assertions:**
- Celery reconnects within 60s of Redis returning (`celery inspect ping`).
- The repeated `idempotency_key` yields **exactly one** order across pre-outage,
  mid-outage and post-recovery fires (at-most-once via the SETNX guard + Alpaca
  `client_order_id`).
- **No orphaned** orders left in `PENDING_SUBMIT` after the queue drains.

**Status:** script delivered; run on a dedicated stack. During the outage the
webhook path 5xx's on task dispatch (expected) — the guarantee is about NOT
double-processing on recovery.

---

## Day 2 — Worker kill mid-flatten · `worker-kill.sh`

**Procedure:** enqueue L1 flattens for ~10 users, `docker kill` the worker
mid-flight, let `restart: on-failure` bring it back, wait for redelivery.

**Assertions:**
- **No duplicate orders** — the global invariant
  `count(*) - count(DISTINCT client_order_id) = 0` on `orders_order` (a
  redelivered task cannot mint a second order for the same anchor).
- Flatten is idempotent on redelivery (re-flattening an already-flat position is
  a no-op; `risk_event{type=FLATTEN}` does not run away).

**Status:** script delivered; run on a dedicated stack.

---

## Day 3 — `run_broker_streams` kill (→ AC-11-6) · `streams-kill.sh`

**Procedure:** seed a fresh heartbeat, `docker compose stop streams`, poll the
broker status.

**Assertions:**
- `get_stream_status` flips to **DEGRADED** within `BROKER_STREAM_HEARTBEAT_TTL`
  (45s) + margin → **≤ 60s**.
- **L1 flatten still works via the REST path** (`flatten_user`) while the stream
  is down — it uses the synchronous adapter `flatten_all`, independent of the
  fill stream.
- On restart, a replayed `broker_exec_id` is **deduped** —
  `Fill.get_or_create(broker_account, broker_exec_id)` inserts one row, and the
  global invariant `no duplicate (broker_account, broker_exec_id)` holds.

**Prereq:** a Redis (not LocMem) cache so the streams and web processes share the
`broker:hb:{id}` heartbeat key. **Status:** script delivered; run on a dedicated
stack.

---

## Day 4 — Alpaca REST 5xx storm · `alpaca-5xx-storm.sh`

**Procedure:** run the worker with a fake adapter whose `place_order` raises
`BrokerError(UNAVAILABLE)` (`STP_LOADTEST_FAKE_5XX`), fire the same
`idempotency_key` 5×.

**Assertions:**
- **Bounded** — `process_alert` (`max_retries=0`) rejects on `BrokerError`
  rather than entering a retry storm; the order lands `REJECTED`.
- **No duplicate** orders for the key under the storm.

**Status:** script delivered; run on a dedicated stack. (TradeStation retry code
is covered by a separate adapter unit test — flag OFF, no live traffic, §4.7.)

---

## Day 5 — DB restart / failover · `db-restart.sh`

**Procedure:** `docker compose restart postgres`; measure DB downtime and app
reconnect time.

**Assertions:**
- The app reconnects on its own within budget (fresh connection → `SELECT 1`).
- Downtime + reconnect windows recorded.

**Status:** script delivered; local run on a dedicated stack. The Railway managed
failover measurement is **[LIVE]**.

---

## Day 6 — Role-removal drill (→ AC-11-14) · `role-removal.sh` — **EXECUTED**

The drill that would have caught **BUG-011** (a blank Railway start command
silently ran gunicorn in `celery-worker`/`celery-beat` for two months). It
`docker run`s the built backend image with `SERVICE_ROLE` blank and bogus — a
non-destructive check (throwaway containers only), so it was run here against the
shared build.

**Assertions (both cases):** container **exits non-zero**, prints the **loud
FATAL message** naming `SERVICE_ROLE`, and **never** starts a web server.

**Captured run (2026-07-12, image `strattraderpro-backend`):**

```
[chaos] backend image under test: strattraderpro-backend
[chaos] case: SERVICE_ROLE blank
    exit code: 1
      | entrypoint: FATAL: SERVICE_ROLE is unset. Refusing to guess a role.
      | entrypoint: set SERVICE_ROLE to one of: web web-dev worker worker-backtest beat streams ws
      | entrypoint: (a blank or wrong value must NOT silently become a web server — see BUG-011)
[PASS]  [SERVICE_ROLE blank] exited non-zero (1)
[PASS]  [SERVICE_ROLE blank] printed the loud FATAL message naming SERVICE_ROLE
[PASS]  [SERVICE_ROLE blank] no web-server banner — it crashed instead of serving HTTP
[chaos] case: SERVICE_ROLE bogus
    exit code: 1
      | entrypoint: FATAL: unrecognised SERVICE_ROLE='frobnicate'.
      | entrypoint: set SERVICE_ROLE to one of: web web-dev worker worker-backtest beat streams ws
      | entrypoint: (a blank or wrong value must NOT silently become a web server — see BUG-011)
[PASS]  [SERVICE_ROLE bogus] exited non-zero (1)
[PASS]  [SERVICE_ROLE bogus] printed the loud FATAL message naming SERVICE_ROLE
[PASS]  [SERVICE_ROLE bogus] no web-server banner — it crashed instead of serving HTTP

[chaos] DRILL PASS — a blank or wrong SERVICE_ROLE crashes loudly and never serves HTTP
```

**Result: PASS.** On a real compose service the four Celery/streams services
carry `restart: on-failure`, so an unset role **crash-loops** rather than sitting
`exited` — assert on `docker inspect -f '{{.State.ExitCode}}'` + the loud log
line (as this drill does), not on `docker compose ps` status text.
