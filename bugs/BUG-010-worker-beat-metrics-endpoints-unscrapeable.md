# BUG-010 — celery-worker and celery-beat metrics endpoints are not scrapeable (both environments)

| | |
|---|---|
| **Severity** | S2 — a shipped feature (worker/beat metrics) is silently non-functional, and it blinds a risk alert |
| **Status** | OPEN — root cause not yet pinned; needs worker/beat runtime logs |
| **Area** | Observability / Railway |
| **Found** | 2026-07-11, **by the BUG-008 dead-man's switch on its first evaluation** |

## Symptom

`TargetDown` went to `pending` with **4 instances** within a minute of being enabled:

```
up{job="worker", service="worker", instance="celery-worker.railway.internal:9101"} = 0   # production
up{job="beat",   service="beat",   instance="celery-beat.railway.internal:9103"}   = 0   # production
   ... and the same two in staging
```

`up = 0` means the agent **reached the scrape but got no valid response** — nothing
is listening on those ports.

## What is NOT the cause

- **The processes are fine.** `celery-worker` and `celery-beat` are both **Online**
  in Railway. Tasks are running; only the metrics endpoint is unreachable.
- **`TASK_METRICS_PORT` is not missing.** It is present in celery-worker's service
  variables (verified in the Railway UI). The `resolved <= 0` early-return in
  `config/task_metrics.py` is therefore *not* the explanation.
- **It's not the bind address.** `prometheus_client.start_http_server()` binds
  `0.0.0.0`, and `streams-prod` — which uses **the same function** — scrapes fine
  (`up = 1`). So the pattern works on Railway's internal network.

## The interesting asymmetry

| Service | How it starts the metrics server | `up` |
|---|---|---|
| `streams-prod` | calls `start_task_metrics_server()` **directly** at startup | **1** |
| `celery-worker` | via Celery's `worker_process_init` signal | **0** |
| `celery-beat` | via Celery's `beat_init` signal | **0** |

Everything that calls the function directly works. Everything that relies on a
**Celery signal** does not. That is where to look.

## Candidate causes (in priority order)

1. **The Railway start command uses a non-prefork pool.** `worker_process_init`
   only fires for the prefork pool — with `--pool=solo/threads/gevent` it is never
   sent, so `_start_task_metrics()` never runs. `docker-compose.yml` uses the
   default prefork pool, but **Railway's start command is configured per-service
   and is not the compose command**, so it can differ. (Does not by itself explain
   beat, which uses `beat_init`.)
2. **Port mismatch.** `TASK_METRICS_PORT`'s value is masked in the UI. The agent
   scrapes worker on **9101** and beat on **9103**. If the variable does not match
   the port in `infra/grafana-agent/agent.yaml`, the scrape hits nothing.
3. **The signal fires but the bind fails.** `_start_task_metrics()` swallows
   `OSError` as "another child holds the port (expected)" — which would also hide a
   genuine bind failure.

## Diagnostic (do this first)

`config/task_metrics.py` logs on success. Grep the celery-worker / celery-beat
deploy logs for:

```
task_metrics.server_started     # INFO, includes the resolved port
task_metrics.start_failed       # exception path
task_metrics.port_in_use        # the swallowed-OSError path
```

Absence of all three ⇒ the signal never fired ⇒ cause #1.
`server_started` with an unexpected port ⇒ cause #2.

## Impact

Every metric emitted from a worker or beat process — including **`celery_queue_depth`**
— has **never reached Grafana**. So `CeleryQueueDepthHigh` has no series, and because
it is self-filtering (`max(celery_queue_depth) > 1000`), an empty result reads as
**Normal**. The alert has been permanently green and permanently blind. Same for any
rule sourced from worker/beat counters.

This is BUG-008's thesis, demonstrated on live infrastructure within sixty seconds
of the dead-man's switch being turned on. Note that FIX-C1 (M10 §6.5b) shipped this
wiring and was signed off — the runbook exists, the env var is set, the code is
correct, and the endpoint has never once answered a scrape.

## Related

- **BUG-008** — the dead-man's switch that found this. Without `TargetDown` there
  was no signal anywhere in the system that these two targets were dead.
- **BUG-009** — `TargetDown` could only find it once the rules were un-paused.
- `docs/runbooks/worker-metrics-scrape.md`
