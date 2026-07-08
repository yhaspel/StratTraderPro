"""Walk-forward backtester models (M09 §8).

Three tables, SQLite-compatible by construction (JSON + BinaryField) so the
default test suite needs no Postgres:

- ``BacktestRun`` — one walk-forward run over 1–10 symbols. Holds the full
  AC-09-1 config, live status/stage/pct, the terminal ``summary`` (per-symbol
  headline metrics incl. PBO — the source for the runs list AND the
  post-eviction record), the reproducibility ``metrics_hash``, and retention.
- ``BacktestSegment`` — one walk-forward window's out-of-sample result for one
  symbol: train/test date ranges (half-open ``[start, end)``), the sweep's
  best params, and the OOS metrics. Unique ``(run, symbol, window_index)``.
- ``BacktestReport`` — the artifacts (canonical JSON + single-file Plotly HTML +
  WeasyPrint PDF). Eviction nulls the artifacts; ``run.summary`` + segments
  survive (AC-09-11).
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class BacktestRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        CANCELLING = "CANCELLING", "Cancelling"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    class Stage(models.TextChoices):
        QUEUED = "queued", "Queued"
        LOADING = "loading", "Loading"
        SWEEPING = "sweeping", "Sweeping"
        REPLAYING = "replaying", "Replaying"
        REPORTING = "reporting", "Reporting"

    # Terminal states — no further transitions, safe to report/evict.
    TERMINAL_STATUSES = (Status.COMPLETED, Status.FAILED, Status.CANCELLED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="backtest_runs"
    )
    strategy = models.ForeignKey(
        "strategies.Strategy", on_delete=models.CASCADE, related_name="backtest_runs"
    )
    config = models.JSONField(default=dict)  # full AC-09-1 payload (validated at POST)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    stage = models.CharField(max_length=12, choices=Stage.choices, default=Stage.QUEUED)
    pct = models.PositiveSmallIntegerField(default=0)  # 0..100
    error_code = models.CharField(max_length=48, blank=True, default="")
    error_message = models.CharField(max_length=512, blank=True, default="")
    # Per-symbol headline metrics incl. PBO, written at completion. Source for the
    # runs list and the post-eviction record (survives artifact eviction).
    summary = models.JSONField(default=dict, blank=True)
    metrics_hash = models.CharField(max_length=64, blank=True, default="")
    retention_days = models.PositiveSmallIntegerField(default=90)
    celery_task_id = models.CharField(max_length=64, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "backtest_run"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"BacktestRun<{self.id} {self.status} {self.stage} {self.pct}%>"

    @property
    def is_active(self) -> bool:
        return self.status in (self.Status.QUEUED, self.Status.RUNNING, self.Status.CANCELLING)


class BacktestSegment(models.Model):
    id = models.BigAutoField(primary_key=True)
    run = models.ForeignKey(
        BacktestRun, on_delete=models.CASCADE, related_name="segments"
    )
    symbol = models.CharField(max_length=16)
    window_index = models.PositiveSmallIntegerField()
    # All ranges are half-open [start, end) calendar days (plan §6.4).
    train_start = models.DateField()
    train_end = models.DateField()
    test_start = models.DateField()
    test_end = models.DateField()
    best_params = models.JSONField(default=dict)
    oos_metrics = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "backtest_segment"
        unique_together = ("run", "symbol", "window_index")
        indexes = [models.Index(fields=["run", "symbol", "window_index"])]

    def __str__(self) -> str:
        return f"BacktestSegment<{self.run_id} {self.symbol} w{self.window_index}>"


class BacktestReport(models.Model):
    """Artifacts for a completed run. Eviction (AC-09-11) nulls ``json``/``html``/
    ``pdf`` and zeroes the byte counts; the row + ``run.summary`` + segments stay."""

    id = models.BigAutoField(primary_key=True)
    run = models.OneToOneField(
        BacktestRun, on_delete=models.CASCADE, related_name="report"
    )
    json = models.JSONField(null=True, blank=True)  # canonical, hashable (metrics_hash)
    html = models.BinaryField(null=True, blank=True)  # single-file inline-Plotly HTML
    pdf = models.BinaryField(null=True, blank=True)  # WeasyPrint tearsheet
    html_bytes = models.IntegerField(default=0)
    pdf_bytes = models.IntegerField(default=0)
    json_bytes = models.IntegerField(default=0)
    evicted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "backtest_report"

    def __str__(self) -> str:
        return f"BacktestReport<{self.run_id} pdf={self.pdf_bytes}B>"

    def evict(self) -> None:
        """Null the artifacts, keep the metrics record (AC-09-11)."""
        from django.utils import timezone

        self.json = None
        self.html = None
        self.pdf = None
        self.html_bytes = 0
        self.pdf_bytes = 0
        self.json_bytes = 0
        self.evicted_at = timezone.now()
        self.save(update_fields=[
            "json", "html", "pdf", "html_bytes", "pdf_bytes", "json_bytes",
            "evicted_at",
        ])
