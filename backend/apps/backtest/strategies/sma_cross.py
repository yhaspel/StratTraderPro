"""SMA-crossover demo adapter (M09 §6.1).

Fast/slow simple-moving-average crossover, long-only. The one end-to-end demo
strategy shipped with M09 (matching system ``Strategy`` slug ``sma-cross-demo``
seeded by ``manage.py seed_demo_strategy``).

Look-ahead safety: SMAs are trailing means of past-and-current closes; the
crossover test compares the current row against the immediately prior row via
``.shift(1)`` — never a future row. Fills happen next-bar-open in the engines.
"""
from __future__ import annotations

import pandas as pd

from .registry import register

# Default declared grid — 12 combos (all fast < slow), ≥ 10 so PBO is computed,
# ≤ 24 so it fits the CI performance smoke (§10.4).
_FAST = [5, 10, 15]
_SLOW = [20, 30, 40, 50]


@register
class SmaCrossAdapter:
    slug = "sma-cross-demo"
    warmup_bars = max(_SLOW)  # so SMA(slow) is valid at the first in-window bar

    def param_grid(self) -> dict[str, list]:
        return {"fast": list(_FAST), "slow": list(_SLOW)}

    def generate_signals(self, bars: pd.DataFrame, params: dict) -> pd.DataFrame:
        fast = int(params["fast"])
        slow = int(params["slow"])
        close = bars["close"]
        sma_fast = close.rolling(fast, min_periods=fast).mean()
        sma_slow = close.rolling(slow, min_periods=slow).mean()

        above = sma_fast > sma_slow
        prev_above = above.shift(1, fill_value=False)
        # Golden cross: fast crosses up through slow → entry. Death cross → exit.
        entries = above & ~prev_above
        exits = ~above & prev_above
        # Never signal until both SMAs exist (avoid NaN-driven spurious crosses).
        valid = sma_fast.notna() & sma_slow.notna()
        entries = (entries & valid).fillna(False)
        exits = (exits & valid).fillna(False)

        out = pd.DataFrame(index=bars.index)
        out["entries"] = entries.astype(bool)
        out["exits"] = exits.astype(bool)
        return out
