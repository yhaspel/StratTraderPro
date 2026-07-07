# ADR-081 — Four kill-switch levels on one `TradingHalt` table

**Date:** 2026-07-08
**Status:** Accepted
**Milestone:** M08 — Risk Engine, Position Sizing & Kill Switches
**Reference:** `project-plan/08-risk-engine-and-kill-switches.md` §6.3 (kill-switch
engine), §6.4 (daily-loss watcher), §11 (MFA re-prompt), §12 (observability),
review-note 2026-07-05 (build on `brokers.TradingHalt`); AC-08-7, AC-08-8,
AC-08-9, AC-08-10; ADR-050 (the `flatten_all` seam)

## Context

M08 has to expose four escalating ways to stop trading:

- **L0 — per strategy.** Stop one strategy, leave the rest running.
- **L1 — per user (global).** The user's own "halt everything and flatten"
  button.
- **L2 — daily-loss circuit breaker.** The same action as L1, but tripped
  *automatically* when the user's daily P&L breaches their configured loss limit,
  and locked shut until the next trading day.
- **L3 — platform.** An admin stops *all* webhook processing, everyone, at once.

M04 already ships a `brokers.TradingHalt` table and — crucially — the ingest
gate already reads it: `process_alert` and the webhook endpoint reject when an
active halt exists. The 2026-07-05 review note is explicit: **build the levels on
that table, do not invent a parallel kill-switch model.** M04's gate must keep
working unchanged.

Two correctness hazards are called out in the master-plan analysis and the plan's
risk table: (a) a **race** between a halt toggle and an in-flight order, and (b)
**stale broker marks** driving a false daily-loss trip. Both have to be designed
out, not patched later.

## Decision

Extend the existing `brokers.TradingHalt` model with a `level` field (L0–L3), an
`auto` flag, and a nullable `user` (NULL = platform), and drive all four levels
through one engine, `backend/apps/risk/killswitch.py`. There is **one**
kill-switch table; the level is a column, not a new model.

### 1. One table, four levels — the scope is derived from the columns

`TradingHalt` gains:

- `level` — `L0` | `L1` | `L2` | `L3`.
- `auto` — `True` for the L2 auto-trigger (and only L2).
- `user` — already FK, now **nullable**: NULL means platform-wide (L3).
- `strategy` — FK, NULL means "all strategies" (user-level).

A halt is **active while `released_at IS NULL`**, exactly as M04 defined it. The
scope is a pure function of which columns are set (`TradingHalt.scope`):

| Level | `user` | `strategy` | `auto` | Scope |
|---|---|---|---|---|
| **L0** strategy | set | set | — | `STRATEGY` |
| **L1** user-global | set | NULL | — | `USER` |
| **L2** daily-loss | set | NULL | `True` | `USER` (auto) |
| **L3** platform | **NULL** | NULL | — | `PLATFORM` |

Because the level lives on the table M04's gate already queries, **no ingest code
had to change to gain three new kill-switch levels** — the gate reads
`released_at IS NULL` halts as before; the engine simply writes richer rows. This
is the whole reason for building on the existing table rather than beside it.

### 2. `is_blocked` — a fixed precedence, read at two points

`is_blocked(user_id, strategy_id) -> reason | None` is the hot read path. It
checks scopes in a fixed order and returns the **first** matching reason:

1. **Platform** (`level=L3, user IS NULL`) → `PLATFORM_HALTED`.
2. **User** (`user_id, strategy IS NULL`) → `USER_HALTED` (covers both L1 and the
   L2 auto-halt, which is a user-scoped row).
3. **Strategy** (`user_id, strategy_id`) → `STRATEGY_HALTED`.

Platform beats user beats strategy — the broadest halt wins. It is consulted in
**two** places (belt-and-suspenders, AC-08-7/10, plan §6.3): at the **webhook
endpoint** before the alert is enqueued, and again at the **top of
`process_alert`** in case a halt toggled in the window between accept and
processing. An order in flight when a halt lands is still stopped at the second
gate, and the broker-side cancel from the flatten path mops up anything already
submitted.

When `KILL_SWITCHES_ENABLED` is off (§15 rollback), `is_blocked` still honors a
plain **L0 strategy** toggle and nothing else — matching the plan's degraded mode.

### 3. Trigger / release run under `SELECT FOR UPDATE`

The analysis doc flagged a transaction-isolation gap on the toggle path. Both
`trigger_halt` and `release_halt` are `@transaction.atomic` and take a
`SELECT FOR UPDATE` lock on the matching active-halt rows for the scope before
acting:

- **`trigger_halt`** locks active halts at that level/scope; if one already
  exists it returns it (idempotent — no duplicate concurrent triggers), otherwise
  it creates the row, increments `killswitch_trigger_total{scope}`, writes a
  `RiskEvent(KILL_SWITCH_ON)`, and — for L0/L1/L2 with `flatten=True` — schedules
  the flatten on `transaction.on_commit` (so we never flatten against a halt row
  that then rolls back).
- **`release_halt`** locks the target halt and clears `released_at`, writing a
  `RiskEvent(KILL_SWITCH_OFF)` — **unless** it is an L2 auto-halt still inside its
  lock window (§4), in which case it refuses.

The lock serializes concurrent toggles on the same scope, so 50 users hammering
L1 at once (AC-08-11) cannot produce duplicate halts or duplicate flattens.

### 4. L2 — two-poll confirmation and a next-trading-day lock

The daily-loss watcher (`daily_loss_watcher`, a 30-second Celery beat during
market hours) computes each profiled user's P&L and trips L2 through the same
`trigger_halt`. Two design points defend it:

- **Two-poll confirmation (Risk §16 mitigation).** `check_daily_loss` only trips
  L2 after the breach is seen on **two consecutive polls** (a per-user, per-
  trading-day cache counter). A single stale-mark blip clears the counter rather
  than firing the breaker. P&L is computed from cached `Position` marks as the
  **conservative fallback** — the intent (review-note 3) is to prefer a fresh
  broker mark with a short timeout and fall back to the cached mark, never to trip
  off a single stale read.
- **Next-trading-day lock (AC-08-9).** An L2 auto-halt cannot be released until
  the effective trading day rolls over at the **UTC-05 boundary**
  (`trading_day()`). `release_halt` compares `trading_day(created_at)` to
  `trading_day(now)` and refuses (`HALT_LOCKED`, HTTP 409) while they are equal.
  A user cannot un-trip their own daily-loss breaker to keep trading the day they
  hit it; it clears on its own the next day. (An admin force-release path exists
  for genuine false positives — see `docs/runbooks/daily-loss-false-trigger.md`.)

On a confirmed breach the watcher writes `RiskEvent(DAILY_LOSS_BREACH)`,
increments `daily_loss_breach_total`, and triggers L2 with `flatten=True` — same
action as an L1 halt.

### 5. Flatten goes through the adapter's `flatten_all`, and its latency is measured

Flatten (`flatten_user`) iterates the user's `CONNECTED` broker accounts and
calls the M05 adapter seam `adapter.flatten_all(reason=scope)` (ADR-050):

- **Alpaca** — one native call, `close_all_positions(cancel_orders=True)`; the
  ≤5s budget (AC-08-8) is comfortable through a single round-trip (review-note 2).
- **TradeStation** — no bulk endpoint, so a per-position loop places an opposing
  market order for each open position (the documented fallback).

After each broker flattens, `reconcile_positions` re-reads to converge our books.
The **full latency** (first call → last submit) is timed with `time.monotonic()`
and recorded in `killswitch_flatten_latency_seconds`, and a
`RiskEvent(FLATTEN, details={latency_s, accounts, flattened})` is written. The
histogram buckets top out at 10s so a budget breach is visible. Broker errors in
one account are caught and logged so a single failing account cannot abort the
whole flatten.

### 6. MFA re-prompt on L1 and L3 (§11 cookie-theft defense)

Triggering the **global (L1)** or **platform (L3)** kill switch requires a fresh
MFA code, re-verified at the API (`verify_mfa_code`), on top of the normal
MFA-enforced session. The threat (§11) is a **stolen session cookie**: an
attacker with a hijacked session must not be able to *disable* a user's risk
controls or, worse, halt the platform, without a live code from the user's
authenticator. L3 additionally requires `is_staff` (admin-only, AC-08-10) and is
rejected `403` otherwise. L0 (single-strategy toggle) does **not** re-prompt — it
is low-blast-radius and high-frequency, so gating it on MFA would be friction
without a matching threat. Release does not re-prompt either; the dangerous
direction is *disabling* protection, and for L2 the next-day lock already governs
release.

## Consequences

**Positive:**

- **M04's gate kept working for free.** Levels are a column on the table the
  ingest path already reads; no parallel model, no second source of truth for "is
  trading halted."
- **Race-safe toggles.** `SELECT FOR UPDATE` + idempotent trigger + on-commit
  flatten means concurrent triggers can't duplicate halts or flattens, and the
  two-point `is_blocked` check catches orders that raced the toggle.
- **The daily-loss breaker is hard to false-trip and hard to defeat.** Two-poll
  confirmation guards against stale marks; the next-trading-day lock stops a user
  trading through their own limit.
- **Session theft can't disarm risk controls.** L1/L3 need a live MFA code; L3
  needs admin.

**Negative / honest limits:**

- **The ≤5s p99 flatten is measured *locally*, not on staging (deferred).**
  Flatten latency is exercised against `FakeBrokerAdapter`
  (`test_flatten_latency_and_flat`) and the metric is emitted, but the AC-08-8
  "p99 ≤ 5s on staging" and the 50-user load test (AC-08-11) need a deployed
  environment and are deferred to the exit gate. See
  `docs/runbooks/kill-switch-verify-monthly.md`.
- **Fresh-mark vs cached-mark P&L.** The watcher currently computes P&L from
  cached `Position` marks as the conservative fallback; wiring the short-timeout
  fresh broker-mark read in front of it (review-note 3) is the intended hardening
  and is described in `docs/runbooks/daily-loss-false-trigger.md`.
- **The Redis-kill chaos drill is described for local run.** The DoD chaos drill
  (Redis killed mid-L1 → flatten still runs via the cached broker session, audit
  preserved via Postgres) is written up as a local procedure; the staged staging
  run is deferred with the p99 measurement.

## Alternatives considered

1. **A separate `KillSwitchState` model (as the master plan sketched).** Rejected
   per the 2026-07-05 review note: M04 already has `TradingHalt` and its ingest
   gate reads it. A second table would mean two sources of truth for "halted" and
   a migration of the gate. A `level` column is strictly simpler.
2. **Trip L2 on a single poll.** Rejected: broker marks can be momentarily stale;
   a single-poll breaker would fire spurious halts (Risk §16). Two-poll
   confirmation is the mitigation the plan asks for.
3. **Let users release their own L2 immediately.** Rejected: it would make the
   daily-loss limit advisory. The next-trading-day lock is the point of a circuit
   breaker; genuine false positives go through an admin force-release, logged.
4. **A per-position flatten loop for every broker.** Rejected for Alpaca: the
   native `close_all_positions` is one round-trip and keeps L1 well inside budget
   (review-note 2). The loop is kept only where the broker has no bulk endpoint.

## See also

- ADR-080 — the sizing pipeline these switches gate
- ADR-050 — the `BrokerAdapter` / `flatten_all` seam the flatten path rides on
- `docs/runbooks/kill-switch-verify-monthly.md` — the monthly verification drill
- `docs/runbooks/daily-loss-false-trigger.md` — investigating an L2 false trip
- `backend/apps/risk/killswitch.py` — `is_blocked`, `trigger_halt`,
  `release_halt`, `flatten_user`, `check_daily_loss`
- `backend/apps/brokers/models.py` — the extended `TradingHalt`
- `backend/apps/risk/views.py` — the MFA re-prompt + admin-only L3
- `project-plan/08-risk-engine-and-kill-switches.md` §6.3, §6.4, §11, §12
