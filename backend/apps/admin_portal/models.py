"""Admin-portal models (M10 §6.2 / §6.4)."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ImpersonationSession(models.Model):
    """A read-only, time-boxed admin impersonation of a target user (AC-10-7)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="impersonations_started"
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="impersonated_as"
    )
    reason = models.CharField(max_length=255)
    started_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    ua = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        db_table = "admin_impersonation_session"
        indexes = [
            models.Index(fields=["actor", "-started_at"]),
            models.Index(fields=["target", "-started_at"]),
        ]

    @property
    def is_active(self) -> bool:
        return self.ended_at is None and self.expires_at > timezone.now()

    def __str__(self) -> str:
        return f"Impersonation<{self.actor_id}→{self.target_id} active={self.is_active}>"


class FeatureFlag(models.Model):
    """DB override for a registry flag (M10 §6.4). Absence → env default."""

    name = models.CharField(max_length=64, unique=True)
    enabled = models.BooleanField()
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "admin_feature_flag"

    def __str__(self) -> str:
        return f"FeatureFlag<{self.name}={self.enabled}>"
