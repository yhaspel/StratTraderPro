"""M03 — DRF serializers for the strategies API."""
from __future__ import annotations

from rest_framework import serializers

from .models import Strategy, StrategyFile, WebhookConfig


# ---------------------------------------------------------------------------
# Read-side serializers
# ---------------------------------------------------------------------------
class StrategyFileSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = StrategyFile
        fields = ("kind", "filename", "sha256", "size_bytes", "uploaded_at")


class StrategySerializer(serializers.ModelSerializer):
    files = StrategyFileSummarySerializer(many=True, read_only=True)
    type = serializers.SerializerMethodField()
    has_webhook_config = serializers.SerializerMethodField()

    class Meta:
        model = Strategy
        fields = (
            "id", "name", "slug", "description_short",
            "is_system", "is_enabled", "is_community_tested",
            "type", "has_webhook_config",
            "created_at", "updated_at",
            "files",
        )
        read_only_fields = (
            "id", "is_system", "is_community_tested",
            "created_at", "updated_at", "files", "type", "has_webhook_config",
        )

    def get_type(self, obj: Strategy) -> str:
        return "system" if obj.is_system else "user"

    def get_has_webhook_config(self, obj: Strategy) -> bool:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        return obj.webhook_configs.filter(user=request.user).exists()


class StrategyUpdateSerializer(serializers.ModelSerializer):
    """For PATCH /strategies/{id}/. System strategies allow only `is_enabled`."""
    class Meta:
        model = Strategy
        fields = ("name", "is_enabled")


# ---------------------------------------------------------------------------
# Upload (write-only)
# ---------------------------------------------------------------------------
class StrategyUploadSerializer(serializers.Serializer):
    """Multipart upload — three files + a mandatory acknowledgement.

    The view extracts the files from ``request.FILES`` directly (multipart
    handling lives there); this serializer is mainly for the acknowledgement
    field validation.
    """
    accept_untested_risk = serializers.BooleanField(
        required=True,
        help_text="Must be true. Maps to AC-03-5.",
    )

    def validate_accept_untested_risk(self, value):
        if not value:
            raise serializers.ValidationError(
                "You must acknowledge the untested-strategy risk.",
            )
        return value


# ---------------------------------------------------------------------------
# Webhook config
# ---------------------------------------------------------------------------
class WebhookConfigReadSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = WebhookConfig
        fields = (
            "id", "version", "json_schema", "payload_template",
            "url", "created_at", "rotated_at", "updated_at",
        )

    def get_url(self, obj: WebhookConfig) -> str:
        from .services import build_webhook_url
        return build_webhook_url(user_id=obj.user_id, strategy_id=obj.strategy_id)


class WebhookConfigUpdateSerializer(serializers.Serializer):
    """PUT /webhook-config/ — schema + payload_template only. Secret rotation
    is a separate endpoint."""
    json_schema = serializers.JSONField(required=True)
    payload_template = serializers.JSONField(required=True)


class WebhookDryRunSerializer(serializers.Serializer):
    payload = serializers.JSONField(required=True)
