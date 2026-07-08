"""Market-data services (M06 §6.2) — idempotent bar upserts + gap detection."""
from __future__ import annotations

import logging
from datetime import timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Bar, MacroSeries

logger = logging.getLogger(__name__)

_TF_DELTA = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}


def _dec(v) -> Decimal:
    return Decimal(str(v))


def upsert_bars(symbol: str, tf: str, rows: list[dict]) -> dict:
    """Idempotent upsert keyed on (symbol, tf, ts). ``rows`` are dicts with
    ts/open/high/low/close/volume. Returns counts. Safe to re-run (AC-06-1)."""
    created = updated = 0
    for r in rows:
        ts = r["ts"] if not isinstance(r["ts"], str) else parse_datetime(r["ts"])
        if ts is None:
            continue
        # A date-only string parses to naive midnight on Django 5.1 — make it
        # aware in UTC before writing to the tz-aware Bar.ts (FIX-M6-1). Keeps
        # the (symbol,tf,ts) upsert idempotent on re-run.
        if timezone.is_naive(ts):
            ts = timezone.make_aware(ts, dt_timezone.utc)
        _, was_created = Bar.objects.update_or_create(
            symbol=symbol.upper(), tf=tf, ts=ts,
            defaults={
                "open": _dec(r["open"]), "high": _dec(r["high"]),
                "low": _dec(r["low"]), "close": _dec(r["close"]),
                "volume": int(r.get("volume", 0) or 0),
                "source": r.get("source", "FMP"),
            },
        )
        created += int(was_created)
        updated += int(not was_created)
    return {"symbol": symbol.upper(), "tf": tf, "created": created, "updated": updated}


def missing_bars(symbol: str, tf: str, start, end) -> list:
    """Return the list of expected timestamps with no Bar (gap detection). For
    1d it walks calendar days (weekends are naturally absent as expected gaps —
    the caller filters to trading days)."""
    delta = _TF_DELTA.get(tf)
    if delta is None:
        return []
    have = set(
        Bar.objects.filter(symbol=symbol.upper(), tf=tf, ts__gte=start, ts__lte=end)
        .values_list("ts", flat=True)
    )
    missing = []
    cur = start
    while cur <= end:
        if tf == "1d" and cur.weekday() >= 5:  # skip Sat/Sun for daily
            cur += delta
            continue
        if cur not in have:
            missing.append(cur)
        cur += delta
    return missing


def upsert_macro(series_id: str, rows: list[dict]) -> int:
    n = 0
    for r in rows:
        _, created = MacroSeries.objects.update_or_create(
            series_id=series_id, ts=r["ts"],
            defaults={"value": _dec(r["value"]), "source": r.get("source", "FRED")},
        )
        n += int(created)
    return n
