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

# M05 — order lifecycle + reconciliation + OAuth.
RECONCILE_DRIFTS_TOTAL = Counter(
    "reconcile_drifts_total",
    "Reconciliation drifts detected.",
    labelnames=("broker", "kind"),
)
RECONCILE_HEALS_TOTAL = Counter(
    "reconcile_heals_total",
    "Reconciliation heals toward broker truth.",
)
OAUTH_REFRESH_TOTAL = Counter(
    "oauth_refresh_total",
    "OAuth token refreshes by outcome.",
    labelnames=("broker", "result"),
)
ORDER_STATE_TRANSITIONS_TOTAL = Counter(
    "order_state_transitions_total",
    "Order status transitions.",
    labelnames=("broker", "to"),
)
BROKER_WS_RECONNECTS_TOTAL = Counter(
    "broker_ws_reconnects_total",
    "Broker websocket reconnects.",
    labelnames=("broker",),
)

__all__ = [
    "BROKER_CONNECT_TOTAL",
    "BROKER_STREAM_DISCONNECTS_TOTAL",
    "FILLS_INGESTED_TOTAL",
    "BROKER_STREAM_HEARTBEAT_AGE",
    "RECONCILE_DRIFTS_TOTAL",
    "RECONCILE_HEALS_TOTAL",
    "OAUTH_REFRESH_TOTAL",
    "ORDER_STATE_TRANSITIONS_TOTAL",
    "BROKER_WS_RECONNECTS_TOTAL",
]
