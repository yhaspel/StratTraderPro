"""Order/fill Celery tasks (M04 §6.4).

``fill_ingestor`` drains the per-user Redis Streams (``fills:user:*``) through
the consumer group and applies each event via ``ingest_fill_event``. Scheduled
by beat in prod (``CELERY_BEAT_SCHEDULE``); a no-op when ``FILLS_INLINE`` is set
(tests apply fills synchronously, so the streams are always empty).
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=True)
def fill_ingestor(self):
    if getattr(settings, "FILLS_INLINE", False):
        return {"skipped": "inline"}
    from .fills import sweep_all_streams

    try:
        processed = sweep_all_streams()
    except Exception:  # pragma: no cover — transport hiccup; next beat retries
        logger.exception("fill_ingestor.sweep_failed")
        return {"error": "sweep_failed"}
    return {"processed": processed}


@shared_task(bind=True, ignore_result=True)
def reconcile_positions_task(self):
    """M05 §6.3 — every 5 min, reconcile each connected broker account's
    positions against broker truth."""
    from apps.brokers.models import BrokerAccount

    from .reconcile import reconcile_account

    total_drifts = 0
    accounts = 0
    for account in BrokerAccount.objects.filter(status=BrokerAccount.Status.CONNECTED):
        if account.broker == BrokerAccount.Broker.TRADESTATION and not getattr(
            settings, "BROKER_TRADESTATION_ENABLED", False
        ):
            continue
        try:
            events = reconcile_account(account)
        except Exception:  # pragma: no cover — one account must not stop the sweep
            logger.exception("reconcile.account_failed", extra={"account": str(account.id)})
            continue
        accounts += 1
        total_drifts += sum(1 for e in events if e.kind == e.Kind.DRIFT)
    return {"accounts": accounts, "drifts": total_drifts}
