"""Strategy adapter + registry tests (M09 §10.1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.backtest.strategies import get_adapter, registered_slugs
from apps.backtest.strategies.sma_cross import SmaCrossAdapter


def _frame(n=120, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    close = pd.Series(100 + np.cumsum(rng.normal(0.05, 1.0, n)), index=idx).clip(lower=1)
    op = close.shift(1).bfill()
    return pd.DataFrame({"open": op.values, "high": (np.maximum(op, close) + 0.5).values,
                         "low": (np.minimum(op, close) - 0.5).clip(lower=0.1).values,
                         "close": close.values, "volume": np.full(n, 1_000_000)}, index=idx)


class RegistryTests(SimpleTestCase):
    def test_demo_adapter_registered(self):
        self.assertIn("sma-cross-demo", registered_slugs())
        self.assertIsInstance(get_adapter("sma-cross-demo"), SmaCrossAdapter)

    def test_unknown_slug_returns_none(self):
        self.assertIsNone(get_adapter("does-not-exist"))


class SmaCrossTests(SimpleTestCase):
    def test_signals_shape_and_types(self):
        f = _frame()
        sig = SmaCrossAdapter().generate_signals(f, {"fast": 5, "slow": 20})
        self.assertEqual(list(sig.columns), ["entries", "exits"])
        self.assertEqual(sig["entries"].dtype, bool)
        self.assertEqual(sig["exits"].dtype, bool)
        self.assertEqual(len(sig), len(f))
        # No signal while SMA(20) is still NaN (min_periods=20 → valid from index 19).
        self.assertFalse(sig["entries"].iloc[:19].any())
        self.assertFalse(sig["exits"].iloc[:19].any())

    def test_grid_all_fast_below_slow(self):
        grid = SmaCrossAdapter().param_grid()
        self.assertTrue(all(f < s for f in grid["fast"] for s in grid["slow"]))
        combos = len(grid["fast"]) * len(grid["slow"])
        self.assertGreaterEqual(combos, 10)  # ≥ 10 so PBO is computed
        self.assertLessEqual(combos, 24)     # ≤ 24 for the CI smoke

    def test_no_lookahead_future_bars_do_not_change_past_signals(self):
        f = _frame(n=120, seed=2)
        params = {"fast": 5, "slow": 20}
        base = SmaCrossAdapter().generate_signals(f, params)
        mutated = f.copy()
        # Corrupt the last 10 bars only.
        mutated.iloc[-10:, mutated.columns.get_loc("close")] *= 3.0
        after = SmaCrossAdapter().generate_signals(mutated, params)
        # Signals up to the first mutated bar must be identical (no forward peek).
        cut = len(f) - 10
        pd.testing.assert_series_equal(base["entries"].iloc[:cut], after["entries"].iloc[:cut])
        pd.testing.assert_series_equal(base["exits"].iloc[:cut], after["exits"].iloc[:cut])
