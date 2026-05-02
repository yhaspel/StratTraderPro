"""DRF permission classes (M02).

``IsAuthenticatedAndMFAEnforced`` — pass iff the request is authenticated
AND, for views that opt in via ``mfa_required = True``, the authenticated
user has an active MFA device. Returns 403 with code ``MFA_REQUIRED``
otherwise. See plan §6.3.

Views opt in by setting a class attribute::

    class BrokerViewSet(viewsets.ModelViewSet):
        permission_classes = [IsAuthenticatedAndMFAEnforced]
        mfa_required = True

Existing views that don't set ``mfa_required`` behave exactly like
``IsAuthenticated`` (default False).
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission


class IsAuthenticatedAndMFAEnforced(BasePermission):
    """Permission: authenticated + MFA-active for views with ``mfa_required = True``."""

    message = "MFA is required for this endpoint."
    code = "MFA_REQUIRED"

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if getattr(view, "mfa_required", False) and not user.mfa_enabled:
            # Surface the structured error code via a standard attribute that
            # the global exception handler picks up. See ExceptionHandler in
            # apps.users.exception_handler (TBD M03 — for now the auth
            # default handler returns 403 with our message).
            self.message = "MFA_REQUIRED"
            return False
        return True
