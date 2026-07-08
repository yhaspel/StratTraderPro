"""Broker DRF serializers (M04). Secrets are write-only and never echoed."""
from __future__ import annotations

from rest_framework import serializers

from .models import BrokerAccount
from .services import get_stream_status


class BrokerAccountSerializer(serializers.ModelSerializer):
    """Read-side. No key fields — the secret is write-only by construction."""

    stream_status = serializers.SerializerMethodField()

    class Meta:
        model = BrokerAccount
        fields = (
            "id",
            "broker",
            "mode",
            "account_number",
            "nickname",
            "is_default",
            "status",
            "stream_status",
            "last_connected_at",
            "created_at",
        )
        read_only_fields = fields

    def get_stream_status(self, obj: BrokerAccount) -> str:
        return get_stream_status(obj)


class BrokerConnectSerializer(serializers.Serializer):
    """Write-only connect payload. Alpaca paper only in M04."""

    broker = serializers.ChoiceField(
        choices=BrokerAccount.Broker.choices, default=BrokerAccount.Broker.ALPACA
    )
    mode = serializers.ChoiceField(
        choices=BrokerAccount.Mode.choices, default=BrokerAccount.Mode.PAPER
    )
    api_key_id = serializers.CharField(write_only=True, trim_whitespace=True, max_length=128)
    api_secret = serializers.CharField(write_only=True, trim_whitespace=True, max_length=256)
    nickname = serializers.CharField(required=False, allow_blank=True, max_length=64, default="")
    is_default = serializers.BooleanField(required=False, default=False)

    def validate_mode(self, value):
        if value != BrokerAccount.Mode.PAPER:
            raise serializers.ValidationError("Only paper mode is supported in this milestone.")
        return value

    def validate_broker(self, value):
        if value != BrokerAccount.Broker.ALPACA:
            raise serializers.ValidationError("Only Alpaca is supported in this milestone.")
        return value

    def _require_ascii(self, value, field):
        # Keys are stored via encrypt_key(raw.encode("ascii")); a non-ASCII paste
        # (e.g. a Unicode dash) raised UnicodeEncodeError → 500. Reject → 400 (FIX-L5).
        try:
            value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise serializers.ValidationError(f"{field} must be ASCII.") from exc
        return value

    def validate_api_key_id(self, value):
        return self._require_ascii(value, "api_key_id")

    def validate_api_secret(self, value):
        return self._require_ascii(value, "api_secret")


class BrokerRemoveSerializer(serializers.Serializer):
    """MFA re-prompt on broker removal (AC-04-6 / §6.7)."""

    mfa_code = serializers.CharField(write_only=True, max_length=16)
