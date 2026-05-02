"""URL routes for the users app — mounted under /api/v1/."""
from django.urls import path

from .views import (
    CurrentUserView,
    LoginView,
    LogoutView,
    PasswordResetConfirmView,
    PasswordResetView,
    RefreshView,
    RegisterView,
    ResendVerificationView,
    VerifyEmailView,
)
from .views_m02 import (
    MFABackupRegenerateView,
    MFADisableView,
    MFAEnrollConfirmView,
    MFAEnrollView,
    MFAVerifyView,
    PasswordChangeView,
    ProfileUpdateView,
    SessionsListView,
    SessionsRevokeView,
)

# Note: several view symbols above are already function-views wrapped in
# ratelimit decorators (RegisterView, ResendVerificationView, LoginView,
# PasswordResetView, MFAVerifyView). Class-based views still need .as_view().
urlpatterns = [
    # ---- M01 ----
    path("auth/register/", RegisterView, name="auth-register"),
    path("auth/verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),
    path("auth/resend-verification/", ResendVerificationView, name="auth-resend-verification"),
    path("auth/login/", LoginView, name="auth-login"),
    path("auth/refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/password/reset/", PasswordResetView, name="auth-password-reset"),
    path(
        "auth/password/reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
    path("users/me/", CurrentUserView.as_view(), name="users-me"),

    # ---- M02 — MFA ----
    path("auth/mfa/enroll/", MFAEnrollView.as_view(), name="auth-mfa-enroll"),
    path("auth/mfa/enroll/confirm/", MFAEnrollConfirmView.as_view(), name="auth-mfa-enroll-confirm"),
    path("auth/mfa/verify/", MFAVerifyView, name="auth-mfa-verify"),
    path("auth/mfa/disable/", MFADisableView.as_view(), name="auth-mfa-disable"),
    path(
        "auth/mfa/backup-codes/regenerate/",
        MFABackupRegenerateView.as_view(),
        name="auth-mfa-backup-regenerate",
    ),

    # ---- M02 — profile, password change, sessions ----
    path("users/me/update/", ProfileUpdateView.as_view(), name="users-me-update"),
    path("users/me/password/", PasswordChangeView.as_view(), name="users-me-password"),
    path("users/me/sessions/", SessionsListView.as_view(), name="users-me-sessions"),
    path("users/me/sessions/revoke/", SessionsRevokeView.as_view(), name="users-me-sessions-revoke"),
]
