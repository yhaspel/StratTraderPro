"""Market-data models (M06 §6.2).

``Bar`` is an idempotent OHLCV store keyed on ``(symbol, tf, ts)``. The plan
calls for month-based Postgres partitioning; that is an index-size optimization
deferred to a follow-up (documented in ADR-061) — the functional contract is a
plain indexed table, which is SQLite-testable and correct at MVP scale.
"""
from __future__ import annotations

from django.db import models


class Bar(models.Model):
    class TF(models.TextChoices):
        M1 = "1m", "1 minute"
        M5 = "5m", "5 minutes"
        M15 = "15m", "15 minutes"
        H1 = "1h", "1 hour"
        D1 = "1d", "1 day"

    id = models.BigAutoField(primary_key=True)
    symbol = models.CharField(max_length=16, db_index=True)
    tf = models.CharField(max_length=4, choices=TF.choices)
    ts = models.DateTimeField(db_index=True)
    open = models.DecimalField(max_digits=18, decimal_places=6)
    high = models.DecimalField(max_digits=18, decimal_places=6)
    low = models.DecimalField(max_digits=18, decimal_places=6)
    close = models.DecimalField(max_digits=18, decimal_places=6)
    volume = models.BigIntegerField(default=0)
    source = models.CharField(max_length=16, default="FMP")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "marketdata_bar"
        unique_together = ("symbol", "tf", "ts")
        indexes = [models.Index(fields=["symbol", "tf", "ts"])]

    def __str__(self) -> str:
        return f"Bar<{self.symbol} {self.tf} {self.ts:%Y-%m-%d} c={self.close}>"


class MacroSeries(models.Model):
    """A single macro/credit observation (FRED or FMP) — e.g. HY OAS, 10Y-2Y."""

    id = models.BigAutoField(primary_key=True)
    series_id = models.CharField(max_length=32, db_index=True)  # e.g. BAMLH0A0HYM2
    ts = models.DateField()
    value = models.DecimalField(max_digits=18, decimal_places=6)
    source = models.CharField(max_length=16, default="FRED")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "marketdata_macro_series"
        unique_together = ("series_id", "ts")
        indexes = [models.Index(fields=["series_id", "ts"])]

    def __str__(self) -> str:
        return f"MacroSeries<{self.series_id} {self.ts} {self.value}>"
