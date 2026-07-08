"""Performance metrics (M09 §6.6, AC-09-6).

All metrics implemented in-repo over numpy/pandas — no quantstats. Annualisation
on 252 trading days. Named ``stats.py`` (NOT ``metrics.py`` — that name is
reserved for the Prometheus objects, repo per-app convention §12). Every metric
is unit-tested against hand-computed fixtures (§10.1).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

ANNUALIZATION = 252


def _finite(x, default=0.0):
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return default
    return xf if math.isfinite(xf) else default


def drawdown_series(equity: pd.Series) -> pd.Series:
    if equity is None or len(equity) == 0:
        return pd.Series(dtype="float64")
    running_max = equity.cummax()
    return equity / running_max - 1.0


def compute_metrics(
    equity: pd.Series,
    trades: list,
    initial_cash: float,
    exposure_bars: int,
    n_bars: int,
) -> dict:
    """Full AC-09-6 metric set for one OOS curve + its trades."""
    empty = {
        "total_return": 0.0, "cagr": 0.0, "sharpe": 0.0, "sortino": 0.0, "mar": 0.0,
        "max_drawdown": 0.0, "win_pct": 0.0, "profit_factor": None, "avg_win": 0.0,
        "avg_loss": 0.0, "expectancy": 0.0, "exposure_pct": 0.0, "turnover": 0.0,
        "trade_count": 0,
    }
    if equity is None or len(equity) == 0:
        empty["trade_count"] = len(trades)
        return empty

    eq = equity.astype("float64")
    rets = eq.pct_change().dropna().to_numpy()
    final = float(eq.iloc[-1])
    total_return = final / initial_cash - 1.0

    n_periods = len(rets)
    years = n_periods / ANNUALIZATION if n_periods else 0.0
    if years > 0 and (1.0 + total_return) > 0:
        cagr = (1.0 + total_return) ** (1.0 / years) - 1.0
    else:
        cagr = 0.0

    sharpe = _sharpe(rets)
    sortino = _sortino(rets)
    dd = drawdown_series(eq)
    max_dd = float(dd.min()) if len(dd) else 0.0
    mar = cagr / abs(max_dd) if max_dd < 0 else 0.0

    tr = _trade_stats(trades)
    exposure_pct = (exposure_bars / n_bars * 100.0) if n_bars else 0.0
    turnover = _turnover(trades, eq)

    return {
        "total_return": _finite(total_return),
        "cagr": _finite(cagr),
        "sharpe": _finite(sharpe),
        "sortino": _finite(sortino),
        "mar": _finite(mar),
        "max_drawdown": _finite(max_dd),
        "win_pct": tr["win_pct"],
        "profit_factor": tr["profit_factor"],
        "avg_win": tr["avg_win"],
        "avg_loss": tr["avg_loss"],
        "expectancy": tr["expectancy"],
        "exposure_pct": _finite(exposure_pct),
        "turnover": _finite(turnover),
        "trade_count": len(trades),
    }


def _sharpe(rets: np.ndarray) -> float:
    if len(rets) < 2:
        return 0.0
    sd = rets.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(rets.mean() / sd * math.sqrt(ANNUALIZATION))


def _sortino(rets: np.ndarray) -> float:
    if len(rets) < 2:
        return 0.0
    downside = np.minimum(rets, 0.0)
    dd = math.sqrt(float((downside ** 2).mean()))
    if dd == 0:
        return 0.0
    return float(rets.mean() / dd * math.sqrt(ANNUALIZATION))


def _trade_stats(trades: list) -> dict:
    if not trades:
        return {"win_pct": 0.0, "profit_factor": None, "avg_win": 0.0, "avg_loss": 0.0, "expectancy": 0.0}
    pnls = [float(t.pnl) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_pct = len(wins) / len(pnls) * 100.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    expectancy = sum(pnls) / len(pnls)
    return {
        "win_pct": _finite(win_pct),
        "profit_factor": _finite(profit_factor, None) if profit_factor is not None else None,
        "avg_win": _finite(avg_win),
        "avg_loss": _finite(avg_loss),
        "expectancy": _finite(expectancy),
    }


def _turnover(trades: list, equity: pd.Series) -> float:
    if not trades or len(equity) == 0:
        return 0.0
    notional = sum(t.qty * t.entry_price + t.qty * t.exit_price for t in trades)
    mean_eq = float(equity.mean())
    return notional / mean_eq if mean_eq > 0 else 0.0


def sharpe_stability(sharpes: list[float]) -> dict:
    """Per-window Sharpe stability: mean/σ across windows (AC-09-6)."""
    vals = [_finite(s) for s in sharpes]
    if not vals:
        return {"mean": 0.0, "std": 0.0, "n": 0}
    arr = np.asarray(vals, dtype="float64")
    return {
        "mean": _finite(arr.mean()),
        "std": _finite(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "n": len(vals),
    }
