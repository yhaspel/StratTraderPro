"""Kill-switch engine (M08 §6.3/§6.4).

Four levels, all stored on ``brokers.TradingHalt`` (no parallel model):
L0 strategy, L1 user-global, L2 daily-loss (auto), L3 platform (user NULL).
``is_blocked`` is consulted at the webhook AND in ``process_alert``. Halt-toggle
and daily-loss paths use ``SELECT FOR UPDATE`` (transaction-isolation gap in the
analysis doc). Flatten goes through the broker adapter's ``flatten_all`` and its
latency is measured.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.brokers.models import BrokerAccount, TradingHalt

from .metrics import DAILY_LOSS_BREACH, KILLSWITCH_FLATTEN_LATENCY, KILLSWITCH_TRIGGER
from .models import RiskEvent

logger = logging.getLogger(__name__)

# Effective trading-day boundary (UTC-05) for the L2 auto-reset (AC-08-9).
_DAY_OFFSET = timedelta(hours=5)


def _enabled() -> bool:
    return getattr(settings, "KILL_SWITCHES_ENABLED", True)


def trading_day(dt=None):
    dt = dt or timezone.now()
    return (dt - _DAY_OFFSET).date()


# ---------------------------------------------------------------------------
# Read path (hot)
# ---------------------------------------------------------------------------
def is_blocked(user_id, strategy_id=None) -> str | None:
    """Return a block reason code or None. Order: platform → user → strategy."""
    if not _enabled():
        # Even with the engine off, honor a plain strategy toggle (plan §15).
        if strategy_id and TradingHalt.objects.filter(
            user_id=user_id, strategy_id=strategy_id, level=TradingHalt.Level.L0, released_at__isnull=True
        ).exists():
            return "STRATEGY_HALTED"
        return None
    if TradingHalt.objects.filter(
        user__isnull=True, level=TradingHalt.Level.L3, released_at__isnull=True
    ).exists():
        return "PLATFORM_HALTED"
    if TradingHalt.objects.filter(
        user_id=user_id, strategy__isnull=True, released_at__isnull=True
    ).exists():
        return "USER_HALTED"
    if strategy_id and TradingHalt.objects.filter(
        user_id=user_id, strategy_id=strategy_id, released_at__isnull=True
    ).exists():
        return "STRATEGY_HALTED"
    return None


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------
@transaction.atomic
def trigger_halt(*, user_id, level, strategy_id=None, reason="", created_by_id=None,
                 auto=False, flatten=False) -> TradingHalt:
    """Create (or reuse) an active halt for the scope. SELECT FOR UPDATE on
    matching active halts prevents duplicate concurrent triggers."""
    scope_q = TradingHalt.objects.select_for_update().filter(released_at__isnull=True, level=level)
    if level == TradingHalt.Level.L3:
        scope_q = scope_q.filter(user__isnull=True)
    elif level == TradingHalt.Level.L0:
        scope_q = scope_q.filter(user_id=user_id, strategy_id=strategy_id)
    else:
        scope_q = scope_q.filter(user_id=user_id, strategy__isnull=True)
    existing = scope_q.first()
    if existing is not None:
        return existing

    halt = TradingHalt.objects.create(
        user_id=None if level == TradingHalt.Level.L3 else user_id,
        strategy_id=strategy_id if level == TradingHalt.Level.L0 else None,
        level=level, auto=auto, reason=(reason or level)[:255], created_by_id=created_by_id,
    )
    scope = halt.scope
    KILLSWITCH_TRIGGER.labels(scope=scope).inc()
    RiskEvent.objects.create(
        user_id=None if level == TradingHalt.Level.L3 else user_id,
        type=RiskEvent.Type.KILL_SWITCH_ON, scope=scope,
        details={"level": level, "auto": auto, "reason": reason},
    )
    if flatten and level != TradingHalt.Level.L3 and user_id is not None:
        transaction.on_commit(lambda: flatten_user(user_id, scope=scope, strategy_id=strategy_id))
    return halt


@transaction.atomic
def release_halt(halt_id, released_by_id=None) -> bool:
    halt = TradingHalt.objects.select_for_update().filter(id=halt_id, released_at__isnull=True).first()
    if halt is None:
        return False
    # L2 daily-loss auto halts cannot be released until the next trading day.
    if halt.auto and halt.level == TradingHalt.Level.L2 and trading_day(halt.created_at) == trading_day():
        return False
    halt.released_at = timezone.now()
    halt.released_by_id = released_by_id
    halt.save(update_fields=["released_at", "released_by"])
    RiskEvent.objects.create(
        user=halt.user, type=RiskEvent.Type.KILL_SWITCH_OFF, scope=halt.scope,
        details={"level": halt.level},
    )
    return True


def flatten_user(user_id, *, scope="USER", strategy_id=None) -> dict:
    """Flatten all of a user's positions via each broker's ``flatten_all``.
    Latency (first call → last submit) is measured for AC-08-8's p99 budget."""
    from apps.brokers.services import build_adapter
    from apps.orders.services import reconcile_positions

    t0 = time.monotonic()
    accounts = list(BrokerAccount.objects.filter(user_id=user_id, status=BrokerAccount.Status.CONNECTED))
    flattened = 0
    for account in accounts:
        try:
            adapter = build_adapter(account)
            acks = adapter.flatten_all(reason=scope)
            flattened += len(acks)
            reconcile_positions(account, adapter)
        except Exception:  # pragma: no cover — best-effort; broker cancel still attempted
            logger.warning("killswitch.flatten.error", extra={"account": str(account.id)})
    latency = time.monotonic() - t0
    KILLSWITCH_FLATTEN_LATENCY.observe(latency)
    RiskEvent.objects.create(
        user_id=user_id, type=RiskEvent.Type.FLATTEN, scope=scope,
        details={"latency_s": round(latency, 3), "accounts": len(accounts), "flattened": flattened},
    )
    return {"latency_s": latency, "flattened": flattened}


# ---------------------------------------------------------------------------
# Daily-loss watcher (L2)
# ---------------------------------------------------------------------------
def user_daily_pnl(user) -> tuple[Decimal, Decimal]:
    """Return (pnl_usd, equity). Unrealized from cached Position marks (the
    conservative fallback when fresh broker marks time out — §review-note-3)."""
    from apps.orders.models import Position

    pnl = Decimal("0")
    equity = Decimal("0")
    for p in Position.objects.filter(user=user):
        if p.market_price is not None:
            pnl += (p.market_price - p.avg_cost) * p.qty
            equity += abs(p.market_price * p.qty)
    return pnl, equity


def check_daily_loss(user, *, require_consecutive: int = 2) -> bool:
    """Trip L2 if the user's daily P&L breaches their profile threshold on
    ``require_consecutive`` polls (two-poll confirmation avoids stale-mark false
    positives — §review-note-3 / risk table). Returns whether L2 was triggered."""
    from django.core.cache import cache

    from .models import RiskProfile

    profile = RiskProfile.objects.filter(user=user).first()
    if profile is None:
        return False
    pnl, equity = user_daily_pnl(user)
    loss_usd = pnl <= -abs(profile.daily_loss_usd)
    loss_pct = equity > 0 and (pnl / equity * 100) <= -abs(profile.daily_loss_pct)
    key = f"risk:dl:{user.id}:{trading_day()}"
    if not (loss_usd or loss_pct):
        cache.delete(key)
        return False
    try:
        cache.add(key, 0, timeout=3600)
        n = cache.incr(key)
    except ValueError:  # pragma: no cover
        cache.set(key, 1, timeout=3600)
        n = 1
    if n < require_consecutive:
        return False
    DAILY_LOSS_BREACH.inc()
    RiskEvent.objects.create(
        user=user, type=RiskEvent.Type.DAILY_LOSS_BREACH, scope="USER",
        details={"pnl": str(pnl), "equity": str(equity)},
    )
    trigger_halt(user_id=user.id, level=TradingHalt.Level.L2, reason="DAILY_LOSS_BREACH",
                 auto=True, flatten=True)
    return True
