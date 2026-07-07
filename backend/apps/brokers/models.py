"""Brokers app — models (M04 §8).

- ``BrokerAccount``  — a user's connected broker (Alpaca paper in M04). API
  key pair is Fernet-wrapped at rest with the shared platform KEK (same
  pattern as MFA + webhook secrets — see ``apps.brokers.services``). Write-only
  at the serializer layer; never echoed back.
- ``TradingHalt``    — per-user / per-strategy kill-switch flag. ``released_at
  IS NULL`` means active. M08 builds the full four-level engine ON THIS TABLE
  (do not fork a parallel model — plan §8 / M08 note).
- ``BrokerCallAudit`` — one row per adapter→broker call (endpoint, status,
  latency). NEVER stores request/response bodies or credentials (AC-04-12).
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class BrokerAccount(models.Model):
    class Broker(models.TextChoices):
        ALPACA = "ALPACA", "Alpaca"

    class Mode(models.TextChoices):
        PAPER = "PAPER", "Paper"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONNECTED = "CONNECTED", "Connected"
        DEGRADED = "DEGRADED", "Degraded"
        DOWN = "DOWN", "Down"
        ERROR = "ERROR", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="broker_accounts",
    )
    broker = models.CharField(max_length=16, choices=Broker.choices, default=Broker.ALPACA)
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.PAPER)
    # Fernet-wrapped API key pair. Bytes never leave apps.brokers.services.
    api_key_id_enc = models.BinaryField(help_text="Fernet-wrapped Alpaca API key ID.")
    api_secret_enc = models.BinaryField(help_text="Fernet-wrapped Alpaca API secret.")
    account_number = models.CharField(max_length=64, blank=True, default="")
    nickname = models.CharField(max_length=64, blank=True, default="")
    is_default = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    last_connected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "brokers_account"
        unique_together = ("user", "broker", "account_number")
        indexes = [
            models.Index(fields=["user", "is_default"]),
            models.Index(fields=["broker", "mode"]),
        ]

    def __str__(self) -> str:
        return f"BrokerAccount<{self.broker}:{self.account_number} user={self.user_id}>"

    def __repr__(self) -> str:  # pragma: no cover — redaction guard
        return f"BrokerAccount<{self.id} {self.broker} {self.mode}>"


class TradingHalt(models.Model):
    """Kill-switch flag. Active while ``released_at`` is NULL.

    ``strategy=NULL`` → user-level halt (all strategies).
    ``strategy=<row>`` → strategy-level halt (that strategy only).
    M08 extends this table with severity levels + auto-flatten semantics.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trading_halts",
    )
    strategy = models.ForeignKey(
        "strategies.Strategy",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="trading_halts",
        help_text="NULL = user-level halt (all strategies).",
    )
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "brokers_trading_halt"
        indexes = [
            models.Index(fields=["user", "released_at"]),
            models.Index(fields=["strategy", "released_at"]),
        ]

    @property
    def is_active(self) -> bool:
        return self.released_at is None

    @property
    def scope(self) -> str:
        return "STRATEGY" if self.strategy_id else "USER"

    def __str__(self) -> str:
        state = "active" if self.is_active else "released"
        return f"TradingHalt<{self.scope} user={self.user_id} {state}>"


class BrokerCallAudit(models.Model):
    """One row per adapter→broker HTTP call. Bodies and keys are NEVER stored
    (AC-04-12) — only endpoint name, status, latency and a mapped error code."""

    id = models.BigAutoField(primary_key=True)
    broker_account = models.ForeignKey(
        BrokerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="call_audits",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    broker = models.CharField(max_length=16, default=BrokerAccount.Broker.ALPACA)
    endpoint = models.CharField(max_length=64, help_text="SDK method name, e.g. submit_order.")
    method = models.CharField(max_length=8, default="GET")
    status_code = models.IntegerField(null=True, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    ok = models.BooleanField(default=True)
    error_code = models.CharField(max_length=48, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "brokers_call_audit"
        indexes = [
            models.Index(fields=["broker_account", "created_at"]),
            models.Index(fields=["endpoint", "ok"]),
        ]

    def __str__(self) -> str:
        return f"BrokerCallAudit<{self.endpoint} ok={self.ok} {self.latency_ms}ms>"
