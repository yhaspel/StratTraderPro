# Runbook — Monthly kill-switch verification drill

**Owner:** Yuval
**Cadence:** Monthly (§5 DoD — "runbook committed and dated"). Record the run
date and the metric deltas each time you execute it.
**Status:** Executable checklist. The four levels, `is_blocked` precedence,
`SELECT FOR UPDATE` toggles, the L2 daily-loss breaker, and the adapter
`flatten_all` path are built and unit-tested (M08, AC-08-7…AC-08-10). The
**p99 ≤ 5s flatten measured on staging (AC-08-8) and the 50-user load test
(AC-08-11) are deferred** — they need a deployed environment; what has run is a
**local `FakeBrokerAdapter` latency measurement** (see the last section).
**Companion docs:** `docs/adr/081-kill-switch-levels.md` (the design this
verifies — read §2/§4/§5 first), `docs/runbooks/daily-loss-false-trigger.md`
(if L2 tripped when it shouldn't have), `docs/adr/050-broker-adapter-abstraction.md`
(the `flatten_all` seam), `project-plan/08-risk-engine-and-kill-switches.md`
§6.3, §6.4, §10.4, §12.

## Drill log

| Date run | By | L0 | L1 | L2 | L3 | Chaos (Redis) | `flatten_latency` observed | Notes |
|---|---|---|---|---|---|---|---|---|
| _YYYY-MM-DD_ | | | | | | | | |

> Copy the row each month. "L0…L3" = pass/fail; record the observed
> `killswitch_flatten_latency_seconds` sample and any anomaly.

## Prerequisites

- A test user with a `RiskProfile`, MFA enrolled, and at least one **CONNECTED**
  broker account holding open paper positions (Alpaca paper is the default;
  `docs/runbooks/alpaca-paper-smoke.md` to seed positions).
- The user's MFA device (you re-prompt for L1; §11).
- Admin access for L3 (`is_staff`).
- A Prometheus/Grafana view of the M08 metrics, or `curl` on `/metrics`.

## The metrics you are watching (§12)

| Metric | What it should do during the drill |
|---|---|
| `killswitch_trigger_total{scope}` | +1 on `scope="STRATEGY"` (L0), `"USER"` (L1 and L2), `"PLATFORM"` (L3) as you trip each. |
| `killswitch_flatten_latency_seconds` | One observation per flatten (L1, L2). The bucketed histogram tops out at 10s; a healthy paper flatten lands in the sub-second buckets. |
| `daily_loss_breach_total` | +1 when L2 confirms a breach. |

Snapshot these before you start so the deltas are unambiguous.

## Level 0 — per-strategy toggle rejects one strategy only (AC-08-7)

1. Pick two of the user's strategies, **A** and **B**, both live.
2. Toggle **A**'s kill switch on — the per-strategy toggle on the Strategies page,
   or `POST /api/v1/risk/killswitches/ {scope:"STRATEGY", target_id:<A>, active:true}`.
   L0 does **not** require an MFA re-prompt.
3. Send a test alert for **A** → it must be **rejected `STRATEGY_HALTED`**
   (check the alert's `reject_reason`, and that `killswitch_trigger_total{scope="STRATEGY"}`
   ticked). Send one for **B** → it must place normally. This is the
   "rejects that strategy, does not affect others" assertion.
4. Release **A**
   (`{scope:"STRATEGY", target_id:<A>, active:false}`) and confirm **A** places again.

**Pass:** A blocked, B unaffected, release restores A.

## Level 1 — global halt flattens everything (AC-08-8)

1. Confirm the user holds open paper positions.
2. Click the big red **"Halt my trading"** button (or
   `POST … {scope:"USER", active:true, mfa_code:<code>}`). It **requires a fresh
   MFA code** — verify the request is rejected `MFA_REQUIRED` without one, then
   succeeds with a valid code.
3. Assert, in order:
   - a new active `TradingHalt(level=L1, scope=USER)` row exists;
   - `killswitch_trigger_total{scope="USER"}` +1;
   - **all** positions flatten — one `killswitch_flatten_latency_seconds`
     observation, and a `RiskEvent(type=FLATTEN)` whose `details.flattened`
     matches the number of open positions;
   - any subsequent alert for that user is **rejected `USER_HALTED`** (at both
     the webhook and `process_alert` gates — ADR-081 §2).
4. Release the L1 halt (`{scope:"USER", active:false}`) and confirm new alerts
   place again.

**Pass:** MFA enforced, all positions flat, new alerts blocked while active,
latency observation recorded.

## Level 2 — daily-loss auto-trip and next-day lock (AC-08-9)

L2 is automatic; you provoke it by driving the user's cached P&L below their
limit. Do this on a **paper** account.

1. Lower the test user's `daily_loss_usd` to a small number (e.g. `50`) via
   `PUT /api/v1/risk/profile/`, or arrange for open positions marked at a loss
   beyond the limit.
2. Let the `daily_loss_watcher` beat run (every 30s), or invoke `check_daily_loss`
   directly twice from a shell — L2 requires the breach on **two consecutive
   polls** (ADR-081 §4):

   ```python
   # manage.py shell
   from apps.risk.killswitch import check_daily_loss
   from django.contrib.auth import get_user_model
   u = get_user_model().objects.get(email="<test-user>")
   print(check_daily_loss(u))   # first poll → False (arms the counter)
   print(check_daily_loss(u))   # second poll → True (trips L2)
   ```

3. Assert: `RiskEvent(type=DAILY_LOSS_BREACH)`, `daily_loss_breach_total` +1,
   `killswitch_trigger_total{scope="USER"}` +1, an active
   `TradingHalt(level=L2, auto=True)`, and that positions flattened (L2 flattens
   like L1).
4. **Verify the lock:** try to release it
   (`{scope:"USER", active:false}` or `release_halt`) *the same day* → it must be
   **refused `HALT_LOCKED` (409)**. The auto-halt only releases at the next
   trading-day rollover (UTC-05). To un-block sooner is an admin force-release —
   see `docs/runbooks/daily-loss-false-trigger.md`.

**Pass:** two-poll trip, flatten, and same-day release refused.

## Level 3 — platform halt stops everyone (AC-08-10)

1. As an **admin** (`is_staff`), trigger it:
   `POST … {scope:"PLATFORM", active:true, mfa_code:<code>}`. Confirm a
   **non-admin** call is rejected `403 FORBIDDEN`, and that the admin call without
   a valid MFA code is rejected `MFA_REQUIRED`.
2. Assert an active `TradingHalt(level=L3, user=NULL)` and
   `killswitch_trigger_total{scope="PLATFORM"}` +1.
3. Send alerts for **any** user (not just the test user) → every one is
   **rejected `PLATFORM_HALTED`**. This is the global stop — platform beats user
   beats strategy in `is_blocked`.
4. Release (`{scope:"PLATFORM", active:false}`, admin) and confirm processing
   resumes for everyone.

**Pass:** admin-only, MFA-gated, blocks all users, release restores.

## Chaos drill — kill Redis mid-L1 (§5 DoD, §10.4)

The point: **the flatten must still run with Redis down**, because the flatten
goes through the *cached broker session* (adapter), not Redis, and the audit
survives because the `RiskEvent` / `TradingHalt` writes land in **Postgres**, not
the cache.

1. With the test user holding open paper positions, prime the broker session
   (send one normal order first so the adapter/session is warm).
2. Trigger L1 (`{scope:"USER", active:true, mfa_code:<code>}`) and, in the same
   window, **kill Redis** (`docker compose stop redis`, or stop your local
   `redis-server`).
3. Assert:
   - the flatten **still completes** — positions go flat, a
     `killswitch_flatten_latency_seconds` observation is recorded, and a
     `RiskEvent(FLATTEN)` row exists **in Postgres**;
   - the `TradingHalt(level=L1)` row exists in Postgres;
   - the two-poll L2 cache counter is the only thing that resets (it lives in the
     cache) — L1/L3 do not depend on Redis for correctness.
4. Bring Redis back (`docker compose start redis`) and confirm normal operation
   resumes (the beat watcher, push notifications, etc.).

**Pass:** flatten ran and the audit trail is intact with Redis down.

## The deferred p99 measurement, and the local latency measurement that was done

- **Deferred (AC-08-8 / AC-08-11):** the "p99 ≤ 5s flatten measured on staging"
  and the 50-user / 10-orders-per-sec load test both need a deployed staging
  environment with real broker round-trips. They belong to the M08 exit gate
  (§17) and are **not** done yet.
- **Done locally:** flatten latency is exercised against `FakeBrokerAdapter`
  (`apps/risk/test_risk.py::test_flatten_latency_and_flat`) — the test triggers a
  flatten over seeded fake positions, asserts every position goes flat, and reads
  back the `killswitch_flatten_latency_seconds` observation. This proves the
  measurement plumbing (monotonic timing → histogram → `RiskEvent.details.latency_s`)
  and that flatten empties positions; it does **not** prove the real-broker p99.

When staging exists, run this whole drill there once end to end, capture the p99
from `killswitch_flatten_latency_seconds`, run AC-08-11, and record the result in
the M08 exit-gate checklist (§17).
