"""GDPR export/delete + terms Prometheus counters (M11 §7.7/§7.8, §13).

Module-level so they are multiprocess-safe under gunicorn and defined once per
worker (the export runs on the Celery worker; the request/delete/terms paths run
on the web tier — both scrape their own /metrics).
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

EXPORT_REQUESTS_TOTAL = Counter(
    "gdpr_export_requests_total",
    "Personal-data export jobs enqueued.",
)

EXPORT_JOBS_TOTAL = Counter(
    "gdpr_export_jobs_total",
    "Personal-data export jobs by terminal outcome.",
    labelnames=("result",),  # ready | failed
)

EXPORT_DURATION_SECONDS = Histogram(
    "gdpr_export_duration_seconds",
    "Wall-clock to build + store a personal-data export ZIP.",
)

DELETE_REQUESTS_TOTAL = Counter(
    "gdpr_delete_requests_total",
    "Account soft-delete lifecycle events.",
    labelnames=("action",),  # requested | cancelled | anonymized
)

TERMS_ACCEPTANCES_TOTAL = Counter(
    "terms_acceptances_total",
    "Terms/Privacy acceptances recorded.",
)

__all__ = [
    "EXPORT_REQUESTS_TOTAL",
    "EXPORT_JOBS_TOTAL",
    "EXPORT_DURATION_SECONDS",
    "DELETE_REQUESTS_TOTAL",
    "TERMS_ACCEPTANCES_TOTAL",
]
