"""Prometheus scrape endpoint for long-lived task processes (FIX-C1).

The celery worker/beat and the ``run_broker_streams`` supervisor emit most of
the M06–M08 counters/gauges, but they do NOT sit behind gunicorn's ``/metrics``
— so those series were unscrapeable and the committed dashboards/alerts stayed
dark. When ``TASK_METRICS_PORT`` is set (>0), the process starts a
``prometheus_client`` HTTP server exposing its in-process registry.

The streams supervisor calls this at startup. Full celery worker/beat wiring
(via ``worker_process_init``) is tracked as a follow-up — see
``docs/runbooks/worker-metrics-scrape.md``.
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def start_task_metrics_server(port: int | None = None) -> bool:
    """Start a Prometheus HTTP endpoint for this process. Returns True if it
    started, False when disabled (port <= 0)."""
    resolved = int(port if port is not None else getattr(settings, "TASK_METRICS_PORT", 0) or 0)
    if resolved <= 0:
        return False
    from prometheus_client import start_http_server

    start_http_server(resolved)
    logger.info("task_metrics.server_started", extra={"port": resolved})
    return True
