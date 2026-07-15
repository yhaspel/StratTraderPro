# Service Level Objectives

**Owner:** Yuval
**Status:** The four SLOs are defined here; their backing Prometheus series exist in
code and three of the four have committed alert rules
(`infra/grafana/alerts/alert-rules.yaml`). Live measurement depends on the scrape
being provisioned (`docs/runbooks/worker-metrics-scrape.md`) and the alerts imported
(`docs/runbooks/alerting-setup.md`). **Companion docs:**
`docs/runbooks/incident-triage.md` (the alerts that back these),
`docs/adr/102-observability-topology.md` (where the series come from),
`project-plan/10-admin-audit-observability.md` §6.5.

## How to read this

Each SLO has: a **target**, the **Prometheus series** that measures it, the
**alert** that fires when it's at risk (with the exact threshold from
`alert-rules.yaml`, which is looser than the SLO target on purpose — the alert is an
early warning, not the SLO line itself), an **error budget**, and **burn guidance**.

Error budget = `1 − target`. Burning it fast is a page; burning it slow is a review.
There is no automated multi-window burn-rate alert yet (a follow-up); the guidance
below is how to reason about it by hand from the same series.

## SLO 1 — Webhook availability ≥ 99.9%

- **Target:** ≤ 0.1% of webhook/API responses are 5xx (99.9% availability).
- **Series:** the 5xx ratio on the hooks/API views —
  `sum(rate(django_http_responses_total_by_status_total{status=~"5.."}[5m]))
  / sum(rate(django_http_responses_total_by_status_total[5m]))`.
- **Alerts:** `WebhookErrorRatioWarn` (> 1% / 5m, warning),
  `WebhookErrorRatioCrit` (> 2% / 5m, critical → page).
- **Error budget:** 0.1% of requests. At MVP volume this is small in absolute count
  — a short burst of 5xx eats a large fraction of a monthly budget.
- **Burn:** a sustained > 2% ratio is a fast burn — page, `webhook-debug.md`, check
  Sentry grouped by `release` (GIT_SHA). A ratio hovering between 0.1% and 1% is a
  slow burn — no page, but investigate the erroring view before it climbs. Missed
  webhooks are missed trades; treat availability burn as trading impact.

## SLO 2 — Order submit p95 ≤ 1.5 s

- **Target:** 95th-percentile order-submit latency ≤ 1.5 s.
- **Series:** `histogram_quantile(0.95,
  sum(rate(order_submit_latency_seconds_bucket[10m])) by (le))`.
- **Alert:** `OrderSubmitLatencyHigh` — p95 > **2 s** / 10m (warning). The alert
  threshold (2 s) is deliberately above the SLO target (1.5 s): the SLO is the goal,
  the alert is the "we've clearly blown it" line.
- **Error budget:** 5% of submits may exceed 1.5 s.
- **Burn:** p95 sitting between 1.5 s and 2 s is a slow burn — the broker or worker
  is sluggish; check Alpaca status + `celery -A config.celery inspect stats`. p95 >
  2 s sustained is the alert — order placement is materially slow; a trade that
  should have gone out at signal is landing late.

## SLO 3 — Dashboard API p95 ≤ 300 ms

- **Target:** 95th-percentile dashboard/API view latency ≤ 300 ms.
- **Series:** the django_prometheus **by-view** latency histogram —
  `histogram_quantile(0.95,
  sum(rate(django_http_requests_latency_seconds_by_view_method_bucket[5m])) by (le, view))`,
  filtered to the dashboard/API views. (These series come from the
  `django_prometheus` middleware, which stays wired even though `/metrics` moved out
  of the urlconf — ADR-102 §1.)
- **Alert:** none committed today (no dedicated rule in `alert-rules.yaml`) — this is
  a **dashboard-watched** SLO; it is a UX target, not a paging one. Add a rule if it
  regresses persistently.
- **Error budget:** 5% of dashboard/API reads may exceed 300 ms.
- **Burn:** watch the by-view p95 on the System Health / Trading Ops dashboards. A
  single slow view dominating the p95 points at an N+1 or a missing index; it
  degrades UX, not trading, so it's a review item, not a page.

## SLO 4 — Kill-switch flatten p99 ≤ 5 s

- **Target:** 99th-percentile flatten latency ≤ 5 s (risk gets cut fast).
- **Series:** `histogram_quantile(0.99,
  sum(rate(killswitch_flatten_latency_seconds_bucket[10m])) by (le))`. The histogram
  tops out at 10 s; a healthy paper flatten lands in the sub-second buckets
  (`kill-switch-verify-monthly.md`).
- **Alert:** `KillSwitchFlattenSlow` — p99 > **5 s** / 5m (critical → page). Here the
  alert threshold equals the SLO target: a slow flatten is directly a risk event, so
  crossing the line pages immediately.
- **Error budget:** 1% of flattens may exceed 5 s. This is the tightest budget —
  flatten latency is the time risk stays on the books after the decision to cut it.
- **Burn:** any p99 > 5 s is a page — verify positions actually went flat, check the
  broker's `close_all_positions` responsiveness, and postmortem. Note the p99 target
  is measured on staging with real broker round-trips (deferred to the M08 exit gate,
  `kill-switch-verify-monthly.md`); locally it's measured against `FakeBrokerAdapter`.

## Summary

| SLO | Target | Alert (threshold) | Budget | Pages? |
|---|---|---|---|---|
| Webhook availability | ≥ 99.9% (5xx ≤ 0.1%) | `WebhookErrorRatioCrit` (> 2%/5m) | 0.1% | yes (crit) |
| Order submit p95 | ≤ 1.5 s | `OrderSubmitLatencyHigh` (> 2s/10m) | 5% | no (warn) |
| Dashboard API p95 | ≤ 300 ms | — (dashboard-watched) | 5% | no |
| Flatten p99 | ≤ 5 s | `KillSwitchFlattenSlow` (> 5s/5m) | 1% | yes (crit) |

When an SLO's budget is materially burned by a real incident, record it in the
postmortem (`docs/postmortem-template.md`) under Impact → SLO / error-budget impact.
