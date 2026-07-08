# Runbook — Scraping task-process Prometheus metrics (FIX-C1)

## Problem
Most M06–M08 counters/gauges (`hmm_retrain_total`, `sentiment_*`, `sizing_*`,
`killswitch_*`, `daily_loss_breach_total`, `broker_stream_disconnects_total`,
`broker_ws_reconnects_total`, `fills_ingested_total`, …) increment inside the
**Celery worker/beat** and the **`run_broker_streams`** processes. Those
processes do not sit behind gunicorn's `/metrics`, and they share no
`PROMETHEUS_MULTIPROC_DIR` with the web service — so those series were
unscrapeable and the committed Grafana dashboards / §12 alerts stayed dark.

## What FIX-C1 changed
- The four previously-dead M04 metrics are now emitted at their real call sites
  (`fills_ingested_total` in `ingest_fill_event`, `broker_stream_heartbeat_age_seconds`
  in `get_stream_status`, `order_state_transitions_total` on order status change,
  `broker_ws_reconnects_total` in the stream reconnect loop).
- Gauges have an explicit `multiprocess_mode` (required under multi-process gunicorn).
- The **streams** process (`run_broker_streams`) starts a `prometheus_client`
  HTTP endpoint when `TASK_METRICS_PORT` (>0) is set — set it in that service's
  env and point a Prometheus scrape job at the port.

## Still deferred (follow-up)
The **Celery worker/beat** processes do not yet expose a scrape endpoint. Two
options, to be wired next:

1. **HTTP endpoint per worker** — call `config.task_metrics.start_task_metrics_server()`
   from a `worker_process_init` / `celeryd_after_setup` signal (one port per
   worker; each scraped separately). Simplest.
2. **Multiproc dir** — set `PROMETHEUS_MULTIPROC_DIR` for the worker and run a
   sidecar exporter reading it (mirrors the gunicorn pattern). Needed if a worker
   forks multiple processes.

Until then, worker/beat-emitted series are visible only if the worker also runs
with `TASK_METRICS_PORT` set and a scrape target configured. Track under M10
observability carryover.
