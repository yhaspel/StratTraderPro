"""Sentiment API (M07 §6.6). MFA-enforced; SENTIMENT_ENABLED-gated."""
from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import fail, ok

from .models import ArticleScore, NewsArticle, SentimentScore
from .routing import llm_degraded

_PAGE = 25


def _score_wire(s: SentimentScore) -> dict:
    return {
        "scope": s.scope, "polarity": s.polarity, "impact": s.impact,
        "window_minutes": s.window_minutes,
        "produced_at": s.produced_at.isoformat() if s.produced_at else None,
        "components": s.components,
    }


class _Base(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def _enabled(self):
        return getattr(settings, "SENTIMENT_ENABLED", True)

    def _disabled(self):
        return fail("FEATURE_DISABLED", "Sentiment feature is disabled.", status=503)


class SentimentMarketView(_Base):
    @extend_schema(operation_id="sentiment_market", tags=["sentiment"])
    def get(self, request):
        if not self._enabled():
            return self._disabled()
        since = timezone.now() - timezone.timedelta(days=7)
        qs = SentimentScore.objects.filter(scope="MARKET", produced_at__gte=since).order_by("-produced_at")
        current = qs.first()
        return ok({
            "current": _score_wire(current) if current else None,
            "history": [_score_wire(s) for s in qs[:200]],
            "degraded": llm_degraded(),
        })


class SentimentSymbolView(_Base):
    @extend_schema(operation_id="sentiment_symbol", tags=["sentiment"])
    def get(self, request, sym):
        if not self._enabled():
            return self._disabled()
        scope = f"SYMBOL:{sym.upper()}"
        since = timezone.now() - timezone.timedelta(days=30)
        qs = SentimentScore.objects.filter(scope=scope, produced_at__gte=since).order_by("-produced_at")
        current = qs.first()
        return ok({
            "symbol": sym.upper(),
            "current": _score_wire(current) if current else None,
            "history": [_score_wire(s) for s in qs[:200]],
        })


class SentimentArticlesView(_Base):
    @extend_schema(operation_id="sentiment_articles", tags=["sentiment"])
    def get(self, request):
        if not self._enabled():
            return self._disabled()
        p = request.query_params
        qs = NewsArticle.objects.order_by("-published_at", "-fetched_at")
        if p.get("symbol"):
            qs = qs.filter(symbols_text__contains=f" {p['symbol'].upper()} ")
        if p.get("from") and parse_datetime(p["from"]):
            qs = qs.filter(fetched_at__gte=parse_datetime(p["from"]))
        if p.get("to") and parse_datetime(p["to"]):
            qs = qs.filter(fetched_at__lte=parse_datetime(p["to"]))
        total = qs.count()
        try:
            page = max(1, int(p.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        rows = list(qs[(page - 1) * _PAGE: page * _PAGE])
        # Summary-only (no full body republish — §11 copyright).
        data = []
        for a in rows:
            fb = a.scores.filter(model=ArticleScore.Model.FINBERT).first()
            llama = a.scores.filter(model=ArticleScore.Model.LLAMA).first()
            data.append({
                "id": a.id, "source": a.source, "title": a.title, "url": a.url,
                "symbols": a.symbols, "material": a.material,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "polarity": fb.polarity if fb else None,
                "label": fb.label if fb else None,
                "impact": llama.impact if llama else None,
                "summary": llama.summary if llama else "",
            })
        return ok({"articles": data, "meta": {"page": page, "total": total, "page_size": _PAGE}})
