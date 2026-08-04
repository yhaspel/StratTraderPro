# Milestone 06A — Per-Symbol Regime (Markov Hedge Fund Method)

> **Slot:** After M06 (Market Data + Regime Classifier). Sub-milestone / feature add.
> **Duration:** 4–5 working days
> **Depends on:** M06 (Bar store + regime infrastructure). Soft dependencies on M03 (strategies UI), M04 (webhook ingest gate), M08 (risk-engine sizing input).
> **Unlocks:** Per-symbol throttling in M08; per-strategy regime gates in M04; per-symbol regime badges in the M03 dashboard.
> **Status:** Planning

## 1. Purpose

Turn the deferred [M06 §3](06-market-data-and-regime.md) out-of-scope item — *"Per-symbol HMM (market-wide only in M06; per-symbol later)"* — into a real, shipped feature. Implement Roan's **Markov Hedge Fund Method** (rolling-return labeller → 3×3 transition matrix → stationary distribution → conviction signal) as a per-symbol regime layer that:

1. Replaces the [M06 §6.7](06-market-data-and-regime.md) `GET /api/v1/regime/symbol/{sym}/` 501 placeholder with a real response.
2. Feeds M08's sizing pipeline a **second** regime input (alongside the market-wide ensemble from M06).
3. Lets users gate individual strategies on the current per-symbol regime (M04 webhook ingest hook).
4. Surfaces per-symbol regime tags on the M03 strategies list and the dashboard.

This is the cheap, interpretable, per-asset complement to M06's heavyweight multi-feature market-wide ensemble — **not** a replacement for it, and **not** a tradable strategy in its own right.

## 2. Background & Rationale

### 2.1 Where the method comes from

Framework by Roan ([@RohOnChain](https://x.com/RohOnChain)), packaged with a Claude Code skill and a Pine v5 indicator by Lewis Jackson in his Quant Series video 1 ([video](https://youtu.be/ZVMTeDBmSrI), [repo](https://github.com/jackson-video-resources/markov-hedge-fund-method)). The upstream framework's own README is explicit: *"slot it into a trading agent you already have as a confirmation layer, a standalone signal, or a tail-risk filter — without rewriting your strategy."* That framing is the design brief for this milestone.

We are **re-implementing the math** against our own `Bar` store from M06 §6.2, **not vendoring the upstream skill**. Reasons documented in §11 and ADR 062.

### 2.2 Why per-symbol and not "just add it to M06"

- M06's ensemble already consumes a 15-feature vector (VIX, HY/IG OAS, breadth, NH/NL, yield curve, etc.) for the **market-wide** regime call. Adding a single-feature rolling-return labeller as a third leg of that ensemble would be strictly less informative and would muddy the decision table without measurable lift.
- The Markov method's headline outputs (3×3 transition matrix, stationary distribution, *n*-step forecast) only really make sense **per asset**. "What fraction of historical days did AAPL spend in Bear?" is a tradable property of AAPL. "What fraction did the market spend in Bear?" is a less-useful version of long-run VIX.
- StratTraderPro trades per symbol. Every M03 webhook alert names a symbol; every M08 sizing decision concerns a single position. A per-symbol regime layer maps cleanly onto how the platform actually executes.
- M06 §3 already deferred per-symbol HMM and §6.7 cut a 501 placeholder for it. This milestone fills that exact slot.

### 2.3 Why now — sequencing note

M04 is in progress (Phase A spike done; Phase B+ rescoped to Alpaca per ADR-041 — M04A was scrapped 2026-07-05), M05–M07 are not started. Strictly the dependency graph says this slots after M06 ships. Two safe paths:

- **Path A (default):** Park this plan; pick it up after M06 closes. The 06A label keeps it filed next to its parent.
- **Path B (interleave):** If we want a per-symbol "tail-heavy filter" surfaced to users before M06's market-wide regime UI lands, the model + API in §6.1–§6.3 below can ship standalone behind `SYMBOL_REGIME_ENABLED=False` and integrated into M08/M04 hooks once those land. Calls out the feature-flag gating in §15.

Default to Path A unless we hear otherwise.

## 3. In Scope

- New Django app submodule **`apps/regime/per_symbol/`** containing:
  - `TrackedSymbol` registry (symbols we actively model + asset class).
  - `SymbolRegimeModel` (fitted parameters per symbol).
  - `SymbolRegimeObservation` (daily decoded label + forecast horizons).
  - Pure-Python math module: rolling-return labeller, transition-matrix MLE with Laplace smoothing, stationary distribution solver, *n*-step forecast, conviction signal.
  - Optional `hmmlearn.GaussianHMM` 3-state per-symbol fit with graceful-degrade (mirrors M06's HMM fallback pattern).
- Two Celery beat tasks: nightly fit, end-of-day decode.
- A weekly tracked-symbol refresher that harvests symbols from recent fills + admin-pinned tickers.
- API:
  - `GET /api/v1/regime/symbol/{sym}/` (turn the M06 501 into 200)
  - `GET /api/v1/regime/symbol/{sym}/history/?from&to`
  - `GET /api/v1/regime/symbols/?active=true`
- M03 UI: per-row regime badge on the strategies list (small touch-up).
- M04 hook: optional `regime_gate` field on `WebhookConfig` that rejects an inbound alert if the symbol's current regime is not in an allow-list.
- M08 hook: extend `compute_size` to consume `symbol_regime` and apply (a) a scalar throttle by current label and (b) a "tail-heavy" filter on the stationary distribution's Bear mass.
- ADR 062 — math, smoothing, asset-class threshold defaults, Laplace prior, credit to Roan.
- Help page: "What the per-symbol regime badge means".

## 4. Out of Scope

- Real-time intraday regime (we use daily bars; intraday could come later).
- Multi-asset / cross-symbol coupling (per-symbol independence assumed).
- Tradable Pine *strategy* wrapper. The upstream `.pine` is a chart **indicator** with no entry/exit. If we ever want a tradable wrapper, that is a separate M03 system-strategy effort, not 06A.
- Replacing M06's market-wide ensemble. M06 stays the authoritative market context.
- Per-symbol regime for symbols we have no daily bars for (we don't backfill outside M06's bar pipeline here).
- Continuous re-fitting on every new bar — nightly is plenty.

## 5. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-06A-1 | Given ≥ 252 trading days of dailies in `marketdata.Bar`, a one-shot `fit_symbol_regime` produces a valid 3×3 row-stochastic transition matrix (rows sum to 1.0 ± 1e-9). |
| AC-06A-2 | The stationary distribution solves `πP = π, sum(π) = 1` and matches a direct eigen-solve to 1e-6 tolerance. |
| AC-06A-3 | Symbols with < 252 dailies return `status: "INSUFFICIENT_HISTORY"` from the API with no fitted artifact written. |
| AC-06A-4 | A symbol that has never visited a state gets Laplace-smoothed (`α=1`) transition probabilities; no row contains a 0.0 entry. |
| AC-06A-5 | `GET /api/v1/regime/symbol/{sym}/` returns current label, transition matrix, stationary distribution, *p_bull/p_bear/p_sideways* at horizons [1, 5, 20], conviction = `p_bull_h - p_bear_h`, model fit date, method (`ROLLING_RETURN` or `HMM`). |
| AC-06A-6 | History endpoint returns the labelled daily series; bytes-for-bytes reproducible given the same bars + thresholds (hash-pinned golden test). |
| AC-06A-7 | Nightly fit job processes every active `TrackedSymbol` and persists exactly one `SymbolRegimeModel` row per symbol per fit run; idempotent if rerun without new bars. |
| AC-06A-8 | If `hmmlearn` install/compile fails, the `HMM` method silently degrades to `ROLLING_RETURN`; pipeline does not fail; observation row records `method='ROLLING_RETURN'`. |
| AC-06A-9 | Strategies list (M03 UI) shows a regime badge per row when the strategy's primary symbol is in `TrackedSymbol`. Badge tooltip lists current label, conviction, and stationary Bear mass. |
| AC-06A-10 | When a `WebhookConfig.regime_gate.enabled=true` and the current per-symbol label is not in `allow_labels`, the webhook ingest rejects with HTTP 422 `REGIME_GATE_BLOCKED` and persists a `WebhookEvent(rejected_reason='REGIME_GATE_BLOCKED')`. (Soft-dependent on M04.) |
| AC-06A-11 | M08 `compute_size` applies `SYMBOL_REGIME_SCALE` after the market-wide `REGIME_SCALE`; given canned inputs, output qty is byte-identical to the spec table in §6.6. |
| AC-06A-12 | If `symbol_regime.stationary_distribution['BEAR'] > 0.40`, M08 emits the `SIZING_TAIL_HEAVY` audit annotation and applies an additional 0.5× scalar. |
| AC-06A-13 | When `SYMBOL_REGIME_ENABLED=false` (kill-switch flag), all 06A code paths short-circuit: M08 ignores the symbol-regime input, M04 ignores `regime_gate`, M03 hides the badge, and the API returns 503. |

## 6. Implementation Tasks

### 6.1 Math module (`apps/regime/per_symbol/math.py`)

Pure-functional, no Django, easy to unit-test and reuse in M09 backtester.

```python
LABELS = ("BULL", "SIDEWAYS", "BEAR")

def label_series(prices: pd.Series, *, window: int = 20,
                 bull_pct: float = 5.0, bear_pct: float = -5.0) -> pd.Series:
    """Rolling-return labeller. Returns a categorical series indexed by date."""

def transition_matrix(labels: pd.Series, *, alpha: float = 1.0) -> np.ndarray:
    """MLE with Laplace smoothing (α=1). Returns 3x3 row-stochastic."""

def stationary_distribution(P: np.ndarray) -> np.ndarray:
    """Solve πP = π, sum(π)=1 via left-eigenvector at λ=1."""

def n_step_forecast(P: np.ndarray, current: str, h: int) -> dict[str, float]:
    """Returns {'BULL': ..., 'SIDEWAYS': ..., 'BEAR': ...} at horizon h."""

def conviction(forecast: dict[str, float]) -> float:
    """p_bull - p_bear, ∈ [-1, 1]."""
```

Numerics:
- Laplace smoothing α=1 by default (configurable per asset class).
- Stationary distribution: prefer the linear-system `(P.T - I + ones).solve(ones)` formulation over eigen-decomposition for numerical stability; cross-check with eigen in tests.
- All inputs/outputs use `float64`; we round for storage only.

### 6.2 Asset-class threshold defaults

Per-asset-class tunable in `settings.SYMBOL_REGIME_DEFAULTS`. Initial table:

| asset_class | window_days | bull_pct | bear_pct | notes |
|---|---|---|---|---|
| US_EQUITY | 20 | +5.0 | -5.0 | Roan's upstream default; sanity-checked vs SPY 2010–2025 |
| US_ETF    | 20 | +5.0 | -5.0 | Same |
| CRYPTO    | 14 | +15.0 | -15.0 | Higher vol; shorter lookback |
| FX        | 30 | +2.0 | -2.0  | Lower vol; longer window |
| FUTURES   | 20 | +7.0 | -7.0  | Provisional; revisit when we trade them |

Per-symbol overrides supported via `TrackedSymbol.window_days / bull_threshold_pct / bear_threshold_pct`; nulls inherit the asset-class default.

### 6.3 Data model (`apps/regime/per_symbol/models.py`)

```python
class TrackedSymbol(models.Model):
    symbol = models.CharField(max_length=16, unique=True, db_index=True)
    asset_class = models.CharField(
        max_length=16,
        choices=[('US_EQUITY','US_EQUITY'),('US_ETF','US_ETF'),
                 ('CRYPTO','CRYPTO'),('FX','FX'),('FUTURES','FUTURES')],
        default='US_EQUITY',
    )
    is_active = models.BooleanField(default=True)
    window_days = models.PositiveSmallIntegerField(null=True, blank=True)
    bull_threshold_pct = models.DecimalField(max_digits=6, decimal_places=3,
                                             null=True, blank=True)
    bear_threshold_pct = models.DecimalField(max_digits=6, decimal_places=3,
                                             null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=256, blank=True, default='')

class SymbolRegimeModel(models.Model):
    """One row per (symbol, fit run). Latest row per symbol is authoritative."""
    METHOD_CHOICES = [('ROLLING_RETURN','ROLLING_RETURN'), ('HMM','HMM')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    symbol = models.ForeignKey(TrackedSymbol, on_delete=models.CASCADE,
                               related_name='regime_fits')
    method = models.CharField(max_length=16, choices=METHOD_CHOICES)
    fitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    lookback_days = models.PositiveIntegerField()         # e.g. 252*5
    window_days = models.PositiveSmallIntegerField()
    bull_threshold_pct = models.DecimalField(max_digits=6, decimal_places=3)
    bear_threshold_pct = models.DecimalField(max_digits=6, decimal_places=3)
    laplace_alpha = models.FloatField(default=1.0)
    n_observations = models.PositiveIntegerField()
    transition_matrix = models.JSONField()                # 3x3, ordered BULL,SIDEWAYS,BEAR
    stationary_distribution = models.JSONField()         # 3-vector
    log_likelihood = models.FloatField(null=True, blank=True)  # HMM only
    is_active = models.BooleanField(default=True)        # latest fit per symbol

    class Meta:
        indexes = [models.Index(fields=['symbol', 'is_active'])]

class SymbolRegimeObservation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    symbol = models.ForeignKey(TrackedSymbol, on_delete=models.CASCADE,
                               related_name='regime_observations')
    model = models.ForeignKey(SymbolRegimeModel, on_delete=models.CASCADE)
    ts = models.DateField(db_index=True)                 # bar date
    label = models.CharField(max_length=8)               # BULL|SIDEWAYS|BEAR
    rolling_return_pct = models.DecimalField(max_digits=10, decimal_places=4)
    forecast = models.JSONField()                        # {'h1':{...},'h5':{...},'h20':{...}}
    conviction_h5 = models.DecimalField(max_digits=6, decimal_places=4)
    bear_mass = models.DecimalField(max_digits=6, decimal_places=4)  # π[BEAR]

    class Meta:
        unique_together = ('symbol', 'ts')
        indexes = [models.Index(fields=['symbol', '-ts'])]
```

### 6.4 Tracked-symbol harvester

Sources of truth, evaluated weekly by `regime.refresh_tracked_symbols`:

1. `Order.objects.filter(status__in=FILLED_STATES, filled_at__gte=now-90d).values_list('symbol', flat=True).distinct()` — symbols we've actually filled in the last 90 days.
2. Admin-pinned tickers (e.g., `SPY`, `QQQ`, top movers) configured via `settings.SYMBOL_REGIME_PINNED`.
3. Symbols explicitly added via Django admin (one-off — UI later).

Symbols not seen in 90 days flip to `is_active=False` but rows are retained for audit/backtester reuse.

Cap: hard limit of 500 active symbols. Beyond that, log a warning and require admin to prune.

Symbols are extracted from execution data (Order fills), **not** parsed out of user-uploaded `_Webhook.json` payload templates, because those use TradingView placeholders like `{{ticker}}` that are filled at fire time, not statically.

### 6.5 API (`apps/regime/per_symbol/views.py`)

```
GET /api/v1/regime/symbol/{sym}/                  → current label + matrix + π + forecasts
GET /api/v1/regime/symbol/{sym}/history/?from&to  → time series of labels for charting
GET /api/v1/regime/symbols/?active=true           → list of tracked symbols + latest label
```

Response shape for `GET /api/v1/regime/symbol/{sym}/`:

```json
{
  "symbol": "AAPL",
  "asset_class": "US_EQUITY",
  "status": "OK",
  "as_of": "2026-08-14",
  "method": "ROLLING_RETURN",
  "current_label": "BULL",
  "rolling_return_pct": 7.2,
  "transition_matrix": {
    "BULL":     {"BULL": 0.86, "SIDEWAYS": 0.11, "BEAR": 0.03},
    "SIDEWAYS": {"BULL": 0.18, "SIDEWAYS": 0.71, "BEAR": 0.11},
    "BEAR":     {"BULL": 0.04, "SIDEWAYS": 0.16, "BEAR": 0.80}
  },
  "stationary_distribution": {"BULL": 0.51, "SIDEWAYS": 0.31, "BEAR": 0.18},
  "forecast": {
    "h1":  {"BULL": 0.86, "SIDEWAYS": 0.11, "BEAR": 0.03},
    "h5":  {"BULL": 0.71, "SIDEWAYS": 0.21, "BEAR": 0.08},
    "h20": {"BULL": 0.58, "SIDEWAYS": 0.27, "BEAR": 0.15}
  },
  "conviction_h5": 0.63,
  "bear_mass": 0.18,
  "model": {
    "fitted_at": "2026-08-14T03:30:00Z",
    "lookback_days": 1260,
    "window_days": 20,
    "bull_threshold_pct": 5.0,
    "bear_threshold_pct": -5.0
  }
}
```

`INSUFFICIENT_HISTORY`, `NOT_TRACKED`, `MODEL_STALE` (> 14 days) are additional status values.

### 6.6 M08 integration — sizing scalar

Extend `apps/risk/sizing.compute_size` signature:

```python
def compute_size(alert, profile, regime, symbol_regime, sentiment, account, instrument):
    ...
    # existing market-wide scale stays:
    risk_pct = profile.risk_per_trade_pct * REGIME_SCALE[regime.label]

    # NEW: per-symbol scale, multiplicative
    SYMBOL_REGIME_SCALE = {'BULL': 1.0, 'SIDEWAYS': 0.7, 'BEAR': 0.3}
    risk_pct *= SYMBOL_REGIME_SCALE[symbol_regime.label]

    # NEW: tail-heavy filter
    if symbol_regime.bear_mass > 0.40:
        risk_pct *= 0.5
        sizing_audit['tail_heavy'] = True

    # NEW: strict-mode side mismatch (per-symbol variant)
    if profile.strict_mode and symbol_regime.label == 'BEAR' and alert.side == 'LONG':
        return SizingResult.reject('SYMBOL_REGIME_SIDE_MISMATCH')
    ...
```

`symbol_regime` is fetched fresh from `SymbolRegimeObservation` keyed by `(alert.symbol, today)` with fallback to most-recent row if today's hasn't computed yet; `MODEL_STALE` >14d skips the scaler entirely (defensive — better to behave like M06 didn't exist for this symbol than scale on garbage).

Adds error codes: `SIZING_TAIL_HEAVY` (audit annotation, not rejection), `SYMBOL_REGIME_SIDE_MISMATCH` (rejection).

Cross-reference M08 §6.2; this is a minor signature change there. M08 plan will be updated in the same commit to keep the two files consistent.

### 6.7 M04 integration — regime gate

`WebhookConfig` gains an optional `regime_gate` JSON sub-document:

```json
{
  "enabled": true,
  "scope": "PER_SYMBOL",
  "allow_labels": ["BULL", "SIDEWAYS"],
  "require_min_conviction_h5": 0.0,
  "max_bear_mass": 0.45
}
```

At webhook ingest (M04), after HMAC verification and payload validation:

```python
if cfg.regime_gate and cfg.regime_gate['enabled']:
    obs = latest_symbol_regime(alert.symbol)
    if obs is None:
        log_event('REGIME_GATE_SKIPPED_NO_DATA')   # do not block; fail-open
    else:
        if obs.label not in cfg.regime_gate['allow_labels']:
            return 422, {'code': 'REGIME_GATE_BLOCKED', 'detail': ...}
        if obs.conviction_h5 < cfg.regime_gate.get('require_min_conviction_h5', -1):
            return 422, {'code': 'REGIME_GATE_BLOCKED', 'detail': ...}
        if obs.bear_mass > cfg.regime_gate.get('max_bear_mass', 1.0):
            return 422, {'code': 'REGIME_GATE_BLOCKED', 'detail': ...}
```

Fail-open on missing data is deliberate (per M06's degraded-mode philosophy). Strict users can set `require_data: true` in a follow-up if needed.

UI (modal change in M03 webhook config): three new fields under a "Regime gate (optional)" collapsible — checkbox + multi-select for labels + numeric inputs for conviction floor and bear-mass ceiling. Translation keys `regime_gate.*`.

### 6.8 M03 strategies-list badge

Each row in the strategies list calls `GET /api/v1/regime/symbols/?active=true` once on page load (cached 60s) and renders a small chip next to the strategy name with the regime of the strategy's primary symbol (heuristic: most recently filled symbol on that strategy in the last 90d; fall back to "—" if unknown). Tooltip: label, conviction h5, bear mass, model fit date.

Color: BULL=green, SIDEWAYS=gray, BEAR=amber. Distinct from M06's market badge palette (which uses blue/yellow/red) so the two don't read as the same thing.

### 6.9 Beat schedule additions

| Task | Cadence | Notes |
|------|---------|-------|
| `regime.symbol_compute_observations` | 18:30 ET | After M06 `regime.compute_features_daily`; decodes today's label for each active symbol; persists `SymbolRegimeObservation`. |
| `regime.symbol_fit_models` | 03:30 ET | After M06 `regime.retrain_hmm` (03:00 ET). Refits transition matrix per active symbol. |
| `regime.refresh_tracked_symbols` | weekly Sun 02:00 ET | Reconciles `TrackedSymbol` against fill history and admin pin list. |

All three guarded by `SYMBOL_REGIME_ENABLED`; when false, tasks log "disabled" and exit.

## 7. Tech Stack Notes

- Math: `numpy` + `pandas` only. No additional runtime deps.
- Optional `hmmlearn` (already a M06 dep). 06A piggybacks on the same install; degrades to rolling-return labeller on import failure (mirrors M06's degraded-mode banner pattern).
- Storage: plain Postgres tables; no partitioning needed (≤ 500 symbols × ~250 obs/yr × 5y ≈ 625K rows — trivially small).
- Caching: `SymbolRegimeObservation` for today is fetched per webhook ingest. Cache-Redis with 60s TTL; invalidate on each beat run.
- Reproducibility: pin numpy version; record `numpy.__version__` in `SymbolRegimeModel.notes` for forensic reproducibility across releases.

## 8. Data Model Changes

Migrations:
- `regime.000X_per_symbol_initial` — `TrackedSymbol`, `SymbolRegimeModel`, `SymbolRegimeObservation`.
- `strategies.000X_webhook_regime_gate` — adds `regime_gate JSONB` column to `WebhookConfig` (nullable, default `null`).
- `risk.000X_sizing_decision_symbol_regime` — adds `symbol_regime_snapshot JSONB` column to `SizingDecision` for audit trail.

## 9. API Contract Changes

- Replace M06 §6.7 `GET /api/v1/regime/symbol/{sym}/` 501 with the implementation above.
- Add `GET /api/v1/regime/symbol/{sym}/history/`.
- Add `GET /api/v1/regime/symbols/`.
- M04 webhook ingest gains `REGIME_GATE_BLOCKED` and `REGIME_GATE_SKIPPED_NO_DATA` (logged, not user-visible) codes.
- M08 sizing gains `SIZING_TAIL_HEAVY` (audit annotation), `SYMBOL_REGIME_SIDE_MISMATCH` (rejection), `SYMBOL_REGIME_MODEL_STALE` (audit annotation).

OpenAPI schema regenerated; SDK clients pick up new types.

## 10. Test Plan

### 10.1 Unit tests

- `label_series` boundary cases: exactly at threshold (use strict `>` not `≥`); NaN handling at the head of the window; window > series length returns empty.
- `transition_matrix` row-stochastic invariant; Laplace smoothing zeros nothing; α=0 reproduces unsmoothed MLE.
- `stationary_distribution` matches eigen-solve to 1e-9 on a panel of 100 random row-stochastic matrices.
- `n_step_forecast` at h=0 returns the unit vector for current; at h=∞ approaches π; convergence test with synthetic doubly-stochastic.
- `conviction` ∈ [-1, 1] on randomized inputs.
- Degenerate cases: a symbol that visited only BULL produces a row-stochastic matrix where Laplace smoothing puts non-zero mass in BEAR transitions.

### 10.2 Golden fixtures

- `tests/regime/per_symbol/golden/spy_2010_2025.json` — committed expected outputs (transition matrix, π, last 30 labels) for SPY daily bars 2010-01-01 to 2025-12-31. Hash-pinned; CI fails on regression.
- Same for BTC-USD (crypto thresholds), TLT (bonds-adjacent), EURUSD (FX thresholds).

### 10.3 Integration

- End-to-end: seed 5y of SPY bars → run nightly fit → query API → response matches the golden fixture exactly.
- `regime.symbol_compute_observations` is idempotent: rerun twice in the same day, only one row per symbol per date.
- `hmmlearn` import-failure simulation (monkeypatch `ImportError`): method silently degrades; observations still produced.
- `INSUFFICIENT_HISTORY` path: seed 100 bars → API returns the status without raising.
- Stale-model guard: backdate `fitted_at` > 14 days → API returns `MODEL_STALE` and M08 skips the scaler.

### 10.4 E2E (Playwright)

- `regime.symbol_badge.spec.ts`: strategies list shows a regime chip for SPY; tooltip contents match API.
- `regime.gate.spec.ts`: configure a strategy with `regime_gate.allow_labels=['BULL']`; force-set symbol regime to BEAR via admin; fire a test webhook → 422 with `REGIME_GATE_BLOCKED`; flip allow-list to include BEAR → fires through.
- `regime.kill_switch.spec.ts`: set `SYMBOL_REGIME_ENABLED=false` env override → badge disappears, gates short-circuit, M08 path uses market-wide only.

### 10.5 Performance

- Fit one symbol: p95 < 250ms (US equity, 5y dailies).
- Full nightly fit of 500 symbols: p95 < 3 min on staging hardware.
- API `GET /regime/symbol/{sym}/` p95 < 50ms (cached); cold p95 < 200ms.
- Webhook ingest with regime gate adds ≤ 5ms p95 to the existing M04 path.

### 10.6 Reproducibility

- Re-fitting yesterday's bars produces a byte-identical `transition_matrix`. Hashed; committed in the golden fixture.

## 11. Security Considerations

- No new user inputs that hit the math module — thresholds are admin-configured per-symbol or per-asset-class. User-set values (e.g., in `regime_gate.allow_labels`) are enum-validated server-side.
- We do **not** vendor the upstream `markov-hedge-fund-method` skill, nor its `uv` / `yfinance` toolchain. We implement the math against our existing `marketdata.Bar` store. Reasons:
  - Avoids a parallel data path that bypasses our rate-limit-aware FMP client.
  - Avoids `uv`-managed Python dep resolution on a production Django/Celery worker.
  - Removes ambiguity about whose code is in our `requirements.txt` (clean credit to Roan in ADR 062 instead).
  - License: the upstream is MIT and explicitly invites this kind of reuse; ADR 062 carries the attribution.
- No external network calls from any 06A code path — everything reads `marketdata.Bar`.
- Audit trail: every `SizingDecision` writes a snapshot of the symbol-regime inputs (`symbol_regime_snapshot` JSONB) so post-hoc analysis can reconstruct decisions even after a model refit.

## 12. Observability

Prometheus:
- `regime_symbol_fit_latency_seconds{method}` — histogram per fit-call.
- `regime_symbol_fit_total{method,result}` — counter (`result ∈ ok|insufficient_history|hmm_degraded|error`).
- `regime_symbol_observations_age_seconds` — gauge of newest observation's lag.
- `regime_symbol_tracked_count` — gauge of active `TrackedSymbol` count (alert at >500).
- `regime_gate_decisions_total{outcome}` — counter (`outcome ∈ pass|blocked|skipped_no_data`).
- `sizing_tail_heavy_total` — counter (when `bear_mass > 0.40`).

Alerts:
- `regime_symbol_observations_age_seconds > 36h` on market days.
- `regime_symbol_fit_total{result='error'}` > 5 in 24h.
- `regime_symbol_tracked_count > 500`.

Grafana: extend M06's **Data Pipelines** dashboard with a "Per-symbol regime" row (fit latency, age, gate decisions).

## 13. Translation & Localization

- Label enum strings (`BULL/SIDEWAYS/BEAR`) translated for display only; API stays canonical English.
- New keys: `regime.symbol.label.BULL/SIDEWAYS/BEAR`, `regime.symbol.badge.tooltip.*`, `regime_gate.*`, `regime.symbol.status.INSUFFICIENT_HISTORY/NOT_TRACKED/MODEL_STALE`.
- Error code labels mapped: `REGIME_GATE_BLOCKED`, `SYMBOL_REGIME_SIDE_MISMATCH`.
- Bear-mass and conviction numeric formatting via `Intl.NumberFormat`.

## 14. Documentation Deliverables

- `/docs/adr/062-per-symbol-markov-regime.md` — math, smoothing, asset-class defaults, Laplace prior choice, credit to Roan (@RohOnChain), upstream link, reasons for re-implementing rather than vendoring.
- `/docs/runbooks/symbol-regime-fit-failure.md` — what to do when nightly fit fails: check bar coverage, force `ROLLING_RETURN` fallback, manual `refit_symbol` admin command.
- `/docs/runbooks/symbol-regime-tracked-symbol-cap.md` — pruning playbook when `regime_symbol_tracked_count > 500`.
- User help: "What the per-symbol regime badge means" — short article with screenshots, the three labels, and what the bear-mass column represents.
- Update [project-plan/06-market-data-and-regime.md](06-market-data-and-regime.md) §3 to mark the deferred per-symbol HMM item as "tracked in 06A".

## 15. Rollback Plan

- Master flag `SYMBOL_REGIME_ENABLED` (default `false` until 06A graduates) short-circuits every 06A path: API returns 503, M08 ignores `symbol_regime`, M04 ignores `regime_gate`, M03 hides the badge, beat tasks no-op.
- Schema migrations are additive (new tables + nullable JSONB columns). Rollback drops only the new tables; existing rows in `strategies_webhook_config` and `risk_sizing_decision` remain valid with the nullable columns at default.
- If the nightly fit job becomes a noisy neighbor (CPU/IO), reduce `TrackedSymbol.is_active` to a smaller core list via admin; tasks will continue on the reduced set with no code change.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Single-feature labeller misses regime breaks that the market-wide HMM catches earlier | High | Low | Per-symbol regime is *augmentation*, not replacement. M06's market regime stays the primary input to sizing. |
| ±5%/20d defaults wrong for non-US-equity asset classes | High | Med | Asset-class defaults table in §6.2 with explicit per-class tuning; ADR 062 documents the calibration evidence. |
| Tracked-symbol count balloons past 500 | Med | Med | Hard cap + admin alert + pruning runbook; harvester biased to "actually-traded" symbols. |
| `hmmlearn` compile fails in production wheels | Low | Low | Graceful degrade to rolling-return labeller (AC-06A-8). M06 has the same dep and the same fallback. |
| User over-relies on regime gate and misses entries during fast transitions | Med | Med | UI tooltip warns gate is fail-open on missing data and lags by one day; help page explains the lag. |
| Bear-mass scalar (0.5×) and SYMBOL_REGIME_SCALE compound with M06's REGIME_SCALE to produce unintendedly tiny sizes | Med | High | Property test: total scalar in `compute_size` floored at 0.05 (5% of base risk_pct) with a `SIZING_SCALAR_FLOORED` audit annotation. |
| User confuses per-symbol regime badge with market regime badge | Med | Low | Distinct color palettes; explicit labels on tooltip; help page side-by-side comparison. |
| Math drift across numpy versions | Low | Low | `numpy.__version__` recorded per fit; CI runs against the production-pinned numpy. |

## 17. Exit Gate Checklist

- [ ] AC-06A-1 … AC-06A-13 pass.
- [ ] Golden fixtures for SPY, BTC-USD, TLT, EURUSD committed and CI-enforced.
- [ ] Nightly fit job demonstrated against the live `Bar` store; ≥ 200 symbols modelled.
- [ ] M08 sizing test suite extended with symbol-regime cases; deterministic outputs verified.
- [ ] M04 webhook gate E2E spec green.
- [ ] M03 strategies list shows the badge with real data.
- [ ] ADR 062 committed with attribution to Roan (@RohOnChain) and link to the upstream repo.
- [ ] M06 §3 updated: per-symbol HMM no longer deferred.
- [ ] Runbooks committed.
- [ ] Grafana **Data Pipelines** dashboard row added.
- [ ] `SYMBOL_REGIME_ENABLED=true` in staging for ≥ 5 trading days with no degraded-mode alerts.
- [ ] Tag `v0.6a.0-per-symbol-regime`.

After this, the platform has a defensible **two-tier** regime architecture: market-wide (M06) for portfolio-level decisions, per-symbol (06A) for individual-trade decisions. M07 (sentiment) and M08 (sizing) consume both.
