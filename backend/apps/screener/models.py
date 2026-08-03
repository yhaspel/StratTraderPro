"""Strategy-screener run storage (M16 §6.3)."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

# Retention: keep the newest N runs per (user, strategy); pruned inline by the
# task after each run finishes — no beat entry (§6.3).
HISTORY_KEEP = 20


class ScreenRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        DONE = "DONE"
        FAILED = "FAILED"

    #: Statuses that count as "an in-flight run" for the one-per-pair rule.
    ACTIVE_STATUSES = (Status.QUEUED, Status.RUNNING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="screen_runs",
    )
    strategy = models.ForeignKey(
        "strategies.Strategy", on_delete=models.CASCADE, related_name="screen_runs",
    )
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.QUEUED, db_index=True,
    )
    criteria = models.JSONField()  # parsed snapshot (reproducibility, AC-16-6)
    # A7: this stores the DESC ``StrategyFile.sha256`` at run time — the spec's
    # original ``criteria_sha256`` was a misnomer (nothing hashes the criteria).
    desc_sha256 = models.CharField(max_length=64)
    results = models.JSONField(default=list)  # [{symbol, name, exchange, sector, market_cap,
                                              #   price, volume, beta, pct_from_52w_high,
                                              #   above_sma_50, above_sma_200, sma200_rising}]
    counts = models.JSONField(default=dict)   # {vendor_matches, enriched, returned,
                                              #  insufficient_history, skipped_rate_limited,
                                              #  skipped_unavailable}   (A4 adds the last one)
    degraded = models.BooleanField(default=False)
    error_code = models.CharField(max_length=48, blank=True, default="")
    celery_task_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "screener_run"
        indexes = [models.Index(fields=["user", "strategy", "-created_at"])]
        constraints = [
            # Race hardening beyond the view's pre-check 409: two POSTs that
            # interleave between the "is a run active?" SELECT and the INSERT
            # would both pass the pre-check. The partial unique index makes the
            # second INSERT fail with IntegrityError, which the view maps to the
            # SAME 409 SCREEN_RUN_ACTIVE. Partial unique indexes work on both
            # SQLite and Postgres, so the SQLite lane proves it too.
            models.UniqueConstraint(
                fields=["user", "strategy"],
                condition=Q(status__in=["QUEUED", "RUNNING"]),
                name="uniq_active_screen_run_per_user_strategy",
            ),
        ]

    def __str__(self):
        return f"ScreenRun<{self.id} {self.status}>"

    @property
    def is_terminal(self) -> bool:
        return self.status in (self.Status.DONE, self.Status.FAILED)
