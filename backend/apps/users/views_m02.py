"""M02 — MFA, profile, sessions, password change views.

Mounted by apps/users/urls.py under /api/v1/. Reuses helpers and the
response envelope from M01 views.

Routes added:
    POST /auth/mfa/enroll/                    -> { qr_png_b64, secret_b32 }
    POST /auth/mfa/enroll/confirm/            -> { backup_codes[] }
    POST /auth/mfa/verify/                    -> { access, refresh, user }
    POST /auth/mfa/disable/                   -> { status: 'ok' }
    POST /auth/mfa/backup-codes/regenerate/   -> { backup_codes[] }
    GET  /users/me/                           -> user + profile (extended)
    PATCH /users/me/                          -> profile update
    POST /users/me/password/                  -> change password
    GET  /users/me/sessions/                  -> active refresh families
    POST /users/me/sessions/revoke/           -> revoke one or all
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.audit.events import AuthEventType as EventType

from . import services
from .metrics_m02 import (
    MFA_BACKUP_USED_TOTAL,
    MFA_CHALLENGE_FAILURES_TOTAL,
    MFA_ENROLLMENTS_TOTAL,
    MFA_VERIFICATIONS_TOTAL,
    MFAVerifyResult,
)
from .mfa import (
    build_provisioning_uri,
    consume_backup_code,
    decode_mfa_token,
    decrypt_secret,
    encrypt_secret,
    generate_backup_codes,
    generate_totp_secret,
    render_qr_png_b64,
    verify_totp,
)
from .models import MFADevice, RefreshTokenFamily, UserProfile
from .responses import fail, ok
from .serializers import (
    MFABackupRegenerateSerializer,
    MFADisableSerializer,
    MFAEnrollConfirmSerializer,
    MFAVerifySerializer,
    PasswordChangeSerializer,
    ProfileUpdateSerializer,
    SessionRevokeSerializer,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _retry_after():
    return {"Retry-After": "60"}


def _mfa_disabled_response():
    return fail("FEATURE_DISABLED", "MFA is currently disabled by ops.", status=503)


def _validation_fail(serializer):
    return fail(
        "VALIDATION_ERROR", "Invalid input.", status=400, details=serializer.errors,
    )


def _current_family_jti(request) -> str | None:
    """Pull the family_id of the access-token in use, so the sessions list
    can mark the entry that issued *this* request."""
    auth = getattr(request, "auth", None)
    if auth is None:
        return None
    return auth.get("family_id") if hasattr(auth, "get") else None


# ---------------------------------------------------------------------------
# MFA — enroll
# ---------------------------------------------------------------------------
class MFAEnrollView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_mfa_enroll",
        tags=["mfa"],
        summary="Begin TOTP enrollment",
        description="Generate (or replace) a pending MFA device. Returns "
        "the QR PNG (base64) + raw secret. Confirm via /enroll/confirm/.",
    )
    def post(self, request):
        if not settings.MFA_ENABLED:
            return _mfa_disabled_response()

        user = request.user
        if user.mfa_enabled:
            return fail(
                "MFA_ALREADY_ENABLED",
                "MFA is already enabled. Disable it before re-enrolling.",
                status=400,
            )

        secret = generate_totp_secret()
        uri = build_provisioning_uri(secret, account_name=user.email)
        qr_b64 = render_qr_png_b64(uri)

        # Replace any unverified leftover device.
        MFADevice.objects.filter(user=user, verified=False).delete()
        MFADevice.objects.create(
            user=user,
            secret_encrypted=encrypt_secret(secret),
            verified=False,
        )

        return ok({"secret_b32": secret, "qr_png_b64": qr_b64, "otpauth_uri": uri})


class MFAEnrollConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_mfa_enroll_confirm",
        tags=["mfa"],
        summary="Confirm TOTP enrollment with a verification code",
    )
    def post(self, request):
        if not settings.MFA_ENABLED:
            return _mfa_disabled_response()

        ser = MFAEnrollConfirmSerializer(data=request.data)
        if not ser.is_valid():
            return _validation_fail(ser)

        user = request.user
        device = MFADevice.objects.filter(user=user).first()
        if device is None:
            return fail("MFA_NOT_STARTED", "Start enrollment via /enroll/ first.", status=400)
        if device.verified:
            return fail(
                "MFA_ALREADY_ENABLED", "MFA is already enabled.", status=400,
            )

        secret = decrypt_secret(device.secret_encrypted)
        if not verify_totp(secret, ser.validated_data["code"]):
            MFA_CHALLENGE_FAILURES_TOTAL.inc()
            services.record_event(
                EventType.MFA_CHALLENGE_FAIL,
                user=user, request=request, metadata={"phase": "enroll"},
            )
            return fail("MFA_CODE_INVALID", "TOTP code is invalid.", status=400)

        device.verified = True
        device.enrolled_at = timezone.now()
        device.save(update_fields=["verified", "enrolled_at", "updated_at"])

        codes = generate_backup_codes(user)
        MFA_ENROLLMENTS_TOTAL.inc()
        services.record_event(
            EventType.MFA_ENROLLED, user=user, request=request,
        )
        services.send_mfa_enabled_email(user)
        return ok({"backup_codes": codes})


# ---------------------------------------------------------------------------
# MFA — verify (login completion)
# ---------------------------------------------------------------------------
class MFAVerifyView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="auth_mfa_verify",
        tags=["mfa"],
        summary="Complete MFA challenge — exchange mfa_token + code for tokens",
    )
    def post(self, request):
        if not settings.MFA_ENABLED:
            return _mfa_disabled_response()
        if getattr(request, "limited", False):
            return fail("RATE_LIMITED", "Too many attempts.", status=429, **_retry_after())

        ser = MFAVerifySerializer(data=request.data)
        if not ser.is_valid():
            return _validation_fail(ser)

        try:
            user_id = decode_mfa_token(ser.validated_data["mfa_token"])
        except InvalidToken as exc:
            return fail("TOKEN_INVALID", str(exc) or "MFA token invalid or expired.", status=401)

        try:
            user = User.objects.select_related("mfa_device").get(pk=user_id)
        except User.DoesNotExist:
            return fail("TOKEN_INVALID", "MFA token references unknown user.", status=401)

        if not user.is_active or not user.mfa_enabled:
            return fail("TOKEN_INVALID", "User cannot complete MFA.", status=401)

        code = ser.validated_data["code"]
        is_backup = ser.validated_data.get("is_backup_code", False)

        if is_backup:
            ok_code = consume_backup_code(user, code)
            if ok_code:
                MFA_BACKUP_USED_TOTAL.inc()
                services.record_event(
                    EventType.BACKUP_CODE_USED, user=user, request=request,
                )
        else:
            secret = decrypt_secret(user.mfa_device.secret_encrypted)
            ok_code = verify_totp(secret, code)

        if not ok_code:
            MFA_VERIFICATIONS_TOTAL.labels(result=MFAVerifyResult.FAIL).inc()
            MFA_CHALLENGE_FAILURES_TOTAL.inc()
            services.record_event(
                EventType.MFA_CHALLENGE_FAIL,
                user=user, request=request,
                metadata={"phase": "login", "kind": "backup" if is_backup else "totp"},
            )
            return fail("MFA_CODE_INVALID", "Code is invalid or already used.", status=401)

        MFA_VERIFICATIONS_TOTAL.labels(result=MFAVerifyResult.OK).inc()
        services.record_event(
            EventType.MFA_CHALLENGE_OK,
            user=user, request=request,
            metadata={"kind": "backup" if is_backup else "totp"},
        )
        return ok(services.issue_token_pair(user, request=request))


# django-ratelimit wraps the view BEFORE DRF, so the key fn receives a raw
# Django ASGIRequest — `request.data` (a DRF-only attribute) doesn't exist
# yet and accessing it raises AttributeError, crashing every MFA verify
# attempt with a 500. (Pre-existing M02 bug — masked in tests because
# RATELIMIT_ENABLE=False in test settings.) Switching to the built-in `ip`
# keyer is safe: an attacker brute-forcing TOTP would be on a single IP,
# and 5/min × 6 digits = ~138-day expected time before guessing the right
# code — well outside any reasonable session window.
MFAVerifyView = ratelimit(
    key="ip", rate="5/m", method="POST", block=False,
)(MFAVerifyView.as_view())


# ---------------------------------------------------------------------------
# MFA — disable
# ---------------------------------------------------------------------------
class MFADisableView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_mfa_disable",
        tags=["mfa"],
        summary="Disable MFA. Requires both current password and a current TOTP code.",
    )
    def post(self, request):
        if not settings.MFA_ENABLED:
            return _mfa_disabled_response()

        ser = MFADisableSerializer(data=request.data)
        if not ser.is_valid():
            return _validation_fail(ser)

        user = request.user
        if not user.mfa_enabled:
            return fail("MFA_NOT_ENABLED", "MFA is not enabled.", status=400)

        # Re-auth with password
        if not authenticate(request, username=user.email, password=ser.validated_data["current_password"]):
            return fail("INVALID_CREDENTIALS", "Current password is incorrect.", status=401)

        secret = decrypt_secret(user.mfa_device.secret_encrypted)
        if not verify_totp(secret, ser.validated_data["code"]):
            MFA_CHALLENGE_FAILURES_TOTAL.inc()
            services.record_event(
                EventType.MFA_CHALLENGE_FAIL,
                user=user, request=request, metadata={"phase": "disable"},
            )
            return fail("MFA_CODE_INVALID", "TOTP code is invalid.", status=400)

        user.mfa_device.delete()
        user.backup_codes.all().delete()
        services.record_event(
            EventType.MFA_DISABLED, user=user, request=request,
        )
        services.send_mfa_disabled_email(user)
        return ok({"status": "ok"})


# ---------------------------------------------------------------------------
# MFA — regenerate backup codes
# ---------------------------------------------------------------------------
class MFABackupRegenerateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_mfa_regenerate_backup",
        tags=["mfa"],
        summary="Replace the user's set of backup codes with a fresh batch of 10.",
    )
    def post(self, request):
        if not settings.MFA_ENABLED:
            return _mfa_disabled_response()

        ser = MFABackupRegenerateSerializer(data=request.data)
        if not ser.is_valid():
            return _validation_fail(ser)

        user = request.user
        if not user.mfa_enabled:
            return fail("MFA_NOT_ENABLED", "MFA is not enabled.", status=400)

        if not authenticate(request, username=user.email, password=ser.validated_data["current_password"]):
            return fail("INVALID_CREDENTIALS", "Current password is incorrect.", status=401)

        secret = decrypt_secret(user.mfa_device.secret_encrypted)
        if not verify_totp(secret, ser.validated_data["code"]):
            MFA_CHALLENGE_FAILURES_TOTAL.inc()
            services.record_event(
                EventType.MFA_CHALLENGE_FAIL,
                user=user, request=request, metadata={"phase": "regenerate"},
            )
            return fail("MFA_CODE_INVALID", "TOTP code is invalid.", status=400)

        codes = generate_backup_codes(user)
        services.record_event(
            EventType.BACKUP_CODES_REGENERATED, user=user, request=request,
        )
        return ok({"backup_codes": codes})


# ---------------------------------------------------------------------------
# Profile — get / update
# ---------------------------------------------------------------------------
class ProfileUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="users_me_update",
        tags=["users"],
        summary="Update display_name / timezone / language / notification preferences",
    )
    def patch(self, request):
        ser = ProfileUpdateSerializer(data=request.data, partial=True)
        if not ser.is_valid():
            return _validation_fail(ser)

        user = request.user
        prof, _ = UserProfile.objects.get_or_create(user=user)
        data = ser.validated_data
        user_changed = False

        if "display_name" in data:
            user.display_name = data["display_name"]
            user_changed = True
        if user_changed:
            user.save(update_fields=["display_name", "updated_at"])

        for f in ("timezone", "language", "notification_email"):
            if f in data:
                setattr(prof, f, data[f])
        prof.save()

        services.record_event(
            EventType.PROFILE_UPDATED,
            user=user, request=request,
            metadata={"fields": sorted(data.keys())},
        )
        return ok({
            "user": services.serialize_user(user),
            "profile": services.serialize_profile(prof),
        })


# ---------------------------------------------------------------------------
# Password change (authenticated)
# ---------------------------------------------------------------------------
class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="users_me_password_change",
        tags=["users"],
        summary="Change password. Revokes all other refresh sessions.",
    )
    def post(self, request):
        ser = PasswordChangeSerializer(data=request.data, context={"request": request})
        if not ser.is_valid():
            if "new_password" in ser.errors:
                return fail(
                    "PASSWORD_WEAK", "Password does not meet policy.",
                    status=400, details=ser.errors,
                )
            return _validation_fail(ser)

        user = request.user
        if not authenticate(request, username=user.email, password=ser.validated_data["current_password"]):
            return fail("INVALID_CREDENTIALS", "Current password is incorrect.", status=401)

        user.set_password(ser.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])

        # Revoke every refresh family except the current one (so the active
        # session keeps working — the user shouldn't be logged out from the
        # device they just changed the password on).
        current_jti = _current_family_jti(request)
        current_family_id = None
        if current_jti:
            fam = RefreshTokenFamily.objects.filter(current_jti=current_jti, user=user).first()
            if fam:
                current_family_id = str(fam.family_id)
        services.revoke_other_sessions(
            user, except_family_id=current_family_id, reason="password_changed",
        )

        services.record_event(
            EventType.PASSWORD_CHANGED, user=user, request=request,
        )
        return ok({"status": "ok"})


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
class SessionsListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="users_me_sessions",
        tags=["users"],
        summary="List the user's active refresh-token families.",
    )
    def get(self, request):
        return ok({
            "sessions": services.list_user_sessions(
                request.user, current_jti=_current_family_jti(request),
            ),
        })


class SessionsRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="users_me_sessions_revoke",
        tags=["users"],
        summary="Revoke a single session by family_id, OR all-other if all=true.",
    )
    def post(self, request):
        ser = SessionRevokeSerializer(data=request.data)
        if not ser.is_valid():
            return _validation_fail(ser)

        user = request.user
        if ser.validated_data.get("all"):
            current_jti = _current_family_jti(request)
            current_family_id = None
            if current_jti:
                fam = RefreshTokenFamily.objects.filter(
                    user=user, current_jti=current_jti
                ).first()
                if fam:
                    current_family_id = str(fam.family_id)
            count = services.revoke_other_sessions(
                user, except_family_id=current_family_id, reason="revoke_all",
            )
            services.record_event(
                EventType.SESSION_REVOKED, user=user, request=request,
                metadata={"scope": "all_other", "count": count},
            )
            return ok({"revoked": count})

        family_id = ser.validated_data.get("family_id")
        try:
            fam = user.refresh_families.get(family_id=family_id, revoked_at__isnull=True)
        except RefreshTokenFamily.DoesNotExist:
            return fail("SESSION_NOT_FOUND", "No active session with that id.", status=404)
        fam.revoke(reason="user_revoke")
        services.record_event(
            EventType.SESSION_REVOKED, user=user, request=request,
            metadata={"scope": "single", "family_id": str(fam.family_id)},
        )
        return ok({"revoked": 1})
