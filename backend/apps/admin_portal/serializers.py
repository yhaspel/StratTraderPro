"""Admin-portal serializers (M10 §6.2)."""
from __future__ import annotations

from rest_framework import serializers

from apps.audit.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    actor = serializers.SerializerMethodField()
    # Explicit CharField — auto-mapping GenericIPAddressField hits a
    # Django 5.1 / DRF ip_address_validators arity mismatch.
    ip = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = AuditLog
        fields = [
            "id", "occurred_at", "event_type", "user", "actor",
            "entity_type", "entity_id", "data_before", "data_after",
            "ip", "ua", "self_hash",
        ]

    def get_user(self, obj):
        return str(obj.user_id) if obj.user_id else None

    def get_actor(self, obj):
        return str(obj.actor_id) if obj.actor_id else None


class AdminUserListSerializer(serializers.Serializer):
    id = serializers.CharField()
    email = serializers.EmailField()
    display_name = serializers.CharField()
    is_active = serializers.BooleanField()
    is_staff = serializers.BooleanField()
    is_verified = serializers.BooleanField()
    mfa_enabled = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    broker_count = serializers.IntegerField()


class MfaReasonSerializer(serializers.Serializer):
    mfa_code = serializers.CharField(max_length=16)
    reason = serializers.CharField(max_length=255)


class KillswitchSerializer(serializers.Serializer):
    engage = serializers.BooleanField()
    reason = serializers.CharField(max_length=255)
    mfa_code = serializers.CharField(max_length=16)
    confirm = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


class FlagFlipSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    mfa_code = serializers.CharField(max_length=16)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
