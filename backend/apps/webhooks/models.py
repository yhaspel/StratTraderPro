"""Webhooks app — models (M04 §8).

``AlertMessage`` is the ingest audit row. It is created once a request reaches
secret-verification for a *known* ``WebhookConfig`` (unknown user/strategy get
a generic 401 with no row, to avoid an unbounded-row DoS and any existence
oracle). The ``sig`` field is stripped from ``body_json`` before persistence —
the raw secret never hits the database.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class AlertMessage(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"
        DUPLICATE = "DUPLICATE", "Duplicate"
        INVALID = "INVALID", "Invalid"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alert_messages"
    )
    strategy = models.ForeignKey(
        "strategies.Strategy",
        on_delete=models.CASCADE,
        related_name="alert_messages",
    )
    body_json = models.JSONField(
        default=dict, help_text="Inbound payload with the `sig` field stripped."
    )
    idempotency_key = models.CharField(max_length=128, blank=True, default="", db_index=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RECEIVED)
    reject_reason = models.CharField(max_length=48, blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "webhooks_alert_message"
        indexes = [
            models.Index(fields=["user", "-received_at"]),
            models.Index(fields=["idempotency_key"]),
        ]
        constraints = [
            # P2-5: the committed row is the durable idempotency anchor (survives a
            # crash between the old SETNX and dispatch). Partial — only non-empty
            # keys are unique, so keyless alerts and audit-only SIG_BAD/INVALID
            # rows (which carry no key) can coexist freely.
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                condition=models.Q(idempotency_key__gt=""),
                name="uniq_alert_user_idempotency",
            ),
        ]

    def __str__(self) -> str:
        return f"AlertMessage<{self.id} {self.status}>"
