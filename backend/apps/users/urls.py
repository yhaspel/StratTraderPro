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

# Note: several view symbols above are already function-views wrapped in
# ratelimit decorators (RegisterView, ResendVerificationView, LoginView,
# PasswordResetView). Class-based views still need .as_view().
urlpatterns = [
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
]
