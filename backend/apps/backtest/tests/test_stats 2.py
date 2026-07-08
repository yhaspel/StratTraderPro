"""Performance-metric tests vs hand-computed references (M09 §10.1, AC-09-6)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from django.test import SimpleTestCase

from apps.backtest import stats


@dataclass
class _T:
    pnl: float
    qty: float = 1.0
    entry_price: float = 100.0
    exit_price: float = 100.0


def _eq(values):
    idx = pd.date_range("2020-01-01", periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx, dtype="float64")


class StatsTests(SimpleTestCase):
    def test_total_return_and_max_drawdown(self):
        eq = _eq([100, 120, 90, 108])
        m = stats.compute_metrics(eq, [], initial_cash=100, exposure_bars=4, n_bars=4)
        self.assertAlmostEqual(m["total_return"], 0.08, places=6)
        self.assertAlmostEqual(m["max_drawdown"], -0.25, places=6)  # 90/120 - 1
        self.assertAlmostEqual(m["exposure_pct"], 100.0, places=6)

    def test_drawdown_series(self):
        dd = stats.drawdown_series(_eq([100, 120, 90, 108]))
        self.assertAlmostEqual(dd.iloc[2], -0.25, places=6)
        self.assertAlmostEqual(dd.iloc[3], -0.10, places=6)

    def test_zero_returns_zero_sharpe_sortino(self):
        m = stats.compute_metrics(_eq([100, 100, 100, 100]), [], 100, 4, 4)
        self.assertEqual(m["sharpe"], 0.0)
        self.assertEqual(m["sortino"], 0.0)
        self.assertEqual(m["max_drawdown"], 0.0)

    def test_trade_stats(self):
        trades = [_T(10), _T(-5), _T(20), _T(-5)]
        m = stats.compute_metrics(_eq([100, 101, 102, 103]), trades, 100, 2, 4)
        self.assertAlmostEqual(m["win_pct"], 50.0)
        self.assertAlmostEqual(m["profit_factor"], 3.0)  # 30 / 10
        self.assertAlmostEqual(m["avg_win"], 15.0)
        self.assertAlmostEqual(m["avg_loss"], -5.0)
        self.assertAlmostEqual(m["expectancy"], 5.0)
        self.assertEqual(m["trade_count"], 4)

    def test_profit_factor_none_without_losses(self):
        m = stats.compute_metrics(_eq([100, 101]), [_T(10), _T(20)], 100, 1, 2)
        self.assertIsNone(m["profit_factor"])

    def test_sharpe_stability(self):
        s = stats.sharpe_stability([1.0, 2.0, 3.0])
        self.assertAlmostEqual(s["mean"], 2.0)
        self.assertAlmostEqual(s["std"], 1.0)  # sample std of [1,2,3]
        self.assertEqual(s["n"], 3)

    def test_empty_equity_safe(self):
        m = stats.compute_metrics(pd.Series(dtype="float64"), [], 100, 0, 0)
        self.assertEqual(m["trade_count"], 0)
        self.assertEqual(m["sharpe"], 0.0)
