"""Celery queue-depth introspection (M10 §6.5c).

Celery-over-Redis stores each queue as a Redis list keyed by the queue name, so
``LLEN <queue>`` is the pending-task backlog. Used by the ``celery_queue_depth``
beat task and the ``/admin/health/`` aggregation.
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

QUEUES = ("celery", "backtest")


def _redis_client():
    import redis  # local import — keeps import-time light

    return redis.from_url(settings.CELERY_BROKER_URL)


def queue_depth(name: str) -> int:
    """Pending backlog for ``name`` (0 on any error — never raise into callers)."""
    try:
        return int(_redis_client().llen(name))
    except Exception:  # noqa: BLE001
        logger.warning("admin.queue_depth_failed", extra={"queue": name})
        return 0


def all_queue_depths() -> dict[str, int]:
    return {q: queue_depth(q) for q in QUEUES}
