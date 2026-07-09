# ADR-102 — Observability topology: out-of-urlconf /metrics, task-process scrape, OTel, alerts-as-code

**Date:** 2026-07-10
**Status:** Accepted
**Milestone:** M10 — Admin Portal, Audit Log & Observability
**Reference:** `project-plan/10-admin-audit-observability.md` §6.5, §6.6; AC-10-8…AC-10-12;
`config/metrics_endpoint.py`, `config/otel.py`, `config/celery.py`,
`config/middleware.py`, `config/request_context.py`; `infra/grafana-agent/agent.yaml`;
`infra/grafana/alerts/*.yaml`; the M00.7.5b / M04 Sentry-quota notes in `CHANGELOG.md`;
runbooks `worker-metrics-scrape.md`, `alerting-setup.md`, `incident-triage.md`

## Context

By the end of M09 the metrics story had four accumulated gaps, all deferred to
M10 §6.5/§6.6:

1. **`/metrics` lived inside Django's urlconf** (`django_prometheus.urls`), so
   every scrape traversed the whole middleware chain. Under the ASGI/UvicornWorker
   deploy this triggered a known allauth crash on `/metrics` responses that burned
   ~240 Sentry events/hour; the M04 fix was a `_sentry_before_send` filter — a
   band-aid, not a topology fix.
2. **Task-process metrics were unscrapeable** (FIX-C1): everything emitted inside
   the Celery worker/beat and the `run_broker_streams` process — `killswitch_*`,
   `sentiment_*`, `sizing_*`, `fills_ingested_total`, `broker_*` — sat behind no
   HTTP endpoint and shared no multiproc dir with gunicorn, so the committed
   dashboards and §12 alerts stayed dark.
3. **No container/infra metrics** — Postgres and Redis had no exporters; the
   process-level `process_*` collector is disabled under multi-process gunicorn.
4. **No tracing, no request correlation, and alerts existed only as prose** in the
   backtest runbook, never as importable rules.

## Decision

### 1. `/metrics` is served OUTSIDE Django's urlconf, at the WSGI entry

`config/metrics_endpoint.py` is a **bare WSGI/ASGI exposition app** — no Django
view, no middleware. `wrap_wsgi(django_app)` dispatches `PATH_INFO == "/metrics"`
to the exposition app and everything else to Django; it is wired into
`config/wsgi.py` — **the scraped gunicorn prod entry** (prod HTTP is WSGI/gthread,
see `docker/backend.Dockerfile`: `gunicorn config.wsgi:application …
--worker-class gthread --threads 4`). Because the exposition runs in the **same
gunicorn process**, the Prometheus multiprocess mmap files
(`PROMETHEUS_MULTIPROC_DIR`) are readable; it uses `MultiProcessCollector` when
that dir is set, else the default registry. A parallel `wrap_asgi_http` is wired
into `config/asgi.py` so the dev/daphne runserver mirrors the same `/metrics`.

Consequences of the move:

- **The scrape bypasses the middleware chain entirely.** The allauth crash cannot
  occur, so the **`_sentry_before_send` `/metrics` mitigation is DELETED** — it was
  compensating for the exact interaction this topology removes. (The deploy also
  reverted to WSGI/gthread, under which the ASGI-specific crash can't happen at
  all.)
- **The `django_prometheus.urls` include is removed** from `config/urls.py`. Its
  **middlewares and DB-engine wrappers stay** — they are what *produce*
  `django_http_*` and `django_db_*`; only the in-urlconf exposition endpoint is
  gone. Rollback is a one-line re-add of the include.
- **Basic auth** guards the endpoint when `METRICS_BASIC_AUTH_USERNAME` /
  `METRICS_BASIC_AUTH_PASSWORD` are set (constant-time compare); unset → open, for
  dev/test. The grafana-agent scrape sends those credentials.

### 2. FIX-C1: every task process exposes its own `/metrics` port

`config/task_metrics.start_task_metrics_server()` starts a `prometheus_client`
HTTP server on `TASK_METRICS_PORT` (>0; 0 = disabled). It is fired from Celery
signals in `config/celery.py`: `worker_process_init` (workers) and `beat_init`
(beat); the streams supervisor starts it directly. In compose the ports are
per-service: **worker 9101, worker-backtest 9102, beat 9103, streams 9104**.

The worker runs **`--concurrency=1`**. This is not incidental: multiple prefork
children can't share one port, so a second child's bind would fail. At
concurrency 1 there is a clean 1:1 process-to-port mapping; the bind-failure path
is caught and logged as expected (`task_metrics.port_in_use`) rather than fatal.
Full wiring + Railway provisioning is in `docs/runbooks/worker-metrics-scrape.md`.

### 3. Postgres/Redis exporters + env-var scrape targets

`docker-compose.yml` gains **postgres-exporter** (`prometheuscommunity/postgres-exporter`,
:9187) and **redis-exporter** (`oliver006/redis_exporter`, :9121).
`infra/grafana-agent/agent.yaml` gained `basic_auth` on the backend job (the §1
credentials) and scrape jobs for worker/worker-backtest/beat/streams/postgres/redis.
Every target is an **env var** — `WORKER_TARGET`, `WORKER_BACKTEST_TARGET`,
`BEAT_TARGET`, `STREAMS_TARGET`, `POSTGRES_EXPORTER_TARGET`,
`REDIS_EXPORTER_TARGET` (and `BACKEND_TARGET`) — so the same agent config drives
compose (`worker:9101`) and Railway (**Railway internal DNS**, e.g.
`worker.railway.internal:9101`). External labels `cluster`/`env` derive from
`RAILWAY_ENVIRONMENT_NAME`, so staging and prod ship to the same workspace,
tagged.

### 4. OTel init at wsgi + asgi + worker; OTLP export only when endpoint set

`config/otel.init_otel()` is idempotent (once per process) and instruments Django,
Celery, redis, psycopg2, and httpx. It is called from **`config/wsgi.py`** (so the
scraped web tier is traced — asgi-only wiring would leave the prod WSGI tier
untraced), **`config/asgi.py`** (dev/daphne), and **`worker_process_init`** (so
task spans exist). A `BatchSpanProcessor` + OTLP HTTP exporter is added **only when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set** — empty default = no export, keeping
tests/dev clean. Tracing failures are swallowed: OTel must never break boot.

### 5. Request-id correlation across web → Celery → Sentry → Tempo

`config/middleware.RequestIdMiddleware` honors an inbound `X-Request-ID` or mints a
**ULID**, stores it in a contextvar (`config/request_context.py`), echoes it on the
response, and tags the Sentry scope. The `RequestContextFilter` injects
`request_id`/`task_id` into every JSON log line. Across the Celery boundary,
`before_task_publish` copies the id into task headers and `task_prerun`/`postrun`
restore/clear it in the worker's contextvar (eager mode preserves the ambient id).
`config/otel.tag_sentry_correlation()` tags the Sentry scope with `request_id` +
the active OTel `trace_id`, which is what makes the Sentry→Tempo click-through work
(AC-10-10). **Sentry `release = GIT_SHA`** (short SHA from git / `GIT_SHA` env /
`RAILWAY_GIT_COMMIT_SHA`), so errors group by deploy.

### 6. Alert rules are code, cross-checked against exported metric names

`infra/grafana/alerts/*.yaml` commits the alert rules
(`alert-rules.yaml`), contact points (`contact-points.yaml`), and notification
policy (`notification-policy.yaml`) as YAML with env placeholders — imported to
Grafana Cloud per `docs/runbooks/alerting-setup.md`. A pytest
(`config/test_alert_rules.py`) parses every PromQL expression, extracts the metric
identifiers, and asserts each is either exported by some `apps/*/metrics.py` or in
an explicit `_EXTERNAL` allow-list (django_prometheus + exporter series). **A
renamed or removed metric fails CI** — the alerts can't silently rot.

## Consequences

- **`/metrics` is cheap, safe, and auth-gated**; the Sentry-quota band-aid is gone
  with the interaction it patched.
- **Task-process and infra series are finally scrapeable** — the dark dashboards
  and §12 alerts light up once the Railway services + exporters exist (operator
  steps in the runbooks).
- **End-to-end correlation:** one ULID threads log → span → Sentry event, and a
  Sentry error links to its Tempo trace.
- **Alerts can't drift from the code** — the cross-check test is the guardrail.

**Honest limits:**

- **The scrape endpoints and exporters are operator-provisioned on Railway.** Until
  the worker/beat/streams services set `TASK_METRICS_PORT` and the agent targets
  point at them (and the two exporter services exist), those series are absent in
  prod — deferred, with procedures in `worker-metrics-scrape.md`.
- **Railway managed Postgres does not expose CPU** via the exporter — the
  `DBConnectionSaturation` alert is a connection-count proxy; true CPU lives on the
  Railway dashboard (noted in `alert-rules.yaml`).
- **No in-code signal for a deploy/rollback event** — the "deploy rollback" alert
  from the plan has no metric behind it; it is replaced by a **Railway
  deploy-notification** (setup note in `alerting-setup.md`).
- **Tracing is off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set** — a deliberate
  default so CI/dev stay clean; prod must set it to get traces in Tempo.

## Alternatives considered

1. **Keep `/metrics` in the urlconf + retain the Sentry filter.** Rejected: the
   filter is a band-aid over a topology problem; scrapes traversing the middleware
   chain is the root cause. Move the endpoint, delete the band-aid.
2. **One shared multiproc dir for the workers + a sidecar exporter.** Rejected for
   MVP in favor of a per-process HTTP port at `--concurrency=1`: simpler, one
   scrape target per service, no shared-volume coordination. The sidecar option
   stays open if a worker ever needs real prefork concurrency.
3. **Vendor APM (Datadog/New Relic) instead of OTel + Grafana Cloud + Sentry.**
   Rejected on cost and lock-in for a solo operator; OTel keeps the export
   vendor-swappable and the existing Grafana Cloud + Sentry are already paid for.
4. **Alert rules defined only in the Grafana UI.** Rejected: no review, no
   CI cross-check, no reproducibility on a fresh workspace. Rules-as-code + the
   metric-name test is the guardrail.

## See also

- `backend/config/metrics_endpoint.py` — the out-of-urlconf exposition app
- `backend/config/otel.py`, `config/middleware.py`, `config/request_context.py`
- `backend/config/celery.py` — task-metrics start + request-id propagation
- `infra/grafana-agent/agent.yaml` — scrape jobs + env-var targets
- `infra/grafana/alerts/*.yaml` — rules, contact points, notification policy
- `docs/runbooks/worker-metrics-scrape.md`, `alerting-setup.md`, `incident-triage.md`
- ADR-100 (audit chain), ADR-101 (feature flags) — the other M10 ADRs
