# Runbook — Engage / release the L3 platform halt (admin portal)

**Owner:** Yuval
**Status:** Executable. The admin platform kill-switch endpoint, the typed-confirm
+ MFA gate, and the delegation to `apps/risk/killswitch` at level L3 are built and
unit-tested (M10, AC-10-8). **Companion docs:** `docs/adr/081-kill-switch-levels.md`
(the L0–L3 model — read §2 for `is_blocked` precedence and what each level does),
`docs/runbooks/kill-switch-verify-monthly.md` (the monthly drill exercises L0–L3),
`docs/runbooks/strategy-flatten-limitation.md`, `project-plan/10-admin-audit-observability.md`
§6.3, `project-plan/08-risk-engine-and-kill-switches.md` §6.3/§6.4.

## What L3 does — and what it does NOT do

**L3 = platform halt.** It **blocks new order intake for every user** — it wins the
`is_blocked` precedence (platform → user → strategy), so every inbound alert is
rejected `PLATFORM_HALTED` at both the webhook gate and `process_alert` (ADR-081
§2). It creates a single `TradingHalt(level=L3, user=NULL)` row.

**L3 does NOT flatten positions.** This is by design (ADR-081): the platform halt
stops *new* risk from entering; it does not liquidate existing positions. Everyone's
open positions stay exactly as they were. If you need to *also* flatten, that is a
separate, deliberate action — see "How to also flatten" below.

Engaging L3 requires, server-validated:

- **A typed confirmation phrase** — exactly `HALT PLATFORM`. A wrong/empty phrase is
  rejected `400 CONFIRM_PHRASE_MISMATCH`.
- **A fresh MFA code** — a bad/absent code is rejected `403 MFA_REQUIRED`.
- **Admin identity** — `is_staff` + MFA-enrolled, non-impersonation token
  (`IsAdminAndMFAEnforced`), and `ADMIN_PORTAL_ENABLED` on (off → `503
  ADMIN_PORTAL_DISABLED`).

## Engage the platform halt

Via the admin UI: the platform panel's "Halt platform" control — type
`HALT PLATFORM` into the confirm box and enter a current MFA code.

Or via the API:

```
POST /api/v1/admin/platform/killswitch/
{
  "engage": true,
  "reason": "<why — recorded in the audit chain>",
  "mfa_code": "<current TOTP>",
  "confirm": "HALT PLATFORM"
}
```

On success → `200 {"platform_halted": true, "halt_id": <id>,
"note": "L3 blocks new order intake and does NOT flatten positions."}`. It
delegates to `killswitch.trigger_halt(user_id=None, level=L3, …)` and emits an
`admin.platform_halt_engaged` audit row, `killswitch_trigger_total{scope="PLATFORM"}`
ticks, and the `KillSwitchTriggered` alert fires (expected — you did it).

**Verify:** send a test alert for any user → it must be rejected `PLATFORM_HALTED`.
Check `GET /api/v1/admin/platform/status/` → `platform_halted: true`.

## Release the platform halt

```
POST /api/v1/admin/platform/killswitch/
{
  "engage": false,
  "reason": "<why>",
  "mfa_code": "<current TOTP>"
}
```

No confirm phrase is required to *release* (releasing is the safe direction), but
MFA still is. It finds the active `TradingHalt(level=L3, released_at IS NULL)`,
calls `killswitch.release_halt(...)`, emits `admin.platform_halt_released`, and
returns `200 {"platform_halted": false, "released": true}`. If no L3 halt was
active it returns `{"platform_halted": false, "released": false}` (idempotent).

**Verify:** `GET …/platform/status/` → `platform_halted: false`, and a test alert
places again.

## How to ALSO flatten (L3 alone won't)

If the situation calls for flat positions and not just an intake stop, engage a
**flatten** as a distinct action. There is no platform-wide flatten button (that
would liquidate every user's account at once); flatten is per-user, through the
kill-switch engine's L1:

- For a specific user, engage an **L1 user halt with flatten** — the L1 path runs
  the broker adapter's `flatten_all` (Alpaca `close_all_positions`) and blocks that
  user's new orders (`kill-switch-verify-monthly.md` §"Level 1"). That is the
  sanctioned "stop *and* liquidate" action, scoped to one user.
- L2 (daily-loss auto) also flattens, but it is automatic, not something you engage
  by hand.
- **STRATEGY-scope flatten is unsupported** (`FLATTEN_SCOPE_UNSUPPORTED`) — positions
  carry no `strategy_id`, so it can't be scoped; see
  `strategy-flatten-limitation.md`.

So the two-step "everyone stop, and flatten these accounts" is: engage L3 (intake
stop, all users), then engage L1-with-flatten per user for the accounts you need
liquidated. There is no single call that does both platform-wide, on purpose.

## Disabling a user does NOT auto-flatten either

The admin "disable user" action
(`POST /api/v1/admin/users/<id>/disable/`, MFA + reason) sets `is_active=False` and
revokes the user's other sessions — it stops them logging in and trading further.
It **does not flatten their open positions**; the endpoint's own response says so:
`"Open positions are NOT auto-flattened; engage an L1 halt with flatten if needed."`
If a disabled user is holding positions you want closed, follow the L1-with-flatten
path above for that user's account before or after disabling them.

## Quick reference

| Action | Endpoint | Blocks new orders | Flattens | Requires |
|---|---|---|---|---|
| Platform halt (L3) | `POST …/platform/killswitch/ {engage:true}` | all users | **no** | `HALT PLATFORM` + MFA |
| Release L3 | `POST …/platform/killswitch/ {engage:false}` | — | — | MFA |
| Flatten a user (L1) | risk L1 halt with flatten | that user | **yes** | MFA (risk page) |
| Disable a user | `POST …/users/<id>/disable/` | that user (login/trade) | **no** | MFA + reason |
