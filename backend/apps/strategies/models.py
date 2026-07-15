"""
Strategies app — models for M03.

Tables:
- Strategy: top-level entity. ``owner=NULL`` + ``is_system=True`` marks a
  self-hoster-provided "system" strategy; user uploads have an owner and
  ``is_system=False``. The repo ships ZERO strategies — a self-hoster brings
  their own.
- StrategyFile: bytes of the .pine, description, and webhook JSON template
  per strategy. Small-file storage in BYTEA for the MVP; ``object_url`` is
  a stub for future S3-style migration.
- WebhookConfig: per-user/per-strategy HMAC secret + JSON-Schema validated
  payload template + version counter for rotation.

Design notes:
- Soft delete = ``is_enabled=False``. List view filters it out by default.
  No separate ``deleted_at`` until M10 audit-log work needs it.
- ``secret_encrypted`` is Fernet-wrapped using the same KEK as M02
  (apps/users/mfa._fernet). Plain bytes are never written to disk.
- The webhook URL itself is generated (not persisted) via
  ``services.build_webhook_url`` so we can swap the public hostname in
  M04 without a migration.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Strategy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="strategies",
        help_text="NULL for system-seeded strategies.",
    )
    name = models.CharField(max_length=64)
    slug = models.SlugField(max_length=64)
    description_short = models.CharField(
        max_length=256, blank=True, default="",
        help_text="One-line summary surfaced in the list view (extracted from "
                  "description file or set via admin).",
    )
    is_system = models.BooleanField(default=False)
    is_enabled = models.BooleanField(
        default=True,
        help_text="Soft-delete flag. False = hidden from default list.",
    )
    is_community_tested = models.BooleanField(
        default=False,
        help_text="Reserved for a future review workflow. Always False today "
                  "for user uploads; some system rows may be flagged True by "
                  "ops once stress-tested.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "strategies_strategy"
        # (NULL, slug) pairs are allowed because Postgres treats NULLs as
        # distinct in unique constraints. That's actually what we want — system
        # rows are namespaced by NULL owner; per-user uniqueness is enforced
        # at the (owner, slug) level for non-NULL owners.
        unique_together = ("owner", "slug")
        indexes = [
            models.Index(fields=["owner", "is_enabled"]),
            models.Index(fields=["is_system", "is_enabled"]),
        ]

    def __str__(self):
        owner = self.owner.email if self.owner_id else "system"
        return f"Strategy<{self.slug} owner={owner}>"


class StrategyFile(models.Model):
    class Kind(models.TextChoices):
        PINE = "PINE", "Pine"
        DESC = "DESC", "Description"
        WEBHOOK_TEMPLATE = "WEBHOOK_TEMPLATE", "Webhook Template"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    strategy = models.ForeignKey(
        Strategy, on_delete=models.CASCADE, related_name="files",
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    filename = models.CharField(max_length=128)
    sha256 = models.CharField(max_length=64, db_index=True)
    content = models.BinaryField(
        null=True, blank=True,
        help_text="In-DB bytes for small files (≤96KB). NULL when migrated to "
                  "object storage (see ``object_url``).",
    )
    object_url = models.CharField(
        max_length=512, null=True, blank=True,
        help_text="S3-style URL for files migrated out of BYTEA. Reserved.",
    )
    size_bytes = models.IntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "strategies_strategy_file"
        unique_together = ("strategy", "kind")

    def __str__(self):
        return f"StrategyFile<{self.strategy.slug}/{self.kind}>"


class WebhookConfig(models.Model):
    """Per-user, per-strategy webhook configuration.

    The shared secret is Fernet-wrapped at rest. Rotation increments
    ``version`` and overwrites ``secret_encrypted`` — there is no history
    table; old secrets are *gone* after rotate (that's the point of AC-03-7).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="webhook_configs",
    )
    strategy = models.ForeignKey(
        Strategy, on_delete=models.CASCADE, related_name="webhook_configs",
    )
    secret_encrypted = models.BinaryField(
        help_text="Fernet-wrapped HMAC shared secret.",
    )
    json_schema = models.JSONField(
        default=dict,
        help_text="JSON Schema (Draft 2020-12) the inbound payload will be "
                  "validated against in M04.",
    )
    payload_template = models.JSONField(
        default=dict,
        help_text="Default alert body shown in the Copy-TradingView-template "
                  "button. Must validate against ``json_schema``.",
    )
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    rotated_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "strategies_webhook_config"
        unique_together = ("user", "strategy")
        indexes = [models.Index(fields=["user", "strategy"])]

    def __str__(self):
        return (
            f"WebhookConfig<{self.user.email} {self.strategy.slug} "
            f"v{self.version}>"
        )
