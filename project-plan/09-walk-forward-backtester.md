# Milestone 09 — Walk-Forward Backtester

> **Week:** 9
> **Duration:** 5 working days
> **Depends on:** M06 (Market Data), M08 (Risk sizing primitives reused)
> **Unlocks:** M10 (Admin + Audit + Observability) — backtest reports stream into observability as sanity metrics

## 1. Purpose

Deliver a two-stage walk-forward backtesting subsystem: vectorbt for fast parameter sweeps and backtrader for realistic, path-dependent execution validation. Produce an authoritative tearsheet (PDF + HTML + JSON) for any strategy on demand. Make the backtester a first-class citizen so strategies earn the right to trade live by demonstrating stable out-of-sample performance.

## 2. In Scope

- `backtest` Django app: `BacktestRun`, `BacktestReport` models; REST + Celery orchestration.
- vectorbt-based signal/param sweep with configurable parameter grid.
- backtrader replay of the selected params with realistic slippage/commission.
- Walk-forward orchestrator: rolling or anchored windows, configurable train/test/step.
- Tearsheet PDF (WeasyPrint) + HTML (Plotly) + JSON.
- PBO (Probability of Backtest Overfit) calculation on the sweep.
- Progress streaming via WebSocket.
- Cancellation.
- Artifact storage (object storage) with signed URL downloads.
- UI: backtest launcher, runs list, run detail with charts, report download.
- Reuse of M08 sizing primitives so backtest results reflect production sizing behavior.

## 3. Out of Scope

- Monte Carlo path generation for robustness — post-MVP extension.
- Multi-asset portfolios — single-symbol (or paired long/short pair) runs in MVP; multi-symbol basic support but no optimization across symbols.
- Using backtester as live paper-trade equivalent — already covered by paper brokers.
- Optimization of Pine strategies at Pine level — Pine isn't executed; we translate strategies to Python via adapters (§6.2).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-09-1 | User submits a backtest with `strategy`, `symbols[]`, `start`, `end`, `train_window_days`, `test_window_days`, `step_days`, `anchored|rolling`, and a param grid JSON. |
| AC-09-2 | Celery task runs on a dedicated `backtest` queue; does not interfere with order flow. |
| AC-09-3 | vectorbt sweep ranks combinations by a user-selected metric (Sharpe default); top-1 passes to backtrader replay. |
| AC-09-4 | backtrader replay produces per-trade records with MFE/MAE, partial fills, slippage modeled by configurable bp of spread. |
| AC-09-5 | Walk-forward orchestrator concatenates test segments into a continuous OOS equity curve; per-window param choices persisted. |
| AC-09-6 | Final report includes: total return, CAGR, Sharpe, Sortino, MAR, Max DD, %win, profit factor, avg win/loss, expectancy, exposure%, turnover, PBO, per-window Sharpe stability. |
| AC-09-7 | PDF tearsheet rendered with charts (equity curve, drawdown, monthly returns heatmap, per-window metrics). |
| AC-09-8 | Progress streamed via WebSocket events `backtest.progress { run_id, pct, stage, eta_seconds }`. |
| AC-09-9 | User can cancel a running backtest; worker halts within 30s. |
| AC-09-10 | A 3-year daily walk-forward on one symbol completes in ≤ 10 min on staging hardware; 10-year in ≤ 30 min. |
| AC-09-11 | Reports retained 90 days default; user-configurable up to 365 days; eviction runs nightly. |
| AC-09-12 | Sizing applied during backtest matches production M08 logic (reused function), with a clearly-labeled "Production sizing" toggle. |

## 5. Definition of Done

Baseline DoD applies, plus:

- Backtest engine has deterministic output for fixed seeds and inputs (verified by hash).
- PBO calculation implemented per Bailey et al. (2015); unit test against paper's reference numbers.
- Report PDF passes basic accessibility (text not rasterized images).
- Runbook `docs/runbooks/backtest-stuck.md` committed.
- Strategy-to-Python adapter contract documented (how a new strategy is registered for backtesting).

## 6. Implementation Tasks

### 6.1 Strategy adapters

Because Pine scripts don't execute server-side, each strategy needs a **Python backtest adapter** that reproduces its entry/exit logic. Options:

1. **Preferred:** Each system strategy ships with a Python module at `backend/apps/backtest/strategies/<slug>.py` implementing a `BacktestStrategy` interface:
   ```python
   class BacktestStrategy(Protocol):
       slug: str
       def generate_signals(self, bars: pd.DataFrame, params: dict) -> pd.Series: ...
       def param_grid(self) -> dict[str, list]: ...
   ```
2. **Fallback** for community-uploaded strategies without an adapter: backtest is disabled with a clear "Backtest not available — no Python adapter registered" banner.

The Trading Strategies project import (§M03) populates both `.pine` + description + a companion `_backtest.py` for system strategies.

### 6.2 vectorbt sweep (`apps/backtest/vbt_engine.py`)

- Construct signals from `strategy.generate_signals()`.
- `vbt.Portfolio.from_signals(close, entries, exits, ...)` with sizing hooks reusing M08 `compute_size`.
- Parameter sweep via vectorbt's vectorized parameter broadcasting.
- Score each combination by chosen metric; rank.

### 6.3 backtrader replay (`apps/backtest/bt_engine.py`)

- Build `bt.Cerebro` with:
  - Data feed from our `Bar` store (pandas DataFrame).
  - Strategy class implementing the same logic as vectorbt version, but with stop/target logic.
  - Broker with commission scheme per asset class (stocks: $0.005/share + exchange fees; options: $0.65/contract).
  - Slippage model: fixed bp of spread or percent of price.
- Run, collect TradeAnalyzer stats, equity curve, drawdown series, per-trade records.

### 6.4 Walk-forward orchestrator (`apps/backtest/wf.py`)

```python
def walk_forward(strategy, symbol, start, end, train_days, test_days, step_days, anchored):
    segments = []
    t = start
    while t + timedelta(days=train_days+test_days) <= end:
        train_start = start if anchored else t
        train_end = t + timedelta(days=train_days)
        test_start = train_end
        test_end = train_end + timedelta(days=test_days)

        best_params, sweep = vbt_sweep(strategy, symbol, train_start, train_end)
        segment_result = bt_replay(strategy, symbol, test_start, test_end, best_params)

        segments.append((best_params, segment_result, sweep))
        t += timedelta(days=step_days)
    return concatenate(segments)
```

### 6.5 PBO calculation (`apps/backtest/pbo.py`)

- Combinatorially-symmetric cross-validation (CSCV) per Bailey et al.
- Inputs: matrix of strategy returns per parameter combo across folds.
- Output: PBO probability ∈ [0,1]; report warns if PBO > 0.5.

### 6.6 Reporting (`apps/backtest/report.py`)

- JSON export of all metrics + equity curve + trades.
- Plotly HTML single-file export.
- WeasyPrint PDF:
  - Cover page (strategy name, date range, params summary, PBO warning badge).
  - Equity curve.
  - Drawdown series.
  - Monthly returns heatmap.
  - Per-window Sharpe bar chart.
  - Trades table (top 20 by P&L).
  - Full metrics table.

### 6.7 API

```
POST /api/v1/backtest/runs/                 create + start
GET  /api/v1/backtest/runs/?status&from&to
GET  /api/v1/backtest/runs/{id}/
POST /api/v1/backtest/runs/{id}/cancel/
GET  /api/v1/backtest/runs/{id}/report.json
GET  /api/v1/backtest/runs/{id}/report.pdf  signed URL
GET  /api/v1/backtest/runs/{id}/report.html
```

### 6.8 UI — Backtest launcher

Route: `/backtest`:
- Strategy picker.
- Symbol picker (multi-select; limit 10 in MVP).
- Date range + window sliders.
- Param grid editor (JSON).
- Sizing toggle ("Production" | "Unit size 1 share").
- Submit → run detail with live progress bar, canceling button.

Route `/backtest/:id`:
- Status header with progress.
- Chart tabs: Equity, Drawdown, Monthly heatmap, Per-window.
- Metrics table.
- Download PDF button.
- Rerun with same config button.

## 7. Tech Stack Notes

- **vectorbt** `1.0.x`. Be mindful of license (AGPL for community edition — acceptable for our internal use; confirm in ADR).
- **backtrader** `1.9.x`. Stable and battle-tested.
- **WeasyPrint** for PDF; requires Cairo + Pango libs in Dockerfile.
- **Plotly** for HTML.
- **`bt`** or `quantstats` considered; decision: keep to vectorbt + backtrader.

## 8. Data Model Changes

Migrations:
- `backtest.0001_initial` — `BacktestRun`, `BacktestReport`, `BacktestSegment` (per walk-forward window).

## 9. API Contract Changes

Paths per §6.7.

## 10. Test Plan

### 10.1 Unit tests

- PBO against reference inputs from Bailey et al.
- WF orchestrator segments computed correctly for rolling + anchored.
- Sizing reuse: backtest and production produce identical qty for same inputs.
- Strategy adapter: golden signal fixture for a sample strategy.
- PDF renders with all sections without errors on headless environment.

### 10.2 Integration

- Full 3-year WF on fixture data completes within SLA; all artifacts produced.
- Cancellation mid-run halts worker; run marked CANCELLED.
- Missing strategy adapter → 400 with `BACKTEST_NO_ADAPTER`.

### 10.3 E2E

- UI launcher happy path → PDF downloaded.
- Progress bar updates during run.
- Rerun clones params correctly.

### 10.4 Performance

- 3y daily single-symbol WF ≤ 10 min.
- 10y daily ≤ 30 min.
- Memory peak ≤ 2 GB in backtest worker.

### 10.5 Reproducibility

- Running same config twice produces identical metrics hash.

## 11. Security Considerations

- Backtest runs user-scoped; user cannot request runs for another user's strategies (unless system strategies accessible read-only).
- Resource caps: per-user concurrent backtests limited (2 default); CPU time limit per run (30 min hard kill).
- Object storage signed URLs: 1h TTL; per-user prefix in R2.
- No arbitrary code execution: strategy adapters are code owned by us (system strategies). Community strategies without adapter cannot backtest.

## 12. Observability

- Prometheus:
  - `backtest_runs_total{status}`
  - `backtest_duration_seconds` histogram
  - `backtest_queue_depth`
  - `backtest_failed_total{reason}`
- Alerts:
  - Queue depth > 5 for > 10 min.
  - Any run exceeds hard time cap.
- Grafana: **Backtest Ops** dashboard.

## 13. Translation & Localization

- UI copy keyed `backtest.*`.
- PDF tearsheet sections (headings, labels, axis) pulled from a dict keyed by language; default `en`. Numbers formatted via locale.
- Metrics names translated: `backtest.metric.sharpe`, `backtest.metric.mar`, etc.
- Dates on charts use user's locale format.
- PBO warning text translated; recommended-action text translated.

## 14. Documentation Deliverables

- `/docs/adr/090-vectorbt-plus-backtrader.md`.
- `/docs/adr/091-walk-forward-protocol.md`.
- `/docs/adr/092-strategy-python-adapter.md`.
- `/docs/runbooks/backtest-stuck.md`.
- User help: "Running your first backtest", "Reading the tearsheet", "Interpreting PBO".

## 15. Rollback Plan

- Feature flag `BACKTEST_ENABLED` hides UI + returns 503 from endpoints.
- Per-user concurrent limit adjustable via settings.
- Object-storage cleanup job ensures orphaned artifacts don't accumulate on rollback.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Backtest hangs on edge-case data | Med | Med | Hard time cap; cancel path; runbook to investigate. |
| vectorbt / backtrader version drift breaks results | Med | Low | Pin versions; golden-file regression tests. |
| Look-ahead bias in strategy adapter | Med | High | Adapter contract specifies `bars` is a past-only view; tests for index alignment. |
| Over-optimistic results due to no slippage | Med | High | Slippage default > 0; surfaced prominently in UI; minimum bp floor. |
| Object storage fills up | Low | Low | Retention job; alert on usage > 80%. |

## 17. Exit Gate Checklist

- [ ] AC-09-1 … AC-09-12 pass.
- [ ] Sample 3-year WF PDF generated + reviewed.
- [ ] Reproducibility hash test green.
- [ ] Backtest Ops dashboard live.
- [ ] ADRs 090–092 committed.
- [ ] User help docs published.
- [ ] Tag `v0.9.0-backtest`.

Proceed to **M10 Admin + Audit + Observability**.
