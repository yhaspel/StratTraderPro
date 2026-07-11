# BUG-008 — Alerting has no dead-man's switch: a dead metrics pipeline is indistinguishable from "all healthy"

- **Severity:** S1 — a safety control that silently doesn't work
- **Status:** FIXED (code + live rules created) — the live rules are **paused**, see BUG-009
- **Area:** Observability / Alerting
- **Found:** 2026-07-11, while investigating BUG-005

## Summary

**14 of the 17 alert rules are *self-filtering*:** the comparison lives inside the
PromQL, so a healthy system returns an **empty** result.

```promql
increase(killswitch_trigger_total[5m]) > 0      # empty  => kill switch has not fired
increase(audit_integrity_check_total{result="fail"}[1h]) > 0
max(broker_stream_heartbeat_age_seconds) > 120
pg_stat_activity_count / pg_settings_max_connections > 0.8
```

Grafana maps *empty → NoData → (`noDataState: OK`) → Normal*. **That mapping is
correct for these rules** — for a `> 0` counter rule, "no series" really does mean
"nothing bad happened". Per-rule, the configuration is right.

The bug is what it means **in aggregate**: silence is ambiguous.

> - "no series because the condition is false" — *healthy*
> - "no series because nothing is being scraped" — **blind**

are the same observation. And **not one rule fired on absence** — there was no
`up == 0`, no `absent()`, no staleness check anywhere in the rule set.

## Impact

Anything that kills the metrics pipeline — the Grafana Agent dying, remote_write
failing, `/metrics` basic-auth rotating, an exporter falling over, or the
ingestion cap rejecting series (BUG-005) — turns **all 14 self-filtering rules
green** and pages nobody.

For a trading bot that is the worst available failure mode: `KillSwitchTriggered`
and `AuditIntegrityFailure` fail **silently open**, and they do so precisely when
the platform is least healthy. The board is not green; it is blind, and it renders
the two states identically.

## Near-miss (worth recording)

The first fix drafted here was "set `noDataState: NoData` on all rules so absence
pages us." **That would have been actively harmful.** Reading
`KillSwitchTriggered`'s actual query — `increase(killswitch_trigger_total[5m]) > 0`
— shows that empty *is* its healthy steady state, so the change would have fired
a permanent, unresolvable alert storm on 14 rules and trained the operator to
ignore the pager. `noDataState: OK` is not a mistake to be corrected; it is load-
bearing, and the ambiguity has to be resolved by a *separate* rule instead.

## Fix

Two rules that fire on **absence** — the only rules in the set that do
(`infra/grafana/alerts/alert-rules.yaml`, group `observability-liveness`):

```yaml
- alert: MetricsPipelineDown
  expr: absent(up{service="backend"})     # 1 exactly when the series has no sample
  for: 5m
  labels: {severity: critical}
- alert: TargetDown
  expr: up == 0
  for: 5m
  labels: {severity: critical}
```

`absent()` covers agent death, remote_write failure, and target removal alike:
once `up` goes stale, it returns 1.

### The import settings are inverted from the intuition — twice-burned, read this

```
MetricsPipelineDown : noDataState=OK, execErrState=Alerting
TargetDown          : noDataState=OK, execErrState=OK
```

The obvious move is to give the dead-man's switch `noDataState: Alerting` —
*"surely THIS is the rule that should page on NoData."* **That is backwards, and
it shipped that way for about four minutes before the rule caught itself.**

`absent(X)` returns an **empty vector exactly when X is present** — i.e. when the
pipeline is healthy. Grafana reads empty as NoData. So `noDataState: Alerting`
makes the rule fire *continuously while everything is fine*: on its very first
evaluation it went `pending` with a `DatasourceNoData` instance (no series labels,
null value) while `up{service="backend"} = 1`.

Empty must map to **OK**. The datasource-unreachable case — the thing that
motivated the rule — surfaces as an **Error**, not NoData, and is covered by
`execErrState: Alerting`.

This is the *same class of mistake* as the near-miss above: reasoning about what
"NoData" ought to mean without checking what it means **for this specific query**.

## Regression guard

`backend/config/test_alert_rules.py::DeadMansSwitchTests` fails CI if the alert
set ever again contains no `absent()` rule or no `up == 0` rule, or if the
dead-man's-switch rules are downgraded below `severity: critical`.

## Status of the live rules

Both rules were created in Grafana on 2026-07-11 and evaluate cleanly
(`health=ok`, `state=inactive` — correct, the backend is up). **They were created
paused**, because they were cloned from an existing rule and *every* imported rule
in this stack turned out to be paused — which is BUG-009, found through exactly
this route. They do nothing until un-paused.

## Related

- BUG-009 — all rules paused (found via this bug; blocks it landing).
- BUG-005 — the quota problem that degrades into blind alerting, which is what
  made this ambiguity worth chasing.
