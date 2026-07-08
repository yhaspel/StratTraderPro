"""Sweep-metric + registry edge tests (M09 §10.1) — coverage of the ranking
metric variants and the adapter-registration guards."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.backtest.strategies.registry import register
from apps.backtest.strategies.sma_cross import SmaCrossAdapter
from apps.backtest.vbt_engine import VectorbtSweepEngine


def _frame(n=180, seed=4):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2019-10-01", periods=n, freq="D", tz="UTC")
    close = pd.Series(100 + np.cumsum(rng.normal(0.05, 1.0, n)), index=idx).clip(lower=1)
    op = close.shift(1).bfill()
    return pd.DataFrame({"open": op.values, "high": (np.maximum(op, close) + 0.5).values,
                         "low": (np.minimum(op, close) - 0.5).clip(lower=0.1).values,
                         "close": close.values, "volume": np.full(n, 1_000_000)}, index=idx)


class SweepMetricTests(SimpleTestCase):
    def test_all_ranking_metrics_produce_a_best_combo(self):
        frame = _frame()
        ad = SmaCrossAdapter()
        eng = VectorbtSweepEngine()
        start, end = date(2019, 10, 1), date(2019, 10, 1) + timedelta(days=170)
        costs = {"slippage_bps": 5, "initial_cash": 100000}
        for metric in ("sharpe", "sortino", "total_return", "mar"):
            res = eng.run(frame, start, end, ad, ad.param_grid(), costs, metric)
            best = res.top()
            self.assertIn("fast", best)
            self.assertIn("slow", best)
            self.assertEqual(len(res.combos), 12)

    def test_returns_matrix_shape(self):
        frame = _frame()
        ad = SmaCrossAdapter()
        start, end = date(2019, 10, 1), date(2019, 10, 1) + timedelta(days=170)
        combos, matrix = VectorbtSweepEngine().returns_matrix(
            frame, start, end, ad, ad.param_grid(), {"slippage_bps": 5, "initial_cash": 100000}
        )
        self.assertEqual(matrix.shape[1], len(combos))
        self.assertEqual(len(combos), 12)


class RegistryGuardTests(SimpleTestCase):
    def test_adapter_without_slug_rejected(self):
        with self.assertRaises(ValueError):
            register(type("NoSlug", (), {}))

    def test_duplicate_slug_rejected(self):
        with self.assertRaises(ValueError):
            register(type("Dup", (), {"slug": "sma-cross-demo"}))  # different class, same slug
