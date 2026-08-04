"""Risk Celery tasks (M08 §6.4) — daily-loss watcher."""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=True)
def daily_loss_watcher(self):
    """Every 30s during market hours: check each user's daily P&L; trip L2 on a
    two-poll-confirmed breach (AC-08-9)."""
    if not getattr(settings, "KILL_SWITCHES_ENABLED", True):
        return {"skipped": "disabled"}
    from django.core.cache import cache

    from .killswitch import check_daily_loss, market_is_open, release_expired_l2_halts
    from .models import RiskProfile

    # Single-flight guard (FIX-M15): a run that overshoots the 30s beat must not
    # overlap the next — two concurrent runs would cache.incr the same key inside
    # one stale window and defeat the two-poll confirmation. TTL > beat interval
    # so an in-progress run keeps the lock; a crash lets it expire.
    lock_key = "risk:daily_loss_watcher:lock"
    if not cache.add(lock_key, "1", timeout=45):
        return {"skipped": "locked"}
    try:
        # Auto-release yesterday's L2 breakers once the trading day rolls over —
        # runs regardless of session so a halt clears even off-hours (AC-08-9).
        released = release_expired_l2_halts()

        # Trip only during market hours — off-hours mark drift must not fire L2
        # (FIX-M15 / FIX-B1). Release above still happens 24/7.
        if not market_is_open():
            return {"skipped": "market_closed", "released": released}

        # P0-1: cover every user with a RiskProfile AND every user holding a
        # connected LIVE account (even with no explicit profile — a default
        # threshold is used), so the L2 breaker arms on live money by default.
        from django.contrib.auth import get_user_model

        from apps.brokers.models import BrokerAccount

        user_ids = set(RiskProfile.objects.values_list("user_id", flat=True))
        user_ids |= set(
            BrokerAccount.objects.filter(
                status=BrokerAccount.Status.CONNECTED, mode=BrokerAccount.Mode.LIVE
            ).values_list("user_id", flat=True)
        )
        tripped = 0
        for user in get_user_model().objects.filter(id__in=user_ids):
            try:
                if check_daily_loss(user):
                    tripped += 1
            except Exception:  # pragma: no cover — one user must not stop the sweep
                logger.warning("daily_loss.check_error", extra={"user": user.id})
        return {"tripped": tripped, "released": released}
    finally:
        cache.delete(lock_key)
