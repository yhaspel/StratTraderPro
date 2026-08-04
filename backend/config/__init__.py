"""Ensure the Celery app is loaded when Django starts so that ``@shared_task``
resolves to our configured app (autodiscovery, and ``task_always_eager`` in
tests). Standard Django+Celery wiring — previously only the worker/beat
commands imported ``config.celery`` explicitly, so eager mode never applied
inside pytest until a task used ``.delay()`` (M04)."""
from .celery import app as celery_app

__all__ = ("celery_app",)
