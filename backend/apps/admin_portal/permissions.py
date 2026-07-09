"""Admin-portal permission (M10 §6.2 / AC-10-4).

``IsAdminAndMFAEnforced`` requires — unconditionally (not gated on a view's
``mfa_required`` attribute like the M02 base class) — an authenticated,
MFA-enrolled staff user that is NOT on an impersonation token. Anonymous → 401,
everything else that fails → 403 (DRF maps this via the authenticator state).
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission


class IsAdminAndMFAEnforced(BasePermission):
    message = "Admin access requires a staff account with MFA enrolled."
    code = "FORBIDDEN"

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        # Impersonation tokens never reach the admin surface.
        if getattr(request, "impersonation", None) is not None:
            return False
        if not user.is_staff:
            return False
        if not getattr(user, "mfa_enabled", False):
            return False
        return True
