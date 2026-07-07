"""Risk models (M08 §8). Kill-switch state lives on ``brokers.TradingHalt``
(extended with levels in M08) — NOT a parallel model."""
from __future__ import annotations

from django.conf import settings
from django.db import models


class RiskProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_profile"
    )
    risk_per_trade_pct = models.DecimalField(max_digits=6, decimal_places=3, default=1.0)
    max_position_pct = models.DecimalField(max_digits=6, decimal_places=2, default=20.0)
    max_concurrent = models.PositiveIntegerField(default=5)
    daily_loss_usd = models.DecimalField(max_digits=14, decimal_places=2, default=1000.0)
    daily_loss_pct = models.DecimalField(max_digits=6, decimal_places=2, default=5.0)
    leverage_cap = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    permitted_asset_classes = models.JSONField(default=list)  # e.g. ["STOCK","ETF"]
    soft_stop_pct = models.DecimalField(max_digits=6, decimal_places=2, default=5.0)
    hard_stop_pct = models.DecimalField(max_digits=6, decimal_places=2, default=10.0)
    strict_mode = models.BooleanField(default=False)
    atr_factor = models.DecimalField(max_digits=5, decimal_places=2, default=1.5)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "risk_profile"

    def __str__(self) -> str:
        return f"RiskProfile<{self.user_id} risk/trade={self.risk_per_trade_pct}%>"

    @staticmethod
    def default_permitted():
        return ["STOCK", "ETF"]


class SizingDecision(models.Model):
    class Result(models.TextChoices):
        OK = "OK", "Sized"
        REJECT = "REJECT", "Rejected"

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sizing_decisions"
    )
    order = models.ForeignKey(
        "orders.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="sizing_decisions"
    )
    alert = models.ForeignKey(
        "webhooks.AlertMessage", on_delete=models.SET_NULL, null=True, blank=True, related_name="sizing_decisions"
    )
    strategy = models.ForeignKey(
        "strategies.Strategy", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    symbol = models.CharField(max_length=32, blank=True, default="")
    requested_qty = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    computed_qty = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    result = models.CharField(max_length=8, choices=Result.choices, default=Result.OK)
    reject_reason = models.CharField(max_length=48, blank=True, default="")
    inputs = models.JSONField(default=dict)  # regime/sentiment/equity/stop_dist/scale…
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "risk_sizing_decision"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["order"]),
        ]

    def __str__(self) -> str:
        return f"SizingDecision<{self.symbol} {self.result} {self.computed_qty}>"


class RiskEvent(models.Model):
    class Type(models.TextChoices):
        DAILY_LOSS_BREACH = "DAILY_LOSS_BREACH", "Daily loss breach"
        KILL_SWITCH_ON = "KILL_SWITCH_ON", "Kill switch on"
        KILL_SWITCH_OFF = "KILL_SWITCH_OFF", "Kill switch off"
        SOFT_STOP = "SOFT_STOP", "Soft stop"
        SIZING_REJECT = "SIZING_REJECT", "Sizing reject"
        FLATTEN = "FLATTEN", "Flatten"

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="risk_events"
    )
    type = models.CharField(max_length=24, choices=Type.choices, db_index=True)
    scope = models.CharField(max_length=16, blank=True, default="")
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "risk_event"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"RiskEvent<{self.type} user={self.user_id}>"
