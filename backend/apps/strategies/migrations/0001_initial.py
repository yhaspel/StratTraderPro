"""M03 — initial Strategies migration.

Creates Strategy, StrategyFile, WebhookConfig per
``project-plan/03-strategies-and-webhook-config.md`` §6.1.
"""
from __future__ import annotations

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Strategy",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=64)),
                ("slug", models.SlugField(max_length=64)),
                ("description_short", models.CharField(
                    blank=True, default="",
                    help_text="One-line summary surfaced in the list view (extracted from description file or set via admin).",
                    max_length=256,
                )),
                ("is_system", models.BooleanField(default=False)),
                ("is_enabled", models.BooleanField(
                    default=True,
                    help_text="Soft-delete flag. False = hidden from default list.",
                )),
                ("is_community_tested", models.BooleanField(
                    default=False,
                    help_text="Reserved for a future review workflow. Always False today for user uploads; some system rows may be flagged True by ops once stress-tested.",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(
                    blank=True,
                    help_text="NULL for system-seeded strategies.",
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="strategies",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "strategies_strategy",
                "unique_together": {("owner", "slug")},
            },
        ),
        migrations.AddIndex(
            model_name="strategy",
            index=models.Index(fields=["owner", "is_enabled"], name="strategies__owner_i_3457b5_idx"),
        ),
        migrations.AddIndex(
            model_name="strategy",
            index=models.Index(fields=["is_system", "is_enabled"], name="strategies__is_syst_d286e1_idx"),
        ),
        migrations.CreateModel(
            name="StrategyFile",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(
                    choices=[("PINE", "Pine"), ("DESC", "Description"), ("WEBHOOK_TEMPLATE", "Webhook Template")],
                    max_length=24,
                )),
                ("filename", models.CharField(max_length=128)),
                ("sha256", models.CharField(db_index=True, max_length=64)),
                ("content", models.BinaryField(
                    blank=True,
                    help_text="In-DB bytes for small files (≤96KB). NULL when migrated to object storage (see ``object_url``).",
                    null=True,
                )),
                ("object_url", models.CharField(
                    blank=True,
                    help_text="S3-style URL for files migrated out of BYTEA. Reserved.",
                    max_length=512, null=True,
                )),
                ("size_bytes", models.IntegerField()),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("strategy", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="files",
                    to="strategies.strategy",
                )),
            ],
            options={
                "db_table": "strategies_strategy_file",
                "unique_together": {("strategy", "kind")},
            },
        ),
        migrations.CreateModel(
            name="WebhookConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("secret_encrypted", models.BinaryField(
                    help_text="Fernet-wrapped HMAC shared secret.",
                )),
                ("json_schema", models.JSONField(
                    default=dict,
                    help_text="JSON Schema (Draft 2020-12) the inbound payload will be validated against in M04.",
                )),
                ("payload_template", models.JSONField(
                    default=dict,
                    help_text="Default alert body shown in the Copy-TradingView-template button. Must validate against ``json_schema``.",
                )),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("rotated_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="webhook_configs",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("strategy", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="webhook_configs",
                    to="strategies.strategy",
                )),
            ],
            options={
                "db_table": "strategies_webhook_config",
                "unique_together": {("user", "strategy")},
            },
        ),
        migrations.AddIndex(
            model_name="webhookconfig",
            index=models.Index(fields=["user", "strategy"], name="strategies__user_id_cf3ce1_idx"),
        ),
    ]
