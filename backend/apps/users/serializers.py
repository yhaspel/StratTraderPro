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
    class Meta:
        model = User
        fields = ["id", "email", "display_name", "is_verified", "created_at"]
        read_only_fields = fields
