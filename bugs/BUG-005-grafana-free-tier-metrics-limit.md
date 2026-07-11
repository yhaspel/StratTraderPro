# BUG-005 — "Free tier limit for Metrics" — caused by the *scrape interval*, not the series count

| | |
|---|---|
| **Severity** | S3 — misleading, with a real degradation path into S1 |
| **Status** | **FIXED** in code (`scrape_interval: 60s`) — awaiting agent deploy |
| **Area** | Observability / Ops / cost |
| **Found** | 2026-07-11, visible as a banner across the Grafana Cloud UI |

## Symptom

Grafana Cloud displays, persistently:

> **You've reached your free tier limit for Metrics. Upgrade to Pro to send more series.**

## The obvious diagnosis was wrong

The banner says *series*, and M10 had just added dashboards, exporters and scrape
targets — so the natural reading was "we emit too many series, go delete some."
This bug's own first draft said exactly that. The numbers say otherwise:

| Measurement | Value |
|---|---|
| `grafanacloud_instance_active_series` | **6,946** |
| 30-day peak active series | **7,074** |
| `max_active_series_per_user` (enforced ingestion cap) | **15,000** |
| `grafanacloud_org_metrics_billable_series` | **13,068** |
| `grafanacloud_org_metrics_included_series` (free allowance) | **10,000** |

Actual series usage is **46% of the enforced cap** and has never approached it.
**Nothing was ever dropped.** But *billable* series were 13,068 against a 10,000
allowance — and that is what the banner reports.

## Root cause

Grafana Cloud does not bill raw active series. It bills:

```
billable_series = active_series x (actual_DPM / included_DPM)
```

The free tier includes **1 datapoint-per-minute per series**. The agent was
scraping every **30s** — 2 DPM:

```
6,946 x (1.98 / 1) ~= 13,068     # matches the reported billable figure exactly
```

The 30s scrape **doubled the bill without adding a single series**. And it bought
nothing: **every alert rule group evaluates at `1m`**, so the extra sample in each
minute was never read by anything.

## Fix

`infra/grafana-agent/agent.yaml`:

```diff
 metrics:
   global:
-    scrape_interval: 30s
+    scrape_interval: 60s
```

Expected: billable ≈ active ≈ 6,946 → ~69% of the allowance; banner clears, with
headroom. No metric is lost and no alert changes behaviour — the scrape is simply
aligned to the evaluation interval already in use.

(`setup-guides/grafana-setup.md` had predicted this exact remedy — *"Free-tier
quota warnings: drop scrape_interval to 60s"* — it had just never been connected
to the banner.)

## Why this is more than a billing footnote

The original concern recorded here was right, even though the mechanism was
wrong: a quota problem **degrades into a safety problem**. Once billable series
exceed the allowance, Grafana Cloud can reject **new** series. A rejected series
makes a self-filtering alert rule return empty — and Grafana reports empty as
*Normal*. The failure mode is not "alerting breaks loudly"; it is "alerting goes
quietly green while blind."

Chasing that path is what surfaced **BUG-008** (no dead-man's switch) and then
**BUG-009** (every alert rule is paused and has never been able to fire). Those
two are far more serious than the banner that led to them.

## Regression guards

1. **CI** — `backend/config/test_alert_rules.py::ScrapeIntervalBudgetTests` fails
   the build if `scrape_interval` drops below 60s. The interval is a *billing*
   lever, which is not remotely obvious from reading the agent config, so the test
   spells it out.
2. **Alerting** — `infra/grafana/alerts/usage-alerts.yaml` adds `MetricsBudgetHigh`
   (>85%, warning) and `MetricsBudgetExhausted` (>100%, critical) against the
   `grafanacloud-usage` datasource, so the budget alerts *before* the cliff instead
   of leaving a UI banner as the only signal. Both created live 2026-07-11.

   Both are currently **paused** (BUG-009). Once enabled they will fire immediately
   and **correctly** — the budget genuinely is exceeded — and will self-resolve once
   the 60s agent change deploys. That is the alert working, not a false positive.

## Related

- **BUG-008** — no dead-man's switch; the degradation path above is what makes it lethal.
- **BUG-009** — every alert rule is paused, including the two guards added here.
