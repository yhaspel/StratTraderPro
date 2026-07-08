"""Backtest Prometheus metrics (M09 §12).

Module-level ``prometheus_client`` objects (per-app convention). ``stats.py`` is
the *financial* metrics module — this file is Prometheus-only.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

BACKTEST_RUNS = Counter(
    "backtest_runs_total", "Backtest runs by terminal status.", labelnames=("status",)
)
BACKTEST_RUN_DURATION = Histogram(
    "backtest_run_duration_seconds", "Backtest run wall-clock duration.",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800),
)
BACKTEST_ACTIVE_RUNS = Gauge("backtest_active_runs", "Backtest runs currently executing.")
BACKTEST_FAILED = Counter(
    "backtest_failed_total", "Backtest failures by reason.", labelnames=("reason",)
)
# Gauge (not a counter) — summed at write/eviction; no ``_total`` suffix.
BACKTEST_ARTIFACT_BYTES = Gauge(
    "backtest_artifact_bytes", "Total artifact bytes stored (json+html+pdf)."
)
BACKTEST_QUEUE_WAIT = Histogram(
    "backtest_queue_wait_seconds", "Enqueue → task start wait.",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200),
)

__all__ = [
    "BACKTEST_RUNS", "BACKTEST_RUN_DURATION", "BACKTEST_ACTIVE_RUNS",
    "BACKTEST_FAILED", "BACKTEST_ARTIFACT_BYTES", "BACKTEST_QUEUE_WAIT",
]
