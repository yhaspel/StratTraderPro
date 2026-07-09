"""Envelope serializers + OpenAPI examples for auth endpoints (M01).

These exist solely to give drf-spectacular concrete shapes for each response
(instead of `dict`), so that the emitted schema is strong enough for
frontend type generation.

Error codes (per plan §9): USER_EXISTS, INVALID_CREDENTIALS, EMAIL_NOT_VERIFIED,
ACCOUNT_LOCKED, RATE_LIMITED, TOKEN_INVALID, TOKEN_EXPIRED, PASSWORD_WEAK,
VALIDATION_ERROR.
"""
from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, extend_schema_serializer
from rest_framework import serializers


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------
class ApiErrorSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable machine-readable error code.")
    message = serializers.CharField()
    details = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        required=False,
        help_text="Optional field→messages map for validation errors.",
    )


class ErrorEnvelopeSerializer(serializers.Serializer):
    error = ApiErrorSerializer()


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------
class AuthUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    display_name = serializers.CharField()
    is_verified = serializers.BooleanField()
    mfa_enabled = serializers.BooleanField(required=False)
    # M10 — the frontend adminGuard reads is_staff off the login token-pair payload.
    is_staff = serializers.BooleanField(required=False)


class RegisterDataSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()


class StatusDataSerializer(serializers.Serializer):
    status = serializers.CharField()


class TokenPairDataSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = AuthUserSerializer()
    mfa_required = serializers.BooleanField(required=False)


# ---------------------------------------------------------------------------
# Response envelopes (per-endpoint)
# ---------------------------------------------------------------------------
@extend_schema_serializer(
    examples=[
        OpenApiExample(
            "Registration accepted",
            value={
                "data": {
                    "id": "6f2e5a1d-0c9b-4b4e-8d6a-111111111111",
                    "email": "trader@example.com",
                },
            },
            response_only=True,
            status_codes=["201"],
        ),
        OpenApiExample(
            "Duplicate email (anti-enumeration)",
            value={"data": {"status": "pending_verification"}},
            response_only=True,
            status_codes=["202"],
        ),
    ]
)
class RegisterOkEnvelopeSerializer(serializers.Serializer):
    data = RegisterDataSerializer()


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            "Login success",
            value={
                "data": {
                    "access": "eyJhbGciOi...access.jwt",
                    "refresh": "eyJhbGciOi...refresh.jwt",
                    "user": {
                        "id": "6f2e5a1d-0c9b-4b4e-8d6a-111111111111",
                        "email": "trader@example.com",
                        "display_name": "Jane Trader",
                        "is_verified": True,
                    },
                    "mfa_required": False,
                },
            },
            response_only=True,
            status_codes=["200"],
        ),
    ]
)
class TokenPairEnvelopeSerializer(serializers.Serializer):
    data = TokenPairDataSerializer()


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            "Status ok",
            value={"data": {"status": "ok"}},
            response_only=True,
            status_codes=["200"],
        ),
    ]
)
class StatusEnvelopeSerializer(serializers.Serializer):
    data = StatusDataSerializer()


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            "Current user",
            value={
                "data": {
                    "id": "6f2e5a1d-0c9b-4b4e-8d6a-111111111111",
                    "email": "trader@example.com",
                    "display_name": "Jane Trader",
                    "is_verified": True,
                    "created_at": "2026-04-17T12:00:00Z",
                },
            },
            response_only=True,
            status_codes=["200"],
        ),
    ]
)
class CurrentUserEnvelopeSerializer(serializers.Serializer):
    class _CurrentUserData(serializers.Serializer):
        id = serializers.UUIDField()
        email = serializers.EmailField()
        display_name = serializers.CharField()
        is_verified = serializers.BooleanField()
        created_at = serializers.DateTimeField()

    data = _CurrentUserData()


# ---------------------------------------------------------------------------
# Shared error examples (re-used via OpenApiExample in views)
# ---------------------------------------------------------------------------
ERROR_EXAMPLES = {
    "INVALID_CREDENTIALS": OpenApiExample(
        "Invalid credentials",
        value={"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password."}},
        response_only=True,
        status_codes=["401"],
    ),
    "EMAIL_NOT_VERIFIED": OpenApiExample(
        "Email not verified",
        value={"error": {"code": "EMAIL_NOT_VERIFIED", "message": "Please verify your email before signing in."}},
        response_only=True,
        status_codes=["403"],
    ),
    "ACCOUNT_LOCKED": OpenApiExample(
        "Account locked",
        value={"error": {"code": "ACCOUNT_LOCKED", "message": "Account temporarily locked due to repeated failures."}},
        response_only=True,
        status_codes=["423"],
    ),
    "RATE_LIMITED": OpenApiExample(
        "Rate limited",
        value={"error": {"code": "RATE_LIMITED", "message": "Too many requests."}},
        response_only=True,
        status_codes=["429"],
    ),
    "TOKEN_INVALID": OpenApiExample(
        "Token invalid or expired",
        value={"error": {"code": "TOKEN_INVALID", "message": "Token is invalid or expired."}},
        response_only=True,
        status_codes=["400", "401"],
    ),
    "PASSWORD_WEAK": OpenApiExample(
        "Password does not meet policy",
        value={
            "error": {
                "code": "PASSWORD_WEAK",
                "message": "Password does not meet policy.",
                "details": {"password": ["This password is too common."]},
            },
        },
        response_only=True,
        status_codes=["400"],
    ),
    "VALIDATION_ERROR": OpenApiExample(
        "Validation error",
        value={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid input.",
                "details": {"email": ["Enter a valid email address."]},
            },
        },
        response_only=True,
        status_codes=["400"],
    ),
}
