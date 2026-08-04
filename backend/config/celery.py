import logging
import os

from celery import Celery
from celery.signals import (
    beat_init,
    before_task_publish,
    task_postrun,
    task_prerun,
    worker_process_init,
)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

logger = logging.getLogger(__name__)

app = Celery("strattraderpro")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Verify Celery is working."""
    print(f"Request: {self.request!r}")  # noqa: T201


# ---------------------------------------------------------------------------
# FIX-C1 (M10 §6.5b) — expose a scrapeable /metrics for worker/beat processes.
# Multiple prefork children can't share one port; a subsequent child's bind
# fails harmlessly (the first child holds the port). Runbook recommends
# --concurrency=1 for a clean 1:1 port mapping.
# ---------------------------------------------------------------------------
def _start_task_metrics():
    try:
        from config.task_metrics import start_task_metrics_server

        start_task_metrics_server()
    except OSError:
        logger.info("task_metrics.port_in_use — another worker child holds it (expected)")
    except Exception:  # noqa: BLE001
        logger.exception("task_metrics.start_failed")


@worker_process_init.connect
def _on_worker_init(**_kwargs):
    _start_task_metrics()
    # M10 §6.6 — trace worker tasks too.
    try:
        from config.otel import init_otel, log_otel_status

        init_otel()
        # BUG-006 — Django is already set up in a Celery worker, so logging is
        # configured and this lands. Kept explicit (rather than logging inside
        # init_otel) so all three entrypoints behave identically.
        log_otel_status()
    except Exception:  # noqa: BLE001
        logger.exception("otel.worker_init_failed")


@beat_init.connect
def _on_beat_init(**_kwargs):
    _start_task_metrics()


# ---------------------------------------------------------------------------
# Request-id propagation across the web → Celery boundary (M10 §6.6).
# ---------------------------------------------------------------------------
@before_task_publish.connect
def _propagate_request_id(headers=None, **_kwargs):
    if headers is None:
        return
    from config.request_context import get_request_id

    rid = get_request_id()
    if rid:
        headers["request_id"] = rid


@task_prerun.connect
def _restore_request_id(task_id=None, task=None, **_kwargs):
    from config.request_context import get_request_id, set_request_id, set_task_id

    # Stash the ambient request_id so postrun can restore it. In eager mode the
    # task runs in the caller's context, so the ambient id is already correct and
    # there is no inbound header — we must NOT clobber it. In a real worker the
    # ambient is None and the id arrives via the task header.
    req = getattr(task, "request", None)
    if req is not None:
        try:
            req._prev_request_id = get_request_id()
        except Exception:  # noqa: BLE001,S110
            pass
    rid = getattr(req, "request_id", None) if req is not None else None
    if rid:
        set_request_id(rid)
    set_task_id(task_id)


@task_postrun.connect
def _clear_request_id(task=None, **_kwargs):
    from config.request_context import set_request_id, set_task_id

    req = getattr(task, "request", None)
    prev = getattr(req, "_prev_request_id", None) if req is not None else None
    set_request_id(prev)
    set_task_id(None)
