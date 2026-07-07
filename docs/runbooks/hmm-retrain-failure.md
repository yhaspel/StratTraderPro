# Runbook — HMM retrain failure / stale regime model

**Owner:** Yuval
**Status:** Executable checklist — the nightly retrain, the non-regression swap
guard, and the rule-only staleness fallback are built and unit-tested (M06,
AC-06-4 / AC-06-8) against **seeded fixture data**. The **real overnight retrain
on staging against 10y of live features is a deferred live verification** (needs
the FMP-premium + FRED keys and the backfill; see `docs/adr/061-data-vendor-fmp.md`).
**Companion docs:** `docs/adr/060-regime-ensemble.md` (the ensemble + swap guard +
fallback this operationalizes — read §2/§4 first),
`docs/runbooks/fmp-rate-limit.md` (if the retrain starved because the feature
pipeline couldn't fetch data), `project-plan/06-market-data-and-regime.md`
§6.5, §6.8, §12, §15.

## What this runbook is for

The regime badge keeps working with **no** HMM — that is the design (ADR-060 §4).
So a retrain failure is rarely a user-facing outage; it is a **quiet
degradation** to rule-only that you want to catch and fix before the model rots.
Your job here is to find out *why* the nightly retrain stopped producing an
active, non-stale model and get one back.

## Symptoms / when to open this

- **Alert `regime_model_age_seconds > 48h`** fired during market days (§12). This
  is the primary trigger — the active model is older than the 48h staleness
  threshold, so `compute_observation` has dropped to **rule-only** and every new
  `RegimeObservation.model_degraded = true`.
- **`hmm_retrain_total{result=...}` is incrementing on a non-`"activated"`
  label** night over night:
  - `rejected` — the new model regressed vs the incumbent and the swap guard
    correctly kept the old one (not itself a bug — but if it repeats for days the
    incumbent is aging toward the 48h cliff).
  - `skipped_insufficient_data` — fewer than 120 `FeatureVectorSnapshot` rows;
    the feature pipeline isn't producing daily vectors.
  - `fit_failed` — `hmmlearn` failed to converge on any restart.
- The UI shows the **"Rule-based only"** banner (AC-06-8) and
  `GET /api/v1/regime/current/` returns `model.degraded = true`.
- `GET /api/v1/regime/model/` returns `{"active": null, "degraded": true}` (no
  active model at all).

## How the nightly retrain works (the happy path)

`apps.regime.tasks.retrain_hmm`, scheduled at **07:00 UTC ≈ 03:00 ET**
(`CELERY_BEAT_SCHEDULE["regime-retrain-hmm"]`):

1. Loads every `FeatureVectorSnapshot(scope="MARKET")` ordered by `ts`. If
   `< 120` rows → `skipped_insufficient_data`, return.
2. Splits the standardized feature matrix into train `X[:-90]` and a **90-row
   out-of-sample holdout** `X[-90:]`.
3. `train_hmm` fits a 4-state `GaussianHMM` with **20 random restarts** (seeds
   `REGIME_HMM_SEED + i`, default 42), keeps the max-log-likelihood fit. On any
   exception → `fit_failed`, return.
4. Scores the holdout (`holdout_ll`), assigns state→label by risk-on ranking, and
   creates a **new `HMMModel` row with `active=false`**.
5. Calls `activate_model` — the **non-regression swap guard** — which decides
   whether to promote it.

### The non-regression swap guard (`services.activate_model`, AC-06-4)

The new model is activated **only if it does not regress** against the current
active model:

```
activate  ⇔  new.holdout_ll ≥ current.holdout_ll
             OR  |new.holdout_ll − current.holdout_ll| ≤ 1% · |current.holdout_ll|
```

- **Activate** → the prior active model is flipped `active=false` (archived, not
  deleted), the new one `active=true`, and `hmm_retrain_total{result="activated"}`
  increments.
- **Reject** → the incumbent stays active, `hmm_retrain_total{result="rejected"}`
  increments. The new (rejected) `HMMModel` row is left in the table
  `active=false` for inspection.
- If there is **no** current active model (cold start), the new model is
  activated unconditionally.

So `rejected` is the guard **working** — it refuses to make the active model
worse. It only becomes a problem when it repeats long enough that the *incumbent*
crosses 48h stale.

## Step 1 — Confirm what the active model is

**Via the API:**

```
GET /api/v1/regime/model/     → {version, n_states, trained_at, holdout_ll, degraded}
```

`degraded=true` (or `active: null`) confirms the rule-only fallback is engaged.

**Via the DB / Django shell** — inspect the `HMMModel` rows directly:

```python
# manage.py shell
from apps.regime.models import HMMModel
for m in HMMModel.objects.order_by("-trained_at")[:10]:
    print(m.active, m.version, "holdout_ll=", m.holdout_ll, "trained_at=", m.trained_at)
```

Read it as:

| What you see | Reading |
|---|---|
| An `active=True` row with a recent `trained_at` | Model is fine — the alert may be about the **feature pipeline** stalling, not the model. Check that new `FeatureVectorSnapshot` rows are landing. |
| `active=True` but `trained_at` is > 48h old, and newer `active=False` rows exist with **lower** `holdout_ll` | The swap guard has been **rejecting** regressions. The incumbent is aging. Decide (Step 3) whether to force one through or investigate feature quality. |
| Newest rows are `active=False` and no recent `active=True` | Every recent retrain was rejected or failed — no fresh model got promoted. |
| **No `HMMModel` rows at all** | The retrain has never successfully produced a model (cold start never happened) — almost always `skipped_insufficient_data`. Go to Step 2. |

## Step 2 — Localize the cause via `hmm_retrain_total{result}`

Look at which label incremented on the last few nightly runs:

| `result` | Meaning | Where to look |
|---|---|---|
| `skipped_insufficient_data` | `< 120` daily feature snapshots | The **feature pipeline** isn't producing vectors. Check `compute_features_daily` is running (18:30 ET) and that the FMP/FRED fetch inside it works — see `docs/runbooks/fmp-rate-limit.md`. In CI / unkeyed envs this task is a no-op by design. |
| `fit_failed` | `hmmlearn` didn't converge on any restart | Usually degenerate / collinear features (e.g. a whole block of zeros because a data source is missing). Inspect the recent `FeatureVectorSnapshot.features` for all-zero columns. |
| `rejected` (repeatedly) | New fits keep regressing on holdout | Feature quality or a regime shift the model fits worse. Legit guard behavior — Step 3 to force a fresh model if the incumbent is stale. |
| nothing (no rows) | The task isn't firing at all | Check Celery beat (`regime-retrain-hmm`) and worker health; the task may not be dispatching. |

## Step 3 — Recovery actions

### Manually re-trigger a retrain (safe, idempotent)

Run the exact nightly task on demand — it obeys the same swap guard, so it will
**not** promote a worse model:

```python
# manage.py shell
from apps.regime.tasks import retrain_hmm
print(retrain_hmm())     # → {"version": ..., "holdout_ll": ..., "activated": true/false}
#   or {"skipped": "insufficient_data", ...} / {"error": "fit_failed"}
```

The return dict tells you immediately what happened. If it `activated`, re-check
`GET /api/v1/regime/model/` — `degraded` should now be `false` and the age alert
clears.

### Force rule-only fallback (deactivate a bad model) — §15 rollback

If a model is actively *wrong* (bad labels, decode misbehaving) and you'd rather
run the explainable rule floor than a suspect model, deactivate it. The next
`compute_observation` will see no active model and produce rule-only observations
with `model_degraded=true` — the badge shows "Rule-based only", nothing breaks:

```python
# manage.py shell — the §15 "HMM regresses → rule-based fallback continues" path
from apps.regime.models import HMMModel
HMMModel.objects.filter(active=True).update(active=False)
```

This is also doable via the Django admin (`HMMModel` → untick **active**). It is
the intended safe state, not an outage.

### If the incumbent is stale because retrains keep getting rejected

The guard is doing its job; the fix is upstream. Either (a) the feature pipeline
is feeding degraded vectors — fix the data source and let the next retrain fit
cleanly — or (b) a genuine regime shift means the *new* fit really is worse on the
recent holdout. If you must refresh the model anyway, the supported path is to
**deactivate the stale incumbent** (above) so the next `retrain_hmm` cold-starts
(no incumbent ⇒ unconditional activation of the new fit). Do this deliberately —
it drops the non-regression protection for that one swap.

## Step 4 — Verify recovery

- `GET /api/v1/regime/model/` → `degraded=false`, a recent `trained_at`, a
  populated `holdout_ll`.
- `GET /api/v1/regime/current/` → `model.degraded=false`; the badge's
  "Rule-based only" banner is gone.
- `regime_model_age_seconds` drops back under 48h and the alert clears.
- `hmm_retrain_total{result="activated"}` incremented on your manual run.

## Note on the deferred live verification

Everything above is proven in tests **against seeded fixture features** — the swap
guard, the staleness fallback, decode, and the metrics all have unit coverage
(`test_activate_model_swap_guard`, `test_retrain_task_trains_and_activates`,
`test_compute_observation_rule_only_when_no_model`). What has **not** run yet is
the **real overnight retrain on staging against 10y of live features**; that waits
on the FMP-premium + FRED keys and the historical backfill (deferred externals,
ADR-061). When it does run, walk this runbook once end to end and record the first
live `activated` in the M06 exit-gate checklist (§17).
