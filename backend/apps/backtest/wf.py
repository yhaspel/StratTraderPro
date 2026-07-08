"""Walk-forward orchestrator (M09 §6.4).

Windows are **calendar days** over daily bars, half-open ``[start, end)``
throughout. Rolling mode slides the train window; anchored mode grows it from
``cfg.start``. Trailing days that don't fill a complete train+test window are
dropped. MVP: ``step_days == test_days`` ⇒ contiguous, non-overlapping OOS
segments, so the concatenated OOS curve double-counts nothing.

The golden worked example (pins the §10.1 fixtures):
``start=2020-01-01, end=2021-01-01, train=180, test=60, step=60, rolling`` ⇒
3 windows; ``w_i``'s test start == ``w_{i-1}``'s test end.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from . import stats
from .replay_engine import ReplayConfig, ReplayResult, replay


@dataclass(frozen=True)
class WFConfig:
    start: date
    end: date
    train_days: int
    test_days: int
    step_days: int
    anchored: bool = False


@dataclass(frozen=True)
class Window:
    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date


@dataclass
class WindowResult:
    window: Window
    best_params: dict
    replay: ReplayResult
    oos_metrics: dict


@dataclass
class SymbolResult:
    symbol: str
    windows: list[WindowResult] = field(default_factory=list)
    oos_equity: pd.Series = field(default_factory=lambda: pd.Series(dtype="float64"))
    oos_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype="float64"))


def compute_windows(cfg: WFConfig) -> list[Window]:
    """Pure date math (§6.4). Reproduces the golden worked example exactly."""
    windows: list[Window] = []
    span = timedelta(days=cfg.train_days + cfg.test_days)
    t = cfg.start
    idx = 0
    while t + span <= cfg.end:
        train_start = cfg.start if cfg.anchored else t
        train_end = t + timedelta(days=cfg.train_days)
        test_start = train_end
        test_end = train_end + timedelta(days=cfg.test_days)
        windows.append(Window(idx, train_start, train_end, test_start, test_end))
        t += timedelta(days=cfg.step_days)
        idx += 1
    return windows


def concat_oos(equities: list[pd.Series], initial_cash: float) -> tuple[pd.Series, pd.Series]:
    """Compound each segment's within-segment daily returns into one continuous
    OOS equity curve (return space — equity does not carry across windows)."""
    rets = []
    for eq in equities:
        if len(eq) >= 2:
            rets.append(eq.pct_change().dropna())
    if not rets:
        return pd.Series(dtype="float64"), pd.Series(dtype="float64")
    all_r = pd.concat(rets).sort_index()
    curve = (1.0 + all_r).cumprod() * initial_cash
    return curve, all_r


def walk_forward(
    *,
    adapter,
    bars: pd.DataFrame,
    symbol: str,
    cfg: WFConfig,
    sweep_engine,
    replay_cfg: ReplayConfig,
    metric: str,
    grid: dict,
    costs: dict,
    profile=None,
    should_cancel=None,
    on_window=None,
) -> SymbolResult:
    """Run the walk-forward for one symbol: per window, sweep the train segment,
    take the best params, replay the test segment, then concatenate OOS."""
    windows = compute_windows(cfg)
    win_results: list[WindowResult] = []
    for w in windows:
        if should_cancel is not None and should_cancel():
            break
        ranking = sweep_engine.run(bars, w.train_start, w.train_end, adapter, grid, costs, metric)
        best = ranking.top()
        signals = adapter.generate_signals(bars, best)
        rr = replay(bars, signals, symbol, w.test_start, w.test_end, replay_cfg, profile=profile)
        oos_metrics = stats.compute_metrics(
            rr.equity, rr.trades, replay_cfg.initial_cash, rr.exposure_bars, rr.n_bars
        )
        win_results.append(WindowResult(window=w, best_params=best, replay=rr, oos_metrics=oos_metrics))
        if on_window is not None:
            on_window(w.index + 1, len(windows))

    oos_equity, oos_returns = concat_oos([wr.replay.equity for wr in win_results], replay_cfg.initial_cash)
    return SymbolResult(symbol=symbol, windows=win_results, oos_equity=oos_equity, oos_returns=oos_returns)
