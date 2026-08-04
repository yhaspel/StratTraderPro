"""Custom DRF exception handler that wraps PermissionDenied into our
standard envelope ``{"error": {"code": ..., "message": ...}}``.

Particularly important for MFA gating: the IsAuthenticatedAndMFAEnforced
permission denies with message="MFA_REQUIRED", which we map to a
structured 403 with ``error.code == "MFA_REQUIRED"``.

Wired via ``REST_FRAMEWORK['EXCEPTION_HANDLER']`` in settings.
"""
from __future__ import annotations

from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler

_PERMISSION_CODE_MAP = {
    "MFA_REQUIRED": ("MFA_REQUIRED", "Multi-factor authentication is required."),
}


def custom_exception_handler(exc, context):
    response = drf_default_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, NotAuthenticated):
        return Response(
            {"error": {"code": "AUTH_REQUIRED", "message": "Authentication required."}},
            status=401,
        )
    if isinstance(exc, PermissionDenied):
        message = str(getattr(exc, "detail", "") or exc)
        code, friendly = _PERMISSION_CODE_MAP.get(message, ("FORBIDDEN", message or "Forbidden."))
        return Response(
            {"error": {"code": code, "message": friendly}},
            status=403,
        )

    # Default: keep DRF's structure but rewrap into our envelope, so all
    # error shapes are uniform.
    detail = response.data
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        return response
    return Response(
        {"error": {"code": "VALIDATION_ERROR", "message": "Request was rejected.", "details": detail}},
        status=response.status_code,
    )
