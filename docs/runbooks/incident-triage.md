# Runbook — Incident triage (alert → severity → cause → runbook → escalation)

**Last reviewed:** 2026-08-01 (reduced to the ADR-109 safety core)

**Owner:** Yuval
**Status:** The alert rules are committed as code at
`infra/grafana/alerts/alert-rules.yaml` + `usage-alerts.yaml` (a pytest
cross-checks every referenced series against the exported metric names —
`config/test_alert_rules.py`). Importing them to Grafana Cloud + wiring contact
points is the operator step in `docs/runbooks/alerting-setup.md`.
**Companion docs:** `docs/adr/102-observability-topology.md` (where the series
come from), `docs/adr/109-observability-reduced-scope.md` (why this is the full
rule set), `docs/postmortem-template.md` (for the criticals).
On a self-hosted instance, **you** are the one who responds.

## How to read a page

Every alert carries a `severity` label. The notification policy
(`notification-policy.yaml`) routes:

- **`critical` → email + Telegram** (a page — respond now).
- **`warning` → email** (advisory — triage next working session; escalate if it
  persists or trends).

Both channels sit in the same policy so a Telegram outage still pages by email
(risk register). Start every triage by opening the relevant Grafana dashboard for
context, then follow the row below.

## The alert table

Severity and thresholds are taken verbatim from `alert-rules.yaml`. "Runbook" is
where to go next; "Escalate" is when to open a postmortem / stop trading.

| Alert | Severity | Fires when | Likely cause | Runbook | Escalate |
|---|---|---|---|---|---|
| **WebhookErrorRatioWarn** | warning | 5xx / total responses > **1%** over 5m | A view is throwing — bad deploy, DB/Redis blip, an unhandled edge in ingest or an API view | `webhook-debug.md`; check Sentry (group by `release`=GIT_SHA) | If it climbs toward 2% (the crit), treat as the crit below |
| **WebhookErrorRatioCrit** | critical | 5xx ratio > **2%** over 5m | Sustained server errors — missed webhooks are missed trades | `webhook-debug.md`; Sentry (group by `release`=GIT_SHA) | Page. If ingest is dropping alerts, consider an L3 platform halt (`instance-halt.md`) while you fix. Postmortem. |
| **BrokerStreamSilent** | critical | `max(broker_stream_heartbeat_age_seconds) > 120` for 2m | The trade-updates websocket is dead — no fills/acks arriving; supervisor wedged or broker-side outage | `alpaca-paper-smoke.md`, `reconcile-drift-investigation.md`; restart the `streams` service | Page. Positions/fills may be stale — reconcile before trusting the dashboard. Postmortem if fills were missed. |
| **KillSwitchFlattenSlow** | critical | `killswitch_flatten_latency_seconds` p99 > **5s** over 5m | A flatten is taking too long — broker slow to `close_all_positions`, or many positions | `kill-switch-verify-monthly.md`, `strategy-flatten-limitation.md` | Page. A slow flatten means risk isn't being cut on time (target: p99 ≤ 5s) — verify positions actually flattened. Postmortem. |
| **CeleryQueueDepthHigh** | warning | `max(celery_queue_depth) > 1000` for 5m | A queue is backing up — worker down/undersized, a task storm, or `backtest` with no `worker-backtest` | `backtest-stuck.md` (if it's the `backtest` queue), `sentiment-queue-backlog.md`; confirm workers are up | Escalate if the `celery` (order-flow) queue is the one backing up — order placement is delayed |
| **KillSwitchTriggered** | critical | `increase(killswitch_trigger_total[5m]) > 0` | A kill switch engaged — L0/L1/L2/L3. **May be intentional** (you or an auto-trip) | `daily-loss-false-trigger.md` (if it's an L2 auto-trip you didn't expect), `kill-switch-verify-monthly.md` | Page — confirm it was expected. If it's an L2 false-trigger, follow the daily-loss runbook. Postmortem only if unexpected/erroneous. |
| **AuditIntegrityFailure** | critical | `increase(audit_integrity_check_total{result="fail"}[1h]) > 0` | The nightly verifier found a hash mismatch, a linkage break, or a missing trigger — **possible tamper or corruption** | **`audit-integrity-failure.md`** (freeze audit-consumer trust first) | Page. Treat as a potential security incident until proven benign. Full postmortem. |
| **MetricsPipelineDown** | critical | `absent(up{service="backend"})` for 5m | The Grafana Agent stopped scraping or remote-writing — agent dead, `/metrics` basic-auth broken, or the ingestion cap hit | `alerting-setup.md`, `worker-metrics-scrape.md`; check the `grafana-agent` Railway service logs | Page. **Alerting is blind, not green** — treat every self-filtering rule (kill switch, audit, stream) as unreliable until `up` returns. |
| **TargetDown** | critical | `up == 0` for 5m | One scrape target died — service crashed or is running the wrong process (the BUG-011 class: gunicorn where Celery should be) | `worker-metrics-scrape.md`; inspect/restart the named Railway service | Page. Every rule reading that service's series is blind while it is down. |
| **MetricsBudgetHigh** | warning | billable rate > **85%** of the included allowance for 30m | Scrape interval lowered below 60s, or a new high-cardinality series | **Check `scrape_interval: 60s` in `infra/grafana-agent/agent.yaml` FIRST** (BUG-005 — halving the interval doubles the bill without adding a series); only then hunt for new series | Escalate before 100% — past the cap Grafana may drop new series and alerting degrades to silently-green |
| **MetricsBudgetExhausted** | critical | billable rate > **100%** for 15m | Same causes, past the cliff | Same as MetricsBudgetHigh; `bugs/BUG-005` + the `usage-alerts.yaml` header are the reference | Page. New series may be dropped — even the dead-man's switch can go blind. Fix the rate; do not delete metrics. |

## Advisory — admin logins from a new IP

There is **no alert** for "admin signed in from a new IP" (it would page on every
legitimate travel/ISP change). Instead it is an **advisory review**, done from the
audit chain. During any security-flavored triage — and as a standing habit —
scan for recent successful admin logins:

- The audit chain stores auth events as `auth.login_ok` (and `auth.oauth_login_ok`)
  rows with the source `ip` and `ua`. Filter the admin console audit search
  (`/api/v1/admin/audit/?event_type=auth.login_ok`, or export.csv) for the
  operator account and eyeball the `ip` column.
- A `login_ok` from an unfamiliar IP for a staff account, especially near an
  `AuditIntegrityFailure` or an unexpected `flag.flipped` / `admin.platform_halt_engaged`,
  is a signal to treat the window as a potential compromise: rotate credentials,
  check `admin.impersonation_started` rows, and follow `audit-integrity-failure.md`
  before trusting any audit-derived conclusion.

Because the audit log is hash-chained (ADR-100), these `login_ok` rows themselves
cannot have been silently edited — if the verifier is green, the IP history is
trustworthy; if it is red, that is the `AuditIntegrityFailure` page, and the IP
review is part of that investigation.

## After a critical

Every `critical` that reflects a real incident (not an expected/intentional
kill-switch trip) gets a blameless postmortem — copy `docs/postmortem-template.md`.
Record the date, the alert, and the outcome. For the trading-path alerts
(webhook errors, broker stream, flatten latency), record the trading impact —
missed webhooks and missed fills are missed trades.
