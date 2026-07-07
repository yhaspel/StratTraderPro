"""Market-data Prometheus metrics (M06 §12)."""
from __future__ import annotations

from prometheus_client import Counter

MARKETDATA_REQUESTS = Counter(
    "marketdata_requests_total",
    "FMP/FRED requests by endpoint and result.",
    labelnames=("endpoint", "result"),
)
MARKETDATA_RATELIMIT_WAITS = Counter(
    "marketdata_ratelimit_waits_total",
    "Client-side rate-limit stalls.",
)
MARKETDATA_BARS_INGESTED = Counter(
    "marketdata_bars_ingested_total",
    "Bars upserted by timeframe.",
    labelnames=("tf",),
)

__all__ = ["MARKETDATA_REQUESTS", "MARKETDATA_RATELIMIT_WAITS", "MARKETDATA_BARS_INGESTED"]
