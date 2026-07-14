# M11 Operator Run — Cowork Execution Report

**Date:** 2026-07-12
**Operator:** Claude (Cowork) via Railway web UI
**Scope attempted:** PART A (SERVICE_ROLE cutover). PARTS B–H not started.

---

## HEADLINE: PART A was not a planned change. It was an unplanned outage remediation.

The prompt's premise for PART A was:

> "the image change is **inert** — an existing start command still overrides the image."

**This was false for `backend`.** `backend` (both envs) never had a Custom Start Command — it
always ran the image's default `CMD`. When M11 replaced that `CMD` with the `SERVICE_ROLE`
dispatcher, the auto-deploy from `main` put the dispatcher straight into the boot path.

**Staging `backend` had been crash-looping for ~2 hours** before this session started:

```
entrypoint: FATAL: SERVICE_ROLE is unset. Refusing to guess a role.
entrypoint: set SERVICE_ROLE to one of: web web-dev worker worker-backtest beat streams ws
```

...while Railway displayed **"Online / Deployment successful"** the entire time, and
`GET /healthz` returned nothing. This is BUG-009/BUG-011's lesson in mirror image: last time the
badge said Online while running the *wrong* process; this time it said Online while running
*no* process.

**Production was one redeploy from the same outage.** Prod `backend` also had no start command
and no `SERVICE_ROLE`; it was alive only because it had not redeployed since the merge (still
serving the pre-M11 image). Any push, restart, or variable change would have crash-looped it.

### Correction to `bugs/BUG-011-...md` (follow-up section)

The claim "until then the image change is inert (an existing start command overrides the image
`CMD`)" is **wrong**, and is what caused this. It was true only for the three services that got
start commands during the 2026-07-11 BUG-011 fix (`celery-worker`, `celery-beat`,
`worker-backtest`). `backend` and `streams` were never given one:

| Service | Had start command pre-cutover? | Effect of M11 merge |
|---|---|---|
| `backend` | **NO** | **Crash-looped immediately** (staging); latent in prod |
| `streams` | YES (`python manage.py run_broker_streams`) | inert, kept running |
| `celery-worker` | YES | inert, kept running |
| `celery-beat` | YES | inert, kept running |
| `worker-backtest` | YES | inert, kept running |

---

## PART A — DONE, both environments, end-to-end verified

Verification was **not** the status badge. For each service the **deploy logs** were read and the
**process identity** asserted.

### Staging (env `e895ea5b`)

| Service | `SERVICE_ROLE` | Start cmd deleted | Verified process in logs |
|---|---|---|---|
| `backend` | `web` | n/a (never had one) | `entrypoint: starting SERVICE_ROLE='web'` → `Starting gunicorn 22.0.0`, `Using worker: gthread` — **not** runserver |
| `streams` | `streams` | yes | `SERVICE_ROLE='streams'` → `Starting broker streams supervisor…`, Prometheus endpoint :9104 |
| `celery-worker` | `worker` | yes | `celery/worker/consumer/consumer.py`, `ForkPoolWorker-1`, `task_metrics.server_started` |
| `celery-beat` | `beat` | yes | `SERVICE_ROLE='beat'` → `celery beat v5.3.6 is starting`, `scheduler -> redbeat.schedulers.RedBeatScheduler` |
| `worker-backtest` | `worker-backtest` | yes | celery consumer + `ForkPoolWorker-1` |

Staging `backend` restored:
- `GET /healthz` → `{"status": "ok", "version": "dd93bcb"}`
- `GET /readyz` → `{"status": "ok", "checks": {"db": "ok", "redis": "ok"}}`
- grafana-agent scraping `/metrics` → 200

The M11 migrations applied on that first successful boot:
`audit.0005_alter_auditlog_event_type`, `token_blacklist.0013_...`,
`users.0005_delete_flow_and_terms`.

### Production (env `b52b8bfb`)

| Service | `SERVICE_ROLE` | Start cmd deleted | Verified process in logs |
|---|---|---|---|
| `backend` | `web` | n/a (never had one) | Serving live traffic: `/metrics` 200 (GrafanaAgent), real `/api/v1/auth/oauth/google/available/` 200 from prod frontend |
| `streams-prod` | `streams` | yes | `entrypoint: starting SERVICE_ROLE='streams'` → `Starting broker streams supervisor…` |
| `celery-worker` | `worker` | yes | celery consumer, `ForkPoolWorker-1`, `task_metrics.server_started` |
| `celery-beat` | `beat` | yes | `celery beat v5.3.6`, `scheduler -> redbeat.schedulers.RedBeatScheduler` |
| `worker-backtest-prod` | `worker-backtest` | yes | celery consumer, `ForkPoolWorker-1` |

**No production downtime was observed.** Prod `backend` continued serving on the old image until
the new one rolled in with `SERVICE_ROLE=web` already set.

Not touched (correctly — not backend-image services): `frontend`, `Postgres`, `Redis`,
`grafana-agent`, `postgres-exporter-prod`, `redis-exporter-prod`, `ib-gateway`.

### Rollback values (if ever needed)

| Service | Restore this Custom Start Command |
|---|---|
| `celery-worker` | `celery -A config.celery worker -l info --concurrency=1` |
| `celery-beat` | `celery -A config.celery beat -l info -S redbeat.RedBeatScheduler` |
| `worker-backtest` / `-prod` | `celery -A config.celery worker -Q backtest -l info --concurrency=1 --max-memory-per-child=2000000` |
| `streams` / `streams-prod` | `python manage.py run_broker_streams` |
| `backend` | (none — leave blank) |

---

## AC-11-15 PromQL verification — now CLOSED

Run against Grafana Cloud (`yuval3000.grafana.net`, `grafanacloud-prom`):

| Assertion | Result |
|---|---|
| `up{job=~"worker\|beat\|streams\|worker-backtest"} == 1` | **8/8 series = 1** — `production/{worker,beat,streams,worker-backtest}` and `staging/{worker,beat,streams,worker-backtest}` |
| Total scrape targets | **14 up, 0 down** → `TargetDown` not firing |
| `celery_queue_depth` | **4 live series** (`production/celery`, `production/backtest`, `staging/celery`, `staging/backtest`), all `0` |
| `MetricsPipelineDown` | not firing |

Combined with the per-service deploy-log process identity checks above, AC-11-15 is discharged.

---

## Incidental findings (not acted on)

1. **Prod `/healthz` reports a stale SHA.** It returns `version: e5ecd75` while the deployed
   commit is `dd93bcb`. Consistent with the known Railway quirk that `RAILWAY_GIT_COMMIT_SHA` is
   not refreshed on non-git-triggered redeploys. Means `/healthz` version cannot be trusted as a
   deploy marker.

2. **`EXPORTS_BUCKET` unset** — confirmed in prod + staging boot logs:
   `EXPORTS_BUCKET unset — GDPR exports stay PENDING until Cloudflare R2 is provisioned`.
   The graceful degradation works as designed. This is exactly what PART C fixes.

3. **`METRICS_BASIC_AUTH_USERNAME/PASSWORD` unset on the async tier** — the worker/beat/streams
   services log: `/metrics will 401 (fail closed) in production until both env vars are set
   (backend + grafana-agent)`. Backend has them; the async services do not. Worth checking
   whether their metrics are actually being scraped, or whether this is a latent gap.

---

---

## PART B — DONE and fire-tested end-to-end

Imported via the Grafana **provisioning API** (`POST /api/v1/provisioning/alert-rules`,
`X-Disable-Provenance: true`) into folder `StratTraderPro`, group `slo-burn-rate`, matching the
exact node structure of the existing M10 rules (`query` → `prometheus_math` → `threshold`).

| Rule | Severity | `for` | `isPaused` (re-read from API) | health |
|---|---|---|---|---|
| `ApiErrorBudgetFastBurn` | critical | 2m | **false** | ok, evaluating |
| `ApiErrorBudgetSlowBurn` | warning | 15m | **false** | ok, evaluating |

**BUG-009 gate:** re-read from `/api/v1/provisioning/alert-rules` (not the POST echo).
**23 rules total, `pausedCount = 0`.** Both new rules show a fresh `lastEvaluation` and
`health: ok` with no `lastError` — i.e. they are genuinely evaluating, not merely present.

### Fire-test (AC-10-9 discipline: trip the REAL rule, never a clone)

Lowered the threshold **on the real `ApiErrorBudgetFastBurn` object** (same uid, same labels, same
routing) — original expression stashed and restored byte-for-byte afterwards.

Observed the full transition on the real rule:

```
inactive → pending (activeAt 03:47:40) → firing (03:49:40, severity=critical, value 1e+00)
```

**Delivery confirmed on BOTH contact points** (Grafana's own receiver record, `lastNotifyAttempt`):

| Receiver | Attempt | Duration | Error |
|---|---|---|---|
| `operator-email` | 2026-07-13T03:50:10.454Z | 1s573ms | **none** |
| `operator-telegram` | 2026-07-13T03:50:10.455Z | 141ms | **none** |

Email independently verified in the inbox:
`[FIRING:1] ApiErrorBudgetFastBurn StratTraderPro/stp-alert-rules.prom.yaml (critical)` →
`yuval3000@gmail.com`, 03:50:11Z.

**Restored:** expression identical to the committed YAML (`exprRestoredExactly: true`), rule back
to `inactive`, `isPaused: false`, `pausedCount` still `0`.

### A non-finding, recorded so nobody re-raises it

`django_http_responses_total_by_status_total` returns **no series in production**. This looks
alarming (it is the series all four error-ratio/burn-rate rules depend on) but it is **not a
defect**: `django_http_requests_before_middlewares_total{env="production"} = 0` — prod has served
**zero requests through the Django middleware stack** since the restart. `/metrics` and `/healthz`
bypass the middleware, so an idle pre-beta prod legitimately exports no response counters.

Proven empirically: 8×`200` + 8×`404` were driven against staging and the series appeared
immediately with exactly those counts. The metric, the middleware and the scrape are all healthy.
Consequence: with zero traffic the burn-rate rules evaluate to empty → NoData → `OK`, which is the
intended semantics (no traffic ⇒ no error budget burned).

---

## PART G — restricted audit DB role: **NOT PROVISIONED** (and deliberately not applied)

Queried live production Postgres:

- `SELECT rolname, rolsuper FROM pg_roles WHERE rolcanlogin` → **one row: `postgres`, superuser**.
  `stp_audit_writer` does **not** exist.
- Append-only triggers on `audit_log` **intact**: `audit_log_block_mutation`,
  `audit_log_check_link` (2/2).

The DDL in `docs/runbooks/audit-integrity-failure.md` Appendix A was **not** applied, for two
reasons:

1. **The runbook's premise is wrong.** It says Railway "gives us one role" and the split is
   impossible "until the DB plan allows a second role". The single role is a **superuser** — it can
   `CREATE ROLE` today. The plan is not the constraint.
2. **The DDL is incomplete and would break production.** It grants `SELECT, INSERT` on `audit_log`
   plus the sequence and nothing else — the runbook leaves *"(Whatever grants the app needs on the
   rest of the schema go here, as usual.)"* as an unwritten TODO. Repointing runtime `DATABASE_URL`
   at that role as written would fail on every other table.

This needs a design decision (full grant set + migration-role split, or formally accept the
single-role limitation as WONTFIX with the nightly trigger-presence check as the compensating
control) — and the runbook's Appendix A should be corrected either way.

---

## PARTS C, D, E, F, H — NOT DONE (handed off)

Each was skipped for a specific reason, not for lack of time. Handoff prompt:
**`project-plan/ONE-SHOT-M11-OPERATOR-TAIL.prompt.md`**

| Part | Status | Why not done here |
|---|---|---|
| C — Cloudflare R2 + export vars | Handed off | Requires creating an R2 API token and entering the secret into Railway — credential handling. Need is **confirmed live** (boot logs print `EXPORTS_BUCKET unset`). |
| D — DB password rotation | Handed off | Explicit confirm-gate; **causes downtime**; credential handling. |
| E — Lighthouse FCP on 4G | **Blocked** | Sandbox has no Chrome binary (no sudo; Puppeteer's Chromium download blocked by the network allowlist) **and** the PageSpeed Insights API daily quota is exhausted (HTTP 429). Refused to report an unthrottled FCP as if it were a Slow-4G number. Exact `npx lighthouse` command is in the handoff. |
| F — `seed_terms` | Handed off | Gated on **legal sign-off** of the ToS/Privacy drafts — a human task, not a tooling one. |
| H — full prod bring-up | Handed off | Requires **buying `strattraderpro.com`** and creating a paid Railway project — a spend decision. |
