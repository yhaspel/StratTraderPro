# BUG-005 — Grafana Cloud free-tier metrics limit reached (series being dropped)

| | |
|---|---|
| **Severity** | S3 — dashboards/alerts may be quietly incomplete |
| **Status** | OPEN |
| **Area** | Observability / Ops / cost |
| **Found** | 2026-07-11, visible as a banner across the Grafana Cloud UI |

## Symptom

Grafana Cloud displays, persistently:

> **You've reached your free tier limit for Metrics. Upgrade to Pro to send more series.**

## Why this matters

M10 just added a significant amount of new cardinality to the same free-tier
stack:

- six dashboards
- 14 alert rules across four groups
- `postgres-exporter` + `redis-exporter` on **both** environments
- `TASK_METRICS_PORT` scrape targets for worker / beat / streams

If the stack is at its series cap, **new series can be silently rejected**. The
failure mode is nasty and matches this project's recurring theme: an alert rule
that references a dropped series does not error — it simply evaluates to *No
Data* and therefore **never fires**. A risk/kill-switch alert that never fires is
indistinguishable from a healthy system.

This is a **safety-relevant** concern for a trading platform: the M10 alert rules
include risk and platform-halt conditions.

## Not yet established

- Whether metrics are actually being **dropped**, or the account is merely at the
  soft limit with the banner as a warning.
- Which series, if any, are being rejected.
- Whether any of the 14 alert rules currently sit in `No Data` as a result.

## Next steps

- [ ] Check Grafana Cloud → Billing/Usage for the active series count vs. the free
      tier cap, and whether ingestion is being refused.
- [ ] Review the alert rules' current state — any rule stuck in `No Data` is a
      candidate for a dropped series (not a genuinely quiet system).
- [ ] Reduce cardinality (drop unused exporter series / relabel away
      high-cardinality labels) **or** upgrade the plan.
- [ ] Add a meta-alert on "alert rule in No Data" so a silently blind rule pages
      instead of staying quiet. Absence of signal must not read as absence of
      problem.
