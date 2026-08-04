"""Market-data models (M06 §6.2).

``Bar`` is an idempotent OHLCV store keyed on ``(symbol, tf, ts)``. The plan
calls for month-based Postgres partitioning; that is an index-size optimization
deferred to a follow-up (documented in ADR-061) — the functional contract is a
plain indexed table, which is SQLite-testable and correct at MVP scale.
"""
from __future__ import annotations

from django.conf import settings
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


class DataProviderKey(models.Model):
    """The instance's API key for one market-data vendor (ADR-062).

    ONE row per provider — these are deliberately instance-wide, not per-user:
    the regime pipeline and screener consume shared market data, and a
    self-hosted deployment runs on a single vendor subscription. Set by staff
    via ``PUT /api/v1/marketdata/keys/{provider}/`` (Settings → Data
    Providers); ``FMP_API_KEY`` / ``FRED_API_KEY`` env vars remain the
    fallback (``apps.marketdata.keys.resolve_key``).

    The key is Fernet-wrapped with the shared platform KEK. Bytes never leave
    ``apps.marketdata.keys``; serializers are write-only and never echo.
    """

    class Provider(models.TextChoices):
        FMP = "FMP", "Financial Modeling Prep"
        FRED = "FRED", "FRED (St. Louis Fed)"

    id = models.BigAutoField(primary_key=True)
    provider = models.CharField(max_length=8, choices=Provider.choices, unique=True)
    key_encrypted = models.BinaryField(help_text="Fernet-wrapped API key (platform KEK).")
    key_hint = models.CharField(
        max_length=4, blank=True, default="",
        help_text="Last 4 chars, display-only; empty for short keys.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "marketdata_provider_key"

    def __str__(self) -> str:  # never includes key material
        return f"DataProviderKey<{self.provider} hint=…{self.key_hint}>"
