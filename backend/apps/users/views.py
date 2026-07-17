"""Auth views (M01 + M02)."""
from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.audit.events import AuthEventType as EventType

from . import services
from .cookies import clear_refresh_cookie, read_refresh, token_pair_response
from .metrics import (
    FAMILY_REVOCATIONS_TOTAL,
    LOGIN_TOTAL,
    PASSWORD_RESET_TOTAL,
    LoginResult,
    PasswordResetStep,
)
from .models import EmailVerificationToken, PasswordResetToken
from .responses import fail, ok
from .schema import (
    ERROR_EXAMPLES,
    CurrentUserEnvelopeSerializer,
    ErrorEnvelopeSerializer,
    RegisterOkEnvelopeSerializer,
    StatusEnvelopeSerializer,
    TokenPairEnvelopeSerializer,
)
from .serializers import (
    CurrentUserSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    RefreshSerializer,
    RegisterSerializer,
    ResendVerificationSerializer,
    VerifyEmailSerializer,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _email_keyer(group, request):
    """django-ratelimit key fn — limits per submitted email.

    C1: django-ratelimit wraps ``as_view()`` and calls this with the *raw*
    Django ``HttpRequest`` (before DRF wraps it), so ``request.data`` does not
    exist — reading it raised and every request collapsed into the single
    ``"anon"`` bucket, turning login/register/password-reset/resend into a
    5-requests-to-DoS-everyone surface. Parse the JSON body directly instead so
    each submitted email gets its own bucket.
    """
    try:
        email = (json.loads(request.body or b"{}") or {}).get("email", "")
    except (ValueError, TypeError, AttributeError):
        email = ""
    return (email or "").strip().lower() or "anon"


def _handle_validation(serializer):
    if serializer.is_valid():
        return None
    return fail(
        "VALIDATION_ERROR",
        "Invalid input.",
        status=status.HTTP_400_BAD_REQUEST,
        details=serializer.errors,
    )


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
class RegisterView(APIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    @extend_schema(
        operation_id="auth_register",
        tags=["auth"],
        summary="Register a new account",
        description=(
            "Creates a new user and sends a verification email. "
            "Duplicate emails return 202 with a generic body to prevent enumeration."
        ),
        request=RegisterSerializer,
        responses={
            201: RegisterOkEnvelopeSerializer,
            202: StatusEnvelopeSerializer,
            400: ErrorEnvelopeSerializer,
            429: ErrorEnvelopeSerializer,
        },
        examples=[
            OpenApiExample(
                "Register request",
                value={
                    "email": "trader@example.com",
                    "display_name": "Jane Trader",
                    "password": "correct horse battery staple",
                },
                request_only=True,
            ),
            ERROR_EXAMPLES["PASSWORD_WEAK"],
            ERROR_EXAMPLES["VALIDATION_ERROR"],
            ERROR_EXAMPLES["RATE_LIMITED"],
        ],
    )
    def post(self, request):
        if getattr(request, "limited", False):
            return fail("RATE_LIMITED", "Too many requests.", status=429, **_retry_after())

        ser = RegisterSerializer(data=request.data)
        bad = _handle_validation(ser)
        if bad:
            # Surface password-policy failures as PASSWORD_WEAK for clearer UX.
            if "password" in (ser.errors or {}):
                return fail(
                    "PASSWORD_WEAK",
                    "Password does not meet policy.",
                    status=400,
                    details=ser.errors,
                )
            return bad

        data = ser.validated_data
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=data["email"],
                    password=data["password"],
                    display_name=data["display_name"],
                )
        except IntegrityError:
            # Email enumeration mitigation: respond 202 generically.
            services.record_event(
                EventType.REGISTER,
                email=data["email"],
                request=request,
                metadata={"duplicate": True},
            )
            return ok({"status": "pending_verification"}, status=status.HTTP_202_ACCEPTED)

        token, raw = EmailVerificationToken.issue(user)
        services.send_verification_email(user, raw)
        services.record_event(
            EventType.REGISTER, user=user, request=request
        )
        return ok({"id": str(user.id), "email": user.email}, status=status.HTTP_201_CREATED)


# P2-3: stack a per-IP limit under the per-email one (mirroring LoginView) so one
# IP can't email-bomb by cycling addresses.
RegisterView = ratelimit(key=_email_keyer, rate="3/m", method="POST", block=False)(
    ratelimit(key="ip", rate="10/m", method="POST", block=False)(RegisterView.as_view())
)


# ---------------------------------------------------------------------------
# Verify email
# ---------------------------------------------------------------------------
class VerifyEmailView(APIView):
    permission_classes = [AllowAny]
    serializer_class = VerifyEmailSerializer

    @extend_schema(
        operation_id="auth_verify_email",
        tags=["auth"],
        summary="Verify email via token",
        description="Consumes the verification token and returns a JWT pair on success.",
        request=VerifyEmailSerializer,
        responses={200: TokenPairEnvelopeSerializer, 400: ErrorEnvelopeSerializer},
        examples=[
            OpenApiExample(
                "Verify request",
                value={"token": "uvv_6d2c...sample"},
                request_only=True,
            ),
            ERROR_EXAMPLES["TOKEN_INVALID"],
        ],
    )
    def post(self, request):
        ser = VerifyEmailSerializer(data=request.data)
        bad = _handle_validation(ser)
        if bad:
            return bad
        tok = EmailVerificationToken.consume(ser.validated_data["token"])
        if tok is None:
            return fail("TOKEN_INVALID", "Verification token is invalid or expired.", status=400)
        user = tok.user
        if not user.is_verified:
            user.is_verified = True
            user.save(update_fields=["is_verified", "updated_at"])
        services.record_event(
            EventType.VERIFY_EMAIL, user=user, request=request
        )
        return token_pair_response(services.issue_token_pair(user, request=request))


# ---------------------------------------------------------------------------
# Resend verification
# ---------------------------------------------------------------------------
class ResendVerificationView(APIView):
    permission_classes = [AllowAny]
    serializer_class = ResendVerificationSerializer

    @extend_schema(
        operation_id="auth_resend_verification",
        tags=["auth"],
        summary="Resend verification email",
        description=(
            "Idempotent. Returns 200 whether or not the address maps to an "
            "unverified account, to avoid email enumeration. Returns 503 "
            "EMAIL_SEND_FAILED only when the mail provider rejected a message we "
            "genuinely tried to send."
        ),
        request=ResendVerificationSerializer,
        responses={
            200: StatusEnvelopeSerializer,
            429: ErrorEnvelopeSerializer,
            503: ErrorEnvelopeSerializer,
        },
        examples=[
            OpenApiExample(
                "Resend request",
                value={"email": "trader@example.com"},
                request_only=True,
            ),
            ERROR_EXAMPLES["RATE_LIMITED"],
        ],
    )
    def post(self, request):
        if getattr(request, "limited", False):
            return fail("RATE_LIMITED", "Too many requests.", status=429, **_retry_after())
        ser = ResendVerificationSerializer(data=request.data)
        bad = _handle_validation(ser)
        if bad:
            return bad
        email = ser.validated_data["email"]
        user = User.objects.filter(email=email).first()
        if user and not user.is_verified:
            _, raw = EmailVerificationToken.issue(user)
            sent = services.send_verification_email(user, raw)
            services.record_event(
                EventType.RESEND_VERIFICATION,
                user=user,
                request=request,
                metadata={"sent": sent},
            )
            if not sent:
                # The provider REJECTED the message — no email exists, and telling
                # the user "ok" here is a lie they can only discover by waiting for
                # an email that will never arrive. Report it.
                #
                # Enumeration note: this reply is only reachable when the address
                # belongs to a real unverified account AND the provider is failing.
                # While the sender is healthy every caller still gets an identical
                # 200, so the enumeration guarantee holds in steady state; during a
                # provider outage we accept a narrow leak (rate-limited to 3/min per
                # address) in exchange for not lying to the user.
                return fail(
                    "EMAIL_SEND_FAILED",
                    "We couldn't send the verification email. Please try again shortly.",
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
        # Always 200 otherwise, to avoid email enumeration.
        return ok({"status": "ok"})


ResendVerificationView = ratelimit(key=_email_keyer, rate="3/m", method="POST", block=False)(
    ratelimit(key="ip", rate="10/m", method="POST", block=False)(ResendVerificationView.as_view())
)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class LoginView(APIView):
    permission_classes = [AllowAny]
    serializer_class = LoginSerializer

    @extend_schema(
        operation_id="auth_login",
        tags=["auth"],
        summary="Log in with email + password",
        description=(
            "Returns `{access, refresh, user, mfa_required}`. "
            "`mfa_required` is always false in M01 (MFA ships in M02)."
        ),
        request=LoginSerializer,
        responses={
            200: TokenPairEnvelopeSerializer,
            401: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            423: ErrorEnvelopeSerializer,
            429: ErrorEnvelopeSerializer,
        },
        examples=[
            OpenApiExample(
                "Login request",
                value={"email": "trader@example.com", "password": "correct horse battery staple"},
                request_only=True,
            ),
            ERROR_EXAMPLES["INVALID_CREDENTIALS"],
            ERROR_EXAMPLES["EMAIL_NOT_VERIFIED"],
            ERROR_EXAMPLES["ACCOUNT_LOCKED"],
            ERROR_EXAMPLES["RATE_LIMITED"],
        ],
    )
    def post(self, request):
        if getattr(request, "limited", False):
            LOGIN_TOTAL.labels(result=LoginResult.RATE_LIMITED).inc()
            return fail("RATE_LIMITED", "Too many requests.", status=429, **_retry_after())

        ser = LoginSerializer(data=request.data)
        bad = _handle_validation(ser)
        if bad:
            return bad

        email = ser.validated_data["email"]
        password = ser.validated_data["password"]
        # P2-4: the lockout is scoped to the requesting IP so a remote attacker
        # can't lock a victim out of their own (different) IP. The per-email 5/m
        # rate limit is the primary throttle (ADR-108).
        ip = services._client_ip(request)

        if services.is_locked(email, ip):
            services.record_event(
                EventType.LOGIN_FAIL, email=email, request=request,
                metadata={"reason": "locked"},
            )
            LOGIN_TOTAL.labels(result=LoginResult.LOCKED).inc()
            return fail(
                "ACCOUNT_LOCKED",
                "Account temporarily locked due to repeated failures.",
                status=423,
            )

        user = authenticate(request, username=email, password=password)
        if user is None:
            services.record_failed_login(email, request=request)
            services.record_event(
                EventType.LOGIN_FAIL, email=email, request=request,
                metadata={"reason": "invalid_credentials"},
            )
            # If this attempt just crossed the threshold, notify the user.
            if services.is_locked(email, ip):
                target = User.objects.filter(email=email).first()
                if target:
                    services.send_account_locked_email(target)
                services.record_event(
                    EventType.ACCOUNT_LOCKED, email=email, user=target, request=request,
                )
            LOGIN_TOTAL.labels(result=LoginResult.BAD_PASSWORD).inc()
            return fail("INVALID_CREDENTIALS", "Invalid email or password.", status=401)

        if not user.is_verified:
            services.record_event(
                EventType.LOGIN_FAIL, user=user, request=request,
                metadata={"reason": "unverified"},
            )
            LOGIN_TOTAL.labels(result=LoginResult.UNVERIFIED).inc()
            return fail(
                "EMAIL_NOT_VERIFIED",
                "Please verify your email before signing in.",
                status=403,
            )

        services.clear_failed_logins(email)

        # M02 — if MFA is enrolled, issue a short-lived mfa_token instead of
        # a full token pair. Client must POST it to /auth/mfa/verify/ with a
        # TOTP or backup code to complete login.
        if settings.MFA_ENABLED and user.mfa_enabled:
            from .mfa import issue_mfa_token  # local import to avoid M01 boot cost

            mfa_token = issue_mfa_token(user)
            services.record_event(
                EventType.LOGIN_OK,
                user=user,
                request=request,
                metadata={"mfa_required": True},
            )
            LOGIN_TOTAL.labels(result=LoginResult.OK).inc()
            return ok({"mfa_required": True, "mfa_token": mfa_token})

        pair = services.issue_token_pair(user, request=request)
        pair["mfa_required"] = False
        services.record_event(EventType.LOGIN_OK, user=user, request=request)
        LOGIN_TOTAL.labels(result=LoginResult.OK).inc()
        return token_pair_response(pair)


LoginView = ratelimit(key=_email_keyer, rate="5/m", method="POST", block=False)(
    ratelimit(key="ip", rate="20/m", method="POST", block=False)(LoginView.as_view())
)


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------
class RefreshView(APIView):
    permission_classes = [AllowAny]
    serializer_class = RefreshSerializer

    @extend_schema(
        operation_id="auth_refresh",
        tags=["auth"],
        summary="Rotate a refresh token",
        description=(
            "Consumes the supplied refresh token and issues a new pair in the same family. "
            "Reusing an already-rotated refresh revokes the whole family."
        ),
        request=RefreshSerializer,
        responses={200: TokenPairEnvelopeSerializer, 401: ErrorEnvelopeSerializer},
        examples=[
            OpenApiExample(
                "Refresh request",
                value={"refresh": "eyJhbGciOi...refresh.jwt"},
                request_only=True,
            ),
            ERROR_EXAMPLES["TOKEN_INVALID"],
        ],
    )
    def post(self, request):
        # P1-4: the browser sends the refresh via HttpOnly cookie (no body);
        # non-browser clients may still POST it in the body (read_refresh: body
        # wins, else cookie).
        raw = read_refresh(request)
        if not raw:
            return fail("TOKEN_INVALID", "No refresh token supplied.", status=401)
        try:
            pair = services.rotate_refresh(raw, request=request)
        except InvalidToken as exc:
            resp = fail("TOKEN_INVALID", str(exc) or "Invalid refresh token.", status=401)
            clear_refresh_cookie(resp)  # drop a now-dead cookie so the browser stops retrying it
            return resp
        return token_pair_response(pair)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
class LogoutView(APIView):
    permission_classes = [AllowAny]
    serializer_class = LogoutSerializer

    @extend_schema(
        operation_id="auth_logout",
        tags=["auth"],
        summary="Log out — revokes refresh family",
        request=LogoutSerializer,
        responses={200: StatusEnvelopeSerializer},
        examples=[
            OpenApiExample(
                "Logout request",
                value={"refresh": "eyJhbGciOi...refresh.jwt"},
                request_only=True,
            ),
        ],
    )
    def post(self, request):
        # Accept the refresh from cookie (browser) or body (API); revoke the
        # family and clear the cookie regardless.
        raw = read_refresh(request)
        if raw:
            services.revoke_refresh(raw, request=request)
        resp = ok({"status": "ok"})
        clear_refresh_cookie(resp)
        return resp


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
class PasswordResetView(APIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordResetSerializer

    @extend_schema(
        operation_id="auth_password_reset",
        tags=["auth"],
        summary="Request a password reset email",
        description="Always returns 200 to avoid email enumeration.",
        request=PasswordResetSerializer,
        responses={200: StatusEnvelopeSerializer, 429: ErrorEnvelopeSerializer},
        examples=[
            OpenApiExample(
                "Reset request",
                value={"email": "trader@example.com"},
                request_only=True,
            ),
            ERROR_EXAMPLES["RATE_LIMITED"],
        ],
    )
    def post(self, request):
        if getattr(request, "limited", False):
            return fail("RATE_LIMITED", "Too many requests.", status=429, **_retry_after())
        ser = PasswordResetSerializer(data=request.data)
        bad = _handle_validation(ser)
        if bad:
            return bad
        email = ser.validated_data["email"]
        user = User.objects.filter(email=email).first()
        if user:
            _, raw = PasswordResetToken.issue(user)
            services.send_password_reset_email(user, raw)
            services.record_event(
                EventType.PASSWORD_RESET_REQUESTED, user=user, request=request
            )
        # Increment unconditionally — incrementing only on `if user` would leak
        # email existence via metric volume; anti-enumeration applies here too.
        PASSWORD_RESET_TOTAL.labels(step=PasswordResetStep.REQUESTED).inc()
        return ok({"status": "ok"})


PasswordResetView = ratelimit(key=_email_keyer, rate="3/m", method="POST", block=False)(
    ratelimit(key="ip", rate="10/m", method="POST", block=False)(PasswordResetView.as_view())
)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer

    @extend_schema(
        operation_id="auth_password_reset_confirm",
        tags=["auth"],
        summary="Set a new password using the reset token",
        description="Issues a JWT pair on success and revokes any outstanding refresh families.",
        request=PasswordResetConfirmSerializer,
        responses={200: TokenPairEnvelopeSerializer, 400: ErrorEnvelopeSerializer},
        examples=[
            OpenApiExample(
                "Confirm request",
                value={"token": "prv_7a1c...sample", "password": "correct horse battery staple"},
                request_only=True,
            ),
            ERROR_EXAMPLES["TOKEN_INVALID"],
            ERROR_EXAMPLES["PASSWORD_WEAK"],
        ],
    )
    def post(self, request):
        ser = PasswordResetConfirmSerializer(data=request.data)
        if not ser.is_valid():
            if "password" in (ser.errors or {}):
                return fail(
                    "PASSWORD_WEAK", "Password does not meet policy.",
                    status=400, details=ser.errors,
                )
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        tok = PasswordResetToken.consume(ser.validated_data["token"])
        if tok is None:
            return fail("TOKEN_INVALID", "Reset token is invalid or expired.", status=400)
        user = tok.user
        user.set_password(ser.validated_data["password"])
        # Reset opens a verified session.
        if not user.is_verified:
            user.is_verified = True
        user.save()
        services.clear_failed_logins(user.email)
        # Revoke any outstanding refresh families — password changed.
        revoked_count = 0
        for fam in user.refresh_families.filter(revoked_at__isnull=True):
            fam.revoke(reason="password_reset")
            revoked_count += 1
        if revoked_count:
            FAMILY_REVOCATIONS_TOTAL.inc(revoked_count)
        services.record_event(
            EventType.PASSWORD_RESET_CONFIRMED, user=user, request=request
        )
        PASSWORD_RESET_TOTAL.labels(step=PasswordResetStep.CONFIRMED).inc()
        return token_pair_response(services.issue_token_pair(user, request=request))


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------
@extend_schema(
    operation_id="users_me",
    tags=["auth"],
    summary="Get the currently authenticated user",
    responses={200: CurrentUserEnvelopeSerializer, 401: ErrorEnvelopeSerializer},
)
class CurrentUserView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CurrentUserSerializer

    def get_object(self):
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        return ok(self.get_serializer(self.get_object()).data)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _retry_after():
    return {"Retry-After": "60"}
