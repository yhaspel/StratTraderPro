"""Strategy adapter contract (M09 §6.1).

Pine scripts never execute server-side, so every backtestable strategy needs an
in-repo **Python adapter** (ADR-092). The adapter is *pure* — a function of the
bars frame + params — and returns aligned boolean signals. It never sees the
future: ``bars`` is a past-only view and fills happen next-bar-open in the
engines, so an adapter cannot leak look-ahead as long as it only reads columns
at or before each row (index-alignment tests in §10.1 guard this).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class BacktestStrategy(Protocol):
    slug: str  # matches strategies_strategy.slug
    warmup_bars: int  # max indicator lookback the adapter needs

    def param_grid(self) -> dict[str, list]:
        """The adapter's declared parameter space (name -> allowed values).

        A user-supplied grid must be a **subset refinement** of this (validated
        server-side) — no arbitrary values ever reach an adapter (§11)."""
        ...

    def generate_signals(self, bars: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Return a frame indexed like ``bars`` with boolean ``entries``/``exits``
        columns and optional float ``stop_pct``/``target_pct`` columns (per-entry,
        as a fraction of entry price)."""
