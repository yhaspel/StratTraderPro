"""GDPR export/delete + Terms acceptance endpoints (M11 §7.7/§7.8, API §10).

    GET  /api/v1/users/me/export/            -> start export job; { job_id }
    GET  /api/v1/users/me/export/{job_id}/   -> status; signed URL when READY
    POST /api/v1/users/me/delete/            -> schedule 30-day soft delete
    POST /api/v1/users/me/delete/cancel/     -> cancel pending deletion
    GET  /api/v1/terms/current/              -> current ToS/Privacy + needs_acceptance
    POST /api/v1/terms/accept/               -> record acceptance

Auth: IsAuthenticated (the DRF default), NOT MFA-gated — GDPR rights must be
exercisable by any account, and delete is a reversible 30-day soft delete with an
email confirmation + cancel. Impersonation tokens are write-blocked at the auth
layer, so an admin impersonating a user cannot POST a delete/accept on their behalf.
"""
from __future__ import annotations

from datetime import timedelta

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.audit.services import emit

from .metrics_gdpr import DELETE_REQUESTS_TOTAL, EXPORT_REQUESTS_TOTAL
from .models import DataExportJob
from .responses import fail, ok
from .services import _send_templated
from .tasks import export_storage, run_data_export, signed_export_url

# 30-day soft-delete window (frozen decision §4.3).
DELETE_WINDOW = timedelta(days=30)


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ---------------------------------------------------------------------------
# GDPR export
# ---------------------------------------------------------------------------
class DataExportRequestView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Start a personal-data export",
        responses={202: None},
    )
    def get(self, request):
        user = request.user
        # Reuse an in-flight job instead of stacking duplicates.
        active = (
            DataExportJob.objects.filter(
                user=user, status__in=[DataExportJob.Status.PENDING, DataExportJob.Status.RUNNING]
            )
            .order_by("-created_at")
            .first()
        )
        if active is not None:
            return ok({"job_id": str(active.id), "status": active.status}, status=status.HTTP_202_ACCEPTED)

        job = DataExportJob.objects.create(user=user, status=DataExportJob.Status.PENDING)
        EXPORT_REQUESTS_TOTAL.inc()
        emit(
            "account.export_requested",
            user=user, actor=user, entity_type="export_job", entity_id=str(job.id), request=request,
        )
        run_data_export.delay(str(job.id))
        return ok({"job_id": str(job.id), "status": job.status}, status=status.HTTP_202_ACCEPTED)


class DataExportStatusView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Personal-data export status + signed download URL")
    def get(self, request, job_id):
        try:
            job = DataExportJob.objects.get(id=job_id, user=request.user)
        except (DataExportJob.DoesNotExist, ValueError, TypeError):
            # Never leak another user's job existence — always 404 for non-owners.
            return fail("EXPORT_NOT_FOUND", "Export job not found.", status=status.HTTP_404_NOT_FOUND)

        body = {
            "job_id": str(job.id),
            "status": job.status,
            "created_at": job.created_at.isoformat(),
            "expires_at": job.expires_at.isoformat() if job.expires_at else None,
            "download_url": None,
        }
        if job.status == DataExportJob.Status.READY:
            if job.is_expired:
                body["status"] = DataExportJob.Status.EXPIRED
            else:
                body["download_url"] = signed_export_url(job)
        return ok(body)


class DataExportDownloadView(APIView):
    """P1-3 — serve the export ZIP through an authenticated, owner-checked view.

    The filesystem export backend (the default self-hosted deploy) has no served
    ``/media/`` path, so the previously-advertised signed URL 404'd. This streams
    the bytes only to the owner, only while the job is READY and unexpired."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Download a produced personal-data export (owner only)")
    def get(self, request, job_id):
        from django.http import FileResponse

        try:
            job = DataExportJob.objects.get(id=job_id, user=request.user)
        except (DataExportJob.DoesNotExist, ValueError, TypeError):
            return fail("EXPORT_NOT_FOUND", "Export job not found.", status=status.HTTP_404_NOT_FOUND)
        if job.status != DataExportJob.Status.READY or not job.file_key:
            return fail("EXPORT_NOT_READY", "Export is not ready.", status=status.HTTP_404_NOT_FOUND)
        if job.is_expired:
            return fail("EXPORT_EXPIRED", "This export has expired.", status=status.HTTP_410_GONE)
        try:
            fh = export_storage().open(job.file_key)
        except (FileNotFoundError, OSError):
            return fail("EXPORT_NOT_FOUND", "Export file is no longer available.",
                        status=status.HTTP_404_NOT_FOUND)
        resp = FileResponse(fh, content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="strattraderpro-export-{job.id}.zip"'
        return resp


# ---------------------------------------------------------------------------
# Account soft-delete
# ---------------------------------------------------------------------------
class AccountDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Schedule a 30-day soft account deletion", responses={200: None})
    def post(self, request):
        from django.utils import timezone

        user = request.user
        if user.pending_delete_at is not None:
            return ok({"pending_delete_at": user.pending_delete_at.isoformat(), "already_pending": True})

        user.pending_delete_at = timezone.now() + DELETE_WINDOW
        user.save(update_fields=["pending_delete_at"])
        DELETE_REQUESTS_TOTAL.labels(action="requested").inc()
        emit(
            "account.delete_requested",
            user=user, actor=user, entity_type="user", entity_id=str(user.id), request=request,
            metadata={"pending_delete_at": user.pending_delete_at.isoformat()},
        )
        try:
            _send_templated(
                to=user.email,
                subject="Your StratTraderPro account is scheduled for deletion",
                template_base="account_delete_requested",
                context={
                    "display_name": user.display_name,
                    "pending_delete_at": user.pending_delete_at.strftime("%Y-%m-%d"),
                },
            )
        except Exception:  # noqa: BLE001, S110 — email must not fail the request
            pass
        return ok({"pending_delete_at": user.pending_delete_at.isoformat()})


class AccountDeleteCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Cancel a pending account deletion", responses={200: None})
    def post(self, request):
        user = request.user
        if user.pending_delete_at is None:
            return fail("NO_PENDING_DELETE", "No pending deletion to cancel.", status=status.HTTP_409_CONFLICT)
        user.pending_delete_at = None
        user.save(update_fields=["pending_delete_at"])
        DELETE_REQUESTS_TOTAL.labels(action="cancelled").inc()
        emit(
            "account.delete_cancelled",
            user=user, actor=user, entity_type="user", entity_id=str(user.id), request=request,
        )
        return ok({"cancelled": True})


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------
class TermsCurrentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Current ToS/Privacy versions + whether the user must re-accept")
    def get(self, request):
        from .terms import acceptance_state

        return ok(acceptance_state(request.user))


class _TermsAcceptSerializer(serializers.Serializer):
    tos_version = serializers.CharField(max_length=32)
    privacy_version = serializers.CharField(max_length=32)


class TermsAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=_TermsAcceptSerializer, responses={200: None}, summary="Record Terms/Privacy acceptance")
    def post(self, request):
        from .terms import current_versions, record_acceptance

        ser = _TermsAcceptSerializer(data=request.data)
        if not ser.is_valid():
            return fail("INVALID", "tos_version and privacy_version are required.", status=400, details=ser.errors)

        cur = current_versions()
        tos = ser.validated_data["tos_version"]
        priv = ser.validated_data["privacy_version"]
        # Reject acceptance of a version that is not the current one (prevents
        # recording consent to a stale/forged version).
        if tos != cur["tos_version"] or priv != cur["privacy_version"]:
            return fail(
                "TERMS_VERSION_MISMATCH",
                "Submitted versions do not match the current Terms/Privacy.",
                status=status.HTTP_409_CONFLICT,
                details=cur,
            )
        record_acceptance(request.user, tos_version=tos, privacy_version=priv, ip=_client_ip(request))
        return ok({"accepted": True, **cur})
