# Milestone 09 — Walk-Forward Backtester

> **Week:** 9
> **Duration:** 5 working days
> **Depends on:** M06 (Market Data `Bar` store), M08 (sizing primitives reused), M04 (Channels dashboard socket reused for progress)
> **Unlocks:** M10 (Admin + Audit + Observability) — backtest reports stream into observability as sanity metrics

> **Review note (2026-07-05) — RESOLVED 2026-07-08.** The pre-milestone blockers from the master-plan analysis were investigated and decided:
> 1. **Licensing (was "vectorbt AGPL"):** the premise was wrong — vectorbt OSS is **fair-code (Apache 2.0 + Commons Clause)**, not AGPL: free for use; you may not sell a product/service that is *primarily* this software. StratTraderPro is not primarily vectorbt. **Decision:** use **vectorbt OSS `1.0.0`** for the sweep stage, isolated behind our own `SweepEngine` interface so it stays swappable; record the license reading in **ADR-090**. Additionally, **backtrader is dropped** (GPLv3 + unmaintained since 2023): the replay stage is a **custom in-repo engine** (ADR-090/091).
> 2. **Resource caps:** hard CPU-time budget per run (soft 25 min / hard-kill 30 min + user-visible error), per-user concurrency cap (2), param-grid cap (≤ 500 combos), window cap (≤ 60), on a dedicated Celery `backtest` queue so sweeps can't starve order flow. All in §11.
> 3. **Compliance:** tearsheets carry a non-removable "past performance" disclaimer + PBO warning block (§6.6).
> 4. **Artifact storage:** **decision (operator, 2026-07-08): artifacts are DB-stored** (`BYTEA`/JSON, matching the existing `StrategyFile`/`HMMModel` precedent) — this consciously supersedes the earlier "object storage" directive; there is no object storage in the stack today and no pickles are involved anywhere (JSON params only, so the original CRITICAL-04 "no pickles in DB" concern is satisfied by construction). Downloads are authenticated streaming endpoints, not signed URLs. **Revisit trigger:** migrate to R2 via a storage abstraction when the artifact table exceeds ~5 GB or multi-GB reports appear (§16).

## 1. Purpose

Deliver a two-stage walk-forward backtesting subsystem: **vectorbt** for fast parameter sweeps and a **custom in-repo replay engine** for realistic, path-dependent execution validation (stops/targets, slippage, partial fills, MFE/MAE). Produce an authoritative tearsheet (PDF + HTML + JSON) for any adapter-registered strategy on demand. Make the backtester a first-class citizen so strategies earn the right to trade live by demonstrating stable out-of-sample performance.

## 2. In Scope

- Build out the existing `apps/backtest` stub: `BacktestRun`, `BacktestSegment`, `BacktestReport` models; DRF endpoints + Celery orchestration.
- Bars→DataFrame loader over the M06 `Bar` store (does not exist yet — M09 builds it), with coverage validation and adapter warm-up handling.
- Strategy adapter contract + in-repo registry, plus a seeded demo system strategy (`sma-cross-demo`) with adapter and golden fixtures.
- vectorbt-based parameter sweep behind a `SweepEngine` seam (unit sizing, cost-aware ranking, deterministic).
- Custom replay engine for the selected params: next-bar-open fills, bps slippage, configurable commissions (Alpaca-style $0 default), volume-participation partial fills, intra-bar stop/target with conservative same-bar rule, per-trade MFE/MAE.
- Walk-forward orchestrator: rolling or anchored windows, configurable train/test windows (MVP: `step_days == test_window_days`).
- PBO (Probability of Backtest Overfitting, CSCV per Bailey et al. 2015) on the sweep.
- Tearsheet: JSON (canonical, hashable) + single-file Plotly HTML + WeasyPrint PDF with vector (SVG) charts and a non-removable disclaimer.
- Progress streaming over the **existing** `/ws/dashboard/` socket (`backtest.*` events). Cancellation (cooperative, ≤ 30 s).
- DB artifact storage with authenticated download endpoints; retention (90 d default, ≤ 365 d) with nightly eviction beat job.
- Dedicated Celery `backtest` queue: `CELERY_TASK_ROUTES` (first use in the repo) + new `worker-backtest` compose service with time/memory limits.
- UI: `/backtest` launcher + `/backtest/:id` run detail with chart.js charts (lazy-loaded), runs list, report downloads, rerun.
- Reuse of M08 `apps/risk/sizing.py::compute_size` in the replay stage so backtest results can reflect production sizing behavior (AC-09-12).

## 3. Out of Scope

- Monte Carlo path generation for robustness — post-MVP extension.
- Multi-asset *portfolio* optimization — a run may contain up to 10 symbols, but each symbol is walk-forwarded independently (per-symbol OOS curves and reports; no cross-symbol allocation).
- Intraday timeframes — MVP is `tf="1d"` only (config field exists; other `Bar.tf` values rejected with `VALIDATION_ERROR` until a later milestone).
- Options/futures — equities only, matching the Alpaca-first broker reality (ADR-041). No per-contract commission modeling.
- Using the backtester as a live paper-trade equivalent — already covered by paper brokers.
- Executing Pine scripts server-side — strategies are backtested via in-repo Python adapters (§6.1); Pine-level optimization is out.
- The M08 Kelly damper / `TradeHistory`-driven sizing adjustments (referenced in the `risk/sizing.py` docstring) — **not** part of M09; do not build a `TradeHistory` model.
- Object-storage migration for artifacts (revisit trigger in the header note).
- Locales beyond `en` — keys/dict structure ship, translations don't (§13).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-09-1 | User submits a backtest with `strategy` (id), `symbols[]` (1–10), `start`, `end`, `tf` (`"1d"` in MVP), `train_window_days`, `test_window_days`, `step_days` (MVP: must equal `test_window_days`, else 400 `VALIDATION_ERROR`), `mode` (`anchored`\|`rolling`), `metric` (`sharpe` default \| `sortino` \| `total_return` \| `mar`), `initial_cash` (default 100 000), `param_grid` JSON, `costs` (slippage bps, commission), `sizing_mode` (`production`\|`fixed_qty_1`), optional `retention_days` (1–365, default 90). Server-side validation enforces all caps in §11. |
| AC-09-2 | The run executes on a dedicated Celery `backtest` queue (via `CELERY_TASK_ROUTES` + a separate `worker-backtest` service); the default worker does not consume it and order flow is unaffected. Soft/hard time limits 25/30 min are set on the task. |
| AC-09-3 | vectorbt sweep evaluates the full param grid per train window with **unit sizing** and the run's cost model, ranks combinations by the chosen metric; top-1 params pass to the replay stage for that window's test segment. |
| AC-09-4 | The replay engine produces per-trade records (entry/exit ts + price, qty, P&L, MFE, MAE, bars held), models slippage as configurable bps of fill price (default 5 bp, floor 1 bp), commissions (default $0 + optional per-share), and partial fills capped at a configurable % of bar volume (default 10%). Same-bar stop+target hits resolve conservatively (stop first). |
| AC-09-5 | The orchestrator concatenates test segments (by compounding daily returns) into a continuous OOS equity curve per symbol; per-window best params + OOS metrics are persisted as `BacktestSegment` rows. |
| AC-09-6 | The final report includes per symbol: total return, CAGR, Sharpe, Sortino, MAR, Max DD, %win, profit factor, avg win/loss, expectancy, exposure %, turnover, trade count, PBO, and per-window Sharpe stability (mean/σ across windows). |
| AC-09-7 | PDF tearsheet renders with vector charts (equity curve, drawdown, monthly-returns heatmap, per-window metrics), a non-removable "past performance" disclaimer, and a PBO warning badge when PBO > 0.5. Text is real text, not raster. |
| AC-09-8 | Progress streams over the existing dashboard socket as `backtest.progress` `{run_id, pct, stage, eta_seconds}` (stages: `queued/loading/sweeping/replaying/reporting`), plus terminal `backtest.completed`/`backtest.failed`/`backtest.cancelled` events. |
| AC-09-9 | User can cancel a running backtest; the worker halts within 30 s (cooperative flag checked between windows and between param-grid chunks), run ends `CANCELLED`. |
| AC-09-10 | A 3-year daily single-symbol walk-forward completes ≤ 10 min and 10-year ≤ 30 min **on staging hardware** (staging-deferred verification); a reduced local smoke (1y fixture, grid ≤ 24) completes ≤ 60 s in CI. Worker memory peak ≤ 2 GB (grid chunking, §6.2). |
| AC-09-11 | Reports retained 90 days by default; per-run override up to 365 days; nightly beat job evicts expired artifacts (rows keep metrics, artifacts nulled). |
| AC-09-12 | With `sizing_mode="production"`, replay-stage sizing calls the same `compute_size` used by `process_alert`. Parity test (non-tautological): given a fixture user/profile/bars, assert the `SizingInputs` the replay constructs equals what `apps/risk/integration.py::apply_sizing` would construct for the same trade (excepted fields: regime=`NEUTRAL`, sentiment=0.0, intraday_dd=0.0, and `stop_distance` — production passes `None`, the replay populates it) — including the identical `_atr14` computation — and that qty matches through `compute_size`. The UI labels the toggle "Production sizing (regime/sentiment neutralized)"; equity = simulated equity. |

## 5. Definition of Done

Baseline DoD applies (see `project-plan/README.md`), plus:

- Deterministic output: running the same config twice yields an identical `metrics_hash` (SHA-256 over canonical JSON with floats rounded to 1e-9). Verified by test.
- PBO implemented as CSCV per Bailey et al. (2015) and unit-tested against **synthetic known-answer cases** (the paper publishes no plug-in reference numbers): (a) N i.i.d. pure-noise strategies → PBO ≈ 0.5 (seeded, tolerance ±0.15); (b) one planted dominant strategy → PBO < 0.1; (c) properties: PBO ∈ [0, 1], requires even block count (S), deterministic.
- Replay engine semantics covered by golden-file tests (canned bars + params → exact expected trade list) and property tests (no fill outside bar range, cash never negative, equity reconciles with trades).
- PDF passes basic accessibility (selectable text; charts embedded as SVG).
- WeasyPrint system deps (Pango, HarfBuzz, fontconfig + a font — **no Cairo needed for WeasyPrint ≥ 53**) installed in `docker/backend.Dockerfile` **and** in the CI backend job (`ci.yml` runs pytest on the runner, not in Docker).
- Runbook `docs/runbooks/backtest-stuck.md` committed.
- Adapter contract documented (ADR-092) with the registry mechanism and the security rationale (in-repo code only).

## 6. Implementation Tasks

### 6.0 Bars→DataFrame loader (`apps/backtest/data.py`)

New — nothing like it exists (`apps/marketdata/services.py` only has `upsert_bars`/`missing_bars`).

- `load_bars(symbol: str, tf: str, start: date, end: date, warmup_bars: int = 0) -> pd.DataFrame` — UTC `DatetimeIndex`, float64 `open/high/low/close`, int64 `volume`, sorted, deduped. Fetches `warmup_bars` extra rows *before* `start` so indicator lookback never sees NaN at window boundaries and never peeks forward.
- **All date intervals in this milestone are half-open `[start, end)`** — loader, windows, segments, slicing (pandas label slicing is inclusive-right, so implementations must use `.loc[start : end - 1 bar]` or boolean masks). This is the single convention that keeps train/test and consecutive OOS segments non-overlapping.
- Coverage validation: `marketdata.services.missing_bars` reports missing timestamps over the raw range and its docstring leaves trading-day filtering to the caller — that caller is us: the loader computes expected days as **weekdays** and applies the rule below. US markets close ~9 weekdays/year, so perfect data ≈ 96.5% of weekdays. Rule: if < **95% of weekdays** in `[start, end)` are present, fail fast with `BACKTEST_INSUFFICIENT_DATA` (message names the largest gaps) — the 95% threshold tolerates the holiday deficit without a calendar dependency. **No live provider calls from the backtest worker** — data comes from the local `Bar` store only; missing data means the operator runs the M06 backfill first (runbook cross-link).

### 6.1 Strategy adapters (`apps/backtest/strategies/`)

Pine scripts don't execute server-side, so each backtestable strategy needs an in-repo **Python adapter**:

```python
class BacktestStrategy(Protocol):
    slug: str                 # matches strategies_strategy.slug
    warmup_bars: int          # max indicator lookback the adapter needs
    def param_grid(self) -> dict[str, list]: ...
    def generate_signals(self, bars: pd.DataFrame, params: dict) -> pd.DataFrame: ...
        # returns a frame indexed like bars with boolean `entries`, `exits`
        # and optional float `stop_pct`, `target_pct` columns (per-entry, as fraction of entry price)
```

- **Registry:** `apps/backtest/strategies/registry.py` maps `slug -> adapter class`; adapters register via a module-level decorator. Lookup failure → 400 `BACKTEST_NO_ADAPTER` and a UI banner ("Backtest not available — no Python adapter registered").
- **Adapters are repo-owned code only** (security §11). Correcting the earlier draft: the M03 `load_strategies` import command does **not** ingest adapter code and must not — uploaded/community strategies without a registered adapter simply can't backtest.
- Ship one end-to-end demo: `sma_cross.py` adapter (fast/slow SMA crossover, grid over windows) + idempotent management command `seed_demo_strategy` that upserts a matching system `Strategy` row (`owner=NULL`, `is_system=True`, `slug="sma-cross-demo"`) via the existing `upsert_system_strategy` service, so the feature is demonstrable on a fresh install.
- Adapter contract guarantees `bars` is a past-only view; index-alignment tests guard against look-ahead (§10.1).

### 6.2 vectorbt sweep (`apps/backtest/vbt_engine.py`)

- Behind a small `SweepEngine` interface (`run(bars, start, end, adapter, grid, costs, metric) -> ranked results` — full bars frame + half-open evaluation boundaries, so warm-up context before `start` is available and signals are masked to `[start, end)`; same shape serves §6.4's per-window sweeps and §6.5's full-range PBO sweep) so the engine is swappable (ADR-090).
- `vbt.Portfolio.from_signals(..., size=1, fees=..., fixed_fees=..., slippage=...)` with the run's cost model applied, so ranking is cost-aware. **Fill alignment with the replay:** shift `entries`/`exits` forward one bar and pass `price=open`, so sweep fills happen at next-bar open exactly like §6.3 — required for cost-aware ranking to be comparable and for the §16 zero-cost cross-check to converge. Per-share commission has no exact vectorbt analogue (`fees` is fractional, `fixed_fees` per order) — approximate per-share as `fixed_fees = per_share_usd × 1` under unit sizing and document the approximation in ADR-090.
- **Unit sizing in the sweep** (size=1): production sizing is applied only in the replay stage — ranking stays sizing-invariant, and vectorized per-trade dynamic sizing is not attempted.
- Param combos generated from `adapter.param_grid()` ∩ user `param_grid` (user grid must be a subset refinement; validated). Broadcast via vectorbt; evaluate in **chunks of ≤ 100 combos** to bound memory (AC-09-10).
- Score by the chosen metric; return the full ranking. (The PBO input matrix comes from a separate full-range sweep — §6.5 — reusing this same engine; it rides the `sweeping` progress stage.)
- Pin `vectorbt==1.0.0` (verified metadata: requires `numpy>=1.23`, `pandas>=2.0,<3.0`, `numba>=0.60`, py≥3.10 — compatible with repo pins `numpy>=1.26,<2.2` / `pandas>=2.1,<2.3` / py3.12). Note the **base install pulls a fat transitive tree** (scipy, matplotlib, plotly, scikit-learn, ipywidgets, dill, …) — matplotlib/plotly arrive transitively regardless of §7's direct pins. **Day-1 task:** fresh-venv resolver check + import + 100-combo smoke on 3.12; build the backend image and run the Trivy scan against the new tree (repo CI fails on fixable HIGH/CRITICAL); budget CI pip-install time (cache). If the numba path misbehaves in CI, disable JIT via `NUMBA_DISABLE_JIT=1` for tests only — correctness first, speed second.

### 6.3 Replay engine (`apps/backtest/replay_engine.py`) — custom, in-repo

Replaces backtrader (dropped: GPLv3 + dormant since 2023 — ADR-090). Deliberately small event loop with **exactly specified semantics** (ADR-091):

- Signals evaluated on bar close t → market entry filled at bar t+1 open, adjusted by slippage bps (buy: `open*(1+bps/1e4)`; sell: mirrored).
- Stops/targets from the adapter's `stop_pct`/`target_pct` are evaluated intra-bar on t+1…: hit if `low ≤ stop` (long) / `high ≥ target`; fill at the level (gap-through fills at open). **Same-bar both-hit resolves to stop first** (conservative).
- Partial fills: fill qty capped at `volume_participation_pct` (default 10%) of the bar's volume; remainder re-attempted next bar (max 5 bars, then cancelled and logged in the trade record).
- Commissions: `per_order_usd` (default 0) + `per_share_usd` (default 0) — Alpaca-style zero-commission default, configurable.
- Sizing hook: `production` mode builds `SizingInputs` (simulated equity, price, ATR-14, stop distance from adapter stops, `regime_label="NEUTRAL"`, `sentiment_polarity=0.0`, `intraday_dd_pct=0.0`, `side="BUY"`, `contract_multiplier=1`, `lot_size=1`, and `requested_qty=Decimal("0")` — required by the dataclass but unread by `compute_size`; a test asserts it stays unread so a future sizing change breaks loudly) and calls `apps.risk.sizing.compute_size` with a profile obtained via `RiskProfile.objects.get_or_create(user=run.user)` (model defaults — same behavior as the risk view's `_get_or_create_profile`). **Documented divergence:** live `apply_sizing` *skips sizing entirely* for profile-less users; the backtest instead sizes with default-profile values — stated in ADR-091 and the UI help text. **ATR-14 must replicate `apps/risk/integration.py::_atr14` exactly** (simple mean of the last ≤ 14 true ranges over 15 bars — not Wilder smoothing), else backtest qty silently diverges from production. `fixed_qty_1` sizes every entry at 1 share.
- Fixed semantics (all four in ADR-091): **long-only in MVP** (adapters emit boolean entries/exits; short signals out of scope); same-bar `entries` and `exits` both true → no-op; **each test segment replays from `initial_cash`** (OOS concatenation compounds in return space, §6.4) — equity does *not* carry across windows; open positions at a segment's final bar are **force-closed at that bar's close** with slippage and commission applied (no exemption).
- Outputs: equity series, drawdown series, per-trade records (incl. MFE/MAE from bar extremes while in-trade), exposure and turnover. Pure function of inputs — no I/O, no RNG.

### 6.4 Walk-forward orchestrator (`apps/backtest/wf.py`)

```python
def walk_forward(adapter, bars, cfg) -> WFResult:
    windows = []
    t = cfg.start
    while t + timedelta(days=cfg.train_days + cfg.test_days) <= cfg.end:
        train_start = cfg.start if cfg.anchored else t
        train_end   = t + timedelta(days=cfg.train_days)
        test_end    = train_end + timedelta(days=cfg.test_days)
        # ALL intervals half-open [start, end). Sweep receives the FULL bars frame plus
        # boundaries so warm-up context before train_start is available to indicators;
        # signals are masked to ts >= train_start and evaluated on ts < train_end.
        ranking = sweep_engine.run(bars, train_start, train_end, adapter, cfg.grid, cfg.costs, cfg.metric)
        best = ranking.top()                     # ties broken deterministically (param tuple order)
        seg = replay(bars, train_end, test_end, adapter, best.params, cfg)   # same: full frame + [test_start, test_end)
        windows.append(Window(train_start, train_end, test_end, best.params, seg))
        t += timedelta(days=cfg.step_days)       # MVP: step_days == test_days ⇒ contiguous, non-overlapping OOS
    return concat_oos(windows)                   # compounds per-segment daily returns into one OOS curve
```

- Windows are **calendar days** over daily bars, half-open `[start, end)` throughout; anchored mode grows the train window from `cfg.start`. Trailing days that don't fill a complete train+test window are dropped (explicit, per the loop bound).
- **Worked example (pins the §10.1 golden fixtures):** `start=2020-01-01, end=2021-01-01, train=180, test=60, step=60, rolling` ⇒ exactly 3 windows: w0 train `[2020-01-01, 2020-06-29)` test `[2020-06-29, 2020-08-28)`; w1 train `[2020-03-01, 2020-08-28)` test `[2020-08-28, 2020-10-27)`; w2 train `[2020-04-30, 2020-10-27)` test `[2020-10-27, 2020-12-26)`; trailing `[2020-12-26, 2021-01-01)` dropped. Anchored: same boundaries with every `train_start=2020-01-01`. Note w_i's test start equals w_{i-1}'s test end — contiguous, zero overlap under half-open intervals.
- MVP validation `step_days == test_days` + half-open intervals guarantee the concatenated OOS curve double-counts nothing; the field stays for future overlapping-window analysis.
- Runs with < 2 complete windows are rejected up front (`VALIDATION_ERROR`).
- Multi-symbol runs execute this per symbol sequentially; progress pct accounts for symbols × windows.

### 6.5 PBO (`apps/backtest/pbo.py`)

- **Input matrix M is built from one dedicated full-range sweep per symbol** (unit sizing, run cost model, all grid combos over `[start, end)`): M = T×N matrix of daily net returns, T = trading days, N = combos. M is **not** assembled from the per-window train sweeps — rolling windows overlap whenever train > test and anchored trains nest, which would duplicate calendar periods and break CSCV's disjoint-block premise. PBO is computed and reported **per symbol**.
- CSCV per Bailey et al. (2015): split M into **S=16 contiguous time-ordered blocks** (S fixed — C(16,8)=12 870 partitions; larger S explodes combinatorially); truncate trailing rows so T is a multiple of S; for each of the C(S, S/2) train/test partitions, find the IS-best combo and its OOS relative rank; PBO = fraction of partitions where the IS-best ranks in the bottom half OOS (logit λ ≤ 0, per paper).
- **Implementation must be vectorized** via precomputed per-block per-combo statistics (block sums / counts), evaluating all 12 870 partitions as matrix ops — a naive per-partition Python loop (~1–2 min) would alone blow the ≤ 60 s CI smoke (AC-09-10).
- Degenerate inputs: if N < 10 or T < 2S, skip PBO — `pbo: null` in the report + an "insufficient trials for overfit estimate" note on the tearsheet.
- Output PBO ∈ [0,1]; report warns prominently when PBO > 0.5.
- Tests: synthetic known-answer cases per §5 (no "paper reference numbers" exist to test against — the earlier draft was wrong about that).

### 6.6 Reporting (`apps/backtest/report.py`, `stats.py`)

- `stats.py`: all AC-09-6 performance metrics implemented in-repo over numpy/pandas (no quantstats dependency), each unit-tested against hand-computed fixtures. Annualization on 252 trading days. (**Named `stats.py`, not `metrics.py`** — `apps/backtest/metrics.py` is reserved for Prometheus objects per the repo's per-app convention, §12.)
- **JSON**: canonical export (sorted keys, floats rounded 1e-9) of config, per-symbol metrics, per-window table, OOS equity + drawdown series, full trade list. `metrics_hash` = SHA-256 of it (reproducibility DoD item, §5).
- **HTML**: single-file Plotly (python `plotly`, MIT) with `include_plotlyjs="inline"` — fully offline, no CDN.
- **PDF**: WeasyPrint (`>=68,<69`) from a Django template; charts rendered server-side by **matplotlib to SVG** with `svg.fonttype="none"` (real `<text>` elements → selectable text; verify WeasyPrint renders them with the installed DejaVu fonts) — Plotly/kaleido is *not* used for PDF; kaleido's headless-Chrome dependency is deliberately avoided. Sections: cover (strategy, range, config summary, **disclaimer block**, PBO badge), OOS equity, drawdown, monthly-returns heatmap, per-window Sharpe bars, top-20 trades by |P&L|, full metrics table. The disclaimer text lives in the §13 server-side locale dict; "non-removable" means it is baked into the template flow and is never part of run config or caller-supplied context.
- Artifacts persisted on `BacktestReport` (`json` JSONField, `html`/`pdf` BinaryField) — sizes recorded; guard: any artifact > 25 MB fails the run with `BACKTEST_REPORT_TOO_LARGE` (should never trigger at MVP scale).

### 6.7 API (`apps/backtest/{serializers,views,urls}.py`)

Mounted at `path("api/v1/backtest/", include("apps.backtest.urls"))`; JWT + MFA per repo defaults; `{"data": ...}` / `{"error": {"code", "message"}}` envelope via the existing exception handler; PageNumber pagination (25).

```
POST /api/v1/backtest/runs/                  create + enqueue  (201; caps → 400/409)
GET  /api/v1/backtest/runs/?status&from&to   list (owner-scoped)
GET  /api/v1/backtest/runs/{id}/             detail incl. segments + progress snapshot
POST /api/v1/backtest/runs/{id}/cancel/      → 202, status CANCELLING
GET  /api/v1/backtest/runs/{id}/report.json
GET  /api/v1/backtest/runs/{id}/report.html  (Content-Disposition: inline)
GET  /api/v1/backtest/runs/{id}/report.pdf   (authenticated stream, attachment)
```

Error codes: `BACKTEST_NO_ADAPTER`, `BACKTEST_INSUFFICIENT_DATA`, `BACKTEST_LIMIT_CONCURRENT` (409), `BACKTEST_GRID_TOO_LARGE`, `BACKTEST_REPORT_TOO_LARGE`, `BACKTEST_TIME_CAP` (run failed on the 25-min soft limit), `BACKTEST_DISABLED` (503, flag off), plus standard `VALIDATION_ERROR`. Regenerate the OpenAPI schema + frontend types (`make schema` flow).

### 6.8 Celery orchestration (`apps/backtest/tasks.py`)

- `run_backtest(run_id)` — routed to the **`backtest` queue** via an **explicit per-task route** `CELERY_TASK_ROUTES = {"apps.backtest.tasks.run_backtest": {"queue": "backtest"}}` (first task-route in the repo; default worker keeps consuming only `celery`). **Do not use a `apps.backtest.tasks.*` glob** — it would drag the eviction task onto the backtest queue and silently break the retention guarantee below; eager-mode tests ignore routing entirely, so this mistake passes CI (add a small settings unit test asserting the route map). `soft_time_limit=1500`, `time_limit=1800`; on `SoftTimeLimitExceeded` mark FAILED with `BACKTEST_TIME_CAP`.
- New compose service `worker-backtest`: `celery -A config.celery worker -Q backtest -l info --concurrency=1 --max-memory-per-child=2000000`. **Railway:** creating the same service on staging/prod is an operator step (documented in the report + runbook).
- Progress: reuse `apps.dashboard.events.push_to_user` — new event constants `backtest.progress`, `backtest.completed`, `backtest.failed`, `backtest.cancelled`. Throttle progress pushes to ≥ 1 s apart. ETA from completed/total (symbols × windows).
- Cancellation: cancel endpoint sets `status=CANCELLING`; task checks the flag between windows and between sweep chunks (both < 30 s granularity on target hardware) and exits cleanly as `CANCELLED`.
- Beat (redbeat, existing pattern in `base.py` `CELERY_BEAT_SCHEDULE`): `backtest-evict-artifacts` nightly at 03:30 UTC — nulls artifacts on runs past retention, keeps rows + `run.summary` + segments. **The eviction task runs on the default `celery` queue** (not `backtest`), so retention keeps working when the backtest worker is scaled to zero or not yet provisioned — this is also what makes §15's "eviction doubles as orphan cleanup while disabled" true.
- **Prod consequence, stated plainly:** until the operator creates the Railway `worker-backtest` service, every prod run sits `QUEUED` forever (the queue-wait alert fires). Marked as an operator step in the runbook and the execution report.

### 6.9 UI — Angular

Routes (lazy `loadChildren` → `features/backtest/backtest.routes.ts`, `canMatch: [authGuard]`; the `features/backtest/` dir exists empty and `nav.backtest` i18n key already exists):

`/backtest` — launcher + runs list:
- Strategy picker (only adapter-registered strategies enabled; others show the no-adapter banner).
- Symbol multi-select (≤ 10), date range, train/test/step inputs (step auto-synced to test in MVP), mode, metric, initial cash, costs, retention days (advanced, default 90), sizing toggle ("Production sizing (regime/sentiment neutralized)" | "Fixed qty 1").
- Param grid editor: **plain `<textarea>` with live `JSON.parse` validation** (webhook-config precedent — Monaco is a known esbuild breaker, see `webhook-config-modal.component.ts` header note).
- Runs table (status chips, created, duration, PBO — worst per-symbol PBO from `run.summary` for multi-symbol runs), pagination; cancel button on active runs.

`/backtest/:id` — run detail:
- Status header with live progress bar + stage + ETA via the existing `DashboardWsService.events$` (filter `type.startsWith("backtest.")`); fallback: poll detail endpoint every 5 s when the socket is down.
- Chart tabs: Equity, Drawdown, Monthly heatmap, Per-window — **chart.js@4 + chartjs-chart-matrix (MIT)**, imported dynamically inside the lazy backtest bundle only (keeps the initial bundle within `angular.json` budgets).
- Metrics table (per symbol), segments table (per-window params + Sharpe).
- Download JSON/HTML/PDF via the blob pattern from `orders.facade.ts::exportCsv`; "Rerun with same config" clones into the launcher.

Layers per house style: `core/services/backtest.api.ts` → `abstraction/stores/backtest.store.ts` (signals) → `abstraction/facades/backtest.facade.ts` → standalone components; all strings via `ngx-translate` keys `backtest.*` in `en.json`.

## 7. Tech Stack Notes

- **vectorbt `==1.0.0`** (exact pin; fair-code license reading + swap-seam rationale in ADR-090). Python ≥ 3.10 ✓ (repo is 3.12). Do **not** install `[full]`/`[rust]` extras — base only.
- **Custom replay engine** — replaces backtrader (GPLv3, last release 2023-04, classifiers stop at py3.7). Rationale + exact fill semantics in ADR-090/091.
- **WeasyPrint `>=68,<69`** (BSD). Needs Pango/HarfBuzz/fontconfig + fonts (`libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core` on Debian slim) in **both** `docker/backend.Dockerfile` and the CI backend job. No Cairo (≥ v53 doesn't use it).
- **matplotlib** (PSF-style license) for PDF SVGs; **plotly** (MIT) for the HTML report only — **no kaleido**. Both arrive transitively with vectorbt 1.0.0 anyway (§6.2); pin them explicitly in `base.txt` regardless so the versions we render with are deliberate.
- **chart.js@4 + chartjs-chart-matrix** (MIT) frontend, lazy-loaded; keep `pnpm-lock.yaml` in sync.
- No quantstats, no `bt`, no joblib, no new numba pin beyond what vectorbt brings.

## 8. Data Model Changes

Migration `backtest.0001_initial` (app stub already in `INSTALLED_APPS`):

- `BacktestRun` — uuid pk, `user` FK, `strategy` FK, `config` JSON (full AC-09-1 payload), `status` (`QUEUED/RUNNING/CANCELLING/COMPLETED/FAILED/CANCELLED`), `stage`, `pct`, `error_code`/`error_message`, **`summary` JSON (per-symbol headline metrics incl. PBO, written at completion — source for the runs list and the post-eviction record)**, `metrics_hash`, `retention_days` (default 90, ≤ 365), `celery_task_id`, `started_at`/`finished_at`, timestamps. Indexes: `(user, -created_at)`, `(status)`.
- `BacktestSegment` — FK run, `symbol`, `window_index`, train/test date ranges, `best_params` JSON, `oos_metrics` JSON. Unique `(run, symbol, window_index)`.
- `BacktestReport` — OneToOne run, `json` JSONField (null), `html` BinaryField (null), `pdf` BinaryField (null), `html_bytes`/`pdf_bytes` size ints, `created_at`. **Eviction nulls `html`/`pdf` and the `json` artifact entirely; `run.summary` and `BacktestSegment` rows survive** (this is what AC-09-11's "rows keep metrics" means).

SQLite-compatible by construction (JSON + BinaryField) — the default test suite needs no Postgres.

## 9. API Contract Changes

Paths + error codes per §6.7; OpenAPI schema + generated frontend types updated in the same PR (repo rule: types are generated from the repo-root `docs/openapi/openapi.json`).

## 10. Test Plan

### 10.1 Unit

- PBO synthetic known-answer + property tests (§5, §6.5).
- WF window math: rolling + anchored fixtures (exact expected window tuples), `step==test` validation, < 2 windows rejected, warm-up bars respected at every boundary.
- Replay engine golden files: canned bars + params → exact trade list (entries, partial-fill sequences, stop-first same-bar case, gap-through stop, MFE/MAE values). Property tests: fills within bar range, cash ≥ 0, equity reconciles to trades.
- Metrics: each AC-09-6 metric vs hand-computed reference frames.
- Sizing parity (AC-09-12, non-tautological form): fixture user/profile/bars → assert the `SizingInputs` the replay constructs equals what `apply_sizing` would construct for the same trade (excepted fields: regime/sentiment/intraday_dd neutralized, `stop_distance` — production passes `None` while the replay populates it from adapter stops), including an identical `_atr14` value; then assert equal qty through `compute_size`. Because `_atr14` has no as-of parameter (always the latest 15 stored bars), the compared trade must sit at the fixture's final bar. Plus: assert `requested_qty` stays unread by `compute_size`.
- Adapter: `sma_cross` golden signal fixture; look-ahead guard (mutating future bars must not change past signals).
- Report: PDF renders headless with all sections (assert text extractable, non-zero SVGs); JSON canonicalization → stable hash.

### 10.2 Integration (Celery eager where possible)

- Full 1-year WF on fixture bars (seeded via `upsert_bars`): completes, all three artifacts produced, segments persisted, `run.summary` written, WS events emitted (capture via channels test utils), metrics_hash stable across two runs. **The happy-path fixture must include realistic holiday gaps** (e.g., omit New Year's Day and Christmas) so the §6.0 weekday-coverage rule is exercised against a real-shaped calendar, not an all-weekdays fixture that can't catch threshold bugs.
- Cancellation: flag flips mid-run (chunk boundary) → `CANCELLED`, no report.
- 400/409 paths: `BACKTEST_NO_ADAPTER`, `BACKTEST_INSUFFICIENT_DATA` (gapped fixture), `BACKTEST_GRID_TOO_LARGE`, `BACKTEST_LIMIT_CONCURRENT`, flag-off 503.
- Retention eviction job nulls expired artifacts only.

### 10.3 E2E / frontend

- Karma specs for `backtest.store` + facade (submit → progress event application → download call), matching the existing store-spec pattern. (CI runs `pnpm build` only — specs exist for local/`test:ci`; extending `ci.yml` is out of scope.)
- Manual checklist in PR: launcher happy path → PDF downloaded; progress bar updates; rerun clones config.

### 10.4 Performance

- Local CI smoke: 1y daily, 1 symbol, grid ≤ 24 ⇒ ≤ 60 s.
- Staging (deferred, operator): 3y ≤ 10 min, 10y ≤ 30 min, worker RSS ≤ 2 GB; procedure in the runbook.

### 10.5 Reproducibility

- Same config run twice ⇒ identical `metrics_hash`. Numba JIT vs non-JIT paths must agree (run the smoke both ways once in CI via `NUMBA_DISABLE_JIT`).

## 11. Security Considerations

- Runs are owner-scoped end to end (queryset filtering); system strategies (`is_system=True`) are backtestable by any authenticated user, community/user strategies only by their owner.
- **No arbitrary code execution:** adapters are repo-owned code; `param_grid` values validated as bounded numerics/enums against the adapter's declared grid; config JSON schema-validated.
- Resource caps (enforced at POST): ≤ 2 concurrent runs per user (409), grid ≤ 500 combos, ≤ 60 windows, date range ≤ 15 y, symbols ≤ 10. Worker-side: soft/hard time limits 25/30 min, `--max-memory-per-child` 2 GB, dedicated queue.
- Artifact downloads are authenticated + owner-checked streams (no public URLs; DB-stored artifacts per header note).
- MFA enforcement follows repo API defaults; no additional re-prompt (read-only analytics, not a trading action).

## 12. Observability

Per-app `metrics.py` pattern (module-level `prometheus_client` objects; multiprocess rules per repo gotchas — don't assert on `process_*`/`django_db_*`):

- `backtest_runs_total{status}` counter; `backtest_run_duration_seconds` histogram (buckets to 1800 s); `backtest_active_runs` gauge; `backtest_failed_total{reason}` counter; `backtest_artifact_bytes` gauge (summed at eviction/write; no `_total` suffix — that's reserved for counters); `backtest_queue_wait_seconds` histogram (enqueue→start).
- Alerts (rules committed; live wiring is M10): queue wait p95 > 10 min; any run hits the hard time cap; failed-rate > 20% over 1 h.
- Grafana **Backtest Ops** dashboard JSON committed; "live on staging" is operator-deferred.

## 13. Translation & Localization

- UI copy keyed `backtest.*` in `frontend/src/assets/i18n/en.json` (only `en` ships today; ngx-translate per house rules — no hard-coded strings).
- Report labels (PDF/HTML sections, metric names, disclaimer, PBO warning) come from a server-side dict keyed by language, default `en` — structure ready for locales, only `en` populated. Dates ISO-8601, numbers `en` formatting; full locale-aware formatting deferred with the second locale.

## 14. Documentation Deliverables

- `docs/adr/090-vectorbt-plus-custom-replay.md` — engine choices: vectorbt OSS 1.0 fair-code reading + `SweepEngine` seam; backtrader rejected (GPLv3 + dormant); replay-engine ownership rationale. (ADR numbers 090–092 verified free; highest existing is 081.)
- `docs/adr/091-walk-forward-protocol.md` — window math, `step==test` MVP rule, OOS concatenation, replay fill semantics, determinism/hash procedure.
- `docs/adr/092-strategy-python-adapter.md` — adapter contract, registry, warm-up bars, no-uploaded-code security stance.
- `docs/runbooks/backtest-stuck.md` — diagnose queue/worker, cancel/kill, orphan cleanup, staging perf procedure, Railway `worker-backtest` service setup.
- User help: "Running your first backtest", "Reading the tearsheet", "Interpreting PBO".
- `project-plan/PROGRESS.md`: mark the pre-M09 licensing blocker resolved (per header note) + milestone status on close.

## 15. Rollback Plan

- `BACKTEST_ENABLED` (env.bool, default True) — off: UI nav hidden + all endpoints return 503 `BACKTEST_DISABLED`. Matches the repo's per-milestone master-flag convention.
- Per-user concurrency and grid caps adjustable via settings without deploy of code changes.
- Migrations are additive-only; the eviction job doubles as orphan cleanup if the feature is disabled with artifacts in place. Scale `worker-backtest` to zero to stop all processing instantly.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| vectorbt 1.0.0 is recent (2026-04); resolver or numba issues on py3.12/CI | Med | Med | Day-1 install+smoke task (§6.2); exact pin; `NUMBA_DISABLE_JIT` test path; `SweepEngine` seam keeps a custom fallback contained. |
| Custom replay engine gets execution semantics subtly wrong | Med | High | Semantics written down first (ADR-091); golden-file + property tests; conservative same-bar rule; cross-check one config against vectorbt under zero-costs/no-stops **with aligned fills** (entries/exits shifted one bar + `price=open`, per §6.2) — must match within tolerance. |
| Look-ahead bias in adapters or loader | Med | High | Past-only contract, warm-up prefetch, next-bar-open fills, index-alignment tests. |
| Over-optimistic results (costs too low) | Med | High | Slippage floor 1 bp, defaults surfaced in UI and printed on the tearsheet cover; disclaimer + PBO badge. |
| DB artifact growth (artifacts are DB-stored by decision) | Med | Low | Retention eviction, 25 MB per-artifact guard, `backtest_artifact_bytes` metric; documented R2 revisit trigger (~5 GB). |
| Long runs starve the box / order flow | Low | High | Dedicated queue + worker, time/memory caps, concurrency + grid caps, cancel path. |
| WeasyPrint system deps missing in CI or image | Med | Med | Explicit apt list in both Dockerfile and `ci.yml` (§5); PDF render test in the suite. |
| Backtest results diverge from production sizing | Low | Med | AC-09-12 parity test on `compute_size`; neutralized inputs documented in UI copy. |

## 17. Exit Gate Checklist

- [ ] AC-09-1 … AC-09-12 pass (AC-09-10 staging SLA explicitly marked deferred if no staging run happened).
- [ ] Sample 3-year WF PDF generated on the demo strategy + reviewed (synthetic 3y fixture bars acceptable; real-symbol data requires the M06 backfill first — operator + FMP key). 
- [ ] Reproducibility hash test green (JIT and non-JIT).
- [ ] Backtest Ops dashboard JSON committed (staging "live" may be deferred).
- [ ] ADRs 090–092 committed.
- [ ] User help docs published.
- [ ] `CHANGELOG.md` + `PROGRESS.md` + tracker updated.
- [ ] Tag `v0.9.0-backtest` (created; pushing = prod deploy, operator-gated).

Proceed to **M10 Admin + Audit + Observability**.
