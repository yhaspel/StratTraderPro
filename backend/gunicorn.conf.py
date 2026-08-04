"""
Gunicorn config — multi-process Prometheus integration.

Why this file exists:
    `apps/users/metrics.py` (and django-prometheus' built-in counters) hold
    state in module-level Counter() objects. With `--workers N`, each gunicorn
    worker is a separate Python process and so holds its own copy. A scrape of
    /metrics hits one worker and returns just its view, which makes PromQL
    rate() / increase() noisy.

    `prometheus_client` ships a multi-process mode: each worker writes its
    counter state into mmap'd files in a shared directory, and the /metrics
    handler reads ALL files and sums them. Two pieces are required to make it
    safe under gunicorn:

      1. The env var `PROMETHEUS_MULTIPROC_DIR=/tmp/prom-multiproc`
         (set in docker/backend.Dockerfile). django-prometheus checks this on
         import and switches to MultiProcessCollector automatically.

      2. The `child_exit` hook below. When gunicorn reaps a worker (max
         requests reached, crash, restart, etc.) we must call
         `multiprocess.mark_process_dead(pid)` so its mmap files are cleaned
         up. Without this, a dead worker's last-known counter values stay on
         disk and keep inflating the aggregated totals after the worker is
         replaced.

This config file is referenced via `--config /app/gunicorn.conf.py` in
docker/backend.Dockerfile's CMD. Keep the CMD's other flags authoritative
(--bind, --workers, --worker-class, --timeout) so a future tweak doesn't have
to touch two places.
"""
from __future__ import annotations


def child_exit(server, worker):  # noqa: ARG001 — gunicorn hook signature
    """Clean up a worker's prometheus_client mmap files when it exits."""
    try:
        from prometheus_client import multiprocess
    except ImportError:
        # Multi-process mode requires prometheus_client; if it's not installed
        # there's nothing to clean and we silently no-op rather than crash
        # the gunicorn master.
        return
    multiprocess.mark_process_dead(worker.pid)
