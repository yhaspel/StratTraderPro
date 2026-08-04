"""Webhook + order Prometheus metrics (M04 §12)."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

# Ingest outcomes by result label.
WEBHOOK_RECEIVED_TOTAL = Counter(
    "webhook_received_total",
    "Webhook requests by outcome.",
    labelnames=("result",),
)

WEBHOOK_LATENCY = Histogram(
    "webhook_latency_seconds",
    "End-to-end webhook handler latency (accept path).",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0),
)

ORDER_SUBMIT_LATENCY = Histogram(
    "order_submit_latency_seconds",
    "Broker place_order latency.",
    labelnames=("broker",),
    buckets=(0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0),
)

# Result label constants.
R_ACCEPTED = "accepted"
R_SIG_BAD = "sig_bad"
R_SCHEMA_INVALID = "schema_invalid"
R_DUPLICATE = "duplicate"
R_RATE_LIMITED = "rate_limited"
R_HALTED = "halted"
R_DISABLED = "disabled"
R_BAD_REQUEST = "bad_request"

__all__ = [
    "WEBHOOK_RECEIVED_TOTAL",
    "WEBHOOK_LATENCY",
    "ORDER_SUBMIT_LATENCY",
    "R_ACCEPTED",
    "R_SIG_BAD",
    "R_SCHEMA_INVALID",
    "R_DUPLICATE",
    "R_RATE_LIMITED",
    "R_HALTED",
    "R_DISABLED",
    "R_BAD_REQUEST",
]
