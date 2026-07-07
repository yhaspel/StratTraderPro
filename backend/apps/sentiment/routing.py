"""Tiered scoring + routing (M07 §6.4).

Tier 1 (FinBERT) scores every article. Tier 2 (Llama) additionally scores
articles flagged ``material`` OR with FinBERT confidence < 0.7 (AC-07-4). When
the LLM worker is disabled/down, Tier 2 is skipped and FinBERT stands
(AC-07-10). Article text + model output are never logged (AC-07-12).
"""
from __future__ import annotations

import logging
import time

from django.conf import settings

from .metrics import LLM_INFERENCE_LATENCY, LLM_INVALID_RESPONSES, SENTIMENT_SCORED
from .models import ArticleScore, LLMInferenceLog, NewsArticle
from .scorers import PROMPT_VERSION, get_finbert, get_llama

logger = logging.getLogger(__name__)

_CONF_THRESHOLD = 0.7
_LLAMA_POLARITY = {"POSITIVE": 1.0, "NEGATIVE": -1.0, "NEUTRAL": 0.0}


def score_article(article: NewsArticle) -> ArticleScore:
    """Tier-1 score (+ Tier-2 when routed). Returns the FinBERT score row."""
    fb = get_finbert().score(f"{article.title}. {article.body[:1000]}")
    score, _ = ArticleScore.objects.update_or_create(
        article=article, model=ArticleScore.Model.FINBERT,
        defaults={
            "positive": fb.positive, "negative": fb.negative, "neutral": fb.neutral,
            "polarity": fb.polarity, "label": fb.label, "confidence": fb.confidence,
        },
    )
    NewsArticle.objects.filter(pk=article.pk).update(tier1_scored=True)
    SENTIMENT_SCORED.labels(tier="1", result="ok").inc()

    routed = article.material or fb.confidence < _CONF_THRESHOLD
    if routed:
        _score_tier2(article)
    return score


def _score_tier2(article: NewsArticle) -> None:
    llama = get_llama()
    if llama is None:  # worker disabled/down → FinBERT-only (AC-07-10)
        return
    t0 = time.monotonic()
    try:
        res = llama.score(article.title, article.body)
    except Exception:  # pragma: no cover — worker error → keep FinBERT
        logger.warning("llm.score.error", extra={"article": article.pk})
        SENTIMENT_SCORED.labels(tier="2", result="error").inc()
        return
    latency_ms = int((time.monotonic() - t0) * 1000)
    LLM_INFERENCE_LATENCY.observe(time.monotonic() - t0)
    LLMInferenceLog.objects.create(
        article=article, prompt_version=PROMPT_VERSION, valid=res.valid, latency_ms=latency_ms
    )
    if not res.valid:
        LLM_INVALID_RESPONSES.inc()
        SENTIMENT_SCORED.labels(tier="2", result="invalid").inc()
        return
    ArticleScore.objects.update_or_create(
        article=article, model=ArticleScore.Model.LLAMA,
        defaults={
            "label": res.sentiment,
            "polarity": _LLAMA_POLARITY.get(res.sentiment, 0.0) * (res.impact / 10.0),
            "impact": res.impact, "horizon_days": res.horizon_days,
            "summary": res.summary, "prompt_version": PROMPT_VERSION,
            "confidence": 1.0,
        },
    )
    NewsArticle.objects.filter(pk=article.pk).update(tier2_scored=True)
    SENTIMENT_SCORED.labels(tier="2", result="ok").inc()


def llm_degraded() -> bool:
    return not getattr(settings, "LLM_WORKER_ENABLED", False)
