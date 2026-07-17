"""GDPR async jobs (M11 §7.7): personal-data export + nightly anonymize.

Both run on the DEFAULT ``celery`` queue (the one §7.0 fixed so it actually has a
consumer). The export builds a ZIP, streams it to ``STORAGES['exports']``, and
emails the user a 24h signed URL.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.utils import timezone

logger = logging.getLogger(__name__)

# Signed-URL / retention window for a produced export (frozen decision §4.2).
EXPORT_TTL = timedelta(hours=24)


def export_storage():
    """The S3-compatible (or filesystem in dev) backend for personal-data exports."""
    return storages["exports"]


def signed_export_url(job) -> str:
    """A download URL for a READY export job.

    S3/R2 backends produce a real time-limited signed URL. The filesystem backend
    (the default self-hosted deploy) has no served ``/media/`` path — ``.url()``
    would be an unsigned, permanent, 404-ing link — so we point at the
    authenticated download view instead (P1-3), absolutized via FRONTEND_BASE_URL.
    """
    from django.conf import settings
    from django.core.files.storage import FileSystemStorage
    from django.urls import reverse

    storage = export_storage()
    if isinstance(storage, FileSystemStorage):
        path = reverse("users-me-export-download", kwargs={"job_id": str(job.id)})
        return f"{settings.FRONTEND_BASE_URL.rstrip('/')}{path}"
    return storage.url(job.file_key)


@shared_task(bind=True, ignore_result=True, max_retries=2, default_retry_delay=30)
def run_data_export(self, job_id: str):
    """Build + store the export ZIP for a DataExportJob, then email the link."""
    from apps.audit.services import emit

    from .gdpr import build_export_zip
    from .metrics_gdpr import EXPORT_DURATION_SECONDS, EXPORT_JOBS_TOTAL
    from .models import DataExportJob
    from .services import _send_templated

    try:
        job = DataExportJob.objects.select_related("user").get(id=job_id)
    except DataExportJob.DoesNotExist:
        logger.warning("gdpr.export.job_missing job_id=%s", job_id)
        return

    if job.status in (DataExportJob.Status.READY, DataExportJob.Status.EXPIRED):
        return  # idempotent — already produced

    # Defensive guard: if export storage is somehow marked not-ready, leave the
    # job PENDING with a note instead of failing. In practice prod falls back to
    # local filesystem storage (see prod.py), so this branch is not hit by a
    # default self-hosted deploy.
    from django.conf import settings

    if not getattr(settings, "EXPORTS_STORAGE_READY", True):
        job.error = (
            "Export storage is not configured. Set EXPORTS_BUCKET + AWS_* for "
            "S3/R2, or rely on the local filesystem default."
        )
        job.save(update_fields=["error"])
        logger.warning("gdpr.export.storage_not_ready job_id=%s", job.id)
        return

    job.status = DataExportJob.Status.RUNNING
    job.save(update_fields=["status"])

    user = job.user
    try:
        with EXPORT_DURATION_SECONDS.time():
            data = build_export_zip(user)
            file_key = f"exports/{user.id}/{job.id}.zip"
            # overwrite-safe: the key is unique per job id.
            export_storage().save(file_key, ContentFile(data))
        now = timezone.now()
        job.status = DataExportJob.Status.READY
        job.file_key = file_key
        job.size_bytes = len(data)
        job.ready_at = now
        job.expires_at = now + EXPORT_TTL
        job.save(update_fields=["status", "file_key", "size_bytes", "ready_at", "expires_at"])
        EXPORT_JOBS_TOTAL.labels(result="ready").inc()

        emit(
            "account.export_ready",
            user=user, actor=user, entity_type="export_job", entity_id=str(job.id),
            metadata={"size_bytes": len(data)},
        )
        # Email the link (best-effort; the status endpoint also serves it).
        try:
            _send_templated(
                to=user.email,
                subject="Your StratTraderPro data export is ready",
                template_base="data_export_ready",
                context={"display_name": user.display_name, "url": signed_export_url(job)},
            )
        except Exception:  # noqa: BLE001 — email failure must not fail the job
            logger.exception("gdpr.export.email_failed job_id=%s", job.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("gdpr.export.failed job_id=%s", job.id)
        job.status = DataExportJob.Status.FAILED
        job.error = str(exc)[:256]
        job.save(update_fields=["status", "error"])
        EXPORT_JOBS_TOTAL.labels(result="failed").inc()
        emit(
            "account.export_failed",
            user_id=user.id, actor_id=user.id, entity_type="export_job", entity_id=str(job.id),
            metadata={"error": str(exc)[:256]},
        )


@shared_task(bind=True, ignore_result=True)
def anonymize_expired_accounts(self):
    """Nightly: anonymize-in-place any account whose 30-day soft-delete has expired.

    NEVER hard-deletes the User (PK anchors audit FKs). See ``gdpr.anonymize_user``.
    """
    from .gdpr import anonymize_user
    from .metrics_gdpr import DELETE_REQUESTS_TOTAL
    from .models import User

    now = timezone.now()
    due = User.objects.filter(pending_delete_at__isnull=False, pending_delete_at__lte=now, is_active=True)
    count = 0
    for user in due.iterator():
        try:
            anonymize_user(user)
            DELETE_REQUESTS_TOTAL.labels(action="anonymized").inc()
            count += 1
        except Exception:  # noqa: BLE001 — one bad row must not stall the batch
            logger.exception("gdpr.anonymize.failed user_id=%s", user.id)
    if count:
        logger.info("gdpr.anonymize.completed count=%s", count)
    return count
