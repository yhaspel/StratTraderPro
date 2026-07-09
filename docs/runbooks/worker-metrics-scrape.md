# Runbook — Scraping task-process Prometheus metrics (FIX-C1, M10 §6.5b)

**Owner:** Yuval
**Status:** Implemented in code + compose (M10, FIX-C1). The worker/beat/streams
processes each expose a `/metrics` port, the postgres/redis exporters exist, and
the grafana-agent scrape jobs are wired. **Provisioning the equivalent Railway
services is the operator step** (below). **Companion docs:**
`docs/adr/102-observability-topology.md` §2/§3 (the topology), `alerting-setup.md`
(the alerts that need this data), `backtest-stuck.md` §7 (the `worker-backtest`
Railway service, of which this is the metrics half), `infra/grafana-agent/README.md`.

## Problem (recap)

Most M06–M10 counters/gauges (`hmm_retrain_total`, `sentiment_*`, `sizing_*`,
`killswitch_*`, `daily_loss_breach_total`, `broker_stream_disconnects_total`,
`broker_ws_reconnects_total`, `fills_ingested_total`, `celery_queue_depth`,
`audit_*`, …) increment inside the **Celery worker/beat** and the
**`run_broker_streams`** processes. Those processes don't sit behind gunicorn's
`/metrics`, and they share no `PROMETHEUS_MULTIPROC_DIR` with the web service — so
those series were unscrapeable and the committed dashboards / §12 alerts stayed
dark. This runbook is how FIX-C1 makes them scrapeable, end to end.

## What FIX-C1 wired (now implemented, not options)

- **Each task process starts its own `/metrics` HTTP server.**
  `config/task_metrics.start_task_metrics_server()` starts a `prometheus_client`
  server on `TASK_METRICS_PORT` (>0; `0` = disabled). It is fired from Celery
  signals in `config/celery.py` — `worker_process_init` for workers, `beat_init`
  for beat — and directly by the `run_broker_streams` supervisor. (This is the
  HTTP-endpoint-per-worker approach; the multiproc-dir + sidecar alternative was
  the other option and is **not** used — a per-process port at `--concurrency=1` is
  simpler and gives one scrape target per service.)
- **The four previously-dead M04 metrics** are emitted at their real call sites
  (`fills_ingested_total`, `broker_stream_heartbeat_age_seconds`,
  `order_state_transitions_total`, `broker_ws_reconnects_total`), and gauges carry
  an explicit `multiprocess_mode`.

## Per-service `TASK_METRICS_PORT` (compose → Railway)

Each task service sets `TASK_METRICS_PORT` and the grafana-agent scrapes it:

| Service | Command | `TASK_METRICS_PORT` | Agent target env var |
|---|---|---|---|
| `worker` | `celery -A config.celery worker -l info --concurrency=1` | **9101** | `WORKER_TARGET` |
| `worker-backtest` | `celery -A config.celery worker -Q backtest -l info --concurrency=1 --max-memory-per-child=2000000` | **9102** | `WORKER_BACKTEST_TARGET` |
| `beat` | `celery -A config.celery beat -l info -S redbeat.RedBeatScheduler` | **9103** | `BEAT_TARGET` |
| `streams` | `python manage.py run_broker_streams` | **9104** | `STREAMS_TARGET` |

## The `--concurrency=1` port-collision constraint

Both Celery workers run **`--concurrency=1`** deliberately. A `prometheus_client`
HTTP server binds a single port; multiple prefork children in one worker **cannot
share** that port, so a second child's bind would fail. At concurrency 1 there is a
clean **1:1 process-to-port mapping**. The bind-failure path is caught and logged
(`task_metrics.port_in_use — another worker child holds it (expected)`) rather than
crashing the worker — so even if concurrency were raised, the first child holds the
port and the rest no-op, but you'd then only be scraping one child's counters.
Keep `--concurrency=1` for correct task-metrics scraping. (For `worker-backtest`
concurrency 1 is doubly required — a sweep can peak near the 2 GB memory cap; see
`backtest-stuck.md` §7.)

## The grafana-agent targets are env vars = Railway internal DNS

`infra/grafana-agent/agent.yaml` has a scrape job per service; every target is an
**env var**, so the same config drives compose and Railway. On Railway they take
the **internal-DNS** form `<service>.railway.internal:<port>`:

```
WORKER_TARGET=worker.railway.internal:9101
WORKER_BACKTEST_TARGET=worker-backtest.railway.internal:9102
BEAT_TARGET=beat.railway.internal:9103
STREAMS_TARGET=streams.railway.internal:9104
POSTGRES_EXPORTER_TARGET=postgres-exporter.railway.internal:9187
REDIS_EXPORTER_TARGET=redis-exporter.railway.internal:9121
```

(Plus the existing `BACKEND_TARGET=backend.railway.internal:8777` and the
`GRAFANA_PROM_*` remote-write vars from `grafana-agent/README.md`.) The backend
scrape job also carries `basic_auth` = `METRICS_BASIC_AUTH_USERNAME/PASSWORD`
(ADR-102 §1).

## Provisioning the exporter services on Railway

Locally, `docker-compose.yml` runs two exporter containers; on Railway create them
as **separate services** in the same environment (private network):

- **postgres-exporter** — image `prometheuscommunity/postgres-exporter`, env
  `DATA_SOURCE_NAME=postgresql://<user>:<pw>@<pg-host>:5432/<db>?sslmode=…`
  (use the Railway `DATABASE_URL` components). Exposes `:9187`. Point
  `POSTGRES_EXPORTER_TARGET` at `postgres-exporter.railway.internal:9187`. This
  backs the `DBConnectionSaturation` alert (a connection-count proxy — Railway
  managed PG exposes no CPU via the exporter; true CPU is the Railway dashboard).
- **redis-exporter** — image `oliver006/redis_exporter`, env
  `REDIS_ADDR=redis://<redis-host>:6379`. Exposes `:9121`. Point
  `REDIS_EXPORTER_TARGET` at `redis-exporter.railway.internal:9121`.

## Provisioning the task services on Railway

For each of `worker`, `worker-backtest`, `beat`, `streams`: a Railway service off
the **backend image/repo**, with the exact `command` from the table above, the same
backend env (`DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`,
`DJANGO_SETTINGS_MODULE=config.settings.prod`), **plus** its
`TASK_METRICS_PORT` from the table. (The `worker-backtest` service is also the fix
for `backtest-stuck.md` §1 — it must exist or prod backtests sit `QUEUED`.)

## Verify the scrape is live

1. In each task-service's Railway logs, confirm `task_metrics.server_started` on the
   expected port.
2. In Grafana Cloud → Explore → Prometheus:
   - `up{service="worker"}` (and `worker-backtest` / `beat` / `streams` /
     `postgres` / `redis`) → `1`.
   - `celery_queue_depth`, `killswitch_trigger_total`, `sentiment_queue_depth`,
     `audit_events_total`, `pg_stat_activity_count` return data.
3. The task-process and exporter panels on the six dashboards populate, and the
   alerts that read those series (`CeleryQueueDepthHigh`, `SentimentLag`,
   `DBConnectionSaturation`, `AuditIntegrityFailure`, the kill-switch alerts) have
   data to evaluate.
