# ADR-060 — A rule + HMM ensemble for market-regime classification

**Date:** 2026-07-07
**Status:** Accepted
**Milestone:** M06 — Market Data + Regime Classifier
**Reference:** `project-plan/06-market-data-and-regime.md` §5 (DoD — "ADR on why
HMM + rule ensemble chosen over single approach"), §6.4–§6.6, §16 (look-ahead
risk); AC-06-3, AC-06-4, AC-06-6, AC-06-8, AC-06-10

## Context

M06 has to answer one recurring question — *what regime is the market in right
now?* — and hand that answer to M08 (position sizing) and M07 (sentiment
weighting) as a stable, explainable input. Two families of approach were on the
table, and each fails on its own:

- **A deterministic rule score.** A weighted breadth/stress/credit/macro score
  is fully explainable ("we're RISK_OFF because HY spreads and VIX are both
  >1.5σ rich") and is *always available* — it needs no training, no model
  artifact, and no warm-up. But it is a hand-tuned linear surface: it cannot
  discover latent structure (e.g. a low-vol *distribution* that historically
  preceded drawdowns) and its weights encode our priors, not the data's.

- **A single Gaussian HMM.** An `hmmlearn` HMM fits latent states directly from
  the feature distribution and captures regime *persistence* and transition
  structure the rule can't. But it is opaque, it can fit badly right when it
  matters most (a genuine regime shift is exactly when the last 10y of training
  data is least representative), and it has a cold-start / staleness problem —
  if the nightly retrain fails, a lone HMM has no fallback.

Neither is acceptable alone: the rule is explainable-but-blind, the HMM is
powerful-but-fragile-and-opaque.

## Decision

Ship **both**, combine them in a small deterministic ensemble, and make the rule
the graceful-degradation floor. The rule is the always-on, explainable baseline;
the HMM is an override that only speaks when it is fresh and confident; the
ensemble is a fixed decision table; and when the HMM is stale or absent the
system silently falls back to rule-only.

### 1. The rule classifier — explainable, always-on

`backend/apps/regime/rule_classifier.py` scores a standardized (z-scored)
feature vector with a signed linear combination and bins the result. Weights are
signed by **risk-on direction** (positive = risk-on when the z-score is high),
so the sign of each contribution is self-documenting.

**`DEFAULT_WEIGHTS`** (overridable via `settings.REGIME_RULE_WEIGHTS`):

| Group | Feature | Weight | Reads as |
|---|---|---:|---|
| **Breadth** | `pct_above_50sma` | **+1.5** | more names above their 50-day SMA → risk-on |
| | `pct_above_200sma` | **+1.5** | more names above their 200-day SMA → risk-on |
| | `ad_ratio` | **+1.0** | advancers over decliners → risk-on |
| | `nh_nl_diff` | **+1.0** | new-highs minus new-lows → risk-on |
| | `mcclellan_osc` | **+0.8** | breadth momentum → risk-on |
| **Momentum** | `mom_50` | **+1.2** | 50-day price momentum → risk-on |
| | `mom_200` | **+1.2** | 200-day price momentum → risk-on |
| | `rsi_14` | **+0.5** | 14-day RSI → mild risk-on |
| **Volatility / stress** | `vix` | **−1.8** | high implied vol → risk-off |
| | `vix_term_ratio` | **−1.0** | inverted VIX term structure → risk-off |
| | `move` | **−1.0** | high rate vol (MOVE) → risk-off |
| **Credit** | `hy_oas` | **−1.8** | wide HY OAS → risk-off |
| | `ig_oas` | **−1.2** | wide IG OAS → risk-off |
| **Macro** | `yield_spread` | **+0.6** | steeper 10y–2y → risk-on |
| | `dxy` | **−0.5** | strong dollar → mild risk-off |

The two dominant risk-*off* signals are credit (`hy_oas` −1.8) and volatility
(`vix` −1.8); the two dominant risk-*on* signals are breadth
(`pct_above_50sma` / `pct_above_200sma`, both +1.5). That is deliberate — credit
and vol lead, breadth confirms.

**Score → bucket.** The signed contributions sum, scale, and center on 50:

```
score = clip( 50 + 6.0 · Σ (wᵢ · zᵢ) , 0 , 100 )
```

| Score band | Bucket |
|---|---|
| ≥ 70 | `RISK_ON` |
| 50 – 69 | `NEUTRAL` |
| 30 – 49 | `RISK_OFF` |
| < 30 | `PANIC` |

The API always returns the **top-3 contributing features by |z|** as reason
codes (AC-06-3), so every classification is accompanied by *why*.

### 2. The HMM — latent structure the rule can't see

`backend/apps/regime/hmm_model.py` trains a **4-state** `hmmlearn.GaussianHMM`
(`covariance_type="diag"`) on the daily **standardized feature matrix** — not on
price directly, so the states are regimes of the *whole* breadth/stress/credit
surface, not of one series.

- **4 states**, mapped to `BULL` / `CHOP` / `BEAR` / `CRISIS`.
- **Seeded training with random restarts** (`train_hmm`): 20 restarts at seeds
  `seed + i` (default `REGIME_HMM_SEED=42`), `n_iter=50`, `tol=1e-3`; the fit
  with the highest log-likelihood wins. Deterministic given the seed and data,
  which is what makes the nightly retrain and the tests reproducible.
- **State→label heuristic** (`label_states`): states carry no intrinsic meaning,
  so we rank them post-hoc by a **risk-on score** computed from each state's mean
  feature vector:

  ```
  risk_on(state) = mean[mom_50] + mean[mom_200] − mean[vix] − mean[hy_oas]
  ```

  States are sorted risk-on descending and assigned `BULL` (most risk-on) →
  `CHOP` → `BEAR` → `CRISIS` (least). This keeps labels stable across retrains
  even though `hmmlearn`'s internal state indices are arbitrary from run to run.
- **JSON param serialization** (`serialize_model` / `deserialize_model`):
  `startprob`, `transmat`, `means`, diagonal `covars`, and the state-label map
  are stored on `HMMModel.params` so the active model reloads for online decode
  **without** a retrain.
- **Online decode + Viterbi**: `decode_current` returns the current state +
  `predict_proba` vector for the latest bar; `viterbi_sequence` returns the most
  likely state path for the history chart (AC-06-5).

**Nightly non-regression swap** (`retrain_hmm` task + `activate_model`,
AC-06-4). The 03:00-ET retrain fits a new model on the daily feature history,
scores it out-of-sample on the most recent 90 rows (`holdout_ll`), and **only
activates it if it does not regress** against the current active model:

```
activate  ⇔  new.holdout_ll ≥ current.holdout_ll
             OR  |new.holdout_ll − current.holdout_ll| ≤ 1% · |current.holdout_ll|
```

On activation the prior active model is flipped `active=false` (archived, not
deleted) and `hmm_retrain_total{result="activated"}` increments; a regression
increments `{result="rejected"}` and leaves the incumbent active. A too-small
history skips (`skipped_insufficient_data`, < 120 rows) and a convergence failure
records `fit_failed`. **The current model is never made worse by a retrain.**

### 3. The ensemble — a fixed, deterministic decision table

`backend/apps/regime/ensemble.py` combines the two into one label. It is a pure
function of `(rule_bucket, hmm_state, hmm_confidence)` plus `ENSEMBLE_VERSION`,
where `hmm_confidence = max(hmm_probs)` — so the stored label is deterministic
given the inputs and the version (AC-06-6):

| Rule bucket | HMM state | HMM confidence | Ensemble label |
|---|---|---|---|
| `PANIC` | — | — | **CRISIS** |
| `RISK_ON` | `BULL` | — | **BULL** |
| `RISK_ON` | `CHOP` | > 0.7 | **CHOP** |
| `RISK_ON` | `CHOP` | ≤ 0.7 | **NEUTRAL** |
| `RISK_OFF` | `BEAR` / `CHOP` / `CRISIS` | — | **BEAR** |
| other (`NEUTRAL`, unmatched) | `BULL` | > 0.8 | **BULL** |
| other (`NEUTRAL`, unmatched) | `BEAR` / `CRISIS` | > 0.8 | **BEAR** |
| **fallback** | absent / weak | — | **rule's own label** |

The fallback maps the rule bucket to its label directly
(`RISK_ON→BULL`, `NEUTRAL→NEUTRAL`, `RISK_OFF→BEAR`, `PANIC→CRISIS`). The reading
of the table: `PANIC` is an unconditional CRISIS override (a hard rule wins over
any model); the HMM can *sharpen* a rule call (RISK_ON + confident CHOP → CHOP)
or *override a neutral* rule when it is strongly confident (> 0.8); otherwise the
rule's own label stands.

### 4. Graceful degradation is a first-class path, not an error path

`compute_observation` (`backend/apps/regime/services.py`) treats a missing or
**stale** HMM as normal operation, not failure. If there is no active model, or
the active model's `trained_at` is older than **48h** (`MODEL_STALE_HOURS`), or
decode raises, the HMM inputs are dropped and the ensemble collapses to the
fallback row — i.e. **rule-only**. Every observation records
`model_degraded=true` in that case (AC-06-8), which the API surfaces
(`model.degraded`) and the badge renders as a "Rule-based only" state
(`frontend/src/assets/help/regime-badge.html`). This is the whole reason the
ensemble is worth building: the powerful-but-fragile half can fail completely and
the system keeps producing a sane, explainable regime call with zero operator
intervention. The operator recovery path is
`docs/runbooks/hmm-retrain-failure.md`.

### 5. Reproducibility guarantee (AC-06-10)

`backend/apps/regime/features.py::content_hash` hashes the standardized vector
(each feature rounded to 6 dp, keys sorted) with SHA-256 and stores it on
`FeatureVectorSnapshot.content_hash`. Given the same stored bars + macro data and
the same rolling history, feature computation is pure and deterministic, so the
hash is stable — re-running the pipeline reproduces byte-identical features. The
HMM half is reproducible by construction too: fixed seed + fixed restarts + fixed
data ⇒ the same fit. This is what lets the golden-fixture tests assert an exact
committed hash rather than a tolerance.

### 6. Look-ahead-bias avoidance (§16 audit)

The plan rates feature-vector look-ahead bias **Low/High** and requires the
avoidance to be audited in this ADR. The pipeline is **point-in-time by
construction**:

- Every feature is computed from **trailing** windows of already-closed bars —
  momentum (`_mom`), RSI (`_rsi`), the breadth counts (% above SMA, A/D, NH/NL),
  and the McClellan input all read `tail(n)` of the series **up to and including
  the trade-date bar**, never a future bar.
- Standardization uses a **trailing** rolling window (`ROLL_WINDOW = 252`,
  `history[-252:]`) of prior raw values — the z-score for date *t* is computed
  against `[t-252, t)` history only, never centered on future data.
- The authoritative daily vector is computed by `compute_features_daily` at
  **18:30 ET, after the close** (`§6.8`), on that day's settled bars — no
  intraday peeking at a value that isn't final.

There is no step that reads a bar dated after the observation timestamp, so a
model trained on this history could, in principle, have been run live on each
date with the data available *then*.

## Consequences

**Positive:**

- **Always answerable, always explainable.** The rule floor guarantees a regime
  call and reason codes even with no model; the HMM only ever *improves* the
  call.
- **Model risk is bounded.** The non-regression swap means a bad nightly fit
  can't degrade the active model, and the 48h-staleness fallback means a broken
  retrain pipeline degrades to rule-only rather than to stale garbage.
- **Deterministic + reproducible end to end** — content hash on features, fixed
  seed on the HMM, versioned pure-function ensemble — which makes the whole stack
  testable against golden fixtures and auditable for look-ahead bias.

**Negative / honest limits:**

- **The real overnight retrain on staging is deferred.** Tests train on seeded
  fixture data with a fixed seed and assert determinism, the swap guard, and
  decode/Viterbi correctness; the *live* 10-year retrain (and the FMP-premium /
  FRED backfill that feeds it) are deferred externals. The swap guard, staleness
  fallback, and metrics are proven; the model's real-world separation quality on
  10y of live features is not yet measured. Verification lives in
  `docs/runbooks/hmm-retrain-failure.md`.
- **The state→label heuristic is a heuristic.** `risk_on(state)` uses four mean
  features; a genuinely novel regime could land two states close on that score
  and swap `CHOP`/`BEAR` between retrains. The ensemble's confidence gates and
  the rule floor absorb this, but the labeling is not a proof.
- **The rule weights are priors.** They are documented and tunable
  (`REGIME_RULE_WEIGHTS`), not learned. That is the point — the rule is the
  explainable baseline — but it means the rule half never adapts on its own; the
  HMM is where adaptation lives.

## Alternatives considered

1. **Rule only.** Rejected: explainable and robust, but blind to latent
   structure and unable to improve from data — it can only ever be as good as our
   hand-tuned weights. Kept as the *floor*, not the whole system.
2. **Single HMM only.** Rejected: opaque (no reason codes for AC-06-3), fragile
   at regime shifts, and with no fallback when the nightly retrain fails or the
   model is cold. Kept as the *override*, gated by confidence and staleness.
3. **A learned meta-model (stacking rule + HMM into a classifier).** Rejected for
   M06: it reintroduces opacity and a second training/validation surface for
   marginal benefit at this scale, and it would need its own labeled regime
   ground truth we don't have. A fixed, versioned decision table is deterministic,
   auditable, and good enough — revisit if the two disagree often in production.
4. **Per-symbol regimes.** Out of scope for M06 (§3) — market-wide only; the
   `/regime/symbol/{sym}/` endpoint is a documented `501` placeholder.

## See also

- ADR-061 — FMP + FRED data vendors (the feature-pipeline inputs) and the
  deferred `Bar` partitioning
- `docs/runbooks/hmm-retrain-failure.md` — operating the nightly retrain + the
  rule-only fallback
- `backend/apps/regime/rule_classifier.py` — weights + buckets
- `backend/apps/regime/hmm_model.py` — training, labeling, serialization, decode
- `backend/apps/regime/ensemble.py` — the decision table
- `backend/apps/regime/features.py` — point-in-time features + content hash
- `backend/apps/regime/services.py` — orchestration, staleness fallback, swap guard
- `project-plan/06-market-data-and-regime.md` §6.4–§6.6
