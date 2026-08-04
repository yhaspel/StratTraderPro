"""Risk Prometheus metrics (M08 §12)."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

SIZING_DECISIONS = Counter(
    "sizing_decisions_total", "Sizing decisions by result.", labelnames=("result",)
)
SIZING_REJECT_REASON = Counter(
    "sizing_reject_reason_total", "Sizing rejects by reason.", labelnames=("reason",)
)
KILLSWITCH_TRIGGER = Counter(
    "killswitch_trigger_total", "Kill-switch triggers by scope.", labelnames=("scope",)
)
KILLSWITCH_FLATTEN_LATENCY = Histogram(
    "killswitch_flatten_latency_seconds", "Flatten latency (click → last submit).",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0),
)
DAILY_LOSS_BREACH = Counter("daily_loss_breach_total", "Daily-loss circuit-breaker trips.")

__all__ = [
    "SIZING_DECISIONS", "SIZING_REJECT_REASON", "KILLSWITCH_TRIGGER",
    "KILLSWITCH_FLATTEN_LATENCY", "DAILY_LOSS_BREACH",
]
