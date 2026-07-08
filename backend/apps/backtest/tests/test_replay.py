"""Replay engine golden-file + property tests (M09 §10.1, §6.3, ADR-091)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.backtest.replay_engine import ReplayConfig, replay
from apps.backtest.strategies.sma_cross import SmaCrossAdapter

from ._fixtures import bars_df, signals_df

_START = date(2020, 1, 1)
_ZC = dict(slippage_bps=0, per_order_usd=0, per_share_usd=0, volume_participation_pct=100, sizing_mode="fixed_qty_1")


def _full_window(n):
    return _START, _START + timedelta(days=n)


def _cfg(**over):
    kw = {**_ZC, **over}
    return ReplayConfig(initial_cash=100_000.0, **kw)


_BASE_ROWS = [
    (100, 101, 99, 100, 1_000_000),
    (101, 102, 100, 101, 1_000_000),
    (102, 103, 101, 102, 1_000_000),
    (103, 104, 102, 103, 1_000_000),
    (104, 105, 103, 104, 1_000_000),
    (105, 106, 104, 105, 1_000_000),
    (106, 107, 105, 106, 1_000_000),
    (107, 108, 106, 107, 1_000_000),
    (108, 109, 107, 108, 1_000_000),
    (109, 110, 108, 109, 1_000_000),
]


class ReplayGoldenTests(SimpleTestCase):
    def test_basic_signal_entry_and_exit(self):
        bars = bars_df(_BASE_ROWS, _START)
        sig = signals_df(bars.index, entries_at=[1], exits_at=[5])
        rr = replay(bars, sig, "T", *_full_window(10), _cfg())
        self.assertEqual(len(rr.trades), 1)
        t = rr.trades[0]
        self.assertAlmostEqual(t.entry_price, 102.0)   # bar2 open
        self.assertAlmostEqual(t.exit_price, 106.0)    # bar6 open (next-bar market exit)
        self.assertEqual(t.qty, 1.0)
        self.assertAlmostEqual(t.pnl, 4.0)
        self.assertAlmostEqual(t.mfe, 4.0)             # best high 106 − entry 102
        self.assertAlmostEqual(t.mae, -1.0)            # worst low 101 − entry 102
        self.assertEqual(t.exit_reason, "signal")
        self.assertAlmostEqual(rr.equity.iloc[-1], 100_004.0)

    def test_stop_hit_exits_at_level(self):
        rows = list(_BASE_ROWS)
        rows[4] = (104, 105, 96, 100, 1_000_000)  # low 96 ≤ stop 96.9
        bars = bars_df(rows, _START)
        sig = signals_df(bars.index, entries_at=[1], stop_pct=0.05)
        rr = replay(bars, sig, "T", *_full_window(10), _cfg())
        t = rr.trades[0]
        self.assertEqual(t.exit_reason, "stop")
        self.assertAlmostEqual(t.exit_price, 96.9, places=4)  # 102 * 0.95
        self.assertAlmostEqual(t.pnl, -5.1, places=4)

    def test_gap_through_stop_fills_at_open(self):
        rows = list(_BASE_ROWS)
        rows[4] = (95, 96, 94, 95, 1_000_000)  # opens below stop 96.9 → gap-through
        bars = bars_df(rows, _START)
        sig = signals_df(bars.index, entries_at=[1], stop_pct=0.05)
        rr = replay(bars, sig, "T", *_full_window(10), _cfg())
        t = rr.trades[0]
        self.assertEqual(t.exit_reason, "stop")
        self.assertAlmostEqual(t.exit_price, 95.0, places=4)  # filled at the gapped open
        self.assertAlmostEqual(t.pnl, -7.0, places=4)

    def test_target_hit_exits_at_level(self):
        rows = list(_BASE_ROWS)
        rows[4] = (104, 108, 103, 107, 1_000_000)  # high 108 ≥ target 107.1
        bars = bars_df(rows, _START)
        sig = signals_df(bars.index, entries_at=[1], target_pct=0.05)
        rr = replay(bars, sig, "T", *_full_window(10), _cfg())
        t = rr.trades[0]
        self.assertEqual(t.exit_reason, "target")
        self.assertAlmostEqual(t.exit_price, 107.1, places=4)  # 102 * 1.05
        self.assertAlmostEqual(t.pnl, 5.1, places=4)

    def test_same_bar_stop_and_target_resolves_stop_first(self):
        rows = list(_BASE_ROWS)
        rows[4] = (104, 108, 96, 100, 1_000_000)  # BOTH stop (low 96) and target (high 108)
        bars = bars_df(rows, _START)
        sig = signals_df(bars.index, entries_at=[1], stop_pct=0.05, target_pct=0.05)
        rr = replay(bars, sig, "T", *_full_window(10), _cfg())
        t = rr.trades[0]
        self.assertEqual(t.exit_reason, "stop")  # conservative
        self.assertAlmostEqual(t.exit_price, 96.9, places=4)

    def test_same_bar_entry_and_exit_is_noop(self):
        bars = bars_df(_BASE_ROWS, _START)
        sig = signals_df(bars.index, entries_at=[1, 3], exits_at=[1])  # bar1 both → no-op
        rr = replay(bars, sig, "T", *_full_window(10), _cfg())
        # Only the bar-3 entry produces a (force-closed) trade.
        self.assertEqual(len(rr.trades), 1)
        self.assertAlmostEqual(rr.trades[0].entry_price, 104.0)  # bar4 open

    def test_force_close_at_final_bar(self):
        bars = bars_df(_BASE_ROWS, _START)
        sig = signals_df(bars.index, entries_at=[7])  # entry fills bar8, never exits
        rr = replay(bars, sig, "T", *_full_window(10), _cfg())
        t = rr.trades[0]
        self.assertEqual(t.exit_reason, "force_close")
        self.assertAlmostEqual(t.exit_price, 109.0)  # final bar close

    def test_partial_fill_cancels_remainder_after_five_bars(self):
        rows = [(100, 101, 99, 100, 1) for _ in range(8)]  # volume 1 → cap 0.1/bar at vpp 10%
        bars = bars_df(rows, _START)
        sig = signals_df(bars.index, entries_at=[0])
        rr = replay(bars, sig, "T", *_full_window(8), _cfg(volume_participation_pct=10))
        t = rr.trades[0]
        self.assertAlmostEqual(t.qty, 0.5, places=6)          # 5 bars × 0.1
        self.assertTrue(t.partial)
        self.assertAlmostEqual(t.cancelled_qty, 0.5, places=6)

    def test_commissions_reduce_pnl(self):
        bars = bars_df(_BASE_ROWS, _START)
        sig = signals_df(bars.index, entries_at=[1], exits_at=[5])
        rr = replay(bars, sig, "T", *_full_window(10),
                    _cfg(per_order_usd=1.0, per_share_usd=0.5))
        t = rr.trades[0]
        # gross 4.0 − entry(1 + 0.5) − exit(1 + 0.5) = 1.0
        self.assertAlmostEqual(t.pnl, 1.0, places=6)


class ReplayPropertyTests(SimpleTestCase):
    def _random_run(self, seed):
        rng = np.random.default_rng(seed)
        n = 160
        close = pd.Series(100 + np.cumsum(rng.normal(0.05, 1.0, n)),
                          index=pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")).clip(lower=1)
        op = close.shift(1).bfill()
        frame = pd.DataFrame({"open": op.values, "high": (np.maximum(op, close) + 0.5).values,
                              "low": (np.minimum(op, close) - 0.5).clip(lower=0.1).values,
                              "close": close.values, "volume": np.full(n, 1_000_000)},
                             index=close.index)
        sig = SmaCrossAdapter().generate_signals(frame, {"fast": 5, "slow": 20})
        rr = replay(frame, sig, "T", date(2020, 1, 1), date(2020, 1, 1) + timedelta(days=n), _cfg())
        return frame, rr

    def test_cash_never_negative_and_equity_reconciles(self):
        for seed in range(5):
            frame, rr = self._random_run(seed)
            self.assertGreater(float(rr.equity.min()), 0.0)
            realized = sum(t.pnl for t in rr.trades)
            drift = float(rr.equity.iloc[-1]) - 100_000.0
            self.assertAlmostEqual(realized, drift, places=4)  # flat at end (force-close)

    def test_fills_within_bar_range(self):
        for seed in range(5):
            frame, rr = self._random_run(seed)
            for t in rr.trades:
                ebar = frame.loc[t.entry_ts]
                self.assertGreaterEqual(t.entry_price + 1e-9, float(ebar["low"]))
                self.assertLessEqual(t.entry_price - 1e-9, float(ebar["high"]))
                xbar = frame.loc[t.exit_ts]
                self.assertGreaterEqual(t.exit_price + 1e-9, float(xbar["low"]))
                self.assertLessEqual(t.exit_price - 1e-9, float(xbar["high"]))
