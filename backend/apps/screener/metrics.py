"""Screener Prometheus metrics (M16 §6.8).

Amendment A6: metrics only. ADR-109 (PR #50) deleted the Data Pipelines
dashboard and reduced Grafana to the 3-dashboard safety core, so the spec's
"wire both into the System Health dashboard's Data Pipelines row" targets a
dashboard that no longer exists. The series ship and stay queryable in Explore;
whether they earn a panel is a future ADR-109-scope decision (see ADR-063).

Vendor traffic needs nothing new here — the screener call already shows up as
``marketdata_requests_total{endpoint="company-screener"}``.
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

SCREEN_RUNS_TOTAL = Counter(
    "screen_runs_total",
    "Screener runs by terminal result.",
    labelnames=("result",),  # done | degraded | failed
)

SCREEN_RUN_DURATION_SECONDS = Histogram(
    "screen_run_duration_seconds",
    "Wall-clock duration of a screener run.",
    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 180, 240, 300),
)

__all__ = ["SCREEN_RUNS_TOTAL", "SCREEN_RUN_DURATION_SECONDS"]
