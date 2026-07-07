# ADR-051 — Position reconciliation: two-cycle confirmation, heal toward broker truth

**Date:** 2026-07-07
**Status:** Accepted
**Milestone:** M05 — TradeStation + Order Lifecycle
**Reference:** `project-plan/05-tradestation-and-order-lifecycle.md` §6.3, §12, §16;
AC-05-6

## Context

We keep a persisted `orders.Position` row per `(broker_account, symbol)` so the
dashboard can render holdings without a broker round-trip on every page load.
That snapshot is *derived* from the fill stream, and any derived cache can drift
from source of truth: a missed `trade_updates` event during a WebSocket blip, a
fill that happened outside our pipeline (a manual order in the broker's own UI),
a partial we booked but the broker later busted, or an off-by-a-share rounding.

M05 needs a loop that (a) *notices* the drift, (b) decides *who is right*, and
(c) corrects our side **without ever touching the market**. The one thing a
reconciliation job must never do is "fix" a position by placing an order — that
turns a bookkeeping discrepancy into a real trade. This ADR records the policy
and why it is shaped the way it is.

## Decision

### 1. A Celery beat job compares our snapshot to broker truth every 5 minutes

`apps.orders.tasks.reconcile_positions_task` runs on the beat schedule
(`CELERY_BEAT_SCHEDULE["reconcile-positions"]`, default
`RECONCILE_INTERVAL_SECONDS=300`). For **each `BrokerAccount` in status
`CONNECTED`** it calls `reconcile_account(account)`
(`apps/orders/reconcile.py`), which:

1. Builds the account's adapter and calls **`adapter.list_positions()`** — the
   broker's authoritative holdings. This is the same protocol method for Alpaca
   and TradeStation (ADR-050); reconciliation is broker-agnostic.
2. Loads our `Position` rows for that account (`select_for_update`, inside a
   `@transaction.atomic`).
3. Walks the **union** of symbols on both sides (so a symbol we hold but the
   broker doesn't, and vice-versa, are both examined). Missing on either side is
   treated as quantity `0`.

TradeStation accounts are skipped while `BROKER_TRADESTATION_ENABLED=false`
(they can't be reconciled against a broker we aren't allowed to call yet); one
account raising an exception is logged and does **not** abort the sweep of the
others.

### 2. Tolerance: 0.01 shares / 1 contract

Per symbol we compare `|broker_qty − our_qty|` against a tolerance of
`Decimal("0.01")`. Within tolerance the symbol is considered **in sync** — and
any *lingering open drift* for that symbol is closed (its `resolved_at` is
stamped now; see §4). Fractional-share rounding noise therefore never raises a
drift, and a one-contract difference on a futures/option line is above tolerance
and *is* flagged.

### 3. First drift records; second consecutive drift heals

This is the core of the policy — a **two-consecutive-cycle confirmation** before
any state change:

- **First drift** for a symbol: create a `ReconEvent(kind=DRIFT)` capturing
  `our_qty`, `broker_qty`, and a `detail` string, and increment
  `reconcile_drifts_total{broker,kind="position"}`. **Nothing is changed** — we
  have only *observed* a discrepancy once.
- **Second consecutive drift** (an open, unresolved prior `DRIFT` exists for the
  same `(account, symbol)`): call `heal_toward_broker` — i.e. **snap our
  `Position` to the broker's** quantity/avg-cost/mark (or zero it if the broker
  is flat) — then record a `ReconEvent(kind=HEAL)` (already `resolved_at`-stamped),
  increment `reconcile_heals_total`, and resolve the open `DRIFT` rows for that
  symbol. The healed `Position` is pushed to the user's dashboard
  (`POSITION_UPDATED`).

The heal path **never places a corrective order.** `_heal` only does an
`update`/`update_or_create` on our `Position` row. A discrepancy is a bookkeeping
fact about *our cache*, and the remedy is to correct the cache — not to trade.

### 4. A drift that self-resolves is marked resolved

If, on a later cycle, the symbol comes back within tolerance *before* the second
consecutive drift, we do **not** heal — we simply stamp `resolved_at` on the
open `DRIFT` `ReconEvent`(s) for that symbol. The transient blip is recorded (so
it's auditable that it happened) and closed with no state change. `ReconEvent`
also carries a `RESOLVED` kind in its enum for this "no longer drifting"
disposition; the current loop expresses self-resolution by resolving the open
`DRIFT` row rather than emitting a separate `RESOLVED` row.

### 5. A drift persisting > 30 minutes pages ops

Persistence is a **monitoring** concern, handled by the observability layer
(plan §12), not by the reconcile task itself. The Prometheus rule alerts when a
drift for an account/symbol stays unresolved for **> 30 min** — i.e. roughly six
cycles where healing either isn't converging or the drift keeps re-opening. That
is the signal that the discrepancy is not a missed fill our snapshot can absorb
but something needing a human (see `docs/runbooks/reconcile-drift-investigation.md`).

### 6. Why lean toward broker truth

The broker is the **system of record for money.** Their positions ledger is what
actually settles, funds, and can be liquidated; our `Position` is a
read-optimized projection of a fill stream that can lose events. When the two
disagree and the disagreement is *confirmed*, the only safe assumption is that
the broker is right and our projection missed something. Healing *toward* the
broker makes our dashboard match what the user would see if they logged into
Alpaca/TradeStation directly — which is the number they'll act on.

### 7. Why two consecutive cycles

A single-cycle heal invites **oscillation** (plan §16, "reconcile triggers
oscillation", Low/Med): a fill can be in-flight — landed at the broker but not
yet ingested by us — so a snapshot taken mid-flight legitimately disagrees for a
few seconds and then agrees on its own. If we healed on the first disagreement
we could snap our position to a broker value that our own about-to-arrive fill
was already about to produce, and then re-drift when it arrives. Requiring the
drift to reproduce on the **next** cycle (5 min later) gives in-flight fills time
to settle through the stream, so we only heal genuinely-stuck discrepancies.
It's the cheapest possible debounce: confirm, then act.

## Consequences

**Positive:**

- Reconciliation can never *cause* a trade. The worst it does is correct a
  cached number, which is idempotent and reversible.
- Two-cycle confirmation eliminates the heal/re-drift oscillation loop by
  construction, at the cost of at most one extra 5-minute cycle of latency
  before a real drift heals — acceptable for a dashboard cache.
- Every drift, heal, and self-resolution is an auditable `ReconEvent` row,
  queryable via `GET /api/v1/reconciliation/events/`, and every count is a
  Prometheus counter (`reconcile_drifts_total`, `reconcile_heals_total`).
- Broker-agnostic: it consumes only `adapter.list_positions()`, so both current
  brokers and any future one reconcile through the identical path.

**Negative / limits:**

- A *genuine* broker-side change we didn't initiate (e.g. a manual liquidation
  in the broker UI) heals silently into our snapshot after two cycles — correct
  for the cache, but it means our books quietly follow the broker without a
  human necessarily noticing unless the > 30-min alert or a `HEAL` event review
  catches it. The investigation runbook exists for exactly this ambiguity.
- Healing corrects *quantity and cost basis on the snapshot*, not the historical
  `Fill`/`Order` rows — a missed fill is not back-filled as a `Fill`, so P&L
  derived purely from fills can still under-count until the underlying gap is
  investigated. Reconciliation restores *position* truth, not *event* history.
- Up to ~5 min detection latency + one confirmation cycle before a heal. Fine
  for a paper milestone; a live milestone may want a tighter interval or an
  event-driven trigger.

## Alternatives considered

1. **Heal on first drift.** Rejected: oscillates against in-flight fills and can
   snap to a value our own pending fill was about to produce. The single extra
   cycle is cheap insurance.
2. **Auto-place a corrective order to make the broker match *us*.** Rejected
   outright and permanently: it treats the broker (source of truth) as wrong and
   converts a cache miss into a real market order — the single most dangerous
   thing a reconciler could do.
3. **Trust our snapshot, alert only, never heal.** Rejected: leaves the
   dashboard knowingly wrong indefinitely and pushes every discrepancy to a
   human. Heal-toward-broker-after-confirmation keeps the common case
   (a missed fill) self-correcting while still paging on the stuck case.
4. **Tighter tolerance (exact match).** Rejected: fractional-share and rounding
   noise would raise constant false drifts. `0.01` share / 1 contract is below
   any real position change and above rounding jitter.

## See also

- ADR-050 — Broker adapter abstraction (`list_positions()` is the seam this uses)
- `backend/apps/orders/reconcile.py` — `reconcile_account`, `_heal`
- `backend/apps/orders/models.py::ReconEvent` — the audit model + `Kind` enum
- `backend/apps/orders/tasks.py::reconcile_positions_task` — the beat entrypoint
- `backend/apps/orders/views.py::ReconEventListView` — `GET /api/v1/reconciliation/events/`
- `docs/runbooks/reconcile-drift-investigation.md` — investigating a drift
- `project-plan/05-tradestation-and-order-lifecycle.md` §6.3, §12
