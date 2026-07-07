"""Sizing integration into process_alert (M08 §6.2 / AC-08-3/4/5/6).

Gathers the three trusted server-side inputs (regime, sentiment, account equity)
— alerts cannot override sizing params (§11) — computes the size, and persists a
``SizingDecision`` for every path. Returns ``None`` when the user has no
RiskProfile (→ caller uses the raw alert qty, preserving M04 behavior).
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings

from .metrics import SIZING_DECISIONS, SIZING_REJECT_REASON
from .models import RiskProfile, SizingDecision
from .sizing import SizingInputs, compute_size

logger = logging.getLogger(__name__)


def _dec(v, default="0") -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return Decimal(default)


def _latest_regime_label() -> str:
    from apps.regime.models import RegimeObservation

    obs = RegimeObservation.objects.filter(scope="MARKET").order_by("-ts").only("label").first()
    return obs.label if obs else "NEUTRAL"


def _latest_sentiment(symbol: str) -> float:
    from apps.sentiment.models import SentimentScore

    for scope in (f"SYMBOL:{symbol}", "MARKET"):
        s = SentimentScore.objects.filter(scope=scope).order_by("-produced_at").only("polarity").first()
        if s is not None:
            return float(s.polarity)
    return 0.0


def _latest_price(symbol: str) -> Decimal | None:
    from apps.marketdata.models import Bar

    bar = Bar.objects.filter(symbol=symbol.upper()).order_by("-ts").only("close").first()
    return bar.close if bar else None


def _atr14(symbol: str) -> Decimal | None:
    from apps.marketdata.models import Bar

    bars = list(
        Bar.objects.filter(symbol=symbol.upper(), tf="1d").order_by("-ts").values("high", "low", "close")[:15]
    )
    if len(bars) < 2:
        return None
    trs = []
    for i in range(len(bars) - 1):
        h, low, prev_c = bars[i]["high"], bars[i]["low"], bars[i + 1]["close"]
        trs.append(max(h - low, abs(h - prev_c), abs(low - prev_c)))
    return sum(trs) / len(trs) if trs else None


def apply_sizing(*, alert, order, account, adapter, requested_qty, side, symbol, price_hint=None):
    """Returns a SizingResult, or None if sizing is off / no profile."""
    if not getattr(settings, "SIZING_V1_ENABLED", True):
        return None
    profile = RiskProfile.objects.filter(user=alert.user).first()
    if profile is None:
        return None

    # Equity — fresh broker read with a fallback (review-note-3).
    try:
        equity = adapter.get_account().buying_power
    except Exception:  # pragma: no cover — broker hiccup → conservative default
        equity = _dec(getattr(settings, "RISK_DEFAULT_EQUITY", 100000))

    price = price_hint or _latest_price(symbol) or Decimal("100")
    inp = SizingInputs(
        requested_qty=_dec(requested_qty),
        side=side,
        symbol=symbol,
        price=_dec(price),
        equity=_dec(equity),
        regime_label=_latest_regime_label(),
        sentiment_polarity=_latest_sentiment(symbol),
        intraday_dd_pct=0.0,
        atr14=_atr14(symbol),
    )
    result = compute_size(inp, profile)
    SizingDecision.objects.create(
        user=alert.user, order=order, alert=alert, strategy=order.strategy, symbol=symbol,
        requested_qty=_dec(requested_qty), computed_qty=result.qty,
        result=SizingDecision.Result.OK if result.ok else SizingDecision.Result.REJECT,
        reject_reason=result.reason, inputs=result.meta,
    )
    SIZING_DECISIONS.labels(result="ok" if result.ok else "reject").inc()
    if not result.ok:
        SIZING_REJECT_REASON.labels(reason=result.reason).inc()
    return result
