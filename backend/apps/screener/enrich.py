"""Derived (local) screening criteria (M16 §6.1 "derived" rows, §6.4 step 3).

Plain Python over the bar dicts — no pandas, no numpy (§7). Everything here is
deterministic: identical bars in, identical numbers out, which is what the
§10.5 reproducibility test pins.

Windows, per §6.1:
  above_sma: n      close > SMA(n)
  sma_rising: n     SMA(n) today > SMA(n) 20 sessions ago
  near_52w_high: N  close >= (1 - N/100) x 252-session high
  min_history: N    require >= N daily bars
"""
from __future__ import annotations

SLOPE_LOOKBACK = 20   # sessions between the two SMA samples (§6.1)
HIGH_WINDOW = 252     # ~52 weeks of trading sessions

# Rounding for the one derived number we surface to the UI. Two decimals is
# what the panel renders; fixing it here (rather than in the template) is what
# keeps the stored `results` JSON byte-identical across reruns.
_PCT_DP = 2


def sorted_closes(bars: list[dict]) -> list[dict]:
    """Bars oldest-first. FMP returns newest-first; every consumer here assumes
    ascending, so normalise once rather than at each call site."""
    return sorted(bars or [], key=lambda b: str(b.get("ts")))


def _sma(closes: list[float], window: int, offset: int = 0):
    """Mean of ``window`` closes ending ``offset`` sessions before the last bar."""
    end = len(closes) - offset
    start = end - window
    if start < 0 or end <= 0:
        return None
    return sum(closes[start:end]) / window


def compute_metrics(bars: list[dict]) -> dict | None:
    """Derived metrics for one symbol, or ``None`` when there are no usable bars.

    Individual values come back ``None`` when the series is too short for that
    particular window — the caller treats an unavailable value as "does not
    pass" rather than silently widening the screen.
    """
    rows = sorted_closes(bars)
    if not rows:
        return None
    try:
        closes = [float(r["close"]) for r in rows]
        highs = [float(r.get("high", r["close"])) for r in rows]
    except (KeyError, TypeError, ValueError):
        return None
    if not closes:
        return None

    close = closes[-1]
    window_highs = highs[-HIGH_WINDOW:]
    high_252 = max(window_highs) if window_highs else None
    pct_from_high = None
    if high_252:
        pct_from_high = round((high_252 - close) / high_252 * 100, _PCT_DP)

    return {
        "n_bars": len(closes),
        "close": close,
        "sma_50": _sma(closes, 50),
        "sma_200": _sma(closes, 200),
        "sma_50_prev": _sma(closes, 50, SLOPE_LOOKBACK),
        "sma_200_prev": _sma(closes, 200, SLOPE_LOOKBACK),
        "high_252": high_252,
        "pct_from_52w_high": pct_from_high,
    }


def passes(metrics: dict, derived: dict) -> bool:
    """Does one candidate satisfy every derived criterion?

    A criterion whose input could not be computed (series too short for that
    window) is a FAIL, never a pass-by-default.
    """
    for window in derived.get("above_sma", []):
        sma = metrics.get(f"sma_{window}")
        if sma is None or not metrics["close"] > sma:
            return False
    for window in derived.get("sma_rising", []):
        now, prev = metrics.get(f"sma_{window}"), metrics.get(f"sma_{window}_prev")
        if now is None or prev is None or not now > prev:
            return False
    pct = derived.get("near_52w_high")
    if pct is not None:
        high = metrics.get("high_252")
        if high is None or not metrics["close"] >= (1 - pct / 100) * high:
            return False
    return True


def result_row(vendor_row: dict, metrics: dict | None) -> dict:
    """One results-table row: vendor identity + the locally derived columns.

    Key order is fixed so the stored JSON is byte-stable (§10.5).
    """
    m = metrics or {}
    close = m.get("close")
    sma_50, sma_200 = m.get("sma_50"), m.get("sma_200")
    sma_200_prev = m.get("sma_200_prev")
    return {
        "symbol": (vendor_row.get("symbol") or "").upper(),
        "name": vendor_row.get("companyName") or "",
        "exchange": vendor_row.get("exchangeShortName") or vendor_row.get("exchange") or "",
        "sector": vendor_row.get("sector") or "",
        "market_cap": vendor_row.get("marketCap"),
        "price": vendor_row.get("price"),
        "volume": vendor_row.get("volume"),
        "beta": vendor_row.get("beta"),
        "pct_from_52w_high": m.get("pct_from_52w_high"),
        "above_sma_50": None if (close is None or sma_50 is None) else close > sma_50,
        "above_sma_200": None if (close is None or sma_200 is None) else close > sma_200,
        "sma200_rising": (
            None if (sma_200 is None or sma_200_prev is None) else sma_200 > sma_200_prev
        ),
    }


def rank(rows: list[dict], derived: dict) -> list[dict]:
    """§6.4 step 4 — ``pct_from_52w_high`` ascending when ``near_52w_high`` is
    in play, else vendor market cap descending. **Ties always break on symbol**,
    so the order is total and reproducible (AC-06-10 spirit)."""
    if derived.get("near_52w_high") is not None:
        def key(r):
            pct = r.get("pct_from_52w_high")
            # Unranked (no 52w data) sorts last, still deterministically.
            return (pct is None, pct if pct is not None else 0.0, r["symbol"])
    else:
        def key(r):
            cap = r.get("market_cap")
            return (cap is None, -(cap or 0), r["symbol"])
    return sorted(rows, key=key)
