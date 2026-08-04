# M10 — Claude Cowork follow-ups (Chrome-driven web-UI steps)

> **Status: ❌ SCRAPPED 2026-07-14 — OSS pivot; do not implement.**
> Superseded by `project-plan/PIVOT-TO-OSS.md`. These are Railway / Grafana / Sentry web-UI
> operator steps for a hosted service — either already done or moot once the service is torn down.
> Kept as a record.

The CLI-doable M10 operator steps are **done** (see `M10-EXECUTION-REPORT.md` Section B):
cache/Redis hardening merged + deployed; Railway env vars set on backend / celery-worker /
celery-beat / grafana-agent in **both** staging + production; `/metrics` basic auth live
(401→200 verified on prod); `postgres-exporter` + `redis-exporter` created + deployed on
**staging**; staging Redis restored. What remains are web-UI steps for Claude Cowork to drive
via the Chrome MCP.

Copy everything between the lines into Claude Cowork:

---

You are driving Chrome (via the Chrome MCP / claude-in-chrome) to finish the M10 operator setup
for StratTraderPro. Repo: <repo-root>. Work through
the sections; confirm each before moving on. **Never paste secrets into any chat** — read them
from the Railway/Sentry/Grafana UIs directly.

CONTEXT (already done via CLI): Railway env vars are set on backend / celery-worker / celery-beat /
grafana-agent in BOTH staging and production (metrics basic auth user=`metrics`, password stored
on the backend + grafana-agent services; AUDIT_ALERT_EMAIL=you@example.com; TASK_METRICS_PORT
9101/9103; grafana-agent scrape targets WORKER_TARGET/BEAT_TARGET/WORKER_BACKTEST_TARGET/
STREAMS_TARGET/POSTGRES_EXPORTER_TARGET/REDIS_EXPORTER_TARGET). Backend /metrics requires basic
auth and the agent scrapes it with matching creds. Prod backend: https://your-backend.example.com ;
staging: https://your-backend-staging.example.com . Grafana Cloud stack: account YOUR_ORG
(Prometheus datasource `grafanacloud-YOUR_ORG-prom`). Both environments are currently healthy
(/readyz = 200, db+redis ok). Staging Redis was already restored — do NOT touch it.

## SECTION A — Railway (https://railway.app → project StratTraderPro)
A1. Deploy the exporters in PRODUCTION: for each of `postgres-exporter` and `redis-exporter`,
    open the service → switch to the `production` environment → Deploy. They already carry their
    `DATA_SOURCE_NAME` / `REDIS_ADDR` variable-references and just need a first prod deploy.
    (They are already live in staging.) Confirm both reach SUCCESS.
A2. Create service `worker-backtest` (staging AND production): New Service → deploy from the
    GitHub repo (same source as `celery-worker`) → Settings → Custom Start Command =
    `celery -A config.celery worker -Q backtest -l info --concurrency=1 --max-memory-per-child=2000000`.
    Copy the variables `celery-worker` has (DATABASE_URL, REDIS_URL, SECRET_KEY,
    DJANGO_SETTINGS_MODULE=config.settings.prod) and add `TASK_METRICS_PORT=9102`.
A3. Create service `streams` (both envs): deploy from the repo → Custom Start Command =
    `python manage.py run_broker_streams`. Same variables as celery-worker + `TASK_METRICS_PORT=9104`.
A4. (Optional) frontend service: set `GRAFANA_URL`, `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `RELEASE`,
    and `NGINX_ENVSUBST_FILTER=BACKEND_URL|GRAFANA_URL|SENTRY_DSN|SENTRY_ENVIRONMENT|RELEASE`.
A5. (When ready — see B5) set `OTEL_EXPORTER_OTLP_ENDPOINT` + `OTEL_EXPORTER_OTLP_HEADERS` on
    backend / celery-worker / celery-beat / worker-backtest / streams (both envs).
A6. Provision the restricted audit DB role (docs/runbooks/audit-integrity-failure.md appendix):
    in the Postgres service, create a role with INSERT+SELECT only on `audit_log`.

## SECTION B — Grafana Cloud (the YOUR_ORG stack, e.g. https://YOUR_ORG.grafana.net)
B1. Import the six dashboards (Dashboards → New → Import → upload JSON), from `infra/grafana/`:
    system-health, trading-ops, data-pipelines, backtest-ops, auth-health, risk-ops. Select the
    `grafanacloud-YOUR_ORG-prom` datasource. Verify the new "SLO" + "Last incident" panels render.
B2. Import the alert rules from `infra/grafana/alerts/alert-rules.yaml` (Grafana Alerting). Confirm
    every rule group loads with no "no data / bad series" errors (all metrics are now scraped).
B3. Contact points (Alerting → Contact points): (1) email → you@example.com. (2) Telegram —
    create a bot with @BotFather (save the bot token), get your chat id from @userinfobot, then
    create a Telegram contact point with that token + chat id. Template:
    `infra/grafana/alerts/contact-points.yaml`.
B4. Notification policy (`infra/grafana/alerts/notification-policy.yaml`): severity=critical →
    email + Telegram; severity=warning → email.
B5. Tempo + OTel: enable the Grafana Cloud Tempo datasource; from Connections → OpenTelemetry copy
    the OTLP endpoint + the Basic auth token, then do Railway step A5:
    `OTEL_EXPORTER_OTLP_ENDPOINT=<OTLP HTTP endpoint>`,
    `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64(instanceID:token)>`. Redeploy the
    services; confirm traces land in Tempo.
B6. Sentry↔Tempo correlation: in the Sentry project, set the trace link to Grafana Tempo.
B7. Acceptance checks: AC-10-9 — fire a test alert (temporarily lower a threshold) and confirm
    receipt on BOTH email + Telegram. AC-10-10 — trigger a backend error, open the Sentry issue,
    click through to the Tempo trace.

## SECTION C — Sentry + GitHub
C1. In Sentry (sentry.io → StratTraderPro project): note the SENTRY_ORG slug + SENTRY_PROJECT slug;
    create an Auth Token (Settings → Auth Tokens) with scope `project:releases` (+ `project:read`).
C2. In GitHub (github.com/yhaspel/StratTraderPro → Settings → Secrets and variables → Actions):
    add repository SECRET `SENTRY_AUTH_TOKEN`; add repository VARIABLES `SENTRY_ORG` +
    `SENTRY_PROJECT`. This activates the frontend sourcemap-upload CI step.
C3. Set `SENTRY_DSN` on the backend service (both envs) so backend errors report (release=GIT_SHA
    is already wired in code).

Report which sections completed and anything that blocked.

---

## Staging perf verifications (also deferred — need scale/tools, do after the above)
- Audit-search p95 ≤ 500 ms @ 10M rows; verifier ≥ 24h synthetic (~100k) ≤ 5 min; flag-flip E2E
  ≤ 60 s in the real UI; dashboards populated end-to-end.
