"""Impersonation-aware JWT authentication (M10 §6.2 / AC-10-7).

Set as the project-wide ``DEFAULT_AUTHENTICATION_CLASSES`` entry. The
write-block MUST live here, not in a global permission class: every mutating
view overrides ``permission_classes``, which would silently drop a
``DEFAULT_PERMISSION_CLASSES`` entry.

For an ``purpose="impersonation"`` token this authenticator:
  (a) loads the ``ImpersonationSession`` and rejects if ended/expired — so
      ``stop`` revokes immediately (session check, not just token expiry);
  (b) raises ``PermissionDenied`` for any non-SAFE_METHOD request (read-only);
  (c) attaches ``request.impersonation`` for downstream denies (admin routes,
      CSV export) and emits ``admin.impersonated_read`` exactly once per request.
"""
from __future__ import annotations

from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework_simplejwt.authentication import JWTAuthentication


class ImpersonationAwareJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        if token.get("purpose") != "impersonation":
            return result

        from apps.admin_portal.models import ImpersonationSession

        session = (
            ImpersonationSession.objects.select_related("actor", "target")
            .filter(id=token.get("session_id"))
            .first()
        )
        if session is None or not session.is_active:
            raise AuthenticationFailed(
                "Impersonation session has ended or expired.", code="impersonation_ended"
            )

        # Expose the session for downstream denies (IsAdminAndMFAEnforced, CSV).
        request.impersonation = session

        if request.method not in SAFE_METHODS:
            raise PermissionDenied("Impersonation is read-only.", code="IMPERSONATION_READONLY")

        # Audit exactly once per request (authenticate is memoized by DRF).
        from apps.audit.events import AuditEventType
        from apps.audit.services import emit

        emit(
            AuditEventType.ADMIN_IMPERSONATED_READ,
            actor=session.actor,
            user=user,
            request=request,
            entity_type="user",
            entity_id=str(user.id),
            data_after={
                "session_id": str(session.id),
                "method": request.method,
                "path": request.get_full_path()[:255],
            },
        )
        return user, token
