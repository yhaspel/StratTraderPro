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

## Caveat on the AC-11-15 verification

The runbook asks for these PromQL assertions in Grafana Cloud:

```
up{job=~"worker|beat|streams|worker-backtest"} == 1
celery_queue_depth        # 4 live series
```

**These were NOT run.** No Grafana session was established in this run. What *was* done is
arguably the stronger check the runbook was proxying for — asserting the actual process identity
in each service's deploy logs, in both environments, for all ten backend-image services. But the
`up{}` / `celery_queue_depth` queries and the `TargetDown` / `MetricsPipelineDown` check remain
**outstanding** and should be run to close AC-11-15 formally.

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

## PARTS B–H — NOT STARTED

| Part | Status |
|---|---|
| B — burn-rate alert rules import + `isPaused==false` + fire-test | Not started |
| C — Cloudflare R2 + export env vars | Not started (need is confirmed, see finding 2) |
| D — DB password rotation | Not started (requires maintenance-window confirmation) |
| E — Lighthouse FCP on throttled 4G | Not started |
| F — `seed_terms` | Not started (blocked on legal sign-off — a human task) |
| G — restricted audit DB role | Not started |
| H — full prod bring-up | Not started (large; needs scope + budget decision) |
