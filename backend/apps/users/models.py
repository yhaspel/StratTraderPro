"""
User model and auth-supporting tables (M01).

Tables:
- User: email-keyed AbstractBaseUser; UUID PK.
- EmailVerificationToken: single-use, 24h TTL.
- PasswordResetToken: single-use, 1h TTL.
- RefreshTokenFamily: tracks JWT refresh-token families for rotation/reuse detection.
- FailedLoginAttempt: per-email sliding-window counter for account lockout.
- AuthEvent: lightweight audit precursor (folded into AuditLog in M10).
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
