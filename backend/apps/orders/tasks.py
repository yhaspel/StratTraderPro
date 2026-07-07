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
