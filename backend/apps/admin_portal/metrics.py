"""Admin-portal Prometheus metrics (M10 §12). Prometheus-only module."""
from __future__ import annotations

from prometheus_client import Counter, Gauge

FEATURE_FLAG_FLIPS = Counter(
    "feature_flag_flips_total", "Feature-flag flips by flag.", labelnames=("flag",)
)
ADMIN_IMPERSONATION_SESSIONS = Counter(
    "admin_impersonation_sessions_total", "Impersonation sessions started."
)
CELERY_QUEUE_DEPTH = Gauge(
    "celery_queue_depth", "Celery queue depth (Redis LLEN).", labelnames=("queue",)
)

__all__ = ["FEATURE_FLAG_FLIPS", "ADMIN_IMPERSONATION_SESSIONS", "CELERY_QUEUE_DEPTH"]
