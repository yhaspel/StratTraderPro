"""URL routes for the users app — mounted under /api/v1/."""
# allauth's stock Google OAuth views. We mount them at our own paths instead
# of using allauth's default urls.py so the callback URL exactly matches what
# we registered in Google Cloud Console.
from allauth.socialaccount.providers.google.views import (
    oauth2_callback as _allauth_google_oauth2_callback,
)
from allauth.socialaccount.providers.google.views import (
    oauth2_login as _allauth_google_oauth2_login,
)
from django.urls import path
from django.views.generic import RedirectView

from .onboarding import OnboardingStatusView
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
from .views_oauth import (
    OAuthExchangeView,
    OAuthGoogleStartView,
    OAuthPostCallbackView,
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

    # ---- M10.5 — onboarding checklist (auth-only, NOT MFA-gated) ----
    path("onboarding/status/", OnboardingStatusView.as_view(), name="onboarding-status"),

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

    # ---- M2.5 — Google OAuth ----
    # Our wrappers (custom JSON-friendly start, post-callback bridge, exchange)
    path("auth/oauth/google/start/", OAuthGoogleStartView.as_view(), name="auth-oauth-google-start"),
    path("auth/oauth/google/post-callback/", OAuthPostCallbackView.as_view(), name="auth-oauth-google-post-callback"),
    path("auth/oauth/exchange/", OAuthExchangeView.as_view(), name="auth-oauth-exchange"),
    # Allauth's stock callback view at the path we registered in GCP. The
    # name `google_callback` MUST match what allauth's provider expects when
    # it builds the redirect_uri (search-allauth-source for `google_callback`).
    # The `google_login` URL is also required: allauth's view resolves it
    # internally for the redirect_uri reverse-lookup, even though we never hit
    # it directly (our /start/ view drives it).
    path(
        "auth/oauth/google/callback/",
        _allauth_google_oauth2_callback,
        name="google_callback",
    ),
    path(
        "auth/oauth/google/login/",
        _allauth_google_oauth2_login,
        name="google_login",
    ),
    # Stub URL alias so allauth's bundled templates can resolve
    # `{% url 'account_login' %}` without crashing when they render error
    # pages. Redirects to our frontend login route. (Without this, OAuth
    # error paths blow up with NoReverseMatch.)
    path(
        "auth/account/login/",
        RedirectView.as_view(url="/login", query_string=True),
        name="account_login",
    ),
    # Same defensive alias for `account_signup` — referenced from the same
    # allauth templates.
    path(
        "auth/account/signup/",
        RedirectView.as_view(url="/register", query_string=True),
        name="account_signup",
    ),
]
