"""Order / Fill / Position serializers (M04)."""
from __future__ import annotations

from rest_framework import serializers

from .models import Fill, Order, Position


class OrderSerializer(serializers.ModelSerializer):
    unrealized = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "id",
            "client_order_id",
            "broker_order_id",
            "symbol",
            "side",
            "qty",
            "filled_qty",
            "order_type",
            "limit_price",
            "time_in_force",
            "status",
            "reason",
            "strategy",
            "broker_account",
            "created_at",
            "updated_at",
            "unrealized",
        )
        read_only_fields = fields

    def get_unrealized(self, obj) -> None:
        return None  # reserved; orders carry no live P&L (positions do)


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
