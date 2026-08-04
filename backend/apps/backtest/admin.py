"""Backtest admin (M09)."""
from __future__ import annotations

from django.contrib import admin

from .models import BacktestReport, BacktestRun, BacktestSegment


@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "strategy", "status", "stage", "pct", "created_at")
    list_filter = ("status", "stage")
    search_fields = ("id", "user__email", "strategy__slug")
    readonly_fields = ("id", "metrics_hash", "summary", "config", "created_at", "updated_at")


@admin.register(BacktestSegment)
class BacktestSegmentAdmin(admin.ModelAdmin):
    list_display = ("run", "symbol", "window_index", "test_start", "test_end")
    search_fields = ("run__id", "symbol")


@admin.register(BacktestReport)
class BacktestReportAdmin(admin.ModelAdmin):
    list_display = ("run", "html_bytes", "pdf_bytes", "json_bytes", "evicted_at", "created_at")
    readonly_fields = ("run", "html_bytes", "pdf_bytes", "json_bytes", "evicted_at", "created_at")
