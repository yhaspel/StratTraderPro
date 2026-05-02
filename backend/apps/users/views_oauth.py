"""
M2.5 — Google OAuth views.

Three endpoints expose the OAuth flow to the frontend:

    GET  /api/v1/auth/oauth/google/start/
        Returns the Google authorize URL the frontend should redirect to.
        We use allauth's stock Google login view internally (which generates
        the state token and stores it in session), but we wrap it so the
        response is JSON instead of an HTTP 302.

    GET  /api/v1/auth/oauth/google/callback/
        Google redirects back here with `code` + `state`. Allauth's stock
        callback view runs first (validates state, exchanges code, fetches
        userinfo, runs our SocialAdapter, creates/links User and SocialAccount).
        Allauth then redirects to ``LOGIN_REDIRECT_URL`` =
        ``/api/v1/auth/oauth/google/post-callback/`` — handled by
        :class:`OAuthPostCallbackView` below — where we hijack the request,
        issue our exchange code, and 302 the user to the frontend with
        ``?exchange=<code>`` in the URL.

    POST /api/v1/auth/oauth/exchange/
        Frontend POSTs the exchange code; we swap it for our normal
        ``{access, refresh, user}`` token pair, OR ``{mfa_required, mfa_token}``
        if the user has MFA enabled. Code is single-use and ``OAUTH_EXCHANGE_TTL_MINUTES``
        seconds long.

The exchange-code pattern keeps the JWT pair off the redirect URL — JWTs in
URL fragments leak through referer headers, server logs, and browser history.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model, logout as django_logout
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from . import services
from .metrics_oauth import (
    OAUTH_EXCHANGE_TOTAL,
    OAUTH_LOGIN_TOTAL,
    OAuthExchangeResult,
    OAuthLoginResult,
)
from .models import AuthEvent, OAuthExchangeCode
from .responses import fail, ok
from .serializers import OAuthExchangeSerializer

User = get_user_model()


def _feature_disabled_response():
    return fail(
        "FEATURE_DISABLED",
        "Google sign-in is currently disabled.",
        status=503,
    )


# ---------------------------------------------------------------------------
# 1. Start — return the authorize URL for the frontend
# ---------------------------------------------------------------------------
class OAuthGoogleStartView(APIView):
    """
    GET /api/v1/auth/oauth/google/start/

    302s to Google's authorize URL via allauth's stock ``oauth2_login`` view.
    The frontend does ``window.location.assign('.../start/')`` — a top-level
    navigation, NOT an XHR. This is critical: the browser sets the session
    cookie that allauth uses to stash the OAuth state token, and that cookie
    must travel back when Google redirects to our /callback/. A cross-origin
    XHR followed by ``window.location`` drops that cookie and the callback
    rejects with ``PermissionDenied`` from ``verify_and_unstash_state``.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="auth_oauth_google_start",
        tags=["oauth"],
        summary="Redirect the browser to Google's OAuth authorize URL.",
    )
    def get(self, request):
        if not settings.GOOGLE_OAUTH_ENABLED or not settings.GOOGLE_OAUTH_CLIENT_ID:
            return _feature_disabled_response()

        from allauth.socialaccount.providers.oauth2.client import OAuth2Error
        from allauth.socialaccount.providers.google.views import oauth2_login

        try:
            return oauth2_login(request)
        except OAuth2Error as exc:
            return fail("OAUTH_START_FAILED", str(exc), status=502)


# ---------------------------------------------------------------------------
# 2. Post-callback — runs after allauth's stock callback handled state + user
# ---------------------------------------------------------------------------
class OAuthPostCallbackView(APIView):
    """
    Internal: ``LOGIN_REDIRECT_URL`` points here. Hit by allauth after a
    successful Google callback (User created/linked, Django session login
    happened). We immediately tear down the session login (we don't use
    Django sessions) and 302 the browser to the frontend with our
    single-use exchange code.

    Failure mode: if we get here without an authenticated user, allauth's
    callback failed silently (rare). Send the user to the frontend with
    ``?error=oauth_failed``.
    """

    permission_classes = [AllowAny]
    http_method_names = ["get"]

    @extend_schema(exclude=True)
    def get(self, request):
        user = request.user if request.user.is_authenticated else None

        # Always tear down the Django session — we never want stateful
        # session login leaking out of the OAuth machinery.
        django_logout(request)

        frontend_callback = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/oauth/callback"

        if user is None:
            services.record_event(
                AuthEvent.EventType.OAUTH_EXCHANGE_FAIL,
                request=request,
                metadata={"reason": "no_authenticated_user_post_callback"},
            )
            OAUTH_LOGIN_TOTAL.labels(result=OAuthLoginResult.FAIL).inc()
            return redirect(f"{frontend_callback}?error=oauth_failed")

        # Detect first-time-user vs returning-user vs linked-existing-user by
        # comparing User.created_at to "now" and checking if a SocialAccount
        # was just created. We can read the SocialAccount via the related set.
        from allauth.socialaccount.models import SocialAccount
        sa = SocialAccount.objects.filter(user=user, provider="google").first()
        is_new_user = (
            user.created_at is not None
            and (services._now_microsec_diff(user.created_at) < 30_000_000)  # within 30s
        )
        is_newly_linked = (
            sa is not None
            and (services._now_microsec_diff(sa.date_joined) < 30_000_000)
            and not is_new_user
        )

        if is_new_user:
            services.record_event(
                AuthEvent.EventType.OAUTH_USER_CREATED,
                user=user, request=request,
                metadata={"provider": "google"},
            )
            services.send_oauth_account_created_email(user)
        elif is_newly_linked:
            services.record_event(
                AuthEvent.EventType.OAUTH_LINKED,
                user=user, request=request,
                metadata={"provider": "google"},
            )
            services.send_oauth_account_linked_email(user)

        services.record_event(
            AuthEvent.EventType.OAUTH_LOGIN_OK,
            user=user, request=request,
            metadata={"provider": "google"},
        )
        OAUTH_LOGIN_TOTAL.labels(result=OAuthLoginResult.OK).inc()

        # Mint single-use exchange code, redirect to frontend with it.
        _row, raw_code = OAuthExchangeCode.issue(user, provider="google")
        return redirect(f"{frontend_callback}?exchange={raw_code}")


# ---------------------------------------------------------------------------
# 3. Exchange — frontend POSTs the code, gets tokens or MFA challenge
# ---------------------------------------------------------------------------
class OAuthExchangeView(APIView):
    """
    POST /api/v1/auth/oauth/exchange/

    Body: ``{"exchange": "<code>"}``
    Returns either:
      * ``{"access": "...", "refresh": "...", "user": {...}}`` — same as login
      * ``{"mfa_required": true, "mfa_token": "..."}`` — MFA-enrolled user

    The exchange code is consumed (single-use) regardless of whether the
    response includes tokens or an MFA challenge — the user proceeds to
    /auth/mfa/verify/ with the mfa_token to complete login.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="auth_oauth_exchange",
        tags=["oauth"],
        summary="Swap an OAuth exchange code for a JWT pair (or MFA challenge).",
    )
    def post(self, request):
        if not settings.GOOGLE_OAUTH_ENABLED:
            return _feature_disabled_response()

        ser = OAuthExchangeSerializer(data=request.data)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)

        user = OAuthExchangeCode.consume(ser.validated_data["exchange"])
        if user is None:
            services.record_event(
                AuthEvent.EventType.OAUTH_EXCHANGE_FAIL,
                request=request,
                metadata={"reason": "invalid_or_expired_code"},
            )
            OAUTH_EXCHANGE_TOTAL.labels(result=OAuthExchangeResult.INVALID).inc()
            return fail("EXCHANGE_INVALID", "OAuth exchange code is invalid or expired.", status=401)

        if not user.is_active:
            OAUTH_EXCHANGE_TOTAL.labels(result=OAuthExchangeResult.INVALID).inc()
            return fail("EXCHANGE_INVALID", "User is not active.", status=401)

        # M02 MFA gate — Google login proves email control, not second-factor
        # ownership. Trading-touching scopes still demand TOTP.
        if settings.MFA_ENABLED and user.mfa_enabled:
            from .mfa import issue_mfa_token

            mfa_token = issue_mfa_token(user)
            services.record_event(
                AuthEvent.EventType.OAUTH_EXCHANGE_OK,
                user=user, request=request,
                metadata={"mfa_required": True},
            )
            OAUTH_EXCHANGE_TOTAL.labels(result=OAuthExchangeResult.MFA_REQUIRED).inc()
            return ok({"mfa_required": True, "mfa_token": mfa_token})

        services.record_event(
            AuthEvent.EventType.OAUTH_EXCHANGE_OK,
            user=user, request=request,
            metadata={"mfa_required": False},
        )
        OAUTH_EXCHANGE_TOTAL.labels(result=OAuthExchangeResult.OK).inc()
        pair = services.issue_token_pair(user, request=request)
        pair["mfa_required"] = False
        return ok(pair)
