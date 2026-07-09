# On-call

**Owner:** Yuval
**Status:** Solo operation. This is the whole rotation. **Companion docs:**
`docs/runbooks/incident-triage.md` (alert → action), `docs/slo.md` (the four SLOs),
`docs/postmortem-template.md` (after a real incident), `docs/adr/102-observability-topology.md`
(how the signals get to you).

## The rotation

StratTraderPro is operated by one person. There is no follow-the-sun rotation and no
secondary responder in the usual sense.

- **Primary (operator):** Yuval — `yuval3000@gmail.com`, Telegram via the operator
  bot (see `docs/runbooks/alerting-setup.md`).
- **Alternate contact:** _(fill in a name + reachable channel — a trusted person who
  can at minimum see the pages and reach the operator by another route if Telegram
  and email are both missed. Keep this current.)_

Because it is solo, the emphasis is on **automation stopping the bleeding without a
human** (the kill-switch engine auto-trips L2; the platform can be halted from the
phone) rather than on a hand-off. A page is a call to look now; the runbooks are
written so a single person can act from a phone.

## What pages vs what is advisory

Routing is set in `infra/grafana/alerts/notification-policy.yaml`:

- **Pages (critical) → email + Telegram.** Respond now. These are:
  `WebhookErrorRatioCrit`, `BrokerStreamSilent`, `KillSwitchFlattenSlow`,
  `KillSwitchTriggered`, `AuditIntegrityFailure`. Money- or trust-critical: order
  flow is erroring, the fill stream is dead, a flatten is too slow, a kill switch
  fired, or the audit chain failed verification.
- **Advisory (warning) → email only.** Triage next working session; escalate if it
  persists or trends toward its critical sibling. These are:
  `WebhookErrorRatioWarn`, `OrderSubmitLatencyHigh`, `CeleryQueueDepthHigh`,
  `SentimentLag`, `HMMModelStale`, `DBConnectionSaturation`, and the three
  backtest warnings (`BacktestQueueWaitHigh`, `BacktestFailureRate`,
  `BacktestArtifactBloat`).

Both channels are in the same policy so a Telegram outage still delivers criticals
by email.

**Advisory-but-not-an-alert:** admin logins from a new IP. There is no page for it
(it would fire on every legitimate travel/ISP change); it is a manual review of
`auth.login_ok` audit rows during any security-flavored triage — see
`incident-triage.md` (the new-IP advisory).

## When you get paged

1. Open `docs/runbooks/incident-triage.md`, find the alert row, follow the linked
   runbook.
2. If it is a real incident (not an expected/intentional kill-switch trip), stop the
   bleeding first — the runbook says how; a platform-wide intake stop is
   `docs/runbooks/platform-halt.md`.
3. After resolution, if it was a real critical, write a blameless postmortem
   (`docs/postmortem-template.md`) and note the SLO/error-budget impact
   (`docs/slo.md`).

## Runbook index

| Situation | Runbook |
|---|---|
| Any alert fired — what does it mean | `runbooks/incident-triage.md` |
| Webhook / API 5xx | `runbooks/webhook-debug.md` |
| Fill stream silent / broker disconnected | `runbooks/alpaca-paper-smoke.md`, `runbooks/reconcile-drift-investigation.md` |
| Kill switch fired / verify the engine | `runbooks/kill-switch-verify-monthly.md`, `runbooks/daily-loss-false-trigger.md` |
| Halt the whole platform / release | `runbooks/platform-halt.md` |
| Audit integrity verifier failed | `runbooks/audit-integrity-failure.md` |
| Monthly audit spot-check | `runbooks/audit-integrity-verify-monthly.md` |
| Sentiment / LLM behind | `runbooks/sentiment-queue-backlog.md`, `runbooks/llm-worker-cold-start.md` |
| Regime model stale | `runbooks/hmm-retrain-failure.md` |
| Backtests stuck / queue not draining | `runbooks/backtest-stuck.md` |
| Task-process metrics missing | `runbooks/worker-metrics-scrape.md` |
| Set up / re-import alerting | `runbooks/alerting-setup.md` |
