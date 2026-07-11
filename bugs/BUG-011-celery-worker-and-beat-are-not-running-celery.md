# BUG-011 — `celery-worker` and `celery-beat` are not running Celery. They are running a second copy of the web server.

| | |
|---|---|
| **Severity** | **S1 / P0** — the default task queue has no consumer and no scheduler, in **both** environments |
| **Status** | **FIXED & VERIFIED LIVE** 2026-07-11 — start commands set on staging, verified, then production. All 14 scrape targets now `up = 1` (was 4 down). See "Resolution". |
| **Area** | Railway / Celery |
| **Found** | 2026-07-11, by pulling on BUG-010 |

## What is actually happening

The Railway services named `celery-worker` and `celery-beat` have an **empty
Custom Start Command**. They therefore run the backend image's default `CMD` —
the Django entrypoint. Their deploy logs show it plainly:

```
Operations to perform: ... Running migrations: No migrations to apply.
[INFO] Starting gunicorn 22.0.0
[INFO] Listening at: http://0.0.0.0:8080 (1)
[INFO] Using worker: gthread
[INFO] Booting worker with pid: 67 / 68 / 69
```

The string **`celery` does not appear anywhere in `celery-worker`'s logs.**

Both services are running **gunicorn**. Neither is running Celery. Both report
**Online** in Railway, because gunicorn starts perfectly well.

## Consequences

- **The default `celery` queue has no consumer** in production or staging. Every
  task routed to it — reconciliation, sentiment scoring, regime/HMM updates, audit
  integrity checks, artifact eviction, session cleanup — is enqueued into Redis and
  **never executed**.
- **Beat never runs**, so no periodic task has ever fired. Nothing on
  `CELERY_BEAT_SCHEDULE` has executed in production.
- Two extra idle gunicorn web servers are running, migrating the database on boot
  and serving nothing.

## The proof it is not a code bug

`worker-backtest-prod` — which **does** have a start command
(`celery -A config.celery worker -Q backtest ...`) — is a real Celery prefork worker,
and its `worker_process_init` metrics server answers fine:

```
up{job="worker-backtest", env=production} = 1     up{job="streams"} = 1
up{job="worker-backtest", env=staging}    = 1     up{job="backend"} = 1
up{job="worker",          env=production} = 0     up{job="beat", env=production} = 0
up{job="worker",          env=staging}    = 0     up{job="beat", env=staging}    = 0
```

So the FIX-C1 signal wiring in `config/celery.py` is **correct** — it works in the
one service that actually runs Celery. **BUG-010 was a symptom, not a bug.** The
metrics endpoints are silent because there is no Celery process to expose them.

## How this stayed invisible

The one alert designed to catch exactly this — `CeleryQueueDepthHigh`
(`max(celery_queue_depth) > 1000`) — could not fire, for **two independent
reasons**, either of which alone was sufficient:

1. It was **paused** (BUG-009), like every other imported rule.
2. `celery_queue_depth` is emitted **by the worker process**, which does not exist —
   so the series was never scraped anyway. And the rule is self-filtering, so an
   empty result reads as **Normal** (BUG-008).

A queue with no consumer, and the alarm for it silenced twice over. This is the
project's theme in its purest form: *the failure disabled its own detector.*

## Before you fix this — READ

Setting the start command will start a real Celery worker, which will **immediately
begin draining whatever has accumulated in the Redis default queue**. On a trading
platform that is not obviously safe: the backlog may contain **stale, long-expired
tasks** (reconciliation runs, order-related work, signal processing) that would
execute against current market state using old inputs.

**Recommended order:**

1. **Inspect the queue first, do not start a worker.** `LLEN celery` on the prod
   Redis, and sample entries (`LRANGE celery 0 20`) to see what is in there and how
   old it is.
2. **Decide explicitly** whether to purge the backlog (`celery -A config.celery purge`,
   or `DEL celery`) or to let it drain. For anything order-related, purging is
   almost certainly correct — do not replay stale trading tasks.
3. Confirm task idempotency / expiry (`task_expires`) before draining anything.
4. Only then set the start commands:
   - `celery-worker` → `celery -A config.celery worker -l info --concurrency=1`
   - `celery-beat` → `celery -A config.celery beat -l info -S redbeat.RedBeatScheduler`
   (matching `docker-compose.yml`, which has had the correct commands all along.)
5. Do staging first, watch `up{job="worker"} -> 1` and `TargetDown` clear.

## Resolution (2026-07-11)

**The feared stale backlog did not exist.** Both prod and staging Redis contained
exactly three keys — `_kombu.binding.celery.pidbox`, `_kombu.binding.celeryev`,
`_kombu.binding.backtest` — and **no `celery` list key and no `redbeat::` keys**.
Zero queued tasks, so there was nothing to replay and nothing to purge. (It also
independently confirms beat never ran: RedBeat leaves no schedule key behind.)

Start commands set, staging first:

| Service | Start command |
|---|---|
| `celery-worker` | `celery -A config.celery worker -l info --concurrency=1` |
| `celery-beat` | `celery -A config.celery beat -l info -S redbeat.RedBeatScheduler` |

Staging came up as a genuine Celery worker — task registry loaded
(`apps.risk.tasks.daily_loss_watcher`, `apps.regime.tasks.retrain_hmm`,
`apps.sentiment.tasks.*`, `apps.webhooks.tasks.process_alert`) and
`INFO/ForkPoolWorker-1 task_metrics.server_started`. `TargetDown` dropped from 4
instances to exactly 2 (the untouched production pair), which is the dead-man's
switch tracking reality to the instance. Production followed.

**Verified end state: all 14 scrape targets `up = 1`, zero down. `TargetDown`
inactive. `celery_queue_depth` has 4 live series — the metric `CeleryQueueDepthHigh`
depends on, which had never been scraped in the project's history.**

Note what had never executed in production until now: **`apps.risk.tasks.daily_loss_watcher`**
— a beat-scheduled *risk control*. It is worth auditing what else on
`CELERY_BEAT_SCHEDULE` was assumed to be running.

## Follow-up

- **The start commands must not live only in a Railway text box.** They are the
  reason the platform's async tier exists, and a blank field silently substitutes a
  web server. Move them into `railway.json`/config-as-code, or bake role-dispatching
  into the image entrypoint, so the service's identity is version-controlled and
  reviewable.
- Add an operational check that each service is running the process it claims to be
  (e.g. assert `up{job="worker"} == 1` at M12 sign-off, now that `TargetDown` exists).

## Related

- **BUG-010** — the symptom (worker/beat metrics unscrapeable). Closed by this.
- **BUG-008 / BUG-009** — why nothing ever told anyone.
