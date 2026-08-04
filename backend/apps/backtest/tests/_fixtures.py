"""Shared test fixtures for the backtester suite (M09 §10)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone

import numpy as np
import pandas as pd

# A few US market holidays used to exercise the weekday-coverage rule with a
# real-shaped calendar (the happy-path integration fixture must include gaps).
DEFAULT_HOLIDAYS = {
    date(2020, 1, 1), date(2020, 1, 20), date(2020, 2, 17), date(2020, 5, 25),
    date(2020, 7, 3), date(2020, 9, 7), date(2020, 11, 26), date(2020, 12, 25),
    date(2021, 1, 1), date(2021, 1, 18), date(2021, 2, 15), date(2021, 5, 31),
    date(2019, 11, 28), date(2019, 12, 25), date(2019, 1, 1),
}


def make_bar_rows(
    start: date, end: date, *, seed: int = 0, holidays=DEFAULT_HOLIDAYS,
    base: float = 100.0, drift: float = 0.06, vol: float = 1.0, volume: int = 1_000_000,
) -> list[dict]:
    """Weekday daily OHLCV rows over half-open ``[start, end)`` (weekends +
    holidays omitted), a seeded random walk. Prices are clean 2-dp floats so the
    Decimal ATR-14 path is bit-stable (sizing parity)."""
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    cur = start
    price = base
    while cur < end:
        if cur.weekday() < 5 and cur not in holidays:
            price = max(1.0, price + drift + rng.normal(0, vol))
            close = round(price, 2)
            op = round(max(1.0, close - rng.normal(0, vol * 0.5)), 2)
            hi = round(max(op, close) + abs(rng.normal(0, vol * 0.3)), 2)
            lo = round(max(0.5, min(op, close) - abs(rng.normal(0, vol * 0.3))), 2)
            rows.append({
                "ts": datetime(cur.year, cur.month, cur.day, tzinfo=dt_timezone.utc),
                "open": op, "high": hi, "low": lo, "close": close, "volume": volume,
            })
        cur += timedelta(days=1)
    return rows


def seed_bars(symbol: str, start: date, end: date, **kw) -> int:
    from apps.marketdata.services import upsert_bars

    rows = make_bar_rows(start, end, **kw)
    upsert_bars(symbol, "1d", rows)
    return len(rows)


def bars_df(rows: list[tuple], start: date = date(2020, 1, 1)) -> pd.DataFrame:
    """Build an OHLCV frame from explicit (open, high, low, close, volume) rows on
    a consecutive daily UTC index (for hand-computable replay golden tests)."""
    idx = pd.DatetimeIndex(
        [pd.Timestamp(start, tz="UTC") + pd.Timedelta(days=i) for i in range(len(rows))]
    )
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype("float64")
    df["volume"] = df["volume"].astype("int64")
    df.index.name = "ts"
    return df


def signals_df(index, entries_at=(), exits_at=(), stop_pct=None, target_pct=None) -> pd.DataFrame:
    out = pd.DataFrame(index=index)
    out["entries"] = False
    out["exits"] = False
    for i in entries_at:
        out.iloc[i, out.columns.get_loc("entries")] = True
    for i in exits_at:
        out.iloc[i, out.columns.get_loc("exits")] = True
    if stop_pct is not None:
        out["stop_pct"] = float(stop_pct)
    if target_pct is not None:
        out["target_pct"] = float(target_pct)
    return out
