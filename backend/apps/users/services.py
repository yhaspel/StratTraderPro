"""
Auth services: JWT issuance with family rotation, email sending, audit.

Kept separate from views so logic is unit-testable without HTTP.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .metrics import (
    FAMILY_REVOCATIONS_TOTAL,
    REFRESH_TOTAL,
    RefreshResult,
)
from .models import (
    AuthEvent,
    EmailVerificationToken,
    FailedLoginAttempt,
    PasswordResetToken,
    RefreshTokenFamily,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def record_event(
    event_type: str,
    *,
    user=None,
    email: str = "",
    request=None,
    metadata: Optional[dict] = None,
) -> AuthEvent:
    ip = ua = ""
    if request is not None:
        ip = _client_ip(request) or ""
        ua = (request.META.get("HTTP_USER_AGENT") or "")[:512]
    return AuthEvent.objects.create(
        user=user,
        email=email or (getattr(user, "email", "") or ""),
        event_type=event_type,
        ip=ip or None,
        user_agent=ua,
        metadata=metadata or {},
    )


def _client_ip(request) -> Optional[str]:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ---------------------------------------------------------------------------
# JWT issuance with family rotation
# ---------------------------------------------------------------------------
def issue_token_pair(user, *, family: Optional[RefreshTokenFamily] = None) -> dict:
    """Issue a fresh access+refresh pair. Creates a new family unless one is provided."""
    refresh = RefreshToken.for_user(user)
    if family is None:
        family = RefreshTokenFamily.objects.create(user=user, current_jti=str(refresh["jti"]))
    else:
        family.current_jti = str(refresh["jti"])
        family.save(update_fields=["current_jti"])
    refresh["family_id"] = str(family.family_id)
    # Re-mint access from the (now-mutated) refresh so claims line up.
    access = refresh.access_token
    access["email"] = user.email
    access["display_name"] = user.display_name
    access["is_verified"] = user.is_verified
    return {
        "access": str(access),
        "refresh": str(refresh),
        "user": serialize_user(user),
    }


def rotate_refresh(raw_refresh: str, *, request=None) -> dict:
    """
    Rotate a refresh token, returning a new pair. On reuse, revoke the family.

    Raises InvalidToken on any failure. The caller should map this to a 401.
    """
    try:
        token = RefreshToken(raw_refresh)
    except TokenError as exc:
        REFRESH_TOTAL.labels(result=RefreshResult.INVALID).inc()
        raise InvalidToken(str(exc)) from exc

    family_id = token.get("family_id")
    jti = str(token["jti"])
    user_id = token.get("user_id")
    if not family_id or not user_id:
        REFRESH_TOTAL.labels(result=RefreshResult.INVALID).inc()
        raise InvalidToken("Refresh token is missing required claims")

    try:
        family = RefreshTokenFamily.objects.select_related("user").get(family_id=family_id)
    except RefreshTokenFamily.DoesNotExist:
        REFRESH_TOTAL.labels(result=RefreshResult.INVALID).inc()
        raise InvalidToken("Unknown refresh token family")

    if family.is_revoked:
        record_event(
            AuthEvent.EventType.REFRESH_REUSE,
            user=family.user,
            request=request,
            metadata={"family_id": str(family.family_id), "reason": "already_revoked"},
        )
        REFRESH_TOTAL.labels(result=RefreshResult.FAMILY_REVOKED).inc()
        raise InvalidToken("Refresh token family revoked")

    if jti != family.current_jti:
        # Reuse detected — burn the entire family.
        family.revoke(reason="reuse_detected")
        record_event(
            AuthEvent.EventType.REFRESH_REUSE,
            user=family.user,
            request=request,
            metadata={"family_id": str(family.family_id), "presented_jti": jti},
        )
        record_event(
            AuthEvent.EventType.FAMILY_REVOKED,
            user=family.user,
            request=request,
            metadata={"family_id": str(family.family_id)},
        )
        REFRESH_TOTAL.labels(result=RefreshResult.REUSE_DETECTED).inc()
        FAMILY_REVOCATIONS_TOTAL.inc()
        raise InvalidToken("Refresh token reuse detected — family revoked")

    user = family.user
    if not user.is_active:
        REFRESH_TOTAL.labels(result=RefreshResult.INVALID).inc()
        raise InvalidToken("User inactive")

    pair = issue_token_pair(user, family=family)
    record_event(
        AuthEvent.EventType.REFRESH_OK,
        user=user,
        request=request,
        metadata={"family_id": str(family.family_id)},
    )
    REFRESH_TOTAL.labels(result=RefreshResult.OK).inc()
    return pair


def revoke_refresh(raw_refresh: str, *, request=None) -> bool:
    """Revoke the family backing this refresh token. Idempotent; returns True if action taken."""
    try:
        token = RefreshToken(raw_refresh)
    except TokenError:
        return False
    family_id = token.get("family_id")
    if not family_id:
        return False
    try:
        family = RefreshTokenFamily.objects.get(family_id=family_id)
    except RefreshTokenFamily.DoesNotExist:
        return False
    if family.is_revoked:
        return False
    family.revoke(reason="logout")
    record_event(
        AuthEvent.EventType.LOGOUT,
        user=family.user,
        request=request,
        metadata={"family_id": str(family.family_id)},
    )
    FAMILY_REVOCATIONS_TOTAL.inc()
    return True


# ---------------------------------------------------------------------------
# Lockout
# ---------------------------------------------------------------------------
def is_locked(email: str) -> bool:
    threshold = settings.AUTH_LOCKOUT_THRESHOLD
    window = timedelta(minutes=settings.AUTH_LOCKOUT_WINDOW_MINUTES)
    cutoff = timezone.now() - window
    return (
        FailedLoginAttempt.objects.filter(email=email, occurred_at__gte=cutoff).count()
        >= threshold
    )


def record_failed_login(email: str, request=None) -> None:
    FailedLoginAttempt.objects.create(email=email, ip=_client_ip(request) if request else None)


def clear_failed_logins(email: str) -> None:
    FailedLoginAttempt.objects.filter(email=email).delete()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def _send_templated(*, to: str, subject: str, template_base: str, context: dict) -> None:
    """
    Render and send a transactional email. Network failures (Resend down, 422
    on an unverified test-sender recipient, SMTP timeout, …) are LOGGED but
    NOT raised — the user-facing endpoint must not 500 just because the
    provider rejected delivery. The matching AuthEvent is still recorded by
    the caller so we can replay sends later if needed.
    """
    text = render_to_string(f"email/{template_base}.txt", context)
    html = render_to_string(f"email/{template_base}.html", context)
    msg = EmailMultiAlternatives(subject=subject, body=text, to=[to])
    msg.attach_alternative(html, "text/html")
    try:
        msg.send(fail_silently=False)
    except Exception:  # noqa: BLE001 — we genuinely want to swallow ALL errors here
        # structlog scrubber will redact `to` (matches `email`-like fields if
        # present), so this is safe to log even with PII rules in place.
        logger.exception(
            "transactional email send failed",
            extra={"template": template_base, "to": to},
        )


def send_verification_email(user, raw_token: str) -> None:
    link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={raw_token}"
    _send_templated(
        to=user.email,
        subject="Verify your StratTraderPro account",
        template_base="verify_email",
        context={"user": user, "link": link},
    )


def send_password_reset_email(user, raw_token: str) -> None:
    link = f"{settings.FRONTEND_BASE_URL}/password-reset/confirm?token={raw_token}"
    _send_templated(
        to=user.email,
        subject="Reset your StratTraderPro password",
        template_base="password_reset",
        context={"user": user, "link": link},
    )


def send_account_locked_email(user) -> None:
    _send_templated(
        to=user.email,
        subject="Your StratTraderPro account has been locked",
        template_base="account_locked",
        context={
            "user": user,
            "duration_minutes": settings.AUTH_LOCKOUT_DURATION_MINUTES,
        },
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize_user(user) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "is_verified": user.is_verified,
    }


# Re-export to keep imports tidy in views.
__all__ = [
    "issue_token_pair",
    "rotate_refresh",
    "revoke_refresh",
    "is_locked",
    "record_failed_login",
    "clear_failed_logins",
    "record_event",
    "send_verification_email",
    "send_password_reset_email",
    "send_account_locked_email",
    "serialize_user",
    "EmailVerificationToken",
    "PasswordResetToken",
]
