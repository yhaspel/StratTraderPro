"""Admin-portal Celery tasks (M10 §6.5c). Default ``celery`` queue (no glob
routes — M09 rule; explicit per-task routes only)."""
from __future__ import annotations

from celery import shared_task


@shared_task(name="apps.admin_portal.tasks.update_queue_depths")
def update_queue_depths():
    """Refresh the ``celery_queue_depth{queue}`` gauge (every 30 s via beat)."""
    from .metrics import CELERY_QUEUE_DEPTH
    from .queues import all_queue_depths

    depths = all_queue_depths()
    for queue, depth in depths.items():
        CELERY_QUEUE_DEPTH.labels(queue=queue).set(depth)
    return depths
