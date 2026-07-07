"""Orders app — models (M04 §6.4).

- ``Order``     — one row per placed order. ``client_order_id`` is unique and
  is our idempotency anchor at the broker (``stp-{alert_id}``).
- ``Fill``      — immutable execution. ``broker_exec_id`` unique = stream
  dedup anchor (a reconnect REST-catch-up cannot double-count).
- ``Position``  — derived-but-persisted snapshot for dashboard speed;
  ``unique_together (broker_account, symbol)``.

Django's app-prefixed default table names (``orders_order`` etc.) sidestep the
SQL-reserved-word risk on a bare ``order`` table, so no custom ``db_table`` is
strictly needed — but we set them explicitly for grep-ability.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Order(models.Model):
    class Side(models.TextChoices):
        BUY = "BUY", "Buy"
        SELL = "SELL", "Sell"

    class OrderType(models.TextChoices):
        MKT = "MKT", "Market"
        LMT = "LMT", "Limit"

    class TimeInForce(models.TextChoices):
        DAY = "DAY", "Day"

    class Status(models.TextChoices):
        PENDING_SUBMIT = "PENDING_SUBMIT", "Pending submit"
        SUBMITTED = "SUBMITTED", "Submitted"
        PARTIAL = "PARTIAL", "Partially filled"
        FILLED = "FILLED", "Filled"
        CANCELLED = "CANCELLED", "Cancelled"
        REJECTED = "REJECTED", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders"
    )
    strategy = models.ForeignKey(
        "strategies.Strategy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    broker_account = models.ForeignKey(
        "brokers.BrokerAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    raw_alert = models.ForeignKey(
        "webhooks.AlertMessage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    client_order_id = models.CharField(max_length=128, unique=True)
    broker_order_id = models.CharField(max_length=128, blank=True, default="")
    symbol = models.CharField(max_length=24)
    side = models.CharField(max_length=4, choices=Side.choices)
    qty = models.DecimalField(max_digits=18, decimal_places=8)
    order_type = models.CharField(max_length=8, choices=OrderType.choices, default=OrderType.MKT)
    limit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    time_in_force = models.CharField(
        max_length=8, choices=TimeInForce.choices, default=TimeInForce.DAY
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING_SUBMIT
    )
    reason = models.CharField(max_length=64, blank=True, default="")
    filled_qty = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_order"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["broker_account", "status"]),
            models.Index(fields=["broker_order_id"]),
        ]

    def __str__(self) -> str:
        return f"Order<{self.symbol} {self.side} {self.qty} {self.status}>"


class Fill(models.Model):
    id = models.BigAutoField(primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="fills")
    qty = models.DecimalField(max_digits=18, decimal_places=8)
    price = models.DecimalField(max_digits=18, decimal_places=4)
    ts = models.DateTimeField()
    broker_exec_id = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orders_fill"
        indexes = [models.Index(fields=["order", "ts"])]

    def __str__(self) -> str:
        return f"Fill<{self.order_id} {self.qty}@{self.price}>"


class Position(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="positions"
    )
    broker_account = models.ForeignKey(
        "brokers.BrokerAccount", on_delete=models.CASCADE, related_name="positions"
    )
    symbol = models.CharField(max_length=24)
    qty = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    avg_cost = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    market_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_position"
        unique_together = ("broker_account", "symbol")
        indexes = [models.Index(fields=["user", "symbol"])]

    @property
    def unrealized_pnl(self):
        if self.market_price is None:
            return None
        return (self.market_price - self.avg_cost) * self.qty

    def __str__(self) -> str:
        return f"Position<{self.symbol} {self.qty}@{self.avg_cost}>"
