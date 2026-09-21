# StratTraderPro — Silent-Failure Audit Report

**Date run:** 2026-09-21
**Task:** `strattraderpro-silent-failure-audit` (scheduled task, 6-check production sweep)
**Result:** 3 of 6 checks pass their literal thresholds (CHECK 3, 4, 5). 3 of 6 fail their literal thresholds (CHECK 1, 2, 6) — but all three trace to a single root cause, and none reflects a live production regression.

---

## Executive summary

| # | Check | Literal result | What's actually happening |
|---|---|---|---|
| 1 | No alert rule paused | **FAIL** (11 rules vs. expected 21) | Stale baseline — ADR-109 rightsized the rule set to 11 on 2026-08-02. 0 rules paused. |
| 2 | All scrape targets up | **FAIL** (5 series vs. expected 14) | Stale baseline — ADR-109 removed 2 exporter jobs and consolidated to `env=production` only. All 5 present targets healthy. |
| 3 | Beat→queue→worker loop alive | PASS | `celery_queue_depth` fresh, `absent()` empty. |
| 4 | No rule unhealthy/firing | PASS | 11/11 `health=ok`, 0 firing, 0 pending. |
| 5 | Metrics budget < 1.0 DPM ratio | PASS | 0.9771 — under threshold, high end of healthy band. |
| 6 | Frontend runtime config substituted | **FAIL** (wrong URL — domain not provisioned) | Stale baseline — the frontend's public Railway domain changed during the same ADR-109 cutover. The current domain serves fully-substituted config with a valid release SHA. |

**Bottom line:** the production system itself is healthy on all 6 dimensions. The audit task's own hardcoded expected values (rule count, target count, frontend URL) were written before the ADR-109 infrastructure change (executed 2026-08-02, soak-verified 2026-08-03) and were never updated afterward. The "failures" below are a documentation/maintenance issue in the audit definition, not an incident — verified by directly checking the corrected values against the live system.

---

## Failures

### Failure 1 — CHECK 1: alert rule count reads 11, audit expects 21

**Observed:** `GET /api/v1/provisioning/alert-rules` → 11 rules, `isPaused: false` on all 11.
Titles: `AuditIntegrityFailure`, `BrokerStreamSilent`, `CeleryQueueDepthHigh`, `KillSwitchFlattenSlow`, `KillSwitchTriggered`, `MetricsBudgetExhausted`, `MetricsBudgetHigh`, `MetricsPipelineDown`, `TargetDown`, `WebhookErrorRatioCrit`, `WebhookErrorRatioWarn`.

**Expected per task definition:** 21 rules, none paused.

**Root cause:** Not a deletion or regression. **ADR-109** ("reduce Grafana to the safety core") deliberately rightsized the rule set from 23 → 11 on 2026-08-02, via 12 authorized `DELETE` calls (9 "retire" rules + a 3-rule auth folder that was itself a defective, false-positive-generating check). The 11 surviving titles match the ADR-109 "keeper" list exactly. A follow-up soak audit the next day (`ADR-109-H3-VERDICT.txt`, 2026-08-03) already recorded a passing 6-check run with **11** as the expected rule count — i.e., a previous version of this same audit already treated 11 as correct. This scheduled task's "21" constant simply predates that change and was never bumped.

This is unrelated to BUG-009 (all-rules-paused) — that bug is closed, and the paused-on-import trap it describes isn't in play here; 0 rules are paused.

**Evidence:**
- `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md` — PART C: `23 − 9 − 3 = 11`, all 12 deletes returned `HTTP 204`, zero drift confirmed between live and committed YAML for the 11 keepers before deletion.
- `project-plan/ADR-109-H3-VERDICT.txt` (2026-08-03) — `[PASS] rule count == 11 (got 11)`, `[PASS] rule titles match (diff: none)`.

**How to fix:** Update the `strattraderpro-silent-failure-audit` scheduled task definition:
- Change CHECK 1's expected count from **21 → 11**.
- Optionally, pin the exact 11 titles (listed above) instead of a bare count — a count-only check can't tell "the right 11 rules" from "any 11 rules," so a future swap (one keeper silently replaced by something else) wouldn't be caught. A title-set comparison would.

---

### Failure 2 — CHECK 2: scrape target count reads 5, audit expects 14

**Observed:** `up` query → 5 series, all value `1`: `backend`, `beat`, `worker`, `streams`, `worker-backtest`, all `env="production"`. No series at 0; nothing down.

**Expected per task definition:** 14 series, all equal to 1.

**Root cause:** Same ADR-109 cutover. Part of the rightsizing deleted two Railway services — `postgres-exporter-prod` and `redis-exporter-prod` — whose metrics no alert actually depended on, and consolidated scraping to the `production` environment only (a `staging` environment previously contributed a duplicate set of series, which is consistent with 7 jobs × 2 envs ≈ 14 pre-cutover vs. 5 jobs × 1 env = 5 now). This was the plan's explicit PART E target state, confirmed already met at the time and re-confirmed the next day.

Unrelated to BUG-008 (dead-man's-switch) or BUG-010 (worker/beat metrics unscrapeable) — both are closed; this is a target-count change, not a scrape failure.

**Evidence:**
- `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md` — PART E: `count by (job, env) (up)` → exactly 5 series, `env=production` the only value present; E.3 records the two exporter services deleted (with Railway service IDs).
- `project-plan/ADR-109-H3-VERDICT.txt` (2026-08-03) — `[PASS] 5 up targets (got ['backend','beat','streams','worker','worker-backtest'])`, `[PASS] env == production only`.

**How to fix:** Update the scheduled task definition:
- Change CHECK 2's expected series count from **14 → 5**.
- Optionally assert the exact job set (`backend, beat, worker, streams, worker-backtest`) and `env=production` explicitly, rather than a bare count — same reasoning as Failure 1.

---

### Failure 3 — CHECK 6: frontend URL returns "domain not provisioned"

**Observed:** `https://frontend-production-c977f.up.railway.app` returned a **Railway edge-level 404** — "The train has not arrived at the station... check your network settings to confirm your domain has provisioned" — for both `/` and `/config.js`. Reproduced twice (distinct request IDs `MxIIIkBITn6mUlDdO8poTA` and `XzzB4cLTRyiRSbyIBhdwDg` on `/config.js`, `CvoCrLerTjO294lyo3UVLg` on `/`), so not a transient blip. This is a platform-level "nothing is bound to this hostname" response, not an application 404 — meaningfully different from, and more severe-looking than, the nginx/envsubst failure mode (BUG-003/BUG-004) the check was designed to catch.

**Expected per task definition:** `/config.js` served from `https://frontend-production-c977f.up.railway.app`, fully substituted, non-empty `release` SHA.

**Root cause:** The frontend's public Railway domain changed during the same ADR-109 window. `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md` and `project-plan/archived/ONE-SHOT-ADR-109-OPERATOR-CLI.prompt.md` both reference `https://strattraderpro.up.railway.app` as the frontend's identity and explicitly note the old `frontend-production-c977f` host 404s. The frontend Railway *service* itself was not deleted or recreated by ADR-109 (it's listed intact in the post-cutover service inventory) — only the public domain differs, and no file in the repo pins down exactly when or why the domain itself was switched; later documents treat it as already-known. The new domain was most recently exercised live on **2026-09-20** (the day before this audit) in `project-plan/archived/ONE-SHOT-MFA-SKEW-DIAGNOSTICS.prompt.md`, so it is current and in active use.

**Verification performed (not just inferred):** navigated directly to `https://strattraderpro.up.railway.app/config.js` and read the response:

```js
window.STP_CONFIG = {
  backendUrl: 'https://backend-production-f3e8.up.railway.app',
  grafanaUrl: 'https://yuval3000.grafana.net',
  sentryDsn: 'https://eb4bd0535ad19edb19f28b3cc6f90c1f@o4511716412489728.ingest.us.sentry.io/4511716419305472',
  sentryEnvironment: 'production',
  release: '1dcdd7045c7b1e4f20bc1a03d1f5c765c6338492'
};
```

No literal `${` anywhere; `release` is a non-empty 40-character commit SHA. Both of CHECK 6's actual assertions pass cleanly against the correct URL. BUG-003 and BUG-004 (empty release / envsubst allowlist) do not apply — the substitution mechanism is working correctly.

**How to fix:** Update the scheduled task definition:
- Change CHECK 6's target URL from `https://frontend-production-c977f.up.railway.app` to `https://strattraderpro.up.railway.app`.
- Separately (repo hygiene, not this audit): consider documenting the domain change explicitly somewhere durable (e.g. `PROGRESS.md` or a short note in `bugs/README.md`'s ADR-109 section), since right now the correct URL is only recoverable by cross-referencing two ADR-109 session reports — the same kind of undocumented-drift trap this audit exists to catch.

---

## Passing checks (for completeness)

**CHECK 3 — beat→queue→worker loop:** `celery_queue_depth{env="production"}` has 2 fresh series (`queue="backtest"` and `queue="celery"`, both depth 0 — an empty queue, not a stalled one). `absent(celery_queue_depth{env="production"})` returned an empty result, confirming the series is current, not stale. The full chain (beat fired → task reached the queue → worker consumed it → metric written → agent scraped it) is intact.

**CHECK 4 — rule health / unexpected firing:** `GET /api/prometheus/grafana/api/v1/rules` → 11/11 rules report `health: "ok"`. 0 rules in `firing` or `pending` state.

**CHECK 5 — metrics budget:** `grafanacloud_instance_samples_per_second * 60 / grafanacloud_instance_active_series` = **0.9771**. Under the 1.0 violation threshold, but at the high edge of the stated healthy band (0.85–0.96) rather than comfortably inside it. Not a failure — worth a glance on the next run if it keeps trending upward, since it would mean the scrape interval or active-series count is drifting.

---

## Recommended actions

1. **Update the `strattraderpro-silent-failure-audit` scheduled task** with the three corrected values: rule count 21→11 (or the pinned title list), target count 14→5 (or the pinned job list), and the frontend URL → `strattraderpro.up.railway.app`. Until this happens, every future run will re-flag these same three non-issues instead of surfacing a genuinely new one.
2. **Document the frontend domain change** somewhere durable in the repo — it currently only exists as an aside inside two ADR-109 operator-session reports.
3. No action needed on production infrastructure — all 6 underlying systems (alerting, scrape targets, Celery loop, rule health, metrics budget, frontend config) are healthy as of this audit.

---

## Addendum — 2026-09-21, after acting on this report

Two corrections to the analysis above, found while implementing the fixes. Tracked as
[`bugs/BUG-012`](../bugs/BUG-012-silent-failure-audit-prompt-reverted.md).

**1. The root cause is a revert, not a missed update.** This report concludes the baselines
"were written before ADR-109 and never updated afterward." They *were* updated — twice. The
2026-08-01 backup (`stp-adr109-backup-2026-08-01/daily-audit-prompt-BEFORE.md`, 9,359 B)
already had the correct `strattraderpro.up.railway.app` URL and a range-based CHECK 5, and
ADR-109 PART G applied the 11-title / 5-job pinned sets on 2026-08-02 (→ 13,086 B). The file
that ran on 2026-09-21 was **7,351 B, dated 2026-08-18** — smaller than either, with check
bodies matching a ~2026-07-11 ancestor. A later edit rewrote the prompt from a stale copy,
adding a better tab-cleanup protocol while discarding five weeks of baseline corrections.

This matters because the fix is different: bumping three constants would have left the prompt
unversioned and equally liable to be reverted again. It is now version-controlled at
`infra/scheduled-tasks/` with a drift check (`scripts/check_scheduled_task_sync.sh`).

**2. CHECK 5 is a FAIL, not a PASS — the threshold is miscalibrated.** This report records
0.9771 as "under threshold, high end of the healthy band." With `scrape_interval` correctly at
60s the ratio sits at ~1.0 *by definition*, so the `< 1.0` assertion fails on most samples.
Over the 30 days to 2026-09-21 (721 hourly samples): median **1.0000**, mean 0.9966, range
0.50–1.25 — **64.8% of samples are ≥ 1.0**, only 12.6% fall in the claimed 0.85–0.96 band, and
none ever reached 1.5. The 0.9771 reading was a sample from the 35% of time it dips below.
At the moment of verification the instant value was **1.0464** (a FAIL) while the restored
3-hour spec read 0.9732 avg / 1.1980 max (a PASS). The threshold has been restored to the
evidence-based 3h range with `FAIL if ≥ 1.3`.

**Unchanged:** the report's core finding — that production itself is healthy on all six
dimensions — was independently re-verified by direct API queries and holds.

---

## Sources (local files referenced)

- `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md`
- `project-plan/ADR-109-H3-VERDICT.txt`
- `project-plan/archived/ONE-SHOT-ADR-109-OPERATOR-CLI.prompt.md`
- `project-plan/archived/ONE-SHOT-MFA-SKEW-DIAGNOSTICS.prompt.md`
- `bugs/BUG-003-healthz-reports-stale-git-sha.md`
- `bugs/BUG-004-nginx-envsubst-filter-too-narrow.md`
- `bugs/BUG-008-no-dead-mans-switch-alerting-fails-silent.md`
- `bugs/BUG-009-all-alert-rules-imported-paused.md`
- `bugs/BUG-010-worker-beat-metrics-endpoints-unscrapeable.md`
- `bugs/README.md`
- Live queries against `https://yuval3000.grafana.net` (Grafana provisioning/rules/datasource-proxy APIs) and `https://strattraderpro.up.railway.app/config.js`, run 2026-09-21.
