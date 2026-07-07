"""Sentiment Celery tasks (M07 §6.1/§6.5)."""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=True)
def ingest_news(self):
    """Every 15 min: pull each fetcher, persist with dedup (AC-07-1)."""
    if not getattr(settings, "SENTIMENT_ENABLED", True):
        return {"skipped": "disabled"}
    from .fetchers import build_fetchers
    from .metrics import NEWS_DEDUPED, NEWS_INGESTED
    from .services import ingest_article

    ingested = deduped = 0
    for fetcher in build_fetchers():
        try:
            raws = fetcher.fetch_since()
        except Exception:  # pragma: no cover — one bad source must not stop others
            logger.warning("news.fetch.error", extra={"source": getattr(fetcher, "source", "?")})
            continue
        for raw in raws:
            art, created = ingest_article(raw)
            if created:
                ingested += 1
                NEWS_INGESTED.labels(source=raw.source).inc()
            elif art is not None:
                deduped += 1
                NEWS_DEDUPED.inc()
    return {"ingested": ingested, "deduped": deduped}


@shared_task(bind=True, ignore_result=True)
def score_pending_articles(self, limit: int = 200):
    """FinBERT (+ routed Tier-2) for unscored articles (AC-07-3/4)."""
    from .metrics import SENTIMENT_QUEUE_DEPTH
    from .models import NewsArticle
    from .routing import score_article

    scored = 0
    for art in NewsArticle.objects.filter(tier1_scored=False).order_by("fetched_at")[:limit]:
        score_article(art)
        scored += 1
    SENTIMENT_QUEUE_DEPTH.labels(queue="finbert").set(
        NewsArticle.objects.filter(tier1_scored=False).count()
    )
    return {"scored": scored}


@shared_task(bind=True, ignore_result=True)
def aggregate_sentiment(self):
    """Recompute per-symbol EWMA + market-wide, emit sentiment.updated."""
    from .aggregator import WINDOW_MINUTES, aggregate_market, aggregate_symbol
    from .models import NewsArticle

    now = timezone.now()
    since = now - timezone.timedelta(minutes=WINDOW_MINUTES)
    symbols = set()
    for art in NewsArticle.objects.filter(fetched_at__gte=since).only("symbols"):
        symbols.update(art.symbols or [])
    for sym in symbols:
        aggregate_symbol(sym, now)
    market = aggregate_market(now)
    # (A per-user `sentiment.updated` WS push is wired in M08 where sizing
    # consumes it; the market score is already queryable via the API.)
    return {"symbols": len(symbols), "market_polarity": market.polarity}


def queue_backlog() -> dict:
    """Backlog stats for the AC-07-9 alert (>500 or oldest >30 min)."""
    from .models import NewsArticle

    qs = NewsArticle.objects.filter(tier1_scored=False)
    oldest = qs.order_by("fetched_at").values_list("fetched_at", flat=True).first()
    age_min = (timezone.now() - oldest).total_seconds() / 60.0 if oldest else 0.0
    depth = qs.count()
    return {"depth": depth, "oldest_age_min": round(age_min, 1),
            "alert": depth > 500 or age_min > 30}
