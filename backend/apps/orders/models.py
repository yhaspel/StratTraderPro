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
        # Options open/close semantics (M05).
        BUY_TO_OPEN = "BUY_TO_OPEN", "Buy to open"
        SELL_TO_OPEN = "SELL_TO_OPEN", "Sell to open"
        BUY_TO_CLOSE = "BUY_TO_CLOSE", "Buy to close"
        SELL_TO_CLOSE = "SELL_TO_CLOSE", "Sell to close"

    class OrderType(models.TextChoices):
        MKT = "MKT", "Market"
        LMT = "LMT", "Limit"
        STP = "STP", "Stop"
        STP_LMT = "STP_LMT", "Stop limit"

    class TimeInForce(models.TextChoices):
        DAY = "DAY", "Day"
        GTC = "GTC", "Good til cancelled"
        IOC = "IOC", "Immediate or cancel"

    class AssetClass(models.TextChoices):
        STOCK = "STOCK", "Stock"
        ETF = "ETF", "ETF"
        OPTION = "OPTION", "Option"
        FUTURE = "FUTURE", "Future"

    class OptionRight(models.TextChoices):
        CALL = "CALL", "Call"
        PUT = "PUT", "Put"

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
    symbol = models.CharField(max_length=32)
    side = models.CharField(max_length=16, choices=Side.choices)
    qty = models.DecimalField(max_digits=18, decimal_places=8)
    order_type = models.CharField(max_length=8, choices=OrderType.choices, default=OrderType.MKT)
    limit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    stop_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    time_in_force = models.CharField(
        max_length=8, choices=TimeInForce.choices, default=TimeInForce.DAY
    )
    # Asset-class + derivative descriptors (M05). Default STOCK keeps M04 rows valid.
    asset_class = models.CharField(
        max_length=8, choices=AssetClass.choices, default=AssetClass.STOCK
    )
    option_expiry = models.DateField(null=True, blank=True)
    option_strike = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    option_right = models.CharField(
        max_length=4, choices=OptionRight.choices, blank=True, default=""
    )
    future_root = models.CharField(max_length=8, blank=True, default="")
    future_expiry = models.CharField(max_length=8, blank=True, default="")
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


class ReconEvent(models.Model):
    """Reconciliation drift/heal audit (M05 §6.3). Emitted when our persisted
    Position diverges from the broker's truth; a second consecutive drift heals
    toward the broker."""

    class Kind(models.TextChoices):
        DRIFT = "DRIFT", "Drift detected"
        HEAL = "HEAL", "Healed toward broker"
        RESOLVED = "RESOLVED", "Resolved (no longer drifting)"

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recon_events"
    )
    broker_account = models.ForeignKey(
        "brokers.BrokerAccount", on_delete=models.CASCADE, related_name="recon_events"
    )
    symbol = models.CharField(max_length=32)
    asset_class = models.CharField(max_length=8, default=Order.AssetClass.STOCK)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.DRIFT)
    our_qty = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    broker_qty = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    detail = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "orders_recon_event"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["broker_account", "symbol", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"ReconEvent<{self.kind} {self.symbol} ours={self.our_qty} broker={self.broker_qty}>"
