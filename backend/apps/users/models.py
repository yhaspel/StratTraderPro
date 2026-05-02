"""
User model and auth-supporting tables (M01 + M02).

Tables:
- User: email-keyed AbstractBaseUser; UUID PK. (M01)
- EmailVerificationToken: single-use, 24h TTL. (M01)
- PasswordResetToken: single-use, 1h TTL. (M01)
- RefreshTokenFamily: tracks JWT refresh-token families for rotation/reuse
  detection; M02 adds user_agent / ip / last_used_at for the sessions UI.
- FailedLoginAttempt: per-email sliding-window counter for account lockout. (M01)
- AuthEvent: lightweight audit precursor (folded into AuditLog in M10).
- UserProfile: per-user prefs — timezone, language, notifications. (M02)
- MFADevice: TOTP secret (Fernet-encrypted at rest). (M02)
- BackupCode: 10 single-use codes per user, sha256+salt hashed. (M02)
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_verified", True)
        extra.setdefault("display_name", email.split("@")[0] if email else "admin")
        if extra.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    display_name = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    objects = UserManager()

    class Meta:
        db_table = "users_user"

    def __str__(self):
        return self.email

    # ------------------------------------------------------------------
    # M02 — derived MFA flag
    # ------------------------------------------------------------------
    @property
    def mfa_enabled(self) -> bool:
        """True iff the user has a verified MFADevice.

        Derived (not cached) — single source of truth is the MFADevice row.
        Use ``select_related("mfa_device")`` in views that hit this in a hot
        path to avoid the extra query.
        """
        try:
            return bool(self.mfa_device and self.mfa_device.verified)
        except ObjectDoesNotExist:
            return False


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------
def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


class _BaseToken(models.Model):
    """Single-use, time-limited tokens stored hashed."""

    TTL = timedelta(hours=1)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    @classmethod
    def issue(cls, user):
        raw = _generate_token()
        token = cls.objects.create(
            user=user,
            token_hash=_hash_token(raw),
            expires_at=timezone.now() + cls.TTL,
        )
        return token, raw

    @classmethod
    def consume(cls, raw):
        try:
            tok = cls.objects.get(token_hash=_hash_token(raw))
        except cls.DoesNotExist:
            return None
        if tok.consumed_at is not None or tok.expires_at < timezone.now():
            return None
        tok.consumed_at = timezone.now()
        tok.save(update_fields=["consumed_at"])
        return tok


class EmailVerificationToken(_BaseToken):
    TTL = timedelta(hours=24)

    class Meta:
        db_table = "users_email_verification_token"


class PasswordResetToken(_BaseToken):
    TTL = timedelta(hours=1)

    class Meta:
        db_table = "users_password_reset_token"


# ---------------------------------------------------------------------------
# Refresh-token family (JWT rotation w/ reuse detection)
# ---------------------------------------------------------------------------
class RefreshTokenFamily(models.Model):
    family_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="refresh_families"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=64, blank=True, default="")
    # JTI of the currently-valid refresh token in this family. Any other JTI
    # presented for this family is treated as reuse → family revoked.
    current_jti = models.CharField(max_length=64, db_index=True)
    # M02 — sessions UI hints. Captured at family creation, refreshed on
    # successful rotation. Stored verbatim then redacted at serialization.
    user_agent = models.CharField(max_length=512, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "users_refresh_token_family"
        indexes = [models.Index(fields=["user", "revoked_at"])]

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    def revoke(self, reason=""):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.revoke_reason = reason[:64]
            self.save(update_fields=["revoked_at", "revoke_reason"])

    def touch(self, *, ip: str | None = None, user_agent: str | None = None) -> None:
        """Record activity. Called on successful refresh rotation."""
        fields: list[str] = []
        self.last_used_at = timezone.now()
        fields.append("last_used_at")
        if ip:
            self.ip = ip
            fields.append("ip")
        if user_agent:
            self.user_agent = user_agent[:512]
            fields.append("user_agent")
        self.save(update_fields=fields)


# ---------------------------------------------------------------------------
# Failed login attempts (account lockout)
# ---------------------------------------------------------------------------
class FailedLoginAttempt(models.Model):
    id = models.BigAutoField(primary_key=True)
    email = models.EmailField(db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "users_failed_login_attempt"
        indexes = [models.Index(fields=["email", "occurred_at"])]


# ---------------------------------------------------------------------------
# AuthEvent (precursor to full AuditLog in M10)
# ---------------------------------------------------------------------------
class AuthEvent(models.Model):
    class EventType(models.TextChoices):
        REGISTER = "register"
        VERIFY_EMAIL = "verify_email"
        LOGIN_OK = "login_ok"
        LOGIN_FAIL = "login_fail"
        LOGOUT = "logout"
        REFRESH_OK = "refresh_ok"
        REFRESH_REUSE = "refresh_reuse"
        FAMILY_REVOKED = "family_revoked"
        PASSWORD_RESET_REQUESTED = "password_reset_requested"  # noqa: S105
        PASSWORD_RESET_CONFIRMED = "password_reset_confirmed"  # noqa: S105
        ACCOUNT_LOCKED = "account_locked"
        RESEND_VERIFICATION = "resend_verification"
        # M02 — MFA + profile
        MFA_ENROLLED = "mfa_enrolled"
        MFA_DISABLED = "mfa_disabled"
        MFA_CHALLENGE_OK = "mfa_challenge_ok"
        MFA_CHALLENGE_FAIL = "mfa_challenge_fail"
        BACKUP_CODE_USED = "backup_code_used"
        BACKUP_CODES_REGENERATED = "backup_codes_regenerated"
        PASSWORD_CHANGED = "password_changed"  # noqa: S105
        PROFILE_UPDATED = "profile_updated"
        SESSION_REVOKED = "session_revoked"
        # M2.5 — Google OAuth
        OAUTH_LOGIN_OK = "oauth_login_ok"
        OAUTH_USER_CREATED = "oauth_user_created"   # first sign-in via Google created a new User
        OAUTH_LINKED = "oauth_linked"               # Google identity auto-linked to existing email
        OAUTH_EXCHANGE_OK = "oauth_exchange_ok"
        OAUTH_EXCHANGE_FAIL = "oauth_exchange_fail"

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auth_events",
    )
    email = models.EmailField(blank=True, default="")  # captured for anon/failed events
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "users_auth_event"
        indexes = [models.Index(fields=["user", "occurred_at"])]


# ---------------------------------------------------------------------------
# M02 — User profile
# ---------------------------------------------------------------------------
class UserProfile(models.Model):
    """Per-user preferences. Auto-created on user save (see signals.py)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    # IANA tz name. Validated at the serializer layer against
    # zoneinfo.available_timezones().
    timezone = models.CharField(max_length=64, default="America/New_York")
    language = models.CharField(max_length=8, default="en")
    notification_email = models.BooleanField(default=True)
    # FK populated in M04 once Broker model lands. Plain UUID for now to
    # avoid a circular dependency.
    default_broker_id = models.UUIDField(null=True, blank=True)
    terms_version_accepted = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users_user_profile"

    def __str__(self):
        return f"Profile<{self.user.email}>"


# ---------------------------------------------------------------------------
# M02 — MFA device (TOTP)
# ---------------------------------------------------------------------------
class MFADevice(models.Model):
    """One TOTP device per user. ``secret_encrypted`` is Fernet-wrapped at rest.

    Verification flow:
    - Row created when user starts enrollment (verified=False).
    - Flipped to verified=True when /enroll/confirm/ accepts a valid code.
    - On disable: row deleted.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_device"
    )
    secret_encrypted = models.BinaryField()
    verified = models.BooleanField(default=False)
    enrolled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users_mfa_device"

    def __str__(self):
        return f"MFADevice<{self.user.email} verified={self.verified}>"


# ---------------------------------------------------------------------------
# M02 — Backup codes
# ---------------------------------------------------------------------------
class BackupCode(models.Model):
    """Single-use 8-char backup codes. Stored as sha256(code + per-row salt).

    A user has exactly ``MFA_BACKUP_CODE_COUNT`` (default 10) un-used codes
    at any moment. Regenerating wipes the prior set.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="backup_codes"
    )
    code_hash = models.CharField(max_length=128, db_index=True)
    salt = models.CharField(max_length=32)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users_backup_code"
        indexes = [models.Index(fields=["user", "used_at"])]

    @property
    def is_used(self) -> bool:
        return self.used_at is not None


# ---------------------------------------------------------------------------
# M2.5 — OAuth exchange code
# ---------------------------------------------------------------------------
class OAuthExchangeCode(models.Model):
    """
    Single-use code issued at the end of the Google OAuth callback. The
    frontend POSTs this to ``/api/v1/auth/oauth/exchange/`` to swap it for a
    JWT pair (or an MFA challenge if the user has MFA enabled).

    Why not put the JWT in the redirect URL directly? URL fragments leak via
    referer headers, server logs, and browser history. The exchange-code
    pattern keeps the JWT off the wire entirely — the code is single-use,
    short-lived, and only ever transits through one redirect hop.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="oauth_exchange_codes"
    )
    code_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    # Provider that issued this code (currently always 'google'; future: apple, github)
    provider = models.CharField(max_length=32, default="google")

    class Meta:
        db_table = "users_oauth_exchange_code"
        indexes = [models.Index(fields=["user", "consumed_at"])]

    @classmethod
    def issue(cls, user, *, provider: str = "google"):
        """Mint a fresh exchange code. Returns ``(row, raw_code)``."""
        from datetime import timedelta as _td

        raw = secrets.token_urlsafe(32)
        ttl_minutes = settings.OAUTH_EXCHANGE_TTL_MINUTES
        row = cls.objects.create(
            user=user,
            code_hash=_hash_token(raw),
            expires_at=timezone.now() + _td(minutes=ttl_minutes),
            provider=provider,
        )
        return row, raw

    @classmethod
    def consume(cls, raw: str):
        """
        Single-use consumption. Returns the matching User if the code is
        valid + unconsumed + unexpired, else None.
        """
        try:
            row = cls.objects.select_related("user").get(code_hash=_hash_token(raw))
        except cls.DoesNotExist:
            return None
        if row.consumed_at is not None or row.expires_at < timezone.now():
            return None
        row.consumed_at = timezone.now()
        row.save(update_fields=["consumed_at"])
        return row.user
