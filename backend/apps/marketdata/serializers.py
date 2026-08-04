"""Marketdata DRF serializers (ADR-062). Keys are write-only, never echoed."""
from __future__ import annotations

from rest_framework import serializers


class DataProviderKeySetSerializer(serializers.Serializer):
    """Write-only payload for ``PUT /api/v1/marketdata/keys/{provider}/``."""

    api_key = serializers.CharField(write_only=True, trim_whitespace=True, max_length=256)

    def validate_api_key(self, value):
        # Keys are stored via encrypt_key(raw.encode("ascii")); a non-ASCII
        # paste (e.g. a Unicode dash) would raise UnicodeEncodeError → 500.
        # Reject → 400 instead (same guard as brokers FIX-L5).
        try:
            value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise serializers.ValidationError("api_key must be ASCII.") from exc
        return value
