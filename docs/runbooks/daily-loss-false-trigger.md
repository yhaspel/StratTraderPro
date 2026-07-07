# Runbook — Investigating a daily-loss false trigger (L2)

**Owner:** Yuval
**Status:** Executable checklist. The L2 daily-loss breaker — two-poll
confirmation, the `DAILY_LOSS_BREACH` event, the auto-halt, and the
next-trading-day release lock — is built and unit-tested (M08, AC-08-9,
`test_two_poll_breach_trips_l2`, `test_l2_release_locked_until_next_day`).
**Companion docs:** `docs/adr/081-kill-switch-levels.md` (the L2 design — read §4
first), `docs/runbooks/kill-switch-verify-monthly.md` (the monthly drill that
provokes L2 on purpose), `docs/runbooks/reconcile-drift-investigation.md` (if the
P&L is wrong because our `Position` marks drifted from the broker),
`project-plan/08-risk-engine-and-kill-switches.md` §6.4, §16 (stale-mark risk).

## What "false trigger" means here

The L2 circuit breaker halted a user and flattened their positions, but the user
believes they were **not** actually down past their daily-loss limit. Because L2
flattens and then locks until the next trading day (UTC-05), a false trip is
disruptive — the user is out of the market for the rest of the session. Your job
is to decide whether the trip was **real** (the P&L genuinely breached) or
**spurious** (driven by a bad mark), and to release it correctly if it was
spurious.

The design already guards against the most common cause: L2 requires the breach
on **two consecutive 30-second polls** before it trips (§16 mitigation). So a
single stale mark does *not* trip it — a false trigger means the *same* wrong P&L
was seen twice, which points at a persistently bad mark, not a one-off blip.

## When to open this runbook

- A user reports "you flattened me / halted me and I wasn't down that much."
- `daily_loss_breach_total` incremented for a user whose realized P&L looks fine.
- You see an active `TradingHalt(level=L2, auto=True)` you want to validate before
  the next-day auto-release.

## How L2 decides (the happy path)

`apps.risk.tasks.daily_loss_watcher` runs every 30s during market hours and calls
`check_daily_loss(user)` for each profiled user:

1. **P&L computation** (`user_daily_pnl`): sums `(market_price − avg_cost) × qty`
   over the user's `Position` rows, using the **cached `Position` marks** as the
   conservative fallback. The intent (review-note 3 / §6.4) is to prefer a
   **fresh broker mark with a short timeout** and fall back to the cached mark —
   never to trip off a single stale read.
2. **Breach test:** `pnl ≤ −|daily_loss_usd|` **or**
   `pnl/equity·100 ≤ −|daily_loss_pct|`.
3. **Two-poll confirmation:** a per-user, per-trading-day cache counter
   (`risk:dl:<user>:<trading_day>`) increments on each breaching poll and is
   **deleted** on any non-breaching poll. Only when the count reaches **2** does
   L2 trip.
4. **Trip:** writes `RiskEvent(type=DAILY_LOSS_BREACH, details={pnl, equity})`,
   increments `daily_loss_breach_total`, and calls `trigger_halt(level=L2,
   auto=True, flatten=True)` — same action as an L1 halt.

## Step 1 — Confirm the trip and read its recorded P&L

**Via the API** (MFA-enforced, scoped to the user):

```
GET /api/v1/risk/events/?type=DAILY_LOSS_BREACH
GET /api/v1/risk/killswitches/          # the active L2 halt
```

The `DAILY_LOSS_BREACH` event carries `details.pnl` and `details.equity` — the
exact numbers the breaker acted on. Compare `details.pnl` to the user's
`daily_loss_usd` / `daily_loss_pct` (from `GET /api/v1/risk/profile/`).

**Via the DB / shell:**

```python
# manage.py shell
from apps.risk.models import RiskEvent
from apps.brokers.models import TradingHalt
u_id = "<user-id>"
for e in RiskEvent.objects.filter(user_id=u_id, type="DAILY_LOSS_BREACH").order_by("-created_at")[:5]:
    print(e.created_at, e.details)      # {'pnl': ..., 'equity': ...}
halt = TradingHalt.objects.filter(user_id=u_id, level="L2", auto=True, released_at__isnull=True).first()
print(halt and (halt.id, halt.created_at))
```

If `details.pnl` really is past the limit, the trip was **correct** — this is not
a false positive; explain the loss to the user and let the next-day lock expire.
If `details.pnl` looks wrong (far more negative than the user's actual loss), go
to Step 2.

## Step 2 — Was it a stale-mark false positive?

Recompute the P&L from *current* broker truth and compare it to what the breaker
saw:

```python
# manage.py shell
from apps.risk.killswitch import user_daily_pnl
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(id="<user-id>")
print(user_daily_pnl(u))     # (pnl_usd, equity) from current cached Position marks
```

Then cross-check the cached marks against the broker directly:

| What you find | Reading |
|---|---|
| Current recomputed P&L is **fine**, but the `DAILY_LOSS_BREACH` `details.pnl` was far worse | The marks were **stale/bad at trip time**. Because it needed *two* polls, the bad mark persisted for ≥ 30s — likely a stuck `Position.market_price` (no fresh fill/mark), or a mark on a wrong quantity. |
| Our `Position` marks disagree with the broker's positions right now | **Reconciliation drift** is feeding the breaker bad inputs → open `docs/runbooks/reconcile-drift-investigation.md`. Fix the drift first; the P&L is only as good as the marks. |
| A `Position` has a wrong `avg_cost` or a stale `market_price` | A single mispriced line can dominate the sum. Trace that symbol's fills. |
| P&L really is past the limit | **Not** a false positive — the breaker worked. |

The tell for a *false* trigger is: **the recorded `details.pnl` breached, but
current broker truth does not** — i.e. the two confirming polls both read the
same stale mark. That is the §16 stale-mark risk the fresh-mark-with-timeout read
is meant to eliminate; if you keep seeing it, the fix is upstream (fresh marks /
reconciliation), not repeated releases.

## Step 3 — Release the halt

L2 is **locked until the next trading day** on purpose (AC-08-9). There are two
supported paths:

### 3a. Let it auto-clear (the default, for a *real* breach)

Do nothing. At the next trading-day rollover (UTC-05, `trading_day()`), the lock
lifts and the user (or the normal release path) can clear it. `release_halt`
refuses (`HALT_LOCKED`, 409) any same-day attempt — that refusal is the breaker
working, not a bug.

### 3b. Admin force-release (only for a confirmed *false* trigger)

If Step 2 confirmed the trip was spurious and you don't want to strand the user
for the session, force-release. The user's own API call can't (the same-day lock
blocks it) — this is a deliberate admin action:

```python
# manage.py shell — admin force-release of a confirmed false L2 trip
from django.utils import timezone
from apps.brokers.models import TradingHalt
from apps.risk.models import RiskEvent
halt = TradingHalt.objects.get(id="<halt-id>", released_at__isnull=True)
halt.released_at = timezone.now()
halt.released_by_id = "<admin-user-id>"
halt.save(update_fields=["released_at", "released_by"])
RiskEvent.objects.create(user=halt.user, type=RiskEvent.Type.KILL_SWITCH_OFF,
                         scope=halt.scope, details={"level": halt.level, "forced": True, "reason": "false daily-loss trip"})
```

This bypasses the `release_halt` same-day guard directly, so use it **only** after
Step 2 confirms a false positive. Record why (the `forced`/`reason` detail above
is the audit trail). Fix the underlying mark/drift so it doesn't re-trip on the
next two polls — otherwise the watcher will simply trip L2 again.

> Do **not** raise the user's `daily_loss_usd` / `daily_loss_pct` as a way to
> "release" a halt. That silently weakens their risk limit for every future day.
> The limit is the user's decision; a false trip is a data problem, fix the data.

## Step 4 — Verify recovery

- `GET /api/v1/risk/killswitches/` no longer lists the L2 halt (or it shows
  `released_at`).
- The user can place orders again (`is_blocked` returns `None` — no `USER_HALTED`).
- `user_daily_pnl(u)` now reflects correct broker truth; a subsequent watcher
  poll does **not** re-arm the two-poll counter (`risk:dl:<user>:<day>` stays
  clear).
- If the root cause was drift, the reconcile runbook's exit checks are green.
