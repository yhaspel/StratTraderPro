"""Order / Fill / Position serializers (M04)."""
from __future__ import annotations

from rest_framework import serializers

from .models import Fill, Order, Position, ReconEvent

_ORDER_FIELDS = (
    "id",
    "client_order_id",
    "broker_order_id",
    "symbol",
    "asset_class",
    "side",
    "qty",
    "filled_qty",
    "order_type",
    "limit_price",
    "stop_price",
    "time_in_force",
    "option_expiry",
    "option_strike",
    "option_right",
    "future_root",
    "future_expiry",
    "status",
    "reason",
    "strategy",
    "broker_account",
    "created_at",
    "updated_at",
)


class OrderSerializer(serializers.ModelSerializer):
    broker = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (*_ORDER_FIELDS, "broker")
        read_only_fields = fields

    def get_broker(self, obj) -> str | None:
        return obj.broker_account.broker if obj.broker_account_id else None


class FillSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="order.symbol", read_only=True)

    class Meta:
        model = Fill
        fields = ("id", "order", "symbol", "qty", "price", "ts", "broker_exec_id", "created_at")
        read_only_fields = fields


class PositionSerializer(serializers.ModelSerializer):
    unrealized_pnl = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = (
            "id",
            "symbol",
            "qty",
            "avg_cost",
            "market_price",
            "unrealized_pnl",
            "broker_account",
            "updated_at",
        )
        read_only_fields = fields

    def get_unrealized_pnl(self, obj) -> str | None:
        pnl = obj.unrealized_pnl
        return str(pnl) if pnl is not None else None


class OrderDetailSerializer(OrderSerializer):
    fills = FillSerializer(many=True, read_only=True)

    class Meta(OrderSerializer.Meta):
        fields = (*_ORDER_FIELDS, "broker", "fills")


class ReconEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReconEvent
        fields = (
            "id",
            "broker_account",
            "symbol",
            "asset_class",
            "kind",
            "our_qty",
            "broker_qty",
            "detail",
            "created_at",
            "resolved_at",
        )
        read_only_fields = fields
