"""Audit Prometheus metrics (M10 §12). Prometheus-only module (repo convention).

Emitted from web (emit), worker/beat (verifier) — scrapeable only because the
FIX-C1 worker/beat scrape (§6.5b) lands in this milestone.
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

AUDIT_EVENTS_TOTAL = Counter(
    "audit_events_total",
    "Audit rows written by event-type family.",
    labelnames=("family",),
)
AUDIT_EVENTS_DROPPED_TOTAL = Counter(
    "audit_events_dropped_total",
    "Audit emissions that failed and were dropped (business action still succeeded).",
)
AUDIT_INTEGRITY_CHECK_TOTAL = Counter(
    "audit_integrity_check_total",
    "Nightly integrity verifier outcomes.",
    labelnames=("result",),
)
AUDIT_VERIFIER_DURATION = Histogram(
    "audit_verifier_duration_seconds",
    "Wall-clock duration of a verifier run.",
    buckets=(0.1, 0.5, 1, 5, 15, 30, 60, 120, 300),
)

__all__ = [
    "AUDIT_EVENTS_TOTAL",
    "AUDIT_EVENTS_DROPPED_TOTAL",
    "AUDIT_INTEGRITY_CHECK_TOTAL",
    "AUDIT_VERIFIER_DURATION",
]
