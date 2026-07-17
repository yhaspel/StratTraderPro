"""Sizing integration into process_alert (M08 §6.2 / AC-08-3/4/5/6).

Gathers the three trusted server-side inputs (regime, sentiment, account equity)
— alerts cannot override sizing params (§11) — computes the size, and persists a
``SizingDecision`` for every path. Returns ``None`` only when sizing is off or the
user has no RiskProfile on a *paper* account (→ caller uses the raw alert qty, M04
behavior). A live account with no profile fails closed (``NO_RISK_PROFILE``, P0-1).
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from apps.admin_portal.flags import is_enabled

from .metrics import SIZING_DECISIONS, SIZING_REJECT_REASON
from .models import RiskEvent, RiskProfile, SizingDecision
from .sizing import SizingInputs, SizingResult, compute_size

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


def _resolve_price(adapter, symbol: str, price_hint) -> Decimal | None:
    """Trusted sizing price, never fabricated (FIX-H3). Priority:
    limit-price hint → a fresh broker quote (if the adapter exposes one) →
    last daily ``Bar.close``. Returns ``None`` when no trusted price exists."""
    if price_hint is not None and _dec(price_hint) > 0:
        return _dec(price_hint)
    get_quote = getattr(adapter, "get_quote", None)
    if get_quote is not None:
        try:
            quote = get_quote(symbol)
        except Exception:  # pragma: no cover — quote is best-effort, fall through
            logger.warning("sizing.quote_read_failed", extra={"symbol": symbol})
            quote = None
        if quote is not None and _dec(quote) > 0:
            return _dec(quote)
    bar = _latest_price(symbol)
    if bar is not None and _dec(bar) > 0:
        return _dec(bar)
    return None


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
    """Returns a SizingResult, or None if sizing is off / no profile (paper)."""
    if not is_enabled("SIZING_V1_ENABLED"):
        return None

    req_qty = _dec(requested_qty)

    def _persist_reject(reason: str, *, meta=None, equity=None, price=None) -> SizingResult:
        """Fail-closed reject: persist the decision, emit metrics + a SIZING_REJECT
        risk event, and return a reject result so the caller rejects the order."""
        inputs = dict(meta or {})
        if equity is not None:
            inputs["equity"] = str(equity)
        if price is not None:
            inputs["price"] = str(price)
        SizingDecision.objects.create(
            user=alert.user, order=order, alert=alert, strategy=order.strategy, symbol=symbol,
            requested_qty=req_qty, computed_qty=Decimal("0"),
            result=SizingDecision.Result.REJECT, reject_reason=reason, inputs=inputs,
        )
        SIZING_DECISIONS.labels(result="reject").inc()
        SIZING_REJECT_REASON.labels(reason=reason).inc()
        RiskEvent.objects.create(
            user=alert.user, type=RiskEvent.Type.SIZING_REJECT, scope="USER",
            details={"reason": reason, "symbol": symbol},
        )
        return SizingResult.reject(reason, inputs)

    profile = RiskProfile.objects.filter(user=alert.user).first()
    if profile is None:
        # P0-1: fail closed on a live-money account. With no RiskProfile there is
        # no sizing, no position/leverage clamp, no asset-class filter, and the L2
        # daily-loss breaker never arms — so a LIVE order must not go out unsized.
        # Paper keeps the M04 verbatim-qty behavior; auto-provision on broker
        # connect makes the common case safe-by-default rather than reject.
        from apps.brokers.models import BrokerAccount

        if getattr(account, "mode", None) == BrokerAccount.Mode.LIVE:
            return _persist_reject("NO_RISK_PROFILE")
        return None

    # RISK-2: reject asset classes the profile does not permit (order.asset_class
    # is the trusted server-side classification). Enforced before the broker read
    # so a blocked class never even touches the account.
    permitted = profile.permitted_asset_classes or []
    asset_class = getattr(order, "asset_class", None)
    if permitted and asset_class and asset_class not in permitted:
        return _persist_reject(
            "SIZING_ASSET_CLASS_BLOCKED", meta={"asset_class": asset_class, "permitted": permitted}
        )

    # RISK-2: reject once the user is already at max_concurrent OPEN positions and
    # this order would open a *new* symbol (adds/closes on held symbols are fine).
    max_concurrent = int(getattr(profile, "max_concurrent", 0) or 0)
    if max_concurrent > 0:
        from apps.orders.models import Position

        open_positions = list(
            Position.objects.filter(user=alert.user).exclude(qty=0).values_list("symbol", flat=True)
        )
        if symbol.upper() not in {s.upper() for s in open_positions} and len(open_positions) >= max_concurrent:
            return _persist_reject(
                "SIZING_MAX_CONCURRENT", meta={"open": len(open_positions), "max_concurrent": max_concurrent}
            )

    # Equity — fresh broker read. Fail CLOSED: a transient broker hiccup must
    # never size a small account off a $100k constant (FIX-H1 / FIX-H2).
    try:
        acct = adapter.get_account()
    except Exception:  # noqa: BLE001 — broker read failed → reject, never size off a default
        logger.warning("sizing.equity_read_failed", extra={"order": str(order.id)})
        return _persist_reject("SIZING_NO_EQUITY")
    equity = _dec(acct.equity)
    if equity <= 0:
        return _persist_reject("SIZING_NO_EQUITY")

    # RISK-1: real intraday drawdown from broker equity vs the day-open equity
    # (last_equity), so the soft-stop (sizing.py) can actually fire. Only a DROP
    # counts; a green day yields 0.
    last_equity = _dec(getattr(acct, "last_equity", 0) or 0)
    intraday_dd_pct = (
        float((last_equity - equity) / last_equity * 100)
        if last_equity > 0 and equity < last_equity
        else 0.0
    )

    # Price — never fabricate one (FIX-H3).
    price = _resolve_price(adapter, symbol, price_hint)
    if price is None:
        return _persist_reject("SIZING_NO_PRICE", equity=equity)
    price = _dec(price)

    inp = SizingInputs(
        requested_qty=req_qty,
        side=side,
        symbol=symbol,
        price=price,
        equity=equity,
        regime_label=_latest_regime_label(),
        sentiment_polarity=_latest_sentiment(symbol),
        intraday_dd_pct=intraday_dd_pct,
        atr14=_atr14(symbol),
    )
    result = compute_size(inp, profile)
    # Persist the two most safety-relevant inputs alongside the sizing meta (FIX-L3).
    inputs = {**result.meta, "equity": str(equity), "price": str(price)}
    SizingDecision.objects.create(
        user=alert.user, order=order, alert=alert, strategy=order.strategy, symbol=symbol,
        requested_qty=req_qty, computed_qty=result.qty,
        result=SizingDecision.Result.OK if result.ok else SizingDecision.Result.REJECT,
        reject_reason=result.reason, inputs=inputs,
    )
    SIZING_DECISIONS.labels(result="ok" if result.ok else "reject").inc()
    if not result.ok:
        SIZING_REJECT_REASON.labels(reason=result.reason).inc()
        RiskEvent.objects.create(
            user=alert.user, type=RiskEvent.Type.SIZING_REJECT, scope="USER",
            details={"reason": result.reason, "symbol": symbol},
        )
    elif result.meta.get("soft_stop_applied"):
        # SOFT_STOP fires only on an accepted, halved size (FIX-L6).
        RiskEvent.objects.create(
            user=alert.user, type=RiskEvent.Type.SOFT_STOP, scope="USER",
            details={"symbol": symbol, "intraday_dd_pct": result.meta.get("soft_stop_applied")},
        )
    return result
