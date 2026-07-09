# Runbook — Incident triage (alert → severity → cause → runbook → escalation)

**Owner:** Yuval
**Status:** The alert rules are committed as code at
`infra/grafana/alerts/alert-rules.yaml` (a pytest cross-checks every referenced
series against the exported metric names — `config/test_alert_rules.py`). Importing
them to Grafana Cloud + wiring contact points is the operator step in
`docs/runbooks/alerting-setup.md`. **Companion docs:** `docs/adr/102-observability-topology.md`
(why the alerts exist + where the series come from), `docs/oncall.md` (who
responds), `docs/slo.md` (the four SLOs three of these alerts back),
`docs/postmortem-template.md` (for the criticals).

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
| **WebhookErrorRatioCrit** | critical | 5xx ratio > **2%** over 5m | Sustained server errors — the webhook-availability SLO (99.9%) is at risk | `webhook-debug.md`; Sentry; `docs/slo.md` (webhook SLO + burn) | Page. If ingest is dropping alerts, consider an L3 platform halt (`platform-halt.md`) while you fix. Postmortem. |
| **BrokerStreamSilent** | critical | `max(broker_stream_heartbeat_age_seconds) > 120` for 2m | The trade-updates websocket is dead — no fills/acks arriving; supervisor wedged or broker-side outage | `alpaca-paper-smoke.md`, `reconcile-drift-investigation.md`; restart the `streams` service | Page. Positions/fills may be stale — reconcile before trusting the dashboard. Postmortem if fills were missed. |
| **OrderSubmitLatencyHigh** | warning | `order_submit_latency_seconds` p95 > **2s** over 10m | Broker API slow, Alpaca degraded, or worker saturation | Check Alpaca status + `celery -A config.celery inspect stats`; `docs/slo.md` (order-submit SLO p95 ≤ 1.5s, alert at 2s) | Escalate if p95 stays > 2s — the order-submit SLO is burning |
| **KillSwitchFlattenSlow** | critical | `killswitch_flatten_latency_seconds` p99 > **5s** over 5m | A flatten is taking too long — broker slow to `close_all_positions`, or many positions | `kill-switch-verify-monthly.md`, `strategy-flatten-limitation.md`; `docs/slo.md` (flatten SLO p99 ≤ 5s) | Page. A slow flatten means risk isn't being cut on time — verify positions actually flattened. Postmortem. |
| **CeleryQueueDepthHigh** | warning | `max(celery_queue_depth) > 1000` for 5m | A queue is backing up — worker down/undersized, a task storm, or `backtest` with no `worker-backtest` | `backtest-stuck.md` (if it's the `backtest` queue), `sentiment-queue-backlog.md`; confirm workers are up | Escalate if the `celery` (order-flow) queue is the one backing up — order placement is delayed |
| **KillSwitchTriggered** | critical | `increase(killswitch_trigger_total[5m]) > 0` | A kill switch engaged — L0/L1/L2/L3. **May be intentional** (you or an auto-trip) | `daily-loss-false-trigger.md` (if it's an L2 auto-trip you didn't expect), `kill-switch-verify-monthly.md` | Page — confirm it was expected. If it's an L2 false-trigger, follow the daily-loss runbook. Postmortem only if unexpected/erroneous. |
| **SentimentLag** | warning | `sentiment_queue_oldest_age_minutes > 30` for 5m | Scoring is behind — LLM worker cold/off, ingest spike, or a stuck scorer | `sentiment-queue-backlog.md`, `llm-worker-cold-start.md` | Sentiment is an *input* to sizing, not a trade gate — degrades gracefully. Escalate only if chronic. |
| **HMMModelStale** | warning | `regime_model_age_seconds > 172800` (48h) for 30m | Nightly `retrain_hmm` hasn't produced a fresh model in 48h (weekend mute is documented in the rule) | `hmm-retrain-failure.md` | Regime falls back to rule-only classification (M06 AC-06-8) — not urgent; fix the retrain beat |
| **AuditIntegrityFailure** | critical | `increase(audit_integrity_check_total{result="fail"}[1h]) > 0` | The nightly verifier found a hash mismatch, a linkage break, or a missing trigger — **possible tamper or corruption** | **`audit-integrity-failure.md`** (freeze audit-consumer trust first) | Page. Treat as a potential security incident until proven benign. Full postmortem. |
| **DBConnectionSaturation** | warning | `pg_stat_activity_count / pg_settings_max_connections > 0.8` for 5m | Connection leak, a pool misconfig, or genuine load. (Railway managed PG exposes no CPU — this is the saturation proxy; true CPU is the Railway dashboard.) | Check pool sizing + `pg_stat_activity`; Railway PG metrics | Escalate if it hits 100% — new connections will be refused platform-wide |
| **BacktestQueueWaitHigh** | warning | `backtest_queue_wait_seconds` p95 > **600s** (10 min) over 15m | The `worker-backtest` service isn't consuming the queue — the #1 cause is it doesn't exist yet on Railway | **`backtest-stuck.md`** §1/§7 | Not a trading risk — backtests just queue. Stand up / restart `worker-backtest`. |
| **BacktestFailureRate** | warning | `increase(backtest_failed_total[1h]) > 3` | Runs failing — often `BACKTEST_INSUFFICIENT_DATA` (backfill gaps) or `BACKTEST_TIME_CAP` (jobs too big) | `backtest-stuck.md` §5/§6 | Not a trading risk; user-side fix (shrink the job / backfill) |
| **BacktestArtifactBloat** | warning | `backtest_artifact_bytes > 5e9` (5 GB) for 30m | Stored tearsheets approaching the R2-revisit trigger | `backtest-stuck.md` §9 (retention runs nightly) | ADR follow-up if it keeps climbing after eviction |

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
Record the date, the alert, and the outcome. For SLO-backing alerts
(webhook, order-submit, flatten), note the error-budget impact per `docs/slo.md`.
