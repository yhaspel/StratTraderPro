"""Backtest DRF serializers (M09 §6.7).

Input validation enforces AC-09-1 field rules + the §11 caps that don't need the
adapter (symbols ≤ 10, date range ≤ 15 y, ``step_days == test_window_days``,
``tf == "1d"``, retention 1–365, slippage floor 1 bp). Adapter-dependent checks
(grid subset refinement, combos ≤ 500, windows 2–60, ownership, no-adapter) live
in the view where the resolved adapter is available.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import BacktestRun, BacktestSegment

MAX_SYMBOLS = 10
MAX_WINDOWS = 60
MAX_YEARS = 15
SLIPPAGE_FLOOR_BP = 1.0
METRICS = ("sharpe", "sortino", "total_return", "mar")


class CostsSerializer(serializers.Serializer):
    slippage_bps = serializers.FloatField(default=5.0, min_value=SLIPPAGE_FLOOR_BP, max_value=1000.0)
    per_order_usd = serializers.FloatField(default=0.0, min_value=0.0)
    per_share_usd = serializers.FloatField(default=0.0, min_value=0.0)
    volume_participation_pct = serializers.FloatField(default=10.0, min_value=0.001, max_value=100.0)


class BacktestRunCreateSerializer(serializers.Serializer):
    strategy = serializers.UUIDField()
    symbols = serializers.ListField(
        child=serializers.CharField(max_length=16), min_length=1, max_length=MAX_SYMBOLS
    )
    start = serializers.DateField()
    end = serializers.DateField()
    tf = serializers.CharField(default="1d")
    train_window_days = serializers.IntegerField(min_value=1, max_value=6000)
    test_window_days = serializers.IntegerField(min_value=1, max_value=6000)
    step_days = serializers.IntegerField(min_value=1, max_value=6000)
    mode = serializers.ChoiceField(choices=["anchored", "rolling"], default="rolling")
    metric = serializers.ChoiceField(choices=list(METRICS), default="sharpe")
    initial_cash = serializers.FloatField(default=100_000.0, min_value=1.0)
    param_grid = serializers.JSONField(required=False, default=dict)
    costs = CostsSerializer(required=False, default=dict)
    sizing_mode = serializers.ChoiceField(choices=["production", "fixed_qty_1"], default="fixed_qty_1")
    retention_days = serializers.IntegerField(default=90, min_value=1, max_value=365)

    def validate_symbols(self, v):
        seen: list[str] = []
        for s in v:
            u = s.strip().upper()
            if u and u not in seen:
                seen.append(u)
        if not seen:
            raise serializers.ValidationError("At least one symbol is required.")
        if len(seen) > MAX_SYMBOLS:
            raise serializers.ValidationError(f"At most {MAX_SYMBOLS} symbols.")
        return seen

    def validate_tf(self, v):
        if v != "1d":
            raise serializers.ValidationError("Only tf='1d' is supported in the MVP.")
        return v

    def validate_param_grid(self, v):
        if not isinstance(v, dict):
            raise serializers.ValidationError("param_grid must be an object of {name: [values]}.")
        for key, values in v.items():
            if not isinstance(values, list) or not values:
                raise serializers.ValidationError(f"param_grid['{key}'] must be a non-empty list.")
            for item in values:
                if not isinstance(item, (int, float)) or isinstance(item, bool):
                    raise serializers.ValidationError(f"param_grid['{key}'] values must be numeric.")
        return v

    def validate(self, data):
        if data["end"] <= data["start"]:
            raise serializers.ValidationError({"end": "end must be after start."})
        span_days = (data["end"] - data["start"]).days
        if span_days > MAX_YEARS * 366:
            raise serializers.ValidationError({"end": f"Date range must be ≤ {MAX_YEARS} years."})
        # MVP rule: step_days must equal test_window_days (AC-09-1).
        if data["step_days"] != data["test_window_days"]:
            raise serializers.ValidationError(
                {"step_days": "step_days must equal test_window_days in the MVP."}
            )
        return data


class BacktestSegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BacktestSegment
        fields = (
            "symbol", "window_index", "train_start", "train_end", "test_start",
            "test_end", "best_params", "oos_metrics",
        )
        read_only_fields = fields


class BacktestRunListSerializer(serializers.ModelSerializer):
    strategy_slug = serializers.CharField(source="strategy.slug", read_only=True)
    strategy_name = serializers.CharField(source="strategy.name", read_only=True)
    symbols = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    worst_pbo = serializers.SerializerMethodField()

    class Meta:
        model = BacktestRun
        fields = (
            "id", "strategy_slug", "strategy_name", "symbols", "status", "stage",
            "pct", "metrics_hash", "retention_days", "error_code", "error_message",
            "worst_pbo", "duration_seconds", "created_at", "started_at", "finished_at",
        )
        read_only_fields = fields

    def get_symbols(self, obj) -> list:
        return obj.config.get("symbols", [])

    def get_duration_seconds(self, obj):
        if obj.started_at and obj.finished_at:
            return round((obj.finished_at - obj.started_at).total_seconds(), 2)
        return None

    def get_worst_pbo(self, obj):
        per = (obj.summary or {}).get("symbols", {})
        pbos = [m.get("pbo") for m in per.values() if isinstance(m, dict) and m.get("pbo") is not None]
        return max(pbos) if pbos else None


class BacktestRunDetailSerializer(BacktestRunListSerializer):
    config = serializers.JSONField(read_only=True)
    summary = serializers.JSONField(read_only=True)
    segments = BacktestSegmentSerializer(many=True, read_only=True)

    class Meta(BacktestRunListSerializer.Meta):
        fields = BacktestRunListSerializer.Meta.fields + ("config", "summary", "segments")
        read_only_fields = fields
