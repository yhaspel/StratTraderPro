"""Bars → DataFrame loader (M09 §6.0).

Loads the local ``marketdata.Bar`` store into a clean pandas frame for the
sweep + replay engines. **No live provider calls** — data comes from the DB
only; missing data means the operator runs the M06 backfill first.

Conventions (single source of the half-open rule for the whole milestone):

- All date intervals are **half-open ``[start, end)``**. Callers pass ``date``
  boundaries; the loader materialises everything strictly before ``end``.
- ``warmup_bars`` extra rows are fetched *before* ``start`` so indicator lookback
  never sees NaN at a window boundary and never peeks forward.
- Coverage is validated over **weekdays** (US markets close ~9 weekdays/year, so
  perfect data ≈ 96.5% of weekdays): if < 95% of weekdays in ``[start, end)``
  carry a bar, fail fast with ``BACKTEST_INSUFFICIENT_DATA``.
"""
from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone

import pandas as pd

from apps.marketdata.models import Bar

from .exceptions import INSUFFICIENT_DATA, BacktestError

COVERAGE_MIN = 0.95  # ≥ 95% of weekdays present (tolerates the ~3.5% holiday deficit)

_COLUMNS = ["open", "high", "low", "close", "volume"]


def _to_utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=dt_timezone.utc)


def load_bars(
    symbol: str, tf: str, start: date, end: date, warmup_bars: int = 0
) -> pd.DataFrame:
    """Return an OHLCV frame for ``[start, end)`` plus ``warmup_bars`` rows before
    ``start``. UTC ``DatetimeIndex``, float64 OHLC, int64 volume, sorted, deduped.

    Raises ``BACKTEST_INSUFFICIENT_DATA`` when weekday coverage over ``[start, end)``
    (warm-up excluded) is below :data:`COVERAGE_MIN`.
    """
    symbol = symbol.upper()
    start_dt = _to_utc_midnight(start)
    end_dt = _to_utc_midnight(end)

    # In-range rows: strictly [start, end).
    in_range = list(
        Bar.objects.filter(symbol=symbol, tf=tf, ts__gte=start_dt, ts__lt=end_dt)
        .order_by("ts")
        .values("ts", *_COLUMNS)
    )
    # Warm-up rows: the last `warmup_bars` bars strictly before start.
    warmup_rows: list[dict] = []
    if warmup_bars > 0:
        warmup_rows = list(
            Bar.objects.filter(symbol=symbol, tf=tf, ts__lt=start_dt)
            .order_by("-ts")
            .values("ts", *_COLUMNS)[:warmup_bars]
        )
        warmup_rows.reverse()  # back to ascending

    _validate_coverage(symbol, in_range, start, end)

    rows = warmup_rows + in_range
    if not rows:
        raise BacktestError(
            INSUFFICIENT_DATA,
            f"No bars for {symbol} {tf} in [{start}, {end}).",
        )
    frame = pd.DataFrame.from_records(rows)
    idx = pd.DatetimeIndex(pd.to_datetime([r["ts"] for r in rows], utc=True))
    frame = frame.drop(columns=["ts"])
    frame.index = idx
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    for col in ("open", "high", "low", "close"):
        frame[col] = frame[col].astype("float64")
    frame["volume"] = frame["volume"].astype("int64")
    frame.index.name = "ts"
    return frame[_COLUMNS]


def _validate_coverage(symbol: str, in_range_rows: list[dict], start: date, end: date) -> None:
    """Weekday-coverage rule (§6.0). ``in_range_rows`` are the bars strictly inside
    ``[start, end)`` — warm-up rows are intentionally excluded."""
    present_days = {r["ts"].date() for r in in_range_rows}
    expected = _weekdays(start, end)
    if not expected:
        raise BacktestError(
            INSUFFICIENT_DATA,
            f"Range [{start}, {end}) contains no weekdays.",
        )
    present = sum(1 for d in expected if d in present_days)
    coverage = present / len(expected)
    if coverage < COVERAGE_MIN:
        gaps = _largest_gaps(expected, present_days)
        raise BacktestError(
            INSUFFICIENT_DATA,
            (
                f"{symbol}: only {present}/{len(expected)} weekdays present "
                f"({coverage:.1%} < {COVERAGE_MIN:.0%}). Largest gaps: {gaps}. "
                f"Run the M06 backfill first."
            ),
            details={"coverage": coverage, "present": present, "expected": len(expected)},
        )


def _weekdays(start: date, end: date) -> list[date]:
    """Weekday dates in half-open ``[start, end)``."""
    out: list[date] = []
    cur = start
    one = pd.Timedelta(days=1)
    ts = pd.Timestamp(cur)
    end_ts = pd.Timestamp(end)
    while ts < end_ts:
        if ts.weekday() < 5:
            out.append(ts.date())
        ts += one
    return out


def _largest_gaps(expected: list[date], present: set[date], top: int = 3) -> list[str]:
    """Describe the longest consecutive runs of missing weekdays (for the error)."""
    runs: list[tuple[date, date, int]] = []
    run_start: date | None = None
    prev: date | None = None
    for d in expected:
        if d not in present:
            if run_start is None:
                run_start = d
            prev = d
        else:
            if run_start is not None:
                runs.append((run_start, prev, _count(expected, run_start, prev)))
                run_start = None
    if run_start is not None:
        runs.append((run_start, prev, _count(expected, run_start, prev)))
    runs.sort(key=lambda r: r[2], reverse=True)
    return [f"{a}..{b} ({n}d)" for a, b, n in runs[:top]]


def _count(expected: list[date], a: date, b: date) -> int:
    return sum(1 for d in expected if a <= d <= b)
