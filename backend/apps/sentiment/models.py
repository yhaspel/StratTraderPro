"""Sentiment models (M07 §8).

- ``NewsArticle`` — deduped ingested article (unique ``dedup_hash`` = sha256 of
  url+title). ``material`` flags 8-K / halt / guidance for Tier-2 routing.
- ``ArticleScore`` — one score per (article, model). FinBERT (3-class) or Llama
  (structured impact/horizon/summary).
- ``SentimentScore`` — aggregated per-symbol EWMA or market-wide cap-weighted.
- ``TickerRegistry`` / ``AliasTable`` — symbol tagging support.
- ``LLMInferenceLog`` — inference metadata only (NO body/output — AC-07-12).
"""
from __future__ import annotations

from django.db import models


class NewsArticle(models.Model):
    class Source(models.TextChoices):
        FMP = "FMP", "FMP"
        EDGAR = "EDGAR", "SEC EDGAR"
        BENZINGA = "BENZINGA", "Benzinga"
        NASDAQ_HALTS = "NASDAQ_HALTS", "Nasdaq halts"
        FINNHUB = "FINNHUB", "Finnhub"
        ALPACA = "ALPACA", "Alpaca News"

    id = models.BigAutoField(primary_key=True)
    source = models.CharField(max_length=16, choices=Source.choices, db_index=True)
    url = models.URLField(max_length=1000, blank=True, default="")
    title = models.CharField(max_length=512)
    body = models.TextField(blank=True, default="")  # HTML-stripped; 90-day retention
    dedup_hash = models.CharField(max_length=64, unique=True)
    symbols = models.JSONField(default=list)  # tagged tickers
    # Space-padded denormalization (" AAPL MSFT ") for a cross-DB exact symbol
    # filter — SQLite has no JSONField `contains` lookup.
    symbols_text = models.CharField(max_length=256, blank=True, default="", db_index=True)
    material = models.BooleanField(default=False, db_index=True)
    tier1_scored = models.BooleanField(default=False, db_index=True)
    tier2_scored = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sentiment_news_article"
        indexes = [
            models.Index(fields=["source", "-published_at"]),
            models.Index(fields=["tier1_scored", "material"]),
        ]

    def __str__(self) -> str:
        return f"NewsArticle<{self.source} {self.title[:40]!r}>"


class ArticleScore(models.Model):
    class Model(models.TextChoices):
        FINBERT = "FINBERT", "FinBERT"
        LLAMA = "LLAMA", "Llama"
        FALLBACK = "FALLBACK", "Fallback"

    id = models.BigAutoField(primary_key=True)
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="scores")
    model = models.CharField(max_length=12, choices=Model.choices)
    positive = models.FloatField(default=0.0)
    negative = models.FloatField(default=0.0)
    neutral = models.FloatField(default=0.0)
    polarity = models.FloatField(default=0.0)  # pos - neg, [-1, 1]
    label = models.CharField(max_length=12, blank=True, default="")
    confidence = models.FloatField(default=0.0)
    impact = models.IntegerField(null=True, blank=True)  # Llama 0-10
    horizon_days = models.IntegerField(null=True, blank=True)
    summary = models.CharField(max_length=200, blank=True, default="")
    prompt_version = models.CharField(max_length=16, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sentiment_article_score"
        unique_together = ("article", "model")

    def __str__(self) -> str:
        return f"ArticleScore<{self.article_id} {self.model} pol={self.polarity:.2f}>"


class SentimentScore(models.Model):
    id = models.BigAutoField(primary_key=True)
    scope = models.CharField(max_length=32, db_index=True)  # MARKET or SYMBOL:XXX
    polarity = models.FloatField(default=0.0)
    impact = models.FloatField(default=0.0)
    window_minutes = models.IntegerField(default=1440)
    components = models.JSONField(default=dict)  # {articles_count, tier2_count}
    produced_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sentiment_score"
        indexes = [models.Index(fields=["scope", "-produced_at"])]

    def __str__(self) -> str:
        return f"SentimentScore<{self.scope} {self.polarity:.2f}>"


class TickerRegistry(models.Model):
    id = models.BigAutoField(primary_key=True)
    symbol = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=128, blank=True, default="")
    is_etf = models.BooleanField(default=False)

    class Meta:
        db_table = "sentiment_ticker_registry"

    def __str__(self) -> str:
        return f"TickerRegistry<{self.symbol}>"


class AliasTable(models.Model):
    id = models.BigAutoField(primary_key=True)
    alias = models.CharField(max_length=128, unique=True)  # lowercased company name
    symbol = models.CharField(max_length=16, db_index=True)

    class Meta:
        db_table = "sentiment_alias_table"

    def __str__(self) -> str:
        return f"AliasTable<{self.alias}→{self.symbol}>"


class LLMInferenceLog(models.Model):
    """Inference metadata only — NEVER the article body or model output (AC-07-12)."""

    id = models.BigAutoField(primary_key=True)
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="llm_logs")
    prompt_version = models.CharField(max_length=16, default="")
    valid = models.BooleanField(default=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sentiment_llm_inference_log"

    def __str__(self) -> str:
        return f"LLMInferenceLog<{self.article_id} valid={self.valid}>"
