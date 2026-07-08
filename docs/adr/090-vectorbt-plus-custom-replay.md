# ADR-090 — vectorbt for the sweep, a custom in-repo engine for the replay

**Date:** 2026-07-08
**Status:** Accepted
**Milestone:** M09 — Walk-Forward Backtester
**Reference:** `project-plan/09-walk-forward-backtester.md` §1, §6.2, §6.3, §7, §16;
the 2026-07-05 pre-milestone review note (RESOLVED 2026-07-08); AC-09-3, AC-09-4,
AC-09-10; ADR-091 (the protocol these engines execute), ADR-092 (the adapter they
consume)

## Context

M09 is a **two-stage** backtester. Stage one is a fast, vectorized **parameter
sweep** that scores every grid combination on a train window and hands the best
params forward. Stage two is a **path-dependent replay** of those params on the
following test window with realistic execution — next-bar-open fills, bps
slippage, intra-bar stops/targets, volume-participation partial fills, per-trade
MFE/MAE. The two stages want fundamentally different tools: the sweep wants
column-broadcast speed over hundreds of combos; the replay wants an explicit,
auditable event loop whose every fill we can pin in a golden-file test.

Two upstream decisions had to be made before writing a line of engine code, and
both were flagged as blockers in the master-plan analysis:

1. **Which sweep library** — and specifically, is `vectorbt` usable given the
   "AGPL" scare in the analysis note?
2. **Which replay library** — the plan originally named `backtrader`.

## Decision

### 1. vectorbt OSS `1.0.0` for the sweep — the "AGPL" premise was wrong

The blocker premise ("vectorbt is AGPL, so using it forces us to open-source the
platform") is **factually incorrect**. vectorbt OSS is **fair-code**, licensed
**Apache-2.0 + the Commons Clause** — not AGPL, not GPL. The Commons Clause is a
source-available rider that removes one specific freedom from Apache-2.0: you may
not **sell** a product or service whose value derives *substantially* from the
software itself. Reading it against StratTraderPro:

- We may **use** vectorbt freely, including commercially and server-side, with no
  copyleft obligation to publish our own source. Apache-2.0 imposes no such
  obligation and the Commons Clause adds none.
- The only thing forbidden is selling something that **is, in substance,
  vectorbt** — a hosted "vectorbt-as-a-service", a repackaged vectorbt product.
  StratTraderPro is a regime-aware, multi-broker webhook-trading platform in which
  the backtester is one feature among many, and vectorbt is one internal library
  behind that feature. We are not selling vectorbt; the clause does not bite.

So M09 uses **`vectorbt==1.0.0`** (exact pin) for the sweep stage — `size=1` unit
sizing, the run's cost model applied so ranking is cost-aware, evaluated in chunks
of ≤ 100 combos to bound memory (AC-09-10).

### 2. The `SweepEngine` seam keeps vectorbt swappable

vectorbt never appears above the engine boundary. All sweep access goes through a
small **`SweepEngine`** interface in `backend/apps/backtest/vbt_engine.py`:

```
run(bars, start, end, adapter, grid, costs, metric) -> SweepResult
returns_matrix(bars, start, end, adapter, grid, costs) -> (combos, T×N matrix)
```

`VectorbtSweepEngine` is the only implementation today, but the orchestrator
(`wf.py`) and the PBO stage (`pbo.py`) call it only through those two methods.
This matters for two reasons: the fair-code license (if the terms ever changed, or
if a future maintenance lapse forced our hand, we replace one class), and the §16
risk that vectorbt 1.0.0 — a recent release (2026-04) — misbehaves on py3.12/CI.
A custom fallback sweep would be contained behind this seam, not smeared across
the milestone.

### 3. Per-share commission is an approximation under unit sizing

vectorbt's `Portfolio.from_signals` models costs as `fees` (fractional, % of
notional) and `fixed_fees` (flat per order). Our cost model also carries a
**per-share** commission (`per_share_usd`), which vectorbt has **no exact
analogue** for. Because the sweep runs at unit sizing (`size=1`, one share per
signal), one share per order means:

```
fixed_fees = per_order_usd + per_share_usd × 1
```

is exactly right *for the sweep*. The replay stage sizes positions for real, so it
applies `per_share_usd × qty` properly; the sweep's fixed-fee approximation only
has to be good enough to keep the **ranking** cost-aware and comparable to the
replay's fill model, which at unit sizing it is. This is the one place the sweep's
cost handling is deliberately an approximation, and it is confined to ranking, not
to any reported P&L.

To keep the sweep's fills comparable to the replay's, the sweep **shifts
`entries`/`exits` forward one bar and passes `price=open`**, so a signal on close
`t` fills at `t+1` open in both engines. Without this the §16 zero-cost
cross-check (replay vs vectorbt under no slippage/no stops) would not converge.

### 4. backtrader is rejected — the replay is a custom in-repo engine

`backtrader` was the plan's original replay library. It is dropped:

- **License:** GPLv3. A GPLv3 dependency linked into our server process would
  raise exactly the copyleft question the vectorbt scare falsely raised — except
  here it would be real.
- **Maintenance:** the last release is **2023-04**; the project has been dormant
  since. Its packaging classifiers stop at **Python 3.7**; we run 3.12. Taking a
  hard execution-path dependency on an unmaintained, pre-3.8-classified library
  for the milestone's most correctness-sensitive component is not acceptable.

So the replay stage (`replay_engine.py`) is a **custom, in-repo event loop** —
deliberately small, pure (a function of its inputs; no I/O, no RNG), with
**exactly-specified semantics written down first** in **ADR-091** and pinned by
golden-file + property tests. Owning the replay is what lets us guarantee the
same-bar stop-first rule, the partial-fill sequence, and the sizing hook that
reuses production `compute_size` (AC-09-12) — none of which we could assert
precisely against a third-party loop.

### 5. The resolved dependency tree (installed 2026-07-08, Python 3.12)

vectorbt's base install pulls a **fat transitive tree** — scipy, matplotlib,
plotly, scikit-learn, numba, dill, and more arrive whether or not we ask. The
`[full]`/`[rust]` extras are **not** installed (base only, per §7). The resolver
run on the M09 day-1 task produced this working set on py3.12:

| Package | Version | Notes |
|---|---|---|
| `vectorbt` | **1.0.0** | exact pin; the sweep engine |
| `numpy` | 2.1.3 | satisfies repo pin `numpy>=1.26,<2.2` |
| `pandas` | 2.2.3 | satisfies repo pin `pandas>=2.1,<2.3` |
| `numba` | 0.66.0 | JIT backend for vectorbt; no direct pin of ours |
| `scipy` | 1.18.0 | transitive |
| `scikit-learn` | 1.9.0 | transitive |
| `matplotlib` | 3.11.0 | pinned explicitly (`>=3.8,<4.0`) — PDF SVG charts |
| `plotly` | 5.24.1 | pinned explicitly (`>=5.18,<6.0`) — single-file HTML report |
| `weasyprint` | 68.1 | pinned explicitly (`>=68,<69`) — PDF tearsheet |

`matplotlib` and `plotly` arrive transitively with vectorbt regardless, but we
**pin them directly** in `requirements/base.txt` anyway so the versions we render
tearsheets with are a deliberate choice, not an accident of vectorbt's resolver.
We render PDFs with **matplotlib → SVG** (real `<text>`, selectable) and the HTML
with **plotly inline** — **no kaleido** (its headless-Chrome dependency is
deliberately avoided). Fresh-venv resolver check + import + a 100-combo smoke on
3.12 all pass, and the backend image goes through the repo's Trivy scan against
this enlarged tree (CI fails on fixable HIGH/CRITICAL).

### 6. `NUMBA_DISABLE_JIT=1` for tests

vectorbt runs its hot loops through numba JIT. In CI the JIT compile can be slow
and occasionally flaky on a cold runner, so tests run with **`NUMBA_DISABLE_JIT=1`**
(numba executes the same code in pure Python). This is correctness-first, speed-
second — and it does double duty: the reproducibility DoD (§10.5, ADR-091 §determinism)
requires the `metrics_hash` to be **identical across JIT-enabled and JIT-disabled**
runs, so the smoke is run both ways once and the hashes compared. Disabling JIT is
a test/CI knob only; production workers run with JIT on.

## Consequences

**Positive:**

- **No copyleft exposure.** The sweep library is Apache-2.0 + Commons Clause
  (usable), the replay is our own code, and backtrader's GPLv3 never enters the
  tree. The one honest license constraint (don't resell vectorbt-as-a-product) is
  irrelevant to what StratTraderPro is.
- **The library boundary is one class wide.** vectorbt is reachable only through
  `SweepEngine`; a swap or a custom fallback is a contained change.
- **The correctness-critical stage is ours.** The replay's exact semantics are
  specified and test-pinned (ADR-091), not inherited from a dormant dependency.
- **The rendered-artifact versions are deliberate.** matplotlib/plotly/weasyprint
  are pinned regardless of the transitive pull.

**Negative / honest limits:**

- **A fat transitive tree.** vectorbt drags in scipy/scikit-learn/dill/ipywidgets
  we don't otherwise use, enlarging the image and the Trivy surface. Accepted as
  the cost of the fastest sweep option; the base-only install keeps it as small as
  vectorbt allows.
- **The per-share sweep cost is an approximation.** `fixed_fees = per_share × 1`
  is exact only at unit sizing; it exists to keep ranking cost-aware, not to
  report P&L (the replay does that). Documented so nobody reads sweep-stage costs
  as production-grade.
- **vectorbt 1.0.0 is young.** A 2026-04 release on py3.12 is a §16 Med/Med risk;
  the exact pin, the day-1 smoke, the `NUMBA_DISABLE_JIT` escape hatch, and the
  `SweepEngine` seam are the mitigations.

## Alternatives considered

1. **Read the "AGPL" note at face value and drop vectorbt.** Rejected: the premise
   was wrong. vectorbt OSS is fair-code, freely usable server-side; abandoning the
   fastest sweep option over a misread license would have cost us the sweep stage
   for no reason.
2. **Use vectorbt for the replay too.** Rejected: vectorbt is a vectorized
   portfolio simulator, not an intra-bar event engine. Our path-dependent
   semantics (same-bar stop-first, partial-fill re-attempts, force-close at
   segment end, production sizing per entry) don't express cleanly in it, and we
   couldn't golden-file-pin them.
3. **Keep backtrader for the replay.** Rejected: GPLv3 + dormant since 2023 +
   py3.7 classifiers. A copyleft, unmaintained dependency on the most
   correctness-sensitive component is the wrong trade.
4. **Write a custom sweep too (no vectorbt at all).** Rejected for MVP: the sweep
   is embarrassingly parallel column math that vectorbt already does fast and
   correctly; reimplementing it buys nothing today. The `SweepEngine` seam leaves
   that door open if it's ever needed.

## See also

- ADR-091 — the walk-forward protocol + the exact replay fill/sizing/determinism
  semantics these engines implement
- ADR-092 — the strategy adapter contract the sweep and replay both consume
- ADR-080 — the pure `compute_size` the replay reuses for production-mode sizing
- `backend/apps/backtest/vbt_engine.py` — `SweepEngine` + `VectorbtSweepEngine`
- `backend/apps/backtest/replay_engine.py` — the custom replay event loop
- `backend/requirements/base.txt` — the vectorbt / matplotlib / plotly / weasyprint pins
- `docs/runbooks/backtest-stuck.md` — operating the backtest worker
- `project-plan/09-walk-forward-backtester.md` §6.2, §6.3, §7, §16
