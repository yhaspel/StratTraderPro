# ADR-092 — Strategy Python adapters: the backtest contract, registry, and the no-uploaded-code stance

**Date:** 2026-07-08
**Status:** Accepted
**Milestone:** M09 — Walk-Forward Backtester
**Reference:** `project-plan/09-walk-forward-backtester.md` §6.1, §6.2, §6.3, §11;
AC-09-3; ADR-030 (the strategy 3-file upload contract), ADR-090/091 (the engines
that consume adapters); the M03 `load_strategies` import path

## Context

A StratTraderPro `Strategy` is, at rest, a **Pine script** plus a description plus
a webhook template (ADR-030) — either a system-seeded strategy or a user upload.
Pine scripts **do not execute server-side**: live trading happens when TradingView
runs the Pine and POSTs an alert to our webhook. The backtester, though, has to
*generate the signals itself* over historical bars — there is no TradingView in the
loop. So it needs a server-side, executable definition of "when does this strategy
enter and exit?"

The obvious-but-wrong answer is "execute the uploaded Pine (or some translation of
it) on the server." That is arbitrary code execution driven by user-supplied
content — the exact thing §11 forbids. The question this ADR answers is: how does a
strategy become backtestable **without** ever running uploaded code?

## Decision

### 1. Every backtestable strategy has an in-repo Python **adapter**

A backtest signal source is a small, repo-owned Python class implementing the
**`BacktestStrategy`** Protocol (`backend/apps/backtest/strategies/base.py`):

```python
@runtime_checkable
class BacktestStrategy(Protocol):
    slug: str          # matches strategies_strategy.slug
    warmup_bars: int   # max indicator lookback the adapter needs

    def param_grid(self) -> dict[str, list]: ...
        # the adapter's declared parameter space: {name -> allowed values}

    def generate_signals(self, bars: pd.DataFrame, params: dict) -> pd.DataFrame: ...
        # a frame indexed like `bars` with boolean `entries` / `exits`
        # and optional float `stop_pct` / `target_pct` columns
        # (per-entry, as a fraction of entry price)
```

The adapter is a **pure function of the bars frame + params**. It returns aligned
boolean signals and, optionally, per-entry stop/target fractions that the replay
engine turns into intra-bar exits (ADR-091 §5). It does no I/O, holds no state, and
— critically — **never sees the future**: `bars` is a past-only view and all fills
happen next-bar-open in the engines, so as long as an adapter only reads columns at
or before each row, it cannot leak look-ahead. The §10.1 index-alignment tests
enforce this (mutating a future bar must not change any past signal).

The `slug` ties the adapter to its `strategies.Strategy` row; `warmup_bars`
declares the maximum indicator lookback (see §3).

### 2. The registry: `@register` maps slug → adapter, miss → 400 `BACKTEST_NO_ADAPTER`

`backend/apps/backtest/strategies/registry.py` holds a module-level dict
`slug -> adapter class`. Adapters opt in with a **module-level `@register`
decorator**:

```python
@register
class SmaCrossAdapter:
    slug = "sma-cross-demo"
    warmup_bars = 50
    ...
```

Importing the `strategies` package runs every bundled adapter's decorator (import
side effect), so `get_adapter(slug)` and `registered_slugs()` see them all.
`register` refuses a slug-less class and a duplicate slug (two classes claiming one
slug is a bug, not a merge). `get_adapter` returns an **instance**, or `None` on a
miss.

A lookup miss is a first-class outcome, not an error:

- At **POST** time, the create view resolves the adapter; a miss returns
  **400 `BACKTEST_NO_ADAPTER`** ("No Python adapter registered for this strategy").
- The **strategy picker** endpoint returns a `has_adapter` flag per strategy, so
  the UI disables un-backtestable strategies and shows the banner *"Backtest not
  available — no Python adapter registered"* instead of letting the user submit a
  run that can only fail.
- The worker re-checks and raises `BACKTEST_NO_ADAPTER` defensively if a run
  somehow reaches it with no adapter.

### 3. Warm-up bars: prefetch lookback so boundaries carry no NaN / look-ahead

An SMA(50) is undefined for the first 49 bars of any frame. If the loader handed
the sweep exactly `[train_start, train_end)`, the first ~50 in-window bars would
carry NaN indicators — and worse, a naive fix (compute indicators only over the
in-window slice) would make the indicator at `train_start` depend on where the
window happens to start, which is a subtle form of boundary look-ahead.

So the adapter **declares `warmup_bars`** (its max lookback), and the loader
(`data.py`) **prefetches that many bars *before* the window start**. Indicators are
computed over the full frame (warm-up + window) and then masked to the window, so
the indicator at the first in-window bar is the *same* value it would have on any
larger frame — no NaN at the boundary, no dependence on the window edge. The
warm-up rows are execution-excluded (fills only happen inside `[start, end)`) and
coverage-excluded (the weekday-coverage check counts only in-window bars). This is
the ADR-091 half-open contract holding at every window seam.

### 4. Security stance: adapters are **repo-owned code only** — uploads never execute

This is the load-bearing security decision of M09, and it is **structural**, not a
runtime check:

- **Adapters live in the repo** (`apps/backtest/strategies/`) and are reviewed like
  any other code. The registry is populated *only* by our own modules' `@register`
  decorators at import time.
- **The M03 `load_strategies` import path does NOT ingest adapter code — and must
  not.** `load_strategies` walks a directory of Pine + description + webhook files
  and upserts `Strategy` rows; it reads *content as bytes*, never *imports Python*.
  Correcting an earlier draft that implied otherwise: there is no path by which an
  uploaded or community strategy contributes executable backtest code.
- **A strategy without a registered adapter simply cannot be backtested.** An
  uploaded strategy is a Pine blob we can store, display, and route live alerts
  for — but its `slug` has no entry in the registry, so `get_adapter` returns
  `None` and the run is refused with `BACKTEST_NO_ADAPTER`. There is no fallback
  that tries to "run the Pine" or eval anything.
- **Param grids are bounded, not free-form.** A user's `param_grid` must be a
  **subset refinement** of the adapter's declared `param_grid()` — the view rejects
  any key or value the adapter didn't declare (`VALIDATION_ERROR`), and every value
  is validated numeric. No arbitrary value, let alone arbitrary code, reaches an
  adapter (§11).

The net property: **no arbitrary code execution reachable from user input.** The
only Python that runs in a backtest is repo-owned adapter code we wrote and
reviewed. This is why community/uploaded strategies being un-backtestable is a
*feature*, not a gap — backtesting is opt-in per strategy, gated on a human writing
and merging an adapter.

### 5. The seeded demo: `sma-cross-demo`

M09 ships one end-to-end demo so the feature is demonstrable on a fresh install:

- **`SmaCrossAdapter`** (`strategies/sma_cross.py`) — a long-only fast/slow SMA
  crossover. Declared grid: `fast ∈ {5,10,15}`, `slow ∈ {20,30,40,50}` = 12 combos
  (≥ 10 so PBO is computed, ≤ 24 so it fits the CI performance smoke).
  `warmup_bars = 50` (the largest slow SMA). Signals are trailing means compared
  against the prior row via `.shift(1)` — never a future row.
- **`manage.py seed_demo_strategy`** — an **idempotent** management command that
  upserts a matching **system** `Strategy` (`owner=NULL`, `is_system=True`,
  `slug="sma-cross-demo"`) via the existing `upsert_system_strategy` service, so the
  row shape matches the M03 seed catalogue exactly. Run it once on a fresh install
  and the demo strategy appears in the picker, adapter-enabled, ready to backtest.

## Consequences

**Positive:**

- **No arbitrary code execution.** The only executable backtest logic is
  repo-owned adapters; uploaded content is never imported or eval'd (§11). This is
  enforced by architecture (the registry is populated only by our modules), not by
  a filter that could be bypassed.
- **The boundary contract is honest.** `warmup_bars` prefetch means indicators at
  every window edge are NaN-free and window-position-independent — no look-ahead
  smuggled in at the seams.
- **Backtestability is an explicit, reviewed decision.** A strategy becomes
  backtestable only when someone writes and merges an adapter — the right gate for
  a feature whose output is used to justify trading capital.
- **Demonstrable out of the box.** The seeded `sma-cross-demo` + `seed_demo_strategy`
  give a fresh install a working end-to-end backtest with zero external data
  (synthetic fixtures) or key setup.

**Negative / honest limits:**

- **Every backtestable strategy needs hand-written adapter code.** There is no
  auto-translation from Pine; a user's uploaded strategy cannot be backtested until
  a maintainer authors an adapter for it. This is the deliberate cost of the
  no-code-execution stance.
- **Adapter and Pine can drift.** The adapter is a *reimplementation* of the
  strategy's logic in Python; nothing mechanically guarantees it matches the Pine
  the user runs on TradingView. For the seeded demo the two are written to agree;
  for future adapters, keeping them in sync is a review responsibility, not an
  automated check.
- **The registry is import-time global state.** Adapters must be imported for their
  `@register` to run; the package `__init__` imports the bundled ones. A new
  adapter module that nobody imports is invisible — a foot-gun mitigated by keeping
  all adapters under the one package.

## Alternatives considered

1. **Execute the uploaded Pine server-side (via a Pine interpreter / transpiler).**
   Rejected: arbitrary code execution driven by user content — the §11 red line —
   and Pine has no server-side runtime we'd trust anyway. This is the whole reason
   adapters exist.
2. **Let `load_strategies` import a `.py` adapter alongside the 3 files.** Rejected:
   that *is* ingesting and importing user-supplied code, reintroducing the exact
   RCE the design forbids. `load_strategies` stays bytes-only.
3. **A generic "indicator DSL" users configure instead of code.** Rejected for MVP:
   a safe expression DSL is a real project of its own, and the adapter Protocol is
   enough for the strategies we actually ship. The `SweepEngine`/adapter seams leave
   room to add one later behind the same contract.
4. **No `warmup_bars`; compute indicators only over the in-window slice.** Rejected:
   makes boundary indicators depend on the window edge (a subtle look-ahead) and
   leaves NaN at every segment start. Declared warm-up + prefetch is correct.

## See also

- ADR-030 — the strategy 3-file upload contract (`load_strategies`, the bytes-only
  import path)
- ADR-090 — the sweep + replay engines that consume adapter signals
- ADR-091 — the walk-forward protocol (warm-up, next-bar-open fills, stops)
- `backend/apps/backtest/strategies/base.py` — the `BacktestStrategy` Protocol
- `backend/apps/backtest/strategies/registry.py` — `register` / `get_adapter`
- `backend/apps/backtest/strategies/sma_cross.py` — the demo adapter
- `backend/apps/backtest/management/commands/seed_demo_strategy.py` — the seeder
- `project-plan/09-walk-forward-backtester.md` §6.1, §11
