"""Regime Prometheus metrics (M06 §12)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

REGIME_COMPUTE_LATENCY = Histogram(
    "regime_compute_latency_seconds",
    "Feature + classify latency.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)
REGIME_MODEL_AGE = Gauge(
    "regime_model_age_seconds",
    "Age of the active HMM model.",
)
HMM_RETRAIN_TOTAL = Counter(
    "hmm_retrain_total",
    "HMM retrains by outcome.",
    labelnames=("result",),
)

__all__ = ["REGIME_COMPUTE_LATENCY", "REGIME_MODEL_AGE", "HMM_RETRAIN_TOTAL"]
