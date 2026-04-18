"""Auth views (M01)."""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction
from django_ratelimit.decorators import ratelimit
from django_ratelimit.exceptions import Ratelimited
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken

from . import services
from .models import AuthEvent, EmailVerificationToken, PasswordResetToken
from .responses import fail, ok
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
    """django-ratelimit key fn — limits per submitted email when present."""
    try:
        return (request.data or {}).get("email", "") or "anon"
    except Exception:
        return "anon"


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

    @extend_schema(request=RegisterSerializer, responses={201: dict, 409: dict})
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
                AuthEvent.EventType.REGISTER,
                email=data["email"],
                request=request,
                metadata={"duplicate": True},
            )
            return ok({"status": "pending_verification"}, status=status.HTTP_202_ACCEPTED)

        token, raw = EmailVerificationToken.issue(user)
        services.send_verification_email(user, raw)
        services.record_event(
            AuthEvent.EventType.REGISTER, user=user, request=request
        )
        return ok({"id": str(user.id), "email": user.email}, status=status.HTTP_201_CREATED)


RegisterView = ratelimit(key=_email_keyer, rate="3/m", method="POST", block=False)(RegisterView.as_view())


# ---------------------------------------------------------------------------
# Verify email
# ---------------------------------------------------------------------------
class VerifyEmailView(APIView):
    permission_classes = [AllowAny]
    serializer_class = VerifyEmailSerializer

    @extend_schema(request=VerifyEmailSerializer, responses={200: dict, 400: dict})
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
            AuthEvent.EventType.VERIFY_EMAIL, user=user, request=request
        )
        return ok(services.issue_token_pair(user))


# ---------------------------------------------------------------------------
# Resend verification
# ---------------------------------------------------------------------------
class ResendVerificationView(APIView):
    permission_classes = [AllowAny]
    serializer_class = ResendVerificationSerializer

    @extend_schema(request=ResendVerificationSerializer, responses={200: dict})
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
            services.send_verification_email(user, raw)
            services.record_event(
                AuthEvent.EventType.RESEND_VERIFICATION, user=user, request=request
            )
        # Always 200 to avoid email enumeration.
        return ok({"status": "ok"})


ResendVerificationView = ratelimit(key=_email_keyer, rate="3/m", method="POST", block=False)(
    ResendVerificationView.as_view()
)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class LoginView(APIView):
    permission_classes = [AllowAny]
    serializer_class = LoginSerializer

    @extend_schema(request=LoginSerializer, responses={200: dict, 401: dict, 403: dict, 423: dict, 429: dict})
    def post(self, request):
        if getattr(request, "limited", False):
            return fail("RATE_LIMITED", "Too many requests.", status=429, **_retry_after())

        ser = LoginSerializer(data=request.data)
        bad = _handle_validation(ser)
        if bad:
            return bad

        email = ser.validated_data["email"]
        password = ser.validated_data["password"]

        if services.is_locked(email):
            services.record_event(
                AuthEvent.EventType.LOGIN_FAIL, email=email, request=request,
                metadata={"reason": "locked"},
            )
            return fail(
                "ACCOUNT_LOCKED",
                "Account temporarily locked due to repeated failures.",
                status=423,
            )

        user = authenticate(request, username=email, password=password)
        if user is None:
            services.record_failed_login(email, request=request)
            services.record_event(
                AuthEvent.EventType.LOGIN_FAIL, email=email, request=request,
                metadata={"reason": "invalid_credentials"},
            )
            # If this attempt just crossed the threshold, notify the user.
            if services.is_locked(email):
                target = User.objects.filter(email=email).first()
                if target:
                    services.send_account_locked_email(target)
                services.record_event(
                    AuthEvent.EventType.ACCOUNT_LOCKED, email=email, user=target, request=request,
                )
            return fail("INVALID_CREDENTIALS", "Invalid email or password.", status=401)

        if not user.is_verified:
            services.record_event(
                AuthEvent.EventType.LOGIN_FAIL, user=user, request=request,
                metadata={"reason": "unverified"},
            )
            return fail(
                "EMAIL_NOT_VERIFIED",
                "Please verify your email before signing in.",
                status=403,
            )

        services.clear_failed_logins(email)
        pair = services.issue_token_pair(user)
        # MFA placeholder field per plan §6.2 — always false in M01.
        pair["mfa_required"] = False
        services.record_event(AuthEvent.EventType.LOGIN_OK, user=user, request=request)
        return ok(pair)


LoginView = ratelimit(key=_email_keyer, rate="5/m", method="POST", block=False)(
    ratelimit(key="ip", rate="20/m", method="POST", block=False)(LoginView.as_view())
)


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------
class RefreshView(APIView):
    permission_classes = [AllowAny]
    serializer_class = RefreshSerializer

    @extend_schema(request=RefreshSerializer, responses={200: dict, 401: dict})
    def post(self, request):
        ser = RefreshSerializer(data=request.data)
        bad = _handle_validation(ser)
        if bad:
            return bad
        try:
            pair = services.rotate_refresh(ser.validated_data["refresh"], request=request)
        except InvalidToken as exc:
            return fail("TOKEN_INVALID", str(exc) or "Invalid refresh token.", status=401)
        return ok(pair)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
class LogoutView(APIView):
    permission_classes = [AllowAny]
    serializer_class = LogoutSerializer

    @extend_schema(request=LogoutSerializer, responses={200: dict})
    def post(self, request):
        ser = LogoutSerializer(data=request.data)
        bad = _handle_validation(ser)
        if bad:
            return bad
        services.revoke_refresh(ser.validated_data["refresh"], request=request)
        return ok({"status": "ok"})


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
class PasswordResetView(APIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordResetSerializer

    @extend_schema(request=PasswordResetSerializer, responses={200: dict})
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
                AuthEvent.EventType.PASSWORD_RESET_REQUESTED, user=user, request=request
            )
        return ok({"status": "ok"})


PasswordResetView = ratelimit(key=_email_keyer, rate="3/m", method="POST", block=False)(
    PasswordResetView.as_view()
)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: dict, 400: dict})
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
        for fam in user.refresh_families.filter(revoked_at__isnull=True):
            fam.revoke(reason="password_reset")
        services.record_event(
            AuthEvent.EventType.PASSWORD_RESET_CONFIRMED, user=user, request=request
        )
        return ok(services.issue_token_pair(user))


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------
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
