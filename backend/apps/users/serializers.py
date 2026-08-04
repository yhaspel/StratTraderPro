"""Serializers for auth endpoints (M01)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------
def _validate_password_or_raise(password: str, user=None) -> None:
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({"password": list(exc.messages)}) from exc


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    display_name = serializers.CharField(max_length=64, min_length=1)
    password = serializers.CharField(write_only=True, min_length=12, max_length=256, trim_whitespace=False)

    def validate_email(self, value):
        return User.objects.normalize_email(value).lower()

    def validate(self, attrs):
        _validate_password_or_raise(
            attrs["password"],
            user=User(email=attrs["email"], display_name=attrs["display_name"]),
        )
        return attrs


class VerifyEmailSerializer(serializers.Serializer):
    token = serializers.CharField()


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return User.objects.normalize_email(value).lower()


# ---------------------------------------------------------------------------
# Login (we keep simplejwt's serializer around for claim shaping; the LoginView
# uses our own logic so we can inject the family-id claim).
# ---------------------------------------------------------------------------
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_email(self, value):
        return User.objects.normalize_email(value).lower()


class AuthTokenObtainSerializer(TokenObtainPairSerializer):
    """Adds extra claims so frontend can decode display info from the access token."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["display_name"] = user.display_name
        token["is_verified"] = user.is_verified
        return token


# ---------------------------------------------------------------------------
# Refresh / Logout
# ---------------------------------------------------------------------------
class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return User.objects.normalize_email(value).lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=12, max_length=256, trim_whitespace=False)

    def validate(self, attrs):
        _validate_password_or_raise(attrs["password"])
        return attrs


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------
class CurrentUserSerializer(serializers.ModelSerializer):
    """Returns user + nested profile (M02)."""
    mfa_enabled = serializers.BooleanField(read_only=True)
    profile = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "display_name", "is_verified", "created_at",
            "mfa_enabled", "is_staff", "profile",
        ]
        read_only_fields = fields

    def get_profile(self, obj):
        from . import services

        # ensure-on-read: defensive in case signal didn't fire (e.g. legacy users)
        from .models import UserProfile
        prof, _ = UserProfile.objects.get_or_create(user=obj)
        return services.serialize_profile(prof)


# ---------------------------------------------------------------------------
# M02 — MFA serializers
# ---------------------------------------------------------------------------
class MFAEnrollConfirmSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=8, min_length=6)


class MFAVerifySerializer(serializers.Serializer):
    mfa_token = serializers.CharField()
    code = serializers.CharField(max_length=16, min_length=6)
    is_backup_code = serializers.BooleanField(required=False, default=False)


class MFADisableSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    code = serializers.CharField(max_length=16, min_length=6)


class MFABackupRegenerateSerializer(serializers.Serializer):
    """Backup-code regeneration requires defense-in-depth: password + TOTP."""
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    code = serializers.CharField(max_length=8, min_length=6)


# ---------------------------------------------------------------------------
# M02 — Profile, password change, sessions
# ---------------------------------------------------------------------------
def _all_iana_timezones():
    try:
        from zoneinfo import available_timezones
        return available_timezones()
    except ImportError:  # pragma: no cover — Python < 3.9
        return set()


class ProfileUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=64, min_length=1, required=False)
    timezone = serializers.CharField(max_length=64, required=False)
    language = serializers.CharField(max_length=8, required=False)
    notification_email = serializers.BooleanField(required=False)

    SUPPORTED_LANGUAGES = {"en"}

    def validate_timezone(self, value):
        if value not in _all_iana_timezones():
            raise serializers.ValidationError(f"Unknown IANA timezone: {value!r}")
        return value

    def validate_language(self, value):
        if value not in self.SUPPORTED_LANGUAGES:
            raise serializers.ValidationError(
                f"Unsupported language: {value!r}. Supported: {sorted(self.SUPPORTED_LANGUAGES)}"
            )
        return value


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(
        write_only=True, min_length=12, max_length=256, trim_whitespace=False
    )

    def validate(self, attrs):
        user = self.context.get("request").user if self.context.get("request") else None
        _validate_password_or_raise(attrs["new_password"], user=user)
        return attrs


class SessionRevokeSerializer(serializers.Serializer):
    family_id = serializers.UUIDField(required=False)
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("family_id") and not attrs.get("all"):
            raise serializers.ValidationError(
                "Must provide either ``family_id`` or set ``all=true``."
            )
        return attrs


# ---------------------------------------------------------------------------
# M2.5 — OAuth exchange
# ---------------------------------------------------------------------------
class OAuthExchangeSerializer(serializers.Serializer):
    exchange = serializers.CharField(min_length=10, max_length=128)
