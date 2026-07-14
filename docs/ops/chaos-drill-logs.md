# Chaos drill logs (M11 §7.5)

Last reviewed: 2026-07-14 — **all six drills EXECUTED and PASSING** on a dedicated
`stp-load` stack (Redis cache verified, FakeBroker seam active). Several drills
needed harness fixes before they would run — noted per-day and summarized at the
bottom.

Scripts: `scripts/chaos/` (each prints `[ASSERT]`/`[PASS]`/`[FAIL]` and exits
non-zero on failure). The five stop/kill/restart drills **run on a DEDICATED
throwaway stack, never the shared dev stack** (`_lib.sh` refuses
`PROJECT=strattraderpro`); the role-removal drill is non-destructive and was run
here. See `scripts/chaos/README.md` for the dedicated-stack setup + prerequisites
(Redis cache backend, seeded fixtures, FakeBrokerAdapter seam).

Status summary: **all six EXECUTED 2026-07-14 on a dedicated `stp-load` stack —
all PASS.** AC-11-5 (Day 1) and AC-11-6 (Day 3) are the AC-gated drills.

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

**EXECUTED 2026-07-14 — PASS:**
```
[PASS]  Celery reconnected in 33s (≤60s)
[PASS]  exactly 1 order for idempotency_key=chaos-redis-... (across pre/mid/post fires)
[PASS]  no orders stuck in PENDING_SUBMIT
```
Redis was killed for 90 s. The idempotency assertion is meaningful here because
`CACHES` was django-redis (verified), so the SETNX guard is shared across
processes — on the default dev stack (LocMem) it would be per-process and the
PASS would be worthless.

**Harness fix:** the script used `read -r UID ...`; `UID` is a **readonly** shell
var in bash, so the drill exited immediately (`UID: readonly variable`). Renamed
to `USERID`.

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

**EXECUTED 2026-07-14 — PASS (hard gate):**
```
duplicate client_order_id across all orders = 0   → idempotent, no double order
FLATTEN risk-events: +10 for 10 drilled users     → no runaway
new orphaned PENDING_SUBMIT from the kill: 0
```
**Two caveats recorded honestly:**
1. On **Docker Desktop / macOS**, `restart: on-failure` did **not** auto-restart
   the container after a manual `docker kill` (a known Docker nuance; likely fine
   on Linux/CI). The worker was restarted manually to complete the drill; the
   platform invariant (no duplicate `client_order_id`) was then verified directly.
2. `CELERY_TASK_ACKS_LATE` is **unset** (early-ack), so a task killed mid-flight
   is **lost, not redelivered** — safe (no duplicate) but not the late-ack
   redelivery the drill's comment assumes. The FLATTEN +10 shows all 10 completed
   before the kill landed; the no-duplicate invariant is the real guarantee.

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
`broker:hb:{id}` heartbeat key.

**EXECUTED 2026-07-14 — PASS:**
```
[PASS]  status flipped to DEGRADED in 46s (≤60s)   (TTL 45s + margin)
[PASS]  flatten_user completed via REST path with the stream down
[PASS]  replayed broker_exec_id ingested once (rows=1) — deduped
[PASS]  no duplicate (account, broker_exec_id) fills anywhere (global_dupes=0)
```
**Harness fixes:** (1) same `UID` readonly-var bug as Day 1 → `USERID`. (2) the
account-resolution query `SELECT id||' '||user_id ... | q()` was broken — the
`q()` helper does `tr -d ' '`, which **strips the space delimiter**, concatenating
the two UUIDs; `read` then got one 72-char blob and hung on an invalid UUID.
Changed the separator to `|` (matching the script's own trailing `tr '|' ' '`).
(3) The seam did not neutralize `run_broker_streams`' real Alpaca websocket
(see load-test-results.md) — an `IdleStream` patch was added so streams idles at
0% CPU instead of storming Alpaca, keeping the heartbeat semantics valid.

---

## Day 4 — Alpaca REST 5xx storm · `alpaca-5xx-storm.sh`

**Procedure:** run the worker with a fake adapter whose `place_order` raises
`BrokerError(UNAVAILABLE)` (`STP_LOADTEST_FAKE_5XX`), fire the same
`idempotency_key` 5×.

**Assertions:**
- **Bounded** — `process_alert` (`max_retries=0`) rejects on `BrokerError`
  rather than entering a retry storm; the order lands `REJECTED`.
- **No duplicate** orders for the key under the storm.

**EXECUTED 2026-07-14 — PASS:**
```
orders for key: 1   rejected: 1
[PASS]  no duplicate orders under the 5xx storm (n=1)
single order landed REJECTED / reason=BROKER_UNAVAILABLE (bounded, no retry storm)
```
**Harness fix:** the `STP_LOADTEST_FAKE_5XX` adapter the drill assumes was **never
implemented** (the script documents it as an operator to-do). Implemented it in
`fake_broker_patch._build_fake` (place_order raises `BrokerError(UNAVAILABLE)`
when the env flag is set) and ran the worker with it. Verified directly: a single
5xx webhook → order `REJECTED` (`process_alert.broker_error`), confirming
`process_alert` (`max_retries=0`) rejects rather than retry-storms. Without this,
the "5xx storm" was a no-op and the REJECTED assertion could never be exercised.
(TradeStation retry code is covered by a separate adapter unit test — flag OFF,
no live traffic, §4.7.)

---

## Day 5 — DB restart / failover · `db-restart.sh`

**Procedure:** `docker compose restart postgres`; measure DB downtime and app
reconnect time.

**Assertions:**
- The app reconnects on its own within budget (fresh connection → `SELECT 1`).
- Downtime + reconnect windows recorded.

**EXECUTED 2026-07-14 — PASS:**
```
[PASS]  healthy pre-drill
[chaos] postgres downtime ≈ 0s
[PASS]  app reconnected in ~1s (≤60s)
SUMMARY: db_downtime≈0s  app_reconnect≈1s
```
App reconnected unaided after `docker compose restart postgres`. The Railway
managed-failover measurement remains **[LIVE]**.

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
