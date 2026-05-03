"""M03 — Strategies Prometheus counters/gauges (plan §12)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge

# Outcome of a user upload attempt.
STRATEGY_UPLOADS_TOTAL = Counter(
    "strategy_uploads_total",
    "User strategy upload attempts by outcome.",
    labelnames=("result",),
)
StrategyUploadResult = type(
    "StrategyUploadResult",
    (),
    {"OK": "ok", "REJECTED": "rejected", "ERROR": "error"},
)

# Webhook secret rotations.
STRATEGY_WEBHOOK_ROTATIONS_TOTAL = Counter(
    "strategy_webhook_rotations_total",
    "Webhook secret rotations across all users.",
)

# Total strategies stored (system + user). Refreshed on app startup and on
# create/delete; cheap to recompute.
STRATEGY_COUNT_GAUGE = Gauge(
    "strategy_count_gauge",
    "Total Strategy rows by type.",
    labelnames=("type",),
)


def refresh_count_gauge() -> None:
    """Cheap recompute — call on app ready + on each create/delete."""
    from .models import Strategy
    sys = Strategy.objects.filter(is_system=True).count()
    user = Strategy.objects.filter(is_system=False).count()
    STRATEGY_COUNT_GAUGE.labels(type="system").set(sys)
    STRATEGY_COUNT_GAUGE.labels(type="user").set(user)


__all__ = [
    "STRATEGY_UPLOADS_TOTAL",
    "StrategyUploadResult",
    "STRATEGY_WEBHOOK_ROTATIONS_TOTAL",
    "STRATEGY_COUNT_GAUGE",
    "refresh_count_gauge",
]
