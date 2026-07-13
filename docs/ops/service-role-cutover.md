# Runbook — `SERVICE_ROLE` cutover (delete the Railway Custom Start Commands)

**Owner:** Yuval / platform on-call
**Last reviewed:** 2026-07-12 (M11 §7.0)
**Severity:** P1 planned change (a mistake crashes a service loudly, does not corrupt data)
**Gated by:** AC-11-15 [LIVE]
**Companion:** `docs/adr/103-service-role-dispatch.md`, `bugs/BUG-011-celery-worker-and-beat-are-not-running-celery.md`

## Why this exists

BUG-011: a **blank** Railway "Custom Start Command" makes a service run the image's
default `CMD`. That default used to be `migrate && gunicorn`, so `celery-worker` and
`celery-beat` silently ran a *second web server* for two months — the default Celery
queue had no consumer and beat never fired. M11 §7.0 replaced the default with a
`SERVICE_ROLE` dispatcher (`docker/entrypoint.sh`) that **crashes loudly** when the
role is unset instead of impersonating the web tier.

**⚠️ CORRECTION (2026-07-13, from the live cutover — `M11-COWORK-OPERATOR-REPORT.md`):
"the image change is inert until this cutover" is FALSE for any service that had NO Custom
Start Command.** It is inert only for the services whose start command overrides the new
image `CMD` (the ones given commands during the 2026-07-11 BUG-011 fix: `celery-worker`,
`celery-beat`, `worker-backtest`, `streams`). **`backend` never had a start command** — it
ran the image's *default* `CMD` (which used to be gunicorn, correct for the web tier). §7.0
replaced that default `CMD` with the dispatcher, so **`backend` crash-loops on its very next
Railway deploy (`entrypoint: FATAL: SERVICE_ROLE is unset`) unless `SERVICE_ROLE=web` is set
first.** The M11 merge auto-deployed `main` and did exactly that to **staging `backend`
(~2h crash-loop, while Railway showed "Online")**; prod `backend` was latent (survived only
because it had not redeployed since the merge).

**Therefore: set `SERVICE_ROLE=web` on `backend` in BOTH environments BEFORE or immediately
at the merge — do not wait.** The command-bearing services can be cut over at leisure (their
start command keeps them on the old behaviour until you delete it); `backend` cannot. This
runbook still performs the full change: set `SERVICE_ROLE` on every service and **delete
every Custom Start Command** so the image becomes the single source of truth.

## Railway service → `SERVICE_ROLE` mapping (both environments)

Do NOT leave the last mile to inference. Every backend-image service maps to exactly
one role. `backend` maps to **`web`** (production gunicorn), **never** `web-dev`
(`web-dev` is a local-compose-only hot-reload role that refuses to boot in a deployed
env — it checks `DJANGO_SETTINGS_MODULE` ends in `.dev` **and** `RAILWAY_ENVIRONMENT_NAME`
is unset).

| Railway service    | `SERVICE_ROLE` | Resolved process (from the image)                          |
|--------------------|----------------|------------------------------------------------------------|
| `backend`          | `web`          | `migrate && gunicorn config.wsgi:application …`             |
| `celery-worker`    | `worker`       | `celery -A config.celery worker -l info --concurrency=1`    |
| `worker-backtest`  | `worker-backtest` | `celery … worker -Q backtest … --max-memory-per-child=2000000` |
| `celery-beat`      | `beat`         | `celery -A config.celery beat -l info -S redbeat.RedBeatScheduler` |
| `streams`          | `streams`      | `python manage.py run_broker_streams`                      |
| `ws`               | `ws`           | `daphne -b 0.0.0.0 -p $PORT config.asgi:application`        |

`frontend`, `postgres`, `redis`, `postgres-exporter`, `redis-exporter`, `grafana-agent`
are **not** backend-image services and take no `SERVICE_ROLE`.

The `ws` service inherits Railway's injected `$PORT` (the `ws` role uses `${PORT:-8788}`),
so it needs no port override on Railway — unlike local compose, which sets `PORT: 8788`
because the image's `ENV PORT=8777` would otherwise win.

## Procedure — **staging first**, then production

For each backend-image service in the **staging** project:

1. **Set the env var:** add `SERVICE_ROLE=<role>` per the table above (Variables tab).
2. **Delete the Custom Start Command:** Settings → Deploy → *Custom Start Command* →
   clear it and save. (The image `CMD` — the dispatcher — now runs.)
3. Redeploy the service.

After **all** staging services are cut over, verify end-to-end (do not trust a
service's own "Online" — BUG-011 was "Online" the whole time):

```promql
# every task tier is scraping (was 0 for worker/beat during BUG-011)
up{job=~"worker|beat|streams|worker-backtest"} == 1
# beat -> default queue -> worker -> metric is fresh (proves the whole loop)
celery_queue_depth        # 4 live series, recently updated
```

Also confirm in each service's deploy logs that the **right process** is named:
`worker`/`worker-backtest`/`beat` logs must show `celery`, `streams` must show
`run_broker_streams`, `backend` must show `gunicorn` (and **not** `runserver`). If a
service crash-loops with `entrypoint: FATAL: SERVICE_ROLE is unset`, the env var did
not save — re-add it. That crash is the design working: loud, not silent.

Only when staging is green, repeat for **production**.

## Rollback

Per-service, in seconds: re-type the old Custom Start Command in Railway (that is
today's pre-cutover state). This holds for the **command-bearing** services (the code is
inert for them while a start command exists). **`backend` is the exception** — it had no
start command, so its rollback is to re-add `SERVICE_ROLE=web` (or roll back to the pre-M11
deploy), not to re-type a command. Landing the code ahead of the cutover is zero-risk **only
for the command-bearing services**; for `backend`, set `SERVICE_ROLE=web` at the merge.

## The failure mode this prevents

If you delete a start command and forget to set `SERVICE_ROLE`, the service **crashes
visibly** at boot with `entrypoint: FATAL: SERVICE_ROLE is unset` — caught in thirty
seconds — instead of becoming a silent gunicorn that passes health checks while the
async tier goes dark for months.
