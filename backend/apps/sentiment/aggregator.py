"""Sentiment aggregation (M07 §6.5) — per-symbol EWMA + market-wide."""
from __future__ import annotations

from django.utils import timezone

from .models import ArticleScore, NewsArticle, SentimentScore, TickerRegistry

HALF_LIFE_HOURS = 6.0
WINDOW_MINUTES = 1440  # 24h


def ewma(samples: list[tuple[float, float]]) -> float:
    """EWMA over (value, age_hours) with a 6h half-life. weight = 0.5^(age/hl)."""
    num = den = 0.0
    for value, age_h in samples:
        w = 0.5 ** (max(0.0, age_h) / HALF_LIFE_HOURS)
        num += w * value
        den += w
    return round(num / den, 4) if den else 0.0


def _symbol_samples(symbol: str, now):
    since = now - timezone.timedelta(minutes=WINDOW_MINUTES)
    rows = (
        ArticleScore.objects.filter(
            article__symbols_text__contains=f" {symbol} ", article__fetched_at__gte=since
        )
        .select_related("article")
        .order_by("-created_at")
    )
    samples, impacts = [], []
    for s in rows:
        age_h = (now - s.article.fetched_at).total_seconds() / 3600.0
        samples.append((s.polarity, age_h))
        if s.impact is not None:
            impacts.append(s.impact)
    return samples, impacts


def aggregate_symbol(symbol: str, now=None) -> SentimentScore:
    now = now or timezone.now()
    samples, impacts = _symbol_samples(symbol, now)
    polarity = ewma(samples)
    impact = round(sum(impacts) / len(impacts), 3) if impacts else 0.0
    obj, _ = SentimentScore.objects.update_or_create(
        scope=f"SYMBOL:{symbol}",
        produced_at=now,
        defaults={
            "polarity": polarity, "impact": impact, "window_minutes": WINDOW_MINUTES,
            "components": {"articles_count": len(samples)},
        },
    )
    return obj


def aggregate_market(now=None) -> SentimentScore:
    """Cap-weighted average of per-symbol polarities (equal-weight fallback)."""
    now = now or timezone.now()
    since = now - timezone.timedelta(minutes=WINDOW_MINUTES)
    symbols = set()
    tier2 = 0
    for art in NewsArticle.objects.filter(fetched_at__gte=since).only("symbols", "tier2_scored"):
        symbols.update(art.symbols or [])
        tier2 += int(art.tier2_scored)
    if not symbols:
        obj, _ = SentimentScore.objects.update_or_create(
            scope="MARKET", produced_at=now,
            defaults={"polarity": 0.0, "impact": 0.0, "window_minutes": WINDOW_MINUTES,
                      "components": {"articles_count": 0, "tier2_count": tier2}},
        )
        return obj

    weights = dict(
        TickerRegistry.objects.filter(symbol__in=symbols).values_list("symbol", "id")
    )  # id as a stand-in cap weight; real caps loaded weekly in prod
    num = den = 0.0
    count = 0
    for sym in symbols:
        samples, _ = _symbol_samples(sym, now)
        if not samples:
            continue
        pol = ewma(samples)
        w = float(weights.get(sym, 1)) or 1.0
        num += w * pol
        den += w
        count += len(samples)
    polarity = round(num / den, 4) if den else 0.0
    obj, _ = SentimentScore.objects.update_or_create(
        scope="MARKET", produced_at=now,
        defaults={"polarity": polarity, "impact": 0.0, "window_minutes": WINDOW_MINUTES,
                  "components": {"articles_count": count, "tier2_count": tier2, "symbols": len(symbols)}},
    )
    return obj
