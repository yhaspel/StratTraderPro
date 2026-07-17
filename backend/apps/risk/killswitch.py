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
from datetime import time as dt_time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.events import AuditEventType
from apps.audit.services import emit
from apps.brokers.models import BrokerAccount, TradingHalt

from .metrics import DAILY_LOSS_BREACH, KILLSWITCH_FLATTEN_LATENCY, KILLSWITCH_TRIGGER
from .models import RiskEvent

logger = logging.getLogger(__name__)


def _resolve_user(user_id):
    if not user_id:
        return None
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(id=user_id).first()

# The trading day is the US/Eastern calendar day — DST-correct (UTC-4 in EDT,
# UTC-5 in EST), so L2 auto-release lines up with the real market rollover
# (AC-08-9). A fixed UTC-5 offset released an hour late all summer (FIX-M8).
_NY_TZ = ZoneInfo("America/New_York")


def _enabled() -> bool:
    return getattr(settings, "KILL_SWITCHES_ENABLED", True)


def _default_threshold_profile():
    """Conservative daily-loss thresholds for a connected account that has no
    explicit RiskProfile (P0-1). An unsaved instance — only its threshold fields
    are read by ``check_daily_loss``."""
    from .models import RiskProfile

    return RiskProfile(daily_loss_usd=Decimal("1000"), daily_loss_pct=Decimal("5"))


def trading_day(dt=None):
    dt = dt or timezone.now()
    return dt.astimezone(_NY_TZ).date()


# US regular trading hours (ET). Holidays are not modeled — an extra off-day
# poll reads flat (equity == last_equity) and cannot trip (FIX-M15).
_MARKET_OPEN = dt_time(9, 30)
_MARKET_CLOSE = dt_time(16, 0)


def market_is_open(dt=None) -> bool:
    """True during US regular trading hours (Mon–Fri 09:30–16:00 ET)."""
    dt = dt or timezone.now()
    ny = dt.astimezone(_NY_TZ)
    if ny.weekday() >= 5:  # Saturday / Sunday
        return False
    return _MARKET_OPEN <= ny.time() <= _MARKET_CLOSE


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
    # Audit every halt path (admin L3, user L0/L1, auto-L2) — M10 §6.1.
    emit(
        AuditEventType.RISK_HALT_ENGAGED,
        user=None if level == TradingHalt.Level.L3 else _resolve_user(user_id),
        actor=_resolve_user(created_by_id),
        entity_type="trading_halt", entity_id=str(halt.id),
        data_after={"level": level, "scope": scope, "auto": auto, "reason": reason,
                    "strategy_id": str(strategy_id) if strategy_id else None},
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
    emit(
        AuditEventType.RISK_HALT_RELEASED,
        user=halt.user,
        actor=_resolve_user(released_by_id),
        entity_type="trading_halt", entity_id=str(halt.id),
        data_after={"level": halt.level, "scope": halt.scope},
    )
    return True


def flatten_user(user_id, *, scope="USER", strategy_id=None) -> dict:
    """Flatten all of a user's positions via each broker's ``flatten_all``.
    Latency (first call → last submit) is measured for AC-08-8's p99 budget.

    NOTE: ``strategy_id`` is intentionally unused — positions carry no
    strategy_id, so a per-strategy flatten cannot be scoped correctly and would
    liquidate the whole account. STRATEGY-scope flatten is rejected upstream at
    the serializer (FIX-H4). TODO(M09): honor strategy_id once positions are
    tagged with the originating strategy.
    """
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
def user_daily_pnl(user) -> tuple[Decimal, Decimal] | None:
    """Broker-truth daily P&L and equity for ``user`` (FIX-B1).

    Sums ``equity`` and the day's change ``equity - last_equity`` (previous
    trading-day close) across the user's connected broker accounts — NOT
    lifetime unrealized P&L on open positions (which trips every day a swing
    loser is held and never fires for a day-trader who closes round-trips).

    Returns ``(daily_pnl, equity)``, or ``None`` when no usable broker equity
    could be read. ``None`` is the fail-safe sentinel: ``check_daily_loss``
    skips the poll on it, because a monitoring gap must never auto-halt trading.
    """
    from apps.brokers.services import build_adapter

    accounts = list(
        BrokerAccount.objects.filter(user=user, status=BrokerAccount.Status.CONNECTED)
    )
    if not accounts:
        return None
    total_equity = Decimal("0")
    total_pnl = Decimal("0")
    read_ok = False
    for account in accounts:
        try:
            acct = build_adapter(account).get_account()
        except Exception:  # noqa: BLE001 — a broker read failure must not trip/release
            logger.warning("daily_loss.account_read_failed", extra={"account": str(account.id)})
            continue
        equity = Decimal(acct.equity or 0)
        if equity <= 0:  # broker reported no equity figure — unusable
            continue
        read_ok = True
        total_equity += equity
        total_pnl += equity - Decimal(acct.last_equity or 0)
    if not read_ok or total_equity <= 0:
        return None
    return total_pnl, total_equity


def check_daily_loss(user, *, require_consecutive: int = 2) -> bool:
    """Trip L2 if the user's daily P&L breaches their profile threshold on
    ``require_consecutive`` polls (two-poll confirmation avoids stale-mark false
    positives — §review-note-3 / risk table). Returns whether L2 was triggered."""
    from django.core.cache import cache

    from .models import RiskProfile

    profile = RiskProfile.objects.filter(user=user).first()
    if profile is None:
        # P0-1: an account with no explicit profile still gets daily-loss
        # protection using a conservative default threshold — never "skip".
        profile = _default_threshold_profile()
    # Already tripped today — don't re-emit the breach event/metric on every poll.
    if TradingHalt.objects.filter(
        user=user, level=TradingHalt.Level.L2, auto=True, released_at__isnull=True
    ).exists():
        return False
    snapshot = user_daily_pnl(user)
    if snapshot is None:
        # Monitoring gap (no broker equity) — never trip on missing data (FIX-B1).
        return False
    pnl, equity = snapshot
    # A 0 threshold means "no limit on this axis" — not "halt on any flat/down
    # day". With broker-equity P&L, pnl≈0 is the normal flat state, so a zero
    # threshold (unvalidated, user-settable) would otherwise trip at the open.
    loss_usd = profile.daily_loss_usd > 0 and pnl <= -abs(profile.daily_loss_usd)
    loss_pct = (
        profile.daily_loss_pct > 0
        and equity > 0
        and (pnl / equity * 100) <= -abs(profile.daily_loss_pct)
    )
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


def release_expired_l2_halts() -> int:
    """Auto-release L2 daily-loss halts once the trading day (UTC-05) has rolled
    over (AC-08-9). ``release_halt`` returns False for still-locked same-day halts,
    so only genuinely expired ones are counted."""
    released = 0
    for halt in TradingHalt.objects.filter(
        level=TradingHalt.Level.L2, auto=True, released_at__isnull=True
    ):
        if release_halt(halt.id):
            released += 1
    return released
