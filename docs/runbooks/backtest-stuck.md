# Runbook — Backtest run stuck / slow / queue not draining

**Last reviewed:** 2026-07-12

**Owner:** Yuval
**Status:** Executable checklist. The dedicated `backtest` Celery queue, the
`worker-backtest` compose service, cooperative cancellation, the nightly artifact
eviction, and the time/memory caps are built and unit-tested (M09,
AC-09-2/9/10/11). The **staging performance SLA (3y ≤ 10 min, 10y ≤ 30 min, RSS
≤ 2 GB) and the Railway `worker-backtest` service are operator-deferred** — the
procedures for both are in this runbook. **Companion docs:**
`docs/adr/090-vectorbt-plus-custom-replay.md` (engines + deps),
`docs/adr/091-walk-forward-protocol.md` (what a run actually does),
`docs/runbooks/fmp-rate-limit.md` (only relevant to the M06 backfill, not the
backtest worker — the worker never calls a live vendor),
`project-plan/09-walk-forward-backtester.md` §6.0, §6.2, §6.8, §10.4, §12.

## What this runbook is for

A backtest run has a small number of ways to look "stuck," and they have very
different causes:

- **Stuck in `QUEUED` forever** — almost always: *no worker is consuming the
  `backtest` queue* (the #1 cause in prod today). See §1.
- **Stuck in `RUNNING`, pct not moving** — a genuinely long sweep, an OOM restart
  loop, or a wedged worker. See §3 and §4.
- **`FAILED` with `BACKTEST_TIME_CAP`** — the run hit the 25-min soft limit. Not
  stuck — capped. See §5.

Start by reading the run's `status`, `stage`, `pct`, and `error_code`
(`GET /api/v1/backtest/runs/{id}/` or the Django admin `BacktestRun`).

## §1 — "Stuck in QUEUED forever": the worker doesn't exist yet (#1 cause)

**Symptom:** a run sits at `status=QUEUED`, `stage=queued`, `pct=0`; the
`backtest_queue_wait_seconds` p95 climbs and the "queue wait p95 > 10 min" alert
fires (§12). Retention and the runs list still work fine.

**Cause:** `run_backtest` is routed to the dedicated **`backtest` queue** (via the
explicit per-task route in `CELERY_TASK_ROUTES`), and the **default `celery`
worker does not consume it**. In an environment where no `worker-backtest` service
exists, the task is enqueued and never picked up. **On Railway this service is an
operator step** — until it is created, every prod run sits `QUEUED` forever. This
is called out in ADR-090/§6.8 and is the expected state on a fresh prod.

**Why retention still works anyway:** the nightly `evict_expired_artifacts` task is
deliberately routed to the **default `celery` queue**, not `backtest`. So artifact
eviction (and its orphan-cleanup double-duty, §15) keeps running even when the
backtest worker is scaled to zero or not yet provisioned. Only *new runs* are
blocked — nothing silently rots.

**Fix:** stand up the worker (§7 for Railway; local is `docker compose up
worker-backtest`). Once it is consuming `backtest`, queued runs drain in FIFO
order.

## §2 — Inspect the `backtest` queue depth

The queue is a Redis list keyed by queue name. To see how many runs are waiting:

```bash
# how many tasks are parked on the backtest queue (Redis list length)
redis-cli -u "$REDIS_URL" LLEN backtest

# is anything consuming it? active workers + the queues they serve:
celery -A config.celery inspect active_queues
celery -A config.celery inspect active        # currently-executing tasks
celery -A config.celery inspect stats         # per-worker pool + memory
```

Read it as:

| What you see | Reading |
|---|---|
| `LLEN backtest` > 0 and no worker lists `backtest` in `active_queues` | The worker isn't running / isn't provisioned — §1. |
| `LLEN backtest` > 0, a worker *does* serve `backtest`, one task `active` | Normal: `--concurrency=1` means one run at a time; the rest wait. |
| `LLEN backtest` == 0 but a run still says `QUEUED` | The run's DB row is stale, or the task was lost. Re-check the run; if the task id is empty and the queue is empty, it was never enqueued (check the POST succeeded). |

Note `--concurrency=1` is intentional (§7): one sweep can peak near the 2 GB
memory cap, so we run them one at a time rather than risk two colliding.

## §3 — Cancel a running (or queued) run

Cancellation is **cooperative** — it does not kill the process, it flips a flag the
worker checks between windows and between sweep chunks, so it halts within **≤ 30
s** on target hardware (AC-09-9):

```
POST /api/v1/backtest/runs/{id}/cancel/     → 202, status becomes CANCELLING
```

The task sees `status=CANCELLING` at its next checkpoint, stops cleanly, and the
run ends **`CANCELLED`** with **no report** (a `backtest.cancelled` WS event
fires). A queued run cancels immediately (it's checked before work starts).

If a run is `CANCELLING` for **well over 30 s** and not progressing, the worker is
wedged (not merely busy) — go to §4.

## §4 — Hard-kill a wedged worker + orphan cleanup

If cooperative cancel doesn't take (the loop is stuck inside a single vectorbt
call, say), hard-kill the worker process:

```bash
# local compose
docker compose restart worker-backtest      # or: docker compose stop worker-backtest

# Railway: restart the worker-backtest service from the dashboard, or scale to 0/1
```

The task's hard `time_limit=1800` (30 min) is the backstop — Celery kills the
child process at 30 min regardless. On restart, an interrupted run is left in a
non-terminal state (`RUNNING`/`CANCELLING`) with no terminal event.

**Orphan cleanup:** the nightly `backtest-evict-artifacts` beat (03:30 UTC) doubles
as orphan cleanup — it nulls artifacts on runs past retention and keeps the metrics
rows. For a run left dangling by a hard-kill, either re-run it (idempotent — a new
run id) or, if you must tidy the row, mark it `FAILED` via the admin. There is no
partial artifact to leak: a report is only written at successful completion (the
`BacktestReport` `update_or_create` is the last step before `COMPLETED`).

## §5 — `FAILED` with `BACKTEST_TIME_CAP` (not stuck — capped)

**Symptom:** run ended `FAILED`, `error_code=BACKTEST_TIME_CAP`.

**Cause:** the task hit its **soft** time limit `soft_time_limit=1500` (25 min);
`SoftTimeLimitExceeded` is caught and the run is marked `FAILED` with a
user-visible error (the hard `time_limit=1800` / 30 min would kill the process if
the soft handler didn't). This is a **cap, working as designed** — the run was too
big for the budget.

**Fix (user-side):** shrink the job — fewer symbols, a smaller `param_grid`, a
shorter date range, or fewer windows. The §11 caps (grid ≤ 500 combos, ≤ 60
windows, ≤ 10 symbols, ≤ 15 y) bound the worst case, but a run near several of
those at once can still exceed 25 min on modest hardware.

## §6 — Related failure codes (fast triage)

Not "stuck," but you'll see these in the same admin view:

| `error_code` | Meaning | Action |
|---|---|---|
| `BACKTEST_NO_ADAPTER` | Strategy has no registered Python adapter (ADR-092) | Only adapter-backed strategies (e.g. `sma-cross-demo`) are backtestable. Expected for uploaded strategies. |
| `BACKTEST_INSUFFICIENT_DATA` | < 95% weekday coverage in `[start, end)` for a symbol | The local `Bar` store is thin/gapped. **Run the M06 backfill first** — the worker never calls a live vendor. The message names the largest gaps. |
| `BACKTEST_GRID_TOO_LARGE` | > 500 combos | Shrink the grid (or refine the user grid to a subset). |
| `BACKTEST_REPORT_TOO_LARGE` | An artifact > 25 MB | Should never trigger at MVP scale; investigate the config if it does. |
| `BACKTEST_DISABLED` | `BACKTEST_ENABLED=False` | Master rollback flag is off (§15). |

## §7 — Railway `worker-backtest` service setup (operator step)

The dedicated worker is a compose service locally; on Railway it must be created by
hand (this is the fix for §1 in prod). Create a new service off the **backend
image / repo** with this exact start command:

```
celery -A config.celery worker -Q backtest -l info --concurrency=1 --max-memory-per-child=2000000
```

- `-Q backtest` — consume **only** the backtest queue (do not add `celery`; the
  default worker owns that and order flow must stay isolated from sweeps).
- `--concurrency=1` — one run at a time (a sweep can peak near the memory cap).
- `--max-memory-per-child=2000000` — 2 GB (KiB units); Celery recycles the child
  process after a task pushes it past this, bounding RSS (AC-09-10, §6.2 grid
  chunking keeps peak under it).

Give it the same env as the other backend services (`DATABASE_URL`, `REDIS_URL`,
`SECRET_KEY`, `DJANGO_SETTINGS_MODULE=config.settings.prod`, `BACKTEST_ENABLED`).
It needs the WeasyPrint system libs (Pango/HarfBuzz/fontconfig + DejaVu fonts) —
already in `docker/backend.Dockerfile`, so the backend image has them. Verify it is
live with `celery -A config.celery inspect active_queues` (it should list
`backtest`). To **stop all backtest processing instantly**, scale this service to
zero — runs queue up harmlessly and drain when it comes back (retention is
unaffected, §1).

## §8 — Staging performance procedure (deferred / operator)

The performance SLA (AC-09-10) is verified on staging, not in CI (CI runs only the
1-year, grid ≤ 24, ≤ 60 s smoke). When staging exists, run this once and record the
numbers in the M09 exit-gate checklist (§17):

**Targets:** 3-year single-symbol WF **≤ 10 min**; 10-year **≤ 30 min**; worker
peak RSS **≤ 2 GB**.

**How to run:**

1. Ensure the symbol has the bars backfilled (M06 `backfill_bars`) — the worker
   reads the local `Bar` store only; no live vendor calls happen mid-run.
2. Submit a single-symbol run over the target range on the demo strategy
   (`sma-cross-demo`) via the `/backtest` launcher or `POST
   /api/v1/backtest/runs/`. A synthetic 3y/10y fixture is acceptable for the timing
   (real-symbol data needs the FMP key + backfill).
3. **Time it:** the run's `duration_seconds` (from `started_at`/`finished_at`, on
   the detail endpoint) is the wall clock; `backtest_run_duration_seconds` also
   records it. Compare against the target.
4. **Watch memory** on the `worker-backtest` container throughout — Railway service
   metrics, or `docker stats worker-backtest` locally. Peak RSS must stay ≤ 2 GB;
   the `--max-memory-per-child=2000000` cap recycles the child if a sweep pushes
   past it, but a clean run should not approach it thanks to the ≤ 100-combo sweep
   chunking. If RSS is near the cap on a 10y run, reduce the grid or shorten the
   range.

If a target is missed, the levers are: smaller grid, fewer windows, or a bigger
staging instance — captured as a follow-up, not a code change.

## §9 — The metrics you are watching (§12)

| Metric | What it tells you |
|---|---|
| `backtest_active_runs` (gauge) | Runs currently executing. Should be 0 or 1 (concurrency=1). Pinned at 0 with a growing queue ⇒ §1. |
| `backtest_queue_wait_seconds` (histogram) | Enqueue → task start. p95 climbing / the "> 10 min" alert firing ⇒ the worker isn't keeping up or isn't there (§1). |
| `backtest_run_duration_seconds` (histogram, → 1800 s) | Wall-clock per run. The top bucket filling ⇒ runs brushing the time cap (§5). |
| `backtest_runs_total{status}` | Terminal outcomes by status. A rising `FAILED` share ⇒ check `backtest_failed_total{reason}`. |
| `backtest_failed_total{reason}` | Failures by `error_code`. `BACKTEST_TIME_CAP` dominating ⇒ jobs too big; `BACKTEST_INSUFFICIENT_DATA` ⇒ backfill gaps (§6). |
| `backtest_artifact_bytes` (gauge) | Total stored artifact bytes. Trending toward the ~5 GB R2 revisit trigger ⇒ ADR follow-up. |

The Backtest Ops dashboard and the three backtest alert rules were retired by
ADR-109 — all six `backtest_*` series above remain exported and are queryable
ad hoc in Grafana Cloud → Explore when debugging with this runbook.

## §10 — Verify recovery

- The stuck run reaches a terminal state (`COMPLETED` / `CANCELLED` / `FAILED`) and
  emits its `backtest.*` WS event.
- `LLEN backtest` drains to 0 with the worker consuming.
- `backtest_active_runs` returns to 0; `backtest_queue_wait_seconds` p95 falls back
  under the 10-min alert threshold.
- For a `COMPLETED` run, the three artifacts (`report.json/html/pdf`) download and
  the `metrics_hash` is populated.
