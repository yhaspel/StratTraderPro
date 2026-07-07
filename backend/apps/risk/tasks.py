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
    from .killswitch import check_daily_loss, release_expired_l2_halts
    from .models import RiskProfile

    # Auto-release yesterday's L2 circuit breakers once the trading day rolls over (AC-08-9).
    released = release_expired_l2_halts()

    tripped = 0
    for profile in RiskProfile.objects.select_related("user").all():
        try:
            if check_daily_loss(profile.user):
                tripped += 1
        except Exception:  # pragma: no cover — one user must not stop the sweep
            logger.warning("daily_loss.check_error", extra={"user": profile.user_id})
    return {"tripped": tripped, "released": released}
