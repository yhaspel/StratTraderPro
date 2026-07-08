"""Sentiment aggregation (M07 §6.5) — per-symbol EWMA + market-wide."""
from __future__ import annotations

from django.utils import timezone

from .models import ArticleScore, NewsArticle, SentimentScore

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
    """ONE polarity sample per article (M1): prefer the LLAMA row when present,
    else FinBERT — never both, so Tier-2 articles aren't double-counted and the
    two polarity scales aren't blended. Impact is the Llama channel."""
    since = now - timezone.timedelta(minutes=WINDOW_MINUTES)
    articles = (
        NewsArticle.objects.filter(symbols_text__contains=f" {symbol} ", fetched_at__gte=since)
        .prefetch_related("scores")
    )
    samples, impacts = [], []
    for art in articles:
        by_model = {s.model: s for s in art.scores.all()}
        chosen = by_model.get(ArticleScore.Model.LLAMA) or by_model.get(ArticleScore.Model.FINBERT)
        if chosen is None:
            continue
        age_h = (now - art.fetched_at).total_seconds() / 3600.0
        samples.append((chosen.polarity, age_h))
        llama = by_model.get(ArticleScore.Model.LLAMA)
        if llama is not None and llama.impact is not None:
            impacts.append(llama.impact)
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

    # Equal-weight per symbol until real market-cap data exists. The old code
    # weighted by TickerRegistry.id (autoincrement PK) — NOT a cap — so
    # recently-inserted tickers dominated market polarity (FIX-M3).
    # TODO: weight by real market cap once a cap source is loaded.
    num = den = 0.0
    count = 0
    for sym in symbols:
        samples, _ = _symbol_samples(sym, now)
        if not samples:
            continue
        pol = ewma(samples)
        num += pol  # equal weight (1.0)
        den += 1.0
        count += len(samples)
    polarity = round(num / den, 4) if den else 0.0
    obj, _ = SentimentScore.objects.update_or_create(
        scope="MARKET", produced_at=now,
        defaults={"polarity": polarity, "impact": 0.0, "window_minutes": WINDOW_MINUTES,
                  "components": {"articles_count": count, "tier2_count": tier2, "symbols": len(symbols)}},
    )
    return obj
