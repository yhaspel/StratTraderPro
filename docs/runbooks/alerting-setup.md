# Runbook — Grafana Cloud alerting + dashboards setup

**Owner:** Yuval
**Cadence:** One-time per environment, re-run on a fresh Grafana Cloud workspace.
**Status:** The dashboards and the alert rules / contact points / notification
policy are committed as code; **importing them to Grafana Cloud and filling the
secrets is the `[LIVE]` operator step** (M10 §6.5g, AC-10-9, AC-10-10).
**Companion docs:** `docs/adr/102-observability-topology.md` (why the topology is
what it is), `docs/runbooks/incident-triage.md` (what each alert means once it
fires), `docs/runbooks/worker-metrics-scrape.md` (getting the task-process series
scraped so the alerts have data), `infra/grafana-agent/README.md`,
`setup-guides/grafana-setup.md`.

## What ships in the repo

- **Six dashboards** — `infra/grafana/`:
  `trading-ops-dashboard.json`, `risk-ops-dashboard.json`,
  `data-pipelines-dashboard.json`, `backtest-ops-dashboard.json`,
  `auth-health-dashboard.json`, `system-health-dashboard.json`.
- **Alert rules** — `infra/grafana/alerts/alert-rules.yaml` (the rules triaged in
  `incident-triage.md`).
- **Contact points** — `infra/grafana/alerts/contact-points.yaml` (email +
  Telegram, env placeholders).
- **Notification policy** — `infra/grafana/alerts/notification-policy.yaml`
  (critical → email + Telegram; warning → email).

A pytest (`config/test_alert_rules.py`) already guarantees every series referenced
in `alert-rules.yaml` is a real exported metric — so import failures here are about
credentials/wiring, not typos.

## Step 1 — Import the six dashboards

For each JSON in `infra/grafana/`: Grafana Cloud → Dashboards → New → Import →
"Upload JSON file" (or paste). Point the `Prometheus` datasource variable at your
Hosted Prometheus datasource. Each dashboard has a stable UID; re-importing updates
in place. Panels that read task-process or exporter series will show "No data"
until those scrape targets exist (`worker-metrics-scrape.md`).

## Step 2 — Create the contact points

`contact-points.yaml` is a template with two receivers. Create them in
Grafana Cloud → Alerting → Contact points (or provision the YAML), and fill the
secrets:

### Email — `operator-email`
- Type: Email. `addresses` = `${GRAFANA_ALERT_EMAIL}` (your operator inbox —
  `yuval3000@gmail.com`). `singleEmail: true` groups a batch into one message.

### Telegram — `operator-telegram`
- Type: Telegram, needs `bottoken` (`${TELEGRAM_BOT_TOKEN}`) and `chatid`
  (`${TELEGRAM_CHAT_ID}`).
- **Create the bot:** open Telegram, message **@BotFather**, send `/newbot`, follow
  the prompts; it returns the **bot token** (`123456:ABC-…`). Put it in
  `TELEGRAM_BOT_TOKEN`.
- **Get your chat id:** message **@userinfobot**; it replies with your numeric
  **chat id**. Put it in `TELEGRAM_CHAT_ID`. (Send your new bot a `/start` first so
  it's allowed to message you.)

Both receivers sit in the same notification policy on purpose (below) so a Telegram
outage still pages by email.

## Step 3 — Import the notification policy + alert rules

- **Notification policy** (`notification-policy.yaml`): default receiver
  `operator-email`; a nested route sends `severity = critical` to
  `operator-telegram` (`continue: true` so it *also* stays on email), and
  `severity =~ "critical|warning"` to email. Net effect: **critical → email +
  Telegram, warning → email**.
- **Alert rules** (`alert-rules.yaml`): Grafana Cloud → Alerting → import / provision.
  The four groups (`trading-ops`, `risk-and-queues`, `platform-and-audit`,
  `backtest-ops`) land in the `StratTraderPro` folder.

## Step 4 — Tempo datasource + Sentry ↔ Tempo correlation

- Add the **Tempo** datasource in Grafana Cloud (Connections → Data sources →
  Tempo) pointing at your Grafana Cloud Traces stack. This is where the OTel spans
  land when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (ADR-102 §4).
- In **Sentry**, wire the trace linkage so an error opens its trace in Tempo. The
  backend already tags each Sentry event with `trace_id` and `request_id`
  (`config/otel.tag_sentry_correlation()`), and sets `release = GIT_SHA`. Configure
  the Sentry↔Grafana/Tempo integration (or a "trace_id" tag link) so clicking an
  event jumps to the Tempo trace with that id.

## Step 5 — AC-10-9: fire a sample alert end-to-end

Prove the pipe from rule → contact point → your phone/inbox works before you rely
on it:

1. Pick a cheap, safe-to-trip rule. The simplest is to temporarily lower a warning
   threshold (e.g. `CeleryQueueDepthHigh`'s `> 1000` to `> 0` in a scratch copy) or
   use Grafana's "test" on a rule, so it transitions Inactive → Pending → Firing.
2. Confirm a **warning** delivers to **email only**, and a **critical** (temporarily
   force one, e.g. a scratch rule labelled `severity: critical`) delivers to
   **email + Telegram**.
3. Watch the rule go Inactive → Pending(activeAt) → Firing(activeAt + `for`) in the
   Alerting UI, and confirm the message arrives on both channels for the critical.
4. Revert the scratch threshold. Record the run in `docs/oncall.md` / the drill log.

## Step 6 — AC-10-10: Sentry → Tempo click-through

1. Trigger a captured error in a traced environment (OTLP endpoint set) — e.g. hit
   an endpoint that raises, or use a deliberate test exception.
2. Open the event in Sentry; confirm it carries `request_id` and `trace_id` tags and
   groups under the current `release` (GIT_SHA).
3. Click through to the Tempo trace for that `trace_id`; confirm the span tree shows
   the request (Django → DB/redis/httpx → any Celery span it spawned). This is the
   correlation ADR-102 §5 delivers.

## Step 7 — Railway deploy notifications (replaces the "deploy rollback" alert)

The plan's "deploy rollback event" alert has **no in-code signal** — nothing emits
a metric on deploy/rollback (ADR-102 §consequences). Instead, use **Railway's own
deploy notifications**: Railway project → Settings → Notifications → add a webhook
or email/Slack notification on deploy success/failure/rollback for the backend and
worker services. That gives you the "a deploy just happened / just rolled back"
signal without a fabricated Prometheus series. Point it at the same operator inbox
(and optionally the Telegram bot) so deploy events sit alongside the alerts.

## Verify the whole thing is live

- `up{service="backend"}` = 1 in Explore (agent scraping — `grafana-agent/README.md`).
- The six dashboards render with data (task-process/exporter panels populate once
  `worker-metrics-scrape.md` is done).
- Alerting UI shows the four rule groups in the `StratTraderPro` folder, `Normal`.
- A forced sample alert reached email (+ Telegram for critical).
- A Sentry test error links to its Tempo trace.
- A Railway deploy produced a notification.
