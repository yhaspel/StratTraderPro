# Runbook — Investigating a reconciliation drift

**Owner:** Yuval
**Status:** Executable checklist — the broker-agnostic reconciliation loop is
built and unit-tested (M05, AC-05-6). Works against any `CONNECTED`
`BrokerAccount`; in practice that is **Alpaca** today (TradeStation accounts are
skipped while `BROKER_TRADESTATION_ENABLED=false`).
**Companion docs:** `docs/adr/051-reconciliation-policy.md` (the policy this
operationalizes — read it first), `docs/adr/050-broker-adapter-abstraction.md`
(`list_positions()` is the seam), `docs/runbooks/webhook-debug.md` (tracing the
fill that *should* have kept us in sync), `docs/runbooks/tradestation-oauth-recover.md`
(if the drifting account is TS and calls are 401ing),
`project-plan/05-tradestation-and-order-lifecycle.md` §6.3, §12.

## What "drift" means here

Our persisted `orders.Position` (a per-`(broker_account, symbol)` snapshot
derived from the fill stream) disagrees with the broker's authoritative
`list_positions()` by more than **0.01 shares / 1 contract**. Per ADR-051: the
**first** confirmed drift only records a `ReconEvent(DRIFT)`; a **second
consecutive** drift heals our snapshot toward the broker
(`ReconEvent(HEAL)`) — **never by placing an order**; a drift that comes back
within tolerance on its own is marked resolved. Your job when investigating is
to decide **why** the two disagreed, not to re-heal (the loop already does that).

## When to open this runbook

- The **§12 alert "drift persists > 30 min"** fired.
- `reconcile_drifts_total` is climbing, or `reconcile_heals_total` ticked and you
  want to know what got healed and why.
- A user reports their dashboard positions don't match what they see in
  Alpaca/TradeStation directly.
- You deliberately injected a drift to validate the pipeline (see last section).

## Step 1 — Find the ReconEvent rows

**Via the API** (MFA-enforced, scoped to the requesting user):

```
GET /api/v1/reconciliation/events/
```

Returns the latest 500 `ReconEvent`s for the user, newest first. Each row
carries: `broker_account`, `symbol`, `asset_class`, `kind`
(`DRIFT` | `HEAL` | `RESOLVED`), `our_qty`, `broker_qty`, `detail`,
`created_at`, `resolved_at`.

**Via the DB** (ops, cross-user) — table `orders_recon_event`:

```sql
SELECT id, broker_account_id, symbol, kind, our_qty, broker_qty,
       detail, created_at, resolved_at
FROM   orders_recon_event
WHERE  symbol = 'AAPL'                       -- or filter by broker_account_id
ORDER  BY created_at DESC
LIMIT  50;
```

An **open drift** is `kind='DRIFT' AND resolved_at IS NULL`. A pair of
`DRIFT`→`HEAL` for the same symbol close together is the two-cycle confirmation
having fired. A lone `DRIFT` with a later `resolved_at` (and no `HEAL`) is a
**self-resolved** transient — usually an in-flight fill that settled.

## Step 2 — Interpret `our_qty` vs `broker_qty`

`detail` is stamped `ours=<our_qty> broker=<broker_qty>`. Read the *direction*:

| Pattern | Reading | Most likely cause |
|---|---|---|
| `broker_qty > our_qty` | Broker holds **more** than we booked | A **fill we missed** — a `trade_updates` event dropped during a WS blip, or a manual order the user placed in the broker's own UI. |
| `broker_qty < our_qty` | Broker holds **less** than we booked | A fill we **double-counted**, a broker-side bust/cancel, or a manual close in the broker UI. |
| `our_qty = 0`, `broker_qty ≠ 0` | We think we're flat; broker isn't | Missed the **opening** fill entirely, or a position opened outside our pipeline. |
| `our_qty ≠ 0`, `broker_qty = 0` | We think we hold; broker is flat | Missed the **closing** fill, or a manual flatten in the broker UI. |
| Small non-zero diff on a futures/option line | Off by whole contracts | Contract-multiplier or partial-fill accounting; check the `Fill` rows for that order. |

## Step 3 — Missed fill vs genuine broker-side change

This is the decision the runbook exists for. Cross-check the drift against our
own event history for that symbol/account:

1. **Look for the fill we should have.** Trace the order and its fills —
   `GET /api/v1/orders/?symbol=<SYM>&broker=<BROKER>` then the order detail
   (`GET /api/v1/orders/{id}/`) for its lifecycle + `Fill` rows. Or in the DB,
   join `orders_order` → `orders_fill` on the symbol/account around the drift
   time.
   - **A matching order exists but is missing a `Fill`** (or is stuck at
     `SUBMITTED`/`PARTIAL` while the broker shows it done) → **missed fill.**
     The stream lost the event. Confirm the streams service health and let the
     next cycle heal it; the *underlying* gap is the dropped `trade_updates`.
   - **No order of ours explains the broker position at all** → **genuine
     broker-side change** (manual trade in Alpaca/TradeStation, or a broker
     bust). Healing is still correct for the *snapshot*, but flag it — our books
     are following an action we didn't originate.

2. **Check whether the stream was down** around `created_at`:
   `broker_stream_disconnects_total{broker}` /
   `broker_ws_reconnects_total{broker}` spiking near the drift time points hard
   at **missed fill**. The streams service does a REST catch-up on reconnect
   (`get_orders`, deduped on `broker_exec_id`), so a healthy reconnect usually
   *self-heals* the fill and the drift self-resolves before cycle two.

3. **Check the account isn't simply unreachable** — if `list_positions()` is
   erroring (auth/rate-limit), the "drift" may be spurious. For TradeStation,
   `BROKER_REAUTH_REQUIRED` in `BrokerCallAudit` means see the OAuth runbook, not
   this one.

## Step 4 — Check the Prometheus metrics

| Metric | What it tells you |
|---|---|
| `reconcile_drifts_total{broker,kind}` | Rate/volume of detected drifts. A per-broker spike localizes the problem to one broker's stream or account set. `kind="position"` today. |
| `reconcile_heals_total` | How often the second-cycle heal fired. A rising heal rate with a **flat** fill-ingest rate says fills are being lost and reconciliation is papering over it — investigate the stream, don't just accept the heals. |
| `broker_ws_reconnects_total{broker}` / `broker_stream_disconnects_total{broker}` | Stream instability correlating with drifts ⇒ missed-fill story. |
| `fills_ingested_total{broker}` | If this stalls while positions change at the broker, the ingest path is the root cause. |
| `oauth_refresh_total{broker,result}` (TS) | `fail` spikes mean the drift is really an auth outage masquerading as drift. |

The **> 30 min unresolved drift** alert (§12) is the escalation trigger:
roughly six cycles without convergence means healing isn't sticking (the drift
keeps re-opening) — that is **not** a normal missed fill and needs a human
decision (Step 5).

## Step 5 — When to escalate

- **Drift persists > 30 min** (alert fired) and the heal keeps re-opening the
  drift → escalate. Something is continuously diverging: a broken ingest path,
  an account being traded out-of-band, or a symbology mismatch mapping two
  symbols onto one key.
- **Genuine broker-side change** you can't attribute to any user action →
  escalate to the account owner; our books are now following an unexplained
  broker move.
- **Systemic** — many accounts drifting at once → treat as a stream/broker
  incident, not per-account; check the streams service and broker status.

## Manual heal path

The 5-minute loop heals automatically after two cycles. To heal **now** without
waiting (e.g. after you've fixed the streams service and confirmed the broker is
truth), run a reconcile pass for the one account from a Django shell — this is
the same code the beat task calls, so it obeys the same tolerance and
two-cycle/heal rules and still **never places an order**:

```python
# manage.py shell
from apps.brokers.models import BrokerAccount
from apps.orders.reconcile import reconcile_account

acct = BrokerAccount.objects.get(id="<broker-account-uuid>")
events = reconcile_account(acct)     # idempotent; safe to run repeatedly
for e in events:
    print(e.kind, e.symbol, "ours=", e.our_qty, "broker=", e.broker_qty)
```

Because heal requires a *prior* open `DRIFT`, the **first** manual run may only
record the drift; run it a **second** time to trigger the heal (that is the
two-cycle confirmation, not a bug). There is no supported path that heals our
snapshot by trading — if the broker is somehow the one that's wrong, that is a
broker-side correction the user makes in the broker's UI, never something
reconciliation does.

## Deliberately injecting a drift to validate the pipeline (AC-05-6)

To prove detection → confirm → heal end to end on staging with a connected paper
account:

1. **Create a discrepancy our stream won't immediately fix.** Easiest is to
   mutate our snapshot directly so it disagrees with the broker (the broker
   stays truth, we go wrong on purpose):

   ```python
   # manage.py shell — make our books disagree with the broker by > tolerance
   from decimal import Decimal
   from apps.orders.models import Position
   p = Position.objects.get(broker_account_id="<uuid>", symbol="AAPL")
   p.qty = p.qty + Decimal("5")     # or set to 0 to simulate a missed close
   p.save(update_fields=["qty"])
   ```

   (Alternatively, place a small order directly in the Alpaca **paper**
   dashboard so the *broker* moves while our pipeline is quiet — this exercises
   the genuine-broker-change branch instead.)

2. **Run cycle one** — `reconcile_account(acct)` (or wait for the beat). Assert a
   `ReconEvent(DRIFT)` appears (`GET /api/v1/reconciliation/events/`) with the
   right `our_qty`/`broker_qty`, and `reconcile_drifts_total` incremented. Assert
   **no** `Position` change yet and **no** order was placed.

3. **Run cycle two** — call it again (or wait one interval). Assert a
   `ReconEvent(HEAL)`, `reconcile_heals_total` incremented, our `Position` now
   matches the broker, the open `DRIFT` is `resolved_at`-stamped, and the
   dashboard received a `POSITION_UPDATED` push. Confirm the broker's own
   position list is **unchanged** (we healed our cache, we did not trade).

4. **Self-resolution variant** — inject the drift, then *before* cycle two put
   our `Position` back in sync, and run reconcile: assert the open `DRIFT` is
   resolved with **no** `HEAL` row (transient blip path, ADR-051 §4).

Record the ReconEvent ids and metric deltas in the exit-gate checklist — this is
the "reconciliation runbook validated with a deliberate drift" gate.
