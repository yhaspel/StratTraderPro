"""Parameter-sweep engine (M09 §6.2).

vectorbt OSS 1.0.0 behind a small ``SweepEngine`` seam so the engine stays
swappable (ADR-090). Unit sizing (``size=1``) — production sizing is applied
only in the replay stage, so ranking is sizing-invariant.

**Fill alignment with the replay:** entries/exits are shifted forward one bar and
``price=open`` is passed, so sweep fills happen at next-bar open exactly like the
replay (§6.3) — required for cost-aware ranking to be comparable and for the §16
zero-cost cross-check to converge.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
import vectorbt as vbt

from .exceptions import GRID_TOO_LARGE, BacktestError

_CHUNK = 100  # evaluate ≤ 100 combos per vectorbt broadcast to bound memory (AC-09-10)
_MAX_COMBOS = 500  # §11 grid cap (also enforced at POST)


@dataclass
class SweepResult:
    combos: list[dict]
    scores: list[float]
    metric: str

    def ranked(self) -> list[tuple[dict, float]]:
        # Sort by score desc; ties broken deterministically by combo order.
        order = sorted(range(len(self.combos)), key=lambda i: (-self.scores[i], i))
        return [(self.combos[i], self.scores[i]) for i in order]

    def top(self) -> dict:
        return self.ranked()[0][0]


def make_combos(grid: dict) -> list[dict]:
    """Deterministic Cartesian product of the grid (sorted keys, list order)."""
    keys = sorted(grid)
    value_lists = [list(grid[k]) for k in keys]
    combos = [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*value_lists)]
    if len(combos) > _MAX_COMBOS:
        raise BacktestError(GRID_TOO_LARGE, f"{len(combos)} combos > {_MAX_COMBOS} cap.")
    return combos


class VectorbtSweepEngine:
    """The default ``SweepEngine`` implementation (vectorbt)."""

    def run(
        self, bars: pd.DataFrame, start: date, end: date, adapter, grid: dict, costs: dict, metric: str
    ) -> SweepResult:
        combos = make_combos(grid)
        scores: list[float] = []
        for chunk in _chunks(combos, _CHUNK):
            pf = self._portfolio(bars, start, end, adapter, chunk, costs)
            scores.extend(_metric_values(pf, metric).tolist())
        return SweepResult(combos=combos, scores=scores, metric=metric)

    def returns_matrix(
        self, bars: pd.DataFrame, start: date, end: date, adapter, grid: dict, costs: dict
    ) -> tuple[list[dict], np.ndarray]:
        """T×N matrix of per-bar net returns over ``[start, end)`` (the dedicated
        full-range sweep that feeds PBO, §6.5). Columns = combos, rows = bars."""
        combos = make_combos(grid)
        cols = []
        for chunk in _chunks(combos, _CHUNK):
            pf = self._portfolio(bars, start, end, adapter, chunk, costs)
            r = pf.returns()
            arr = r.to_numpy() if hasattr(r, "to_numpy") else np.asarray(r)
            if arr.ndim == 1:
                arr = arr.reshape(-1, 1)
            cols.append(arr)
        matrix = np.hstack(cols) if cols else np.zeros((0, 0))
        return combos, matrix

    # -- internals ----------------------------------------------------------
    def _portfolio(self, bars, start, end, adapter, combos, costs):
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC")
        mask = (bars.index >= start_ts) & (bars.index < end_ts)
        win_close = bars["close"].loc[mask].astype("float64")
        win_open = bars["open"].loc[mask].astype("float64")

        cols = [str(i) for i in range(len(combos))]
        entries = pd.DataFrame(False, index=win_close.index, columns=cols)
        exits = pd.DataFrame(False, index=win_close.index, columns=cols)
        for i, params in enumerate(combos):
            sig = adapter.generate_signals(bars, params)  # full frame (warm-up)
            entries[cols[i]] = sig["entries"].loc[mask].to_numpy(dtype=bool)
            exits[cols[i]] = sig["exits"].loc[mask].to_numpy(dtype=bool)

        # Align fills with the replay: shift one bar + fill at open (§6.2).
        entries = entries.shift(1, fill_value=False)
        exits = exits.shift(1, fill_value=False)

        slippage = float(costs.get("slippage_bps", 5.0)) / 1e4
        fees = float(costs.get("fees", 0.0))
        # Per-share commission has no exact vectorbt analogue; approximate as
        # fixed_fees = per_share × 1 under unit sizing (documented in ADR-090).
        fixed_fees = float(costs.get("per_order_usd", 0.0)) + float(costs.get("per_share_usd", 0.0))
        return vbt.Portfolio.from_signals(
            close=win_close,
            entries=entries,
            exits=exits,
            price=win_open,
            size=1,
            fees=fees,
            fixed_fees=fixed_fees,
            slippage=slippage,
            init_cash=float(costs.get("initial_cash", 100_000.0)),
            freq="1D",
        )


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _metric_values(pf, metric: str) -> np.ndarray:
    """Per-combo score. No-trade combos → NaN → replaced with -inf so they rank
    last deterministically."""
    if metric == "sharpe":
        vals = pf.sharpe_ratio()
    elif metric == "sortino":
        vals = pf.sortino_ratio()
    elif metric == "total_return":
        vals = pf.total_return()
    elif metric == "mar":
        ann = np.asarray(pf.annualized_return(), dtype="float64")
        mdd = np.abs(np.asarray(pf.max_drawdown(), dtype="float64"))
        with np.errstate(divide="ignore", invalid="ignore"):
            vals = np.where(mdd > 0, ann / mdd, 0.0)
    else:
        raise BacktestError("VALIDATION_ERROR", f"Unknown metric {metric!r}.")
    arr = np.atleast_1d(np.asarray(vals, dtype="float64"))
    return np.nan_to_num(arr, nan=-np.inf, posinf=1e12, neginf=-np.inf)
