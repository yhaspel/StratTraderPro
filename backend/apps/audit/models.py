"""Audit log models (M10 §6.1 / §8).

``AuditLog`` is an append-only, hash-chained table. The chain is computed in
application code (``services.emit`` → ``hashing``); Postgres triggers
(``migration 0002``) enforce append-only + linkage. ``AuditVerifierState`` is the
nightly verifier's resume cursor.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .events import EVENT_TYPE_CHOICES


class AuditLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    # default=timezone.now (NOT auto_now_add): emit() assigns the timestamp once,
    # hashes that exact value, and inserts it. auto_now_add would overwrite the
    # hashed value in pre_save → every row would fail verification, and the
    # historical AuthEvent backfill (0003) could not insert past timestamps.
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    # DO_NOTHING + db_constraint=False: the audit log is append-only (0002
    # triggers), so a user delete must NOT emit an UPDATE (SET_NULL) or a
    # cascading DELETE against audit_log — the trigger blocks both. Dropping the
    # DB FK lets the user_id/actor_id UUID dangle after the user row is gone,
    # preserving the immutable row (and its hash) exactly as written.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        null=True,
        blank=True,
        related_name="audit_actions",
    )
    event_type = models.CharField(max_length=64, choices=EVENT_TYPE_CHOICES)
    entity_type = models.CharField(max_length=64, blank=True, default="")
    entity_id = models.CharField(max_length=64, blank=True, default="")
    data_before = models.JSONField(null=True, blank=True)
    data_after = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    ua = models.CharField(max_length=512, blank=True, default="")
    prev_hash = models.CharField(max_length=64)
    self_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "audit_log"
        indexes = [
            models.Index(fields=["user", "occurred_at"]),
            models.Index(fields=["actor", "occurred_at"]),
            models.Index(fields=["event_type", "occurred_at"]),
            models.Index(fields=["entity_type", "entity_id", "occurred_at"]),
            models.Index(fields=["occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"AuditLog<{self.id} {self.event_type} {self.occurred_at:%Y-%m-%dT%H:%M:%S}>"


class AuditVerifierState(models.Model):
    """Singleton cursor for the nightly integrity verifier (pk fixed to 1)."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    last_verified_id = models.BigIntegerField(default=0)
    last_verified_hash = models.CharField(max_length=64, blank=True, default="")
    run_at = models.DateTimeField(null=True, blank=True)
    result = models.CharField(max_length=16, blank=True, default="")

    class Meta:
        db_table = "audit_verifier_state"

    @classmethod
    def load(cls) -> "AuditVerifierState":
        obj, _ = cls.objects.get_or_create(id=1)
        return obj

    def __str__(self) -> str:
        return f"AuditVerifierState<last_id={self.last_verified_id} result={self.result}>"
