"""Broker + fill Prometheus metrics (M04 §12)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge

BROKER_CONNECT_TOTAL = Counter(
    "broker_connect_total",
    "Broker connection attempts by outcome.",
    labelnames=("broker", "result"),
)

BROKER_STREAM_DISCONNECTS_TOTAL = Counter(
    "broker_stream_disconnects_total",
    "trade_updates stream disconnects.",
    labelnames=("broker",),
)

FILLS_INGESTED_TOTAL = Counter(
    "fills_ingested_total",
    "Fills persisted from the stream / catch-up.",
    labelnames=("broker",),
)

BROKER_STREAM_HEARTBEAT_AGE = Gauge(
    "broker_stream_heartbeat_age_seconds",
    "Age of the most recent stream heartbeat per account.",
    labelnames=("account_id",),
)

__all__ = [
    "BROKER_CONNECT_TOTAL",
    "BROKER_STREAM_DISCONNECTS_TOTAL",
    "FILLS_INGESTED_TOTAL",
    "BROKER_STREAM_HEARTBEAT_AGE",
]
