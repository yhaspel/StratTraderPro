# BUG-012 — The daily silent-failure audit was silently reverted to a stale ancestor

- **Status:** FIXED & VERIFIED (2026-09-21)
- **Severity:** S2 — the project's top-level "is production silently broken?" detector was
  reporting three fabricated failures a day and had lost several of its real assertions.
- **Area:** Observability/Ops
- **Detected by:** the 2026-09-21 run of `strattraderpro-silent-failure-audit` itself, which
  reported 3/6 checks failing. Investigating the "failures" found the system healthy and the
  *audit definition* regressed.

## Symptom

The scheduled task reported CHECK 1, CHECK 2 and CHECK 6 as FAIL every run:

| Check | Audit expected | Production actually has |
|---|---|---|
| 1 — no rule paused | 21 alert rules | **11** rules, 0 paused (ADR-109 rightsizing) |
| 2 — targets up | 14 `up` series | **5** series, all `1`, all `env="production"` |
| 6 — frontend config | `frontend-production-c977f.up.railway.app` | host retired 2026-07-15; **`strattraderpro.up.railway.app`** serves valid config |

All three "failures" were false. Production was healthy on all six dimensions.

## Root cause — not "the constants were never updated"

The obvious reading is that the baselines predated ADR-109 and were never bumped. That is
wrong, and the distinction matters: **they were corrected twice, and then lost.**

Reconstructed from the backups in `stp-adr109-backup-2026-08-01/`:

| Version | Size | CHECK 1 | CHECK 2 | CHECK 5 | CHECK 6 |
|---|---|---|---|---|---|
| ~2026-07-11 ancestor | ? | 21 rules | 14 series | instant `< 1.0` | `frontend-production-c977f` |
| 2026-08-01 (`daily-audit-prompt-BEFORE.md`) | 9,359 B | 23 rules | 7 series, named | **3h range, FAIL ≥ 1.3** | **`strattraderpro.up.railway.app`** |
| 2026-08-02 (ADR-109 edits applied) | 13,086 B | **11 pinned titles** | **5 pinned jobs** | 3h range | `strattraderpro.up.railway.app` |
| **2026-08-18 (what was live)** | **7,351 B** | **21 rules** | **14 series** | **instant `< 1.0`** | **`frontend-production-c977f`** |

The live file on 2026-08-18 was *smaller than any prior version* and its check bodies matched
the ~2026-07-11 ancestor — i.e. a later edit rewrote the prompt from a stale copy. It added a
genuinely better tab-handling protocol (STEP 0 tab baseline, unconditional verified CLEANUP,
the `CLEANUP: N tab(s) could not be closed` line) but silently discarded, in one stroke:

- the **2026-07-15 OSS-pivot** correction (CHECK 6 URL, `env=production` only),
- the **2026-08-01** noise-aware CHECK 5 (range-based, not instantaneous),
- the **2026-08-02 ADR-109** corrections (11 pinned rule titles, 5 pinned jobs, the
  `StratTraderPro Auth` folder-absence assertion),
- the drift-**NOTE** output contract, which was the mechanism by which a stale baseline was
  supposed to announce its own replacement value.

Nothing noticed for ~5 weeks. The prompt lived outside version control, so there was no diff
to review and no history to bisect. **The monitor's own definition had no monitor.**

## A fourth defect the audit report missed: CHECK 5 was miscalibrated

The 2026-09-21 report marked CHECK 5 a PASS at 0.9771, "high end of the healthy band". It is
not a pass — it is a coin flip. The reverted CHECK 5 asserts
`samples_per_second * 60 / active_series < 1.0` with a claimed healthy band of 0.85–0.96.

With `scrape_interval` correctly at 60s, that ratio sits **at ~1.0 by definition** (one
datapoint per series per minute). Measured over the 30 days to 2026-09-21 (721 hourly samples,
~1,850 active series):

```
min 0.5000   max 1.2500   mean 0.9966   median 1.0000
>= 1.0  (check FAILS):        467/721 = 64.8%
within claimed band .85-.96:   91/721 = 12.6%
>= 1.5  (true 30s drift):        0/721
```

So the check fails on roughly **two runs in three** while a genuine scrape-interval halving —
which drives the *sustained* value to ~2.0 — never occurred. The 2026-08-01 version had
already diagnosed this and replaced the instant test with a 3-hour range (`FAIL if ≥ 1.3`);
the revert undid it.

This is the same pathology the task exists to catch, inverted: a detector that cries wolf on
two runs in three trains its operator to ignore it, which is precisely how a real regression
walks past.

## Fix

1. **Rebuilt the prompt** as a three-way merge — ADR-109's pinned-set assertions + the
   2026-08-01 range-based CHECK 5 and correct CHECK 6 URL + the newer tab-cleanup protocol,
   with baselines re-verified against live production on 2026-09-21.
2. **Put it under version control** at
   [`infra/scheduled-tasks/strattraderpro-silent-failure-audit.SKILL.md`](../infra/scheduled-tasks/strattraderpro-silent-failure-audit.SKILL.md).
   The live file now carries a header pointing at the repo copy as canonical.
3. **Added the drift detector** — `scripts/check_scheduled_task_sync.sh` diffs the live prompt
   against the repo copy (exit 1 + diff on drift). Per this repo's rule that a bug which could
   have been caught by a test must add that test, this is that test. It was verified to fail
   on an injected change, not merely to pass.
4. **Documented the endpoints** in [`docs/ops/production-endpoints.md`](../docs/ops/production-endpoints.md)
   so the frontend URL is no longer recoverable only from session reports.

## Verification (2026-09-21, against live production)

Every assertion in the restored prompt was executed directly against Grafana Cloud and the
production frontend:

```
CHECK 1  11 rules, paused []                                          PASS
         titles == the pinned 11                                      PASS
         Auth folder uid cfkrwjgh3sxkwa absent (HTTP 404)             PASS
CHECK 2  5 up series == 1: backend,beat,streams,worker,worker-backtest PASS
         no other job, no env != production                           PASS
CHECK 3  celery_queue_depth: 2 series (celery, backtest), depth 0     PASS
         absent(celery_queue_depth{env="production"}) == []           PASS
CHECK 4  11/11 health=ok, 0 firing, 0 pending                         PASS
CHECK 5  3h avg 0.9732 (< 1.3)  |  3h max 1.1980 (< 1.5)              PASS
CHECK 6  /config.js HTTP 200, no ${ }, release=1dcdd704...8492 (40ch) PASS
```

Note CHECK 5 under the restored spec passes at 0.973/1.198 while the reverted instant spec
**fails** at that same moment (1.0464) — the recalibration is what makes the check meaningful.

## Lessons

- **A prompt that defines a safety check is production config.** If it lives outside git, its
  regressions are invisible and unattributable. Version it.
- **A stale baseline degrades to noise, not silence** — and noise is just a slower silence.
  The 2026-08-01 drift-NOTE contract (report the replacement value even when the check passes)
  is the cheap fix, and was itself reverted.
- **Threshold at the mean is not a threshold.** A check whose healthy state sits exactly on its
  failure boundary is a coin flip. Separate the bands: healthy ~1.0, fail ≥ 1.3, real fault ~2.0.
- **Prefer pinned sets to bare counts.** "11 rules" cannot distinguish the right 11 from any 11.

## Related

- [BUG-005](BUG-005-grafana-free-tier-metrics-limit.md) — the real DPM regression CHECK 5 guards
- [BUG-009](BUG-009-all-alert-rules-imported-paused.md) — the paused-rule class CHECK 1 guards
- [BUG-003](BUG-003-healthz-reports-stale-git-sha.md) /
  [BUG-004](BUG-004-nginx-envsubst-filter-too-narrow.md) — the config-substitution class CHECK 6 guards
- `project-plan/2026-09-21-silent-failure-audit-report.md` — the run that surfaced this
- `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md` PART G — the 2026-08-02 edits that were lost
