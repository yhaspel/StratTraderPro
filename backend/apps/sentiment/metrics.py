"""Sentiment Prometheus metrics (M07 §12)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

NEWS_INGESTED = Counter(
    "news_articles_ingested_total", "New articles ingested by source.", labelnames=("source",)
)
NEWS_DEDUPED = Counter("news_articles_deduped_total", "Articles skipped as duplicates.")
SENTIMENT_SCORED = Counter(
    "sentiment_articles_scored_total", "Articles scored by tier/result.",
    labelnames=("tier", "result"),
)
SENTIMENT_QUEUE_DEPTH = Gauge(
    "sentiment_queue_depth", "Unscored article backlog.", labelnames=("queue",)
)
# M10 §6.5c — age of the oldest unscored article (backs the sentiment-lag alert).
SENTIMENT_QUEUE_OLDEST_AGE = Gauge(
    "sentiment_queue_oldest_age_minutes", "Age of the oldest unscored article (minutes)."
)
LLM_INFERENCE_LATENCY = Histogram(
    "llm_inference_latency_seconds", "Llama inference latency.",
    buckets=(0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0),
)
LLM_INVALID_RESPONSES = Counter("llm_invalid_responses_total", "Llama responses failing JSON schema.")

__all__ = [
    "NEWS_INGESTED", "NEWS_DEDUPED", "SENTIMENT_SCORED", "SENTIMENT_QUEUE_DEPTH",
    "SENTIMENT_QUEUE_OLDEST_AGE", "LLM_INFERENCE_LATENCY", "LLM_INVALID_RESPONSES",
]
