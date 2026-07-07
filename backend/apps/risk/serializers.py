"""Risk DRF serializers (M08 §6.1). Profile validators enforce AC-08-2."""
from __future__ import annotations

from rest_framework import serializers

from .models import RiskEvent, RiskProfile, SizingDecision


class RiskProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskProfile
        exclude = ("id", "user", "created_at", "updated_at")

    def validate_risk_per_trade_pct(self, v):
        if not (0 < float(v) <= 5.0):
            raise serializers.ValidationError("risk_per_trade_pct must be in (0, 5].")
        return v

    def validate_max_position_pct(self, v):
        if float(v) > 50:
            raise serializers.ValidationError("max_position_pct must be ≤ 50.")
        return v

    def validate_max_concurrent(self, v):
        if int(v) < 1:
            raise serializers.ValidationError("max_concurrent must be ≥ 1.")
        return v

    def validate_daily_loss_pct(self, v):
        if float(v) > 25:
            raise serializers.ValidationError("daily_loss_pct must be ≤ 25.")
        return v

    def validate_permitted_asset_classes(self, v):
        if not v:
            raise serializers.ValidationError("permitted_asset_classes must be non-empty.")
        allowed = {"STOCK", "ETF", "OPTION", "FUTURE"}
        bad = [a for a in v if a not in allowed]
        if bad:
            raise serializers.ValidationError(f"Unknown asset classes: {bad}.")
        return v

    def validate(self, data):
        soft = data.get("soft_stop_pct", getattr(self.instance, "soft_stop_pct", 5))
        hard = data.get("hard_stop_pct", getattr(self.instance, "hard_stop_pct", 10))
        if float(soft) >= float(hard):
            raise serializers.ValidationError("soft_stop_pct must be < hard_stop_pct.")
        return data


class SizingDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SizingDecision
        fields = (
            "id", "order", "alert", "strategy", "symbol", "requested_qty",
            "computed_qty", "result", "reject_reason", "inputs", "created_at",
        )
        read_only_fields = fields


class RiskEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskEvent
        fields = ("id", "type", "scope", "details", "created_at")
        read_only_fields = fields


class KillSwitchCreateSerializer(serializers.Serializer):
    SCOPES = ("STRATEGY", "USER", "PLATFORM")

    scope = serializers.ChoiceField(choices=[(s, s) for s in SCOPES])
    target_id = serializers.UUIDField(required=False, allow_null=True)  # strategy id for L0
    active = serializers.BooleanField(default=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    flatten = serializers.BooleanField(required=False, default=False)
    mfa_code = serializers.CharField(required=False, allow_blank=True, default="", max_length=16)
