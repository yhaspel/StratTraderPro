# BUG-009 — Every imported alert rule is PAUSED; the entire M10 alerting stack has never been able to fire

- **Severity:** S1 — safety controls that silently don't work
- **Status:** CLOSED — authorized and un-paused during the 2026-07-11 live bring-up
  (PROGRESS M10 close-out; the daily audit has asserted "zero paused rules" since).
  The paused-on-import trap itself is permanent — see the ⛔ gate in
  `docs/runbooks/alerting-setup.md` before ANY future re-import (incl. ADR-109's).
- **Area:** Observability / Alerting
- **Found:** 2026-07-11, while investigating BUG-005
- **Affects:** every StratTraderPro alert rule imported in M10 §B2

## Summary

**18 of 21 Grafana alert rules are `isPaused: true`.** A paused rule never
evaluates and can never fire. This includes every safety-critical alert on the
platform:

| Rule | Severity | Purpose |
|---|---|---|
| `KillSwitchTriggered` | critical | the kill switch fired |
| `KillSwitchFlattenSlow` | critical | flatten p99 > 5s |
| `AuditIntegrityFailure` | critical | audit log tampering |
| `BrokerStreamSilent` | critical | broker trade-updates stream dead |
| `WebhookErrorRatioCrit` | critical | webhook 5xx > 2% |
| `CeleryQueueDepthHigh`, `SentimentLag`, `HMMModelStale`, `DBConnectionSaturation`, `OrderSubmitLatencyHigh`, `WebhookErrorRatioWarn`, 3× backtest | warning | — |

The only three live rules are the `auth-health` group (created by hand, not
imported). **Everything created by the M10 import has been inert since the day it
was imported.**

## Root cause

Grafana's Prometheus-rule converter — the path used to import
`infra/grafana/alerts/alert-rules.yaml` — **creates converted rules in a paused
state by default**, so an operator can review them before they go live. The
imported rules carry the tell-tale label:

```
"__converted_prometheus_rule__": "true"
```

Nothing in the M10 runbook says "now un-pause them", so nobody did.

## Why nothing caught it

This is the worst instance yet of the project's recurring theme, because *every
signal available to an operator says the alerting works*:

- The Alert rules page lists all 17 rules, in the right folders and groups.
- Every rule has the correct PromQL, severity label, and `for` duration.
- The rules API reports **`health: ok`** for all of them — because a paused rule
  never evaluates, and a rule that never evaluates never reports a problem. A
  clean bill of health is *produced by* the defect.
- Contact points work. The notification policy works.
- **AC-10-9 passed.** It gave a false green: the acceptance check fired a *newly
  created* temp rule, which was not paused, so it proved the notification
  pipeline while proving nothing about the rules the platform actually depends
  on. The one test that was supposed to catch this was structurally incapable of
  catching it.

`isPaused` appears nowhere in the Grafana list UI, so the only way to see this is
to read the provisioning API.

## Impact

Between the M10 import and 2026-07-11, if the kill switch had fired, the audit
log had been tampered with, or the broker stream had gone silent, **no alert
would have been sent.** No page, no email, no Telegram. The dashboards would have
shown the problem; nothing would have told anyone to look.

## Detection

```js
// Grafana → provisioning API. `isPaused` is not exposed in the rule list UI.
const rules = await (await fetch('/api/v1/provisioning/alert-rules')).json();
rules.filter(r => r.isPaused).map(r => r.title);   // -> 18 rules
```

## Fix

Set `isPaused: false` on all 18 rules (PUT each rule back through
`/api/v1/provisioning/alert-rules/{uid}` with `X-Disable-Provenance: true`).

> **Blocked pending operator authorization.** Un-pausing 18 rules on a live
> trading platform starts sending real pages, so it is not something to do
> silently on the operator's behalf. Two rules are *expected* to fire immediately
> and correctly once enabled — `MetricsBudgetHigh` and `MetricsBudgetExhausted`
> (see BUG-005) — and will self-resolve once the 60s scrape interval deploys.

## Follow-up (required, or this recurs)

1. **`docs/runbooks/alerting-setup.md`** must state that converted Prometheus
   rules import **paused**, and that un-pausing is a mandatory step.
2. **AC-10-9 must be rewritten.** "Create a temp rule and watch it page" tests the
   notification path and *nothing else*. The acceptance criterion has to assert
   against the **real, production rules** — at minimum that zero rules in the
   StratTraderPro folder have `isPaused: true`.
3. Consider an operational check that asserts `isPaused == false` for every rule
   labelled `severity: critical`, run as part of the M12 sign-off.

## Related

- BUG-008 — even un-paused, nothing fired when the pipeline died (dead-man's switch).
- BUG-005 — found this bug; the budget rules were created paused by cloning a paused rule.
- The theme in `bugs/README.md`: *configuration that is wired, reports healthy, and is completely inert.*
