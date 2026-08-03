# ADR-109 — Observability reduced scope: safety-core alerts only, exporters retired

**Date:** 2026-08-01
**Status:** Accepted
**Amends:** ADR-102 (topology stands; the exporter half of its §3 and the
service-era rule/dashboard surface are retired)
**Reference:** `development-plans/2026-08-01-grafana-reduced-form.md` (the full
work-package plan + adversarial-review log this ADR condenses);
`project-plan/PIVOT-TO-OSS.md` D5; `bugs/BUG-005`, `bugs/BUG-008`,
`bugs/BUG-009`, `bugs/BUG-011`

## Context

Since the 2026-07-15 OSS pivot, StratTraderPro is self-hosted software and the
production Railway environment serves exactly one person. The M10/M11
observability stack was sized for a hosted service: 6 dashboards, 20 alert
rules as code plus 3 hand-made auth rules living only in Grafana Cloud,
SLO/error-budget framing (`docs/slo.md`), and two Prometheus exporter services
whose entire committed consumer surface was one warning alert
(`DBConnectionSaturation`) — the measured budget block in
`infra/grafana-agent/agent.yaml` records that ~7,000 of ~9,130 active series
were ingested to serve two pg_* series.

What must not be lost is the part Sentry cannot do: **detecting silence**. The
project's signature failure mode (bugs/README.md) is "wired, reports healthy,
completely inert" — paused-on-import rules (BUG-009), gunicorn masquerading as
Celery (BUG-011, caught by `TargetDown` within 60 seconds of going live), a
dead pipeline reading as green (BUG-008).

## Decision

1. **The Grafana Cloud pipeline stays** (free tier, grafana-agent,
   alerts-as-code, email + Telegram paging). Uptime pings and Sentry crons
   cannot express `broker_stream_heartbeat_age_seconds > 120` or kill-switch
   semantics; the alerting layer is personal risk management while real money
   moves.
2. **Alert rules 18 → 9 in `alert-rules.yaml`** (+2 kept in
   `usage-alerts.yaml` = 11 live). Kept: `WebhookErrorRatioWarn/Crit`,
   `BrokerStreamSilent`, `KillSwitchFlattenSlow`, `CeleryQueueDepthHigh`,
   `KillSwitchTriggered`, `AuditIntegrityFailure`, `MetricsPipelineDown`,
   `TargetDown`, `MetricsBudgetHigh/Exhausted`. Retired:
   `OrderSubmitLatencyHigh` (tuning signal, panel remains), `SentimentLag` +
   `HMMModelStale` (M06/M07 have no live output; both degrade gracefully by
   design), `DBConnectionSaturation` (sole exporter consumer; symptom covered
   by `WebhookErrorRatioCrit` + Sentry `OperationalError` + the Railway PG
   dashboard), the three backtest rules (research ops, not money in flight;
   `CeleryQueueDepthHigh` still catches a dead `backtest` queue), and the two
   `ApiErrorBudget*Burn` rules (error-budget semantics retired with the
   service posture).
3. **The dead-man's pair is untouchable.** `MetricsPipelineDown` (absent(),
   critical) + `TargetDown` (`up == 0`, critical); `DeadMansSwitchTests` in
   `config/test_alert_rules.py` enforces their existence.
4. **The 3 hand-made auth rules + the `StratTraderPro Auth` folder are deleted
   in Grafana Cloud** (folder UID `cfkrwjgh3sxkwa`, dashboard
   `/d/stp-auth-health`, contact point `auth-health-email`). They existed only
   in the cloud, violating the ADR-102 §6 alerts-as-code invariant. App-layer
   protections remain: ADR-108 IP-scoped lockout, rate limiting, MFA, Sentry;
   the `auth_*` series stay exported and queryable.
5. **Dashboards 6 → 3.** Keep `trading-ops`, `risk-ops`, `system-health`
   (SLO wording → plain targets); delete `auth-health`, `data-pipelines`,
   `backtest-ops` from repo and cloud.
6. **Both exporter services are removed everywhere** — Railway, compose, agent
   scrape jobs (7 → 5). Operator ordering: redeploy the agent (jobs removed)
   **before** deleting the services, or `TargetDown` pages during the cutover.
7. **SLO framing is retired.** `docs/slo.md` deleted; kept alerts keep their
   thresholds as plain safety thresholds in `incident-triage.md`.
8. **PIVOT-TO-OSS D5 is narrowed, not violated.** D5's binding rationale is CI
   coupling: `test_alert_rules.py` requires `infra/grafana/alerts/*.yaml` and
   `infra/grafana-agent/agent.yaml`, which stay. Nothing in CI reads the three
   deleted dashboard JSONs.
9. **Untouched:** Sentry (both SDKs), OTel/Tempo export + Sentry↔Tempo
   correlation, `/metrics` topology and basic auth, task-process metrics
   ports, every `apps/*/metrics.py` emitter (retiring a rule ≠ retiring the
   series), contact points, notification policy, scrape_interval 60s
   (BUG-005, CI-enforced).

## Consequences

- 11 live alert rules, every one of which protects money in flight, instance
  integrity, or the pipeline the alerts ride on. Two fewer Railway services;
  ~5,000 fewer potential series re-admitted by future keep-list mistakes.
- **Coverage honestly lost:** early warning on Postgres connection saturation
  (mitigated by symptom-level `WebhookErrorRatioCrit`, Sentry
  `OperationalError`, Railway PG dashboard); backtest ops alerts (runbook
  remains; queue-depth alert still fires on a wedged queue); auth-anomaly
  alerts (ADR-108 lockout + rate limiting + Sentry remain; revisit if the
  instance ever serves more than one human); order-submit latency alerting
  (panel remains on trading-ops).
- Historical/evidence documents (`docs/ops/`, ADR-106, `backend/loadtest/`,
  milestone plans, EXECUTION-REPORTs, `bugs/`, shipped CHANGELOG entries)
  deliberately retain pre-reduction wording — they are records, not
  instructions.
- Any future re-import of rules re-enters the BUG-009 trap (converted rules
  arrive paused); the ⛔ gate in `alerting-setup.md` and the daily audit's
  zero-paused assertion stay mandatory. A re-import also **duplicates rather
  than reconciles**: the converter creates a folder named after the uploaded
  file (live today: `StratTraderPro/stp-alert-rules.prom.yaml`), so importing
  under a different filename leaves the original rules standing. Retire rules
  by deleting them in place.
