# Milestone 06 — Market Data + Regime Classifier

> **Week:** 6
> **Duration:** 5 working days
> **Depends on:** M05 (Order Lifecycle + second broker)
> **Unlocks:** M07 (Sentiment) and M08 (Risk engine uses regime as an input)

> **Review note (2026-07-05, post-Alpaca pivot — ADR-041):** Alpaca's Market Data API now ships with the M04 broker integration for free (Basic plan: real-time IEX feed + 15-min-delayed SIP, historical bars for 5000+ US equities via `StockHistoricalDataClient` in the already-pinned `alpaca-py`). Decision point at M06 kickoff: keep FMP as primary (it uniquely covers the sector-performance, treasury-curve, and economics endpoints the feature pipeline needs) but consider sourcing plain **equities bars** from Alpaca to cut FMP tier cost and add a real-time-capable second source. The `MarketDataProvider` abstraction (§6.13) was designed for exactly this — implement `AlpacaDataProvider` alongside `FMPProvider` if the dev-cost math favors it. FRED (macro) unchanged; cache aggressively per the analysis doc's rate-limit warning.

## 1. Purpose

Stand up the market-data plane (FinancialModelingPrep premium) with a persistent bar cache, then build the regime classifier stack: a deterministic rule-based breadth score and a Gaussian HMM trained nightly. Surface the current regime + history in the dashboard. Regime output becomes an input for M08 sizing and M07 sentiment weighting.

## 2. In Scope

- `marketdata` app: FMP client with caching + rate limiting + retries.
- Bar store for 1m/5m/15m/1h/1d; idempotent upserts; gap detection.
- Feature pipeline computing the breadth/stress/credit/macro feature vector.
- Rule-based breadth classifier producing `{score_0_100, bucket}` bins.
- Gaussian HMM (`hmmlearn`) training, validation, online decoding.
- Ensemble layer combining rule + HMM.
- Beat schedule: intraday features every 5 min during market hours; nightly HMM retrain at 03:00 ET.
- Regime badge + history chart on dashboard.
- Regime API endpoints.
- Graceful degradation: rule-only when HMM stale > 48h.

## 3. Out of Scope

- Per-symbol HMM (market-wide only in M06; per-symbol later).
- Deep learning regime models (HMM only).
- Sentiment (M07).
- Using regime to modify sizing (M08 consumes regime as input).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-06-1 | FMP client successfully fetches 1d bars for S&P 500 constituents and SPY over the last 10 years; bars stored once, idempotent on re-run. |
| AC-06-2 | Intraday 5-min feature computation runs during US market hours via Celery beat; latest `RegimeObservation` is never older than 10 min while market is open. |
| AC-06-3 | Rule-based classifier produces one of {RISK_ON, NEUTRAL, RISK_OFF, PANIC} with explainable contributing features shown in API response. |
| AC-06-4 | HMM with 4 states trains nightly on the prior 10y of daily features; holdout log-likelihood compared to previous model; swap only if ≥ prior or within 1%. |
| AC-06-5 | Online HMM decode returns state + probabilities; Viterbi produces the most likely state sequence of the last 20 days for the history chart. |
| AC-06-6 | Ensemble label is deterministic given inputs and version; stored per observation. |
| AC-06-7 | Dashboard displays current regime badge with color, tooltip of contributing features, and a time-series chart of the last 90 days. |
| AC-06-8 | If HMM model age > 48h, UI shows a "Rule-based only" warning; API response `model_degraded=true`. |
| AC-06-9 | FMP rate limit breach triggers exponential backoff + cached response fallback; never causes a 5xx on the dashboard. |
| AC-06-10 | All feature computations are reproducible: given the same stored bars + macro data, re-running produces identical output (hashed). |

## 5. Definition of Done

Baseline DoD applies, plus:

- ADR on why HMM + rule ensemble chosen over single approach.
- Backfill script `python manage.py backfill_bars --symbols SPY,QQQ,... --from 2015-01-01` documented.
- Feature computation library has reference outputs pinned in `tests/regime/golden/`.
- Grafana **Data Pipelines** dashboard created with freshness + error panels.

## 6. Implementation Tasks

### 6.1 FMP client (`apps/marketdata/fmp.py`)

- `httpx.AsyncClient` with pool + timeouts.
- Endpoints used:
  - `/stable/historical-price-eod/full?symbol=XXX` — daily.
  - `/stable/historical-chart/5min?symbol=XXX&from&to` — intraday.
  - `/stable/quote?symbol=XXX` — realtime quote.
  - `/stable/historical-market-capitalization?symbol=XXX` — (future for weighting).
  - `/stable/economics/treasury-yield-curve?from&to` — for 10y/2y.
  - `/stable/historical-sector-performance` — sector breadth approximation.
- Rate limiter: token bucket sized to the premium tier's per-minute limit (confirm with Yuval; assume 750/min for sizing).
- Retries: 3 with jitter on 429/5xx; circuit breaker opens on sustained failures.
- Response cache: short TTL (30s) for intraday; long TTL (24h) for daily.

### 6.2 Bar store (`apps/marketdata/models.py`)

```python
class Bar(Model):
    symbol = CharField(max_length=16, db_index=True)
    tf = CharField(max_length=4)                     # '1m','5m','15m','1h','1d'
    ts = DateTimeField(db_index=True)
    open = DecimalField(max_digits=18, decimal_places=6)
    high = DecimalField(...)
    low = DecimalField(...)
    close = DecimalField(...)
    volume = BigIntegerField()
    source = CharField(max_length=16, default='FMP')
    class Meta:
        unique_together = ('symbol','tf','ts')
```

Partitioned by month via `django-postgres-partition` to keep indexes small; drop partitions > 5y on retention policy.

Gap detection: a utility `missing_bars(symbol, tf, from, to)` finds and backfills holes.

### 6.3 Feature pipeline (`apps/regime/features.py`)

Compute features at scheduled timestamps. Inputs:
- SPY/QQQ/IWM prices (1d + intraday).
- S&P 500 constituent prices (for % above SMAs, NH/NL, A/D).
- VIX + VIX3M (FMP).
- HY OAS (`BAMLH0A0HYM2`) + IG OAS (`BAMLC0A0CM`) via FRED API (free).
- 10Y–2Y yield spread.
- DXY.
- MOVE index (FMP or scraped source).

Outputs (vector per timestamp):
```
{
  pct_above_50sma, pct_above_200sma,
  ad_ratio, nh_nl_diff, mcclellan_osc,
  vix, vix_term_ratio, move,
  hy_oas, ig_oas,
  mom_50, mom_200, rsi_14,
  yield_spread, dxy,
}
```

All features standardized (z-score) using rolling 252-day window; z-scores clipped to [-4,4].

### 6.4 Rule classifier (`apps/regime/rule_classifier.py`)

- Weighted linear combination → score in [0,100].
- Thresholds:
  - ≥ 70: RISK_ON
  - 50–69: NEUTRAL
  - 30–49: RISK_OFF
  - < 30: PANIC
- Weights documented in ADR; tunable via `settings.REGIME_RULE_WEIGHTS`.
- Reason codes returned: top-3 contributing features by absolute z-score.

### 6.5 HMM (`apps/regime/hmm_model.py`)

- Library: `hmmlearn.GaussianHMM`.
- 4 states trained on the daily feature vector (not price directly).
- State labels assigned post-hoc by analyzing mean features in each state:
  - Lowest mean volatility + positive momentum → `BULL`.
  - Highest volatility → `CRISIS`.
  - Etc.
- Nightly task `regime.retrain_hmm`:
  - Pull latest 10y of features.
  - Fit HMM with 20 random restarts; pick max log-likelihood.
  - Validate on most recent 90 days OOS; compare to current model.
  - If new model LL ≥ prior × 1.0 OR within 1%: activate via `HMMModel(active=true)` swap; archive prior.
- Online decode: when new feature vector arrives → `predict` returns current state + `predict_proba`.

### 6.6 Ensemble (`apps/regime/ensemble.py`)

Decision table:

| rule | hmm | confidence | label |
|---|---|---|---|
| RISK_ON | BULL | — | BULL |
| RISK_ON | CHOP | >0.7 | CHOP |
| RISK_ON | CHOP | ≤0.7 | NEUTRAL |
| RISK_OFF | BEAR | — | BEAR |
| RISK_OFF | CHOP | — | BEAR |
| PANIC | — | — | CRISIS |
| other | BULL | >0.8 | BULL |
| other | BEAR | >0.8 | BEAR |
| fallback | — | — | rule's label |

Persisted `RegimeObservation.ensemble_label` plus raw components so downstream consumers (M08 sizing) can choose behavior.

### 6.7 API + dashboard

Endpoints:
```
GET /api/v1/regime/current/                  → current label + features + components
GET /api/v1/regime/history/?scope=MARKET&from&to
GET /api/v1/regime/symbol/{sym}/             → placeholder 501 in M06 (per-symbol later)
GET /api/v1/regime/model/                    → active HMM version + trained_at + ll
```

Dashboard widget:
- Current badge (color + icon + label).
- Feature popover listing top-5 contributing features with z-scores.
- 90-day stacked area chart of HMM state probabilities (lightweight-charts + custom renderer, or plotly).

### 6.8 Beat schedule additions

| Task | Cadence | Notes |
|------|---------|-------|
| `marketdata.fetch_daily_bars` | 18:00 ET | All tracked symbols |
| `marketdata.fetch_intraday_bars` | every 1 min (market hours) | Only SPY/QQQ/IWM + top movers |
| `regime.compute_features` | every 5 min (market hours) | Market-wide |
| `regime.compute_features_daily` | 18:30 ET | Authoritative daily vector |
| `regime.retrain_hmm` | 03:00 ET | Guarded by success flag |
| `marketdata.gap_heal` | 04:00 ET | Detect & backfill |

## 7. Tech Stack Notes

- **hmmlearn** over `pomegranate` for maturity + simpler deployment.
- **numpy + pandas** baseline; avoid heavy DSPy/sklearn pipelines for initial scope.
- **FRED API** is free; `fredapi` Python package used for credit spreads.
- **TimescaleDB** is *not* adopted — plain Postgres is sufficient at our scale.
- Feature z-score windowing uses `pandas.rolling` + bfill for initial 252 bars.

## 8. Data Model Changes

Migrations:
- `marketdata.0001_initial` — `Bar` + partition setup.
- `regime.0001_initial` — `RegimeObservation`, `HMMModel`, `FeatureVectorSnapshot`.

## 9. API Contract Changes

Paths per §6.7. `RegimeObservation` response shape:
```json
{
  "ts": "2026-04-14T19:05:00Z",
  "scope": "MARKET",
  "label": "BULL",
  "rule_bucket": "RISK_ON",
  "rule_score": 78.4,
  "hmm_state": "BULL",
  "hmm_probs": {"BULL":0.82,"CHOP":0.12,"BEAR":0.04,"CRISIS":0.02},
  "top_features": [
     {"name":"pct_above_50sma","z":2.1},
     {"name":"vix","z":-1.3},
     {"name":"hy_oas","z":-0.9}
  ],
  "model": {"version":"2026-04-14T03:00:00Z","degraded": false}
}
```

## 10. Test Plan

### 10.1 Unit tests

- FMP client: rate limiter enforces limits; retry on 429; circuit breaker opens after N failures.
- Bar store upsert idempotency; gap detection test with synthetic holes.
- Feature computations match golden fixtures (`tests/regime/golden/*.json`).
- Rule classifier bucket boundaries (property test on scores).
- HMM training deterministic given seed; log-likelihood reported.
- Online decode matches batch decode on a window.
- Ensemble decision table exhaustive test.

### 10.2 Integration

- Run a full day's worth of features end-to-end against a seeded DB.
- Scheduler kicks tasks on time; DB shows fresh observations.
- FMP 429 doesn't break pipeline (degrades to cache).

### 10.3 E2E

- Regime badge renders on dashboard; hovering shows top features.
- Toggle "force stale model" env flag → warning banner appears.

### 10.4 Performance

- Feature computation p95 < 3s.
- HMM retrain completes < 15 min on staging hardware.
- Dashboard current regime response p95 < 150ms (cached).

### 10.5 Reproducibility

- Golden file test: rehash of features vector bytes equals committed expected hash.

## 11. Security Considerations

- FMP API key stored in Railway env; rotated annually; never logged.
- FRED API key similarly protected.
- Bar store contains only public market data — no PII concerns.
- Rate-limit awareness prevents us from inadvertently leaking user patterns to FMP (we fetch on our schedule, not per-user).

## 12. Observability

- Prometheus:
  - `marketdata_requests_total{endpoint,result}`
  - `marketdata_ratelimit_waits_total`
  - `marketdata_bars_ingested_total{tf}`
  - `regime_compute_latency_seconds` histogram
  - `regime_model_age_seconds` gauge
  - `hmm_retrain_total{result}`
- Alerts:
  - `regime_model_age_seconds > 48h` during market days.
  - `regime_compute_latency_seconds` p95 > 10s.
  - FMP error rate > 5% / 10 min.
- Grafana: **Data Pipelines** dashboard.

## 13. Translation & Localization

- Regime labels and rule buckets translated: `regime.label.BULL`, `regime.rule.RISK_ON`, etc.
- Feature names translated: `regime.feature.pct_above_50sma`, `regime.feature.vix`.
- Tooltip descriptions translated with explanatory text per feature.
- Chart axis labels, date formats, and number formats via `Intl`.
- API returns i18n-neutral enum strings; frontend translates for display.

## 14. Documentation Deliverables

- `/docs/adr/060-regime-ensemble.md`.
- `/docs/adr/061-data-vendor-fmp.md`.
- `/docs/runbooks/hmm-retrain-failure.md`.
- `/docs/runbooks/fmp-rate-limit.md`.
- User help: "Understanding the Regime badge".

## 15. Rollback Plan

- `ENABLE_REGIME_UI = false` hides the badge.
- If HMM regresses, `HMMModel.active=false` via admin; rule-based fallback continues.
- Feature pipeline can be paused via Celery beat.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| FMP endpoint changes break parser | Low | Med | Contract tests vs fixture; vendor-change ADR to add before swap. |
| HMM drift during regime shift (fits badly) | Med | Med | Nightly retrain + rule fallback + alert on age. |
| Feature-vector look-ahead bias | Low | High | Use point-in-time data (trade-date features only); audit in ADR. |
| DB bloat from bar partitions | Med | Low | Monthly partitions + retention policy. |
| FMP cost surprise | Low | Med | Cache aggressively; set alert on request count. |

## 17. Exit Gate Checklist

- [ ] AC-06-1 … AC-06-10 pass.
- [ ] Backfill script run against 10y history; DB shows complete series.
- [ ] HMM retrain completes overnight on staging; new model active.
- [ ] Dashboard badge demonstrated with live data.
- [ ] Data Pipelines Grafana dashboard live.
- [ ] ADR 060, 061 committed.
- [ ] Tag `v0.6.0-regime`.

Proceed to **M07 Sentiment Pipeline**.
