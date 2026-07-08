"""Walk-forward window math (M09 §10.1) — pinned to the §6.4 golden example."""
from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase

from apps.backtest.wf import WFConfig, compute_windows


class WindowMathTests(SimpleTestCase):
    def test_golden_rolling_three_windows(self):
        cfg = WFConfig(date(2020, 1, 1), date(2021, 1, 1), 180, 60, 60, anchored=False)
        w = compute_windows(cfg)
        self.assertEqual(len(w), 3)
        self.assertEqual((w[0].train_start, w[0].train_end, w[0].test_start, w[0].test_end),
                         (date(2020, 1, 1), date(2020, 6, 29), date(2020, 6, 29), date(2020, 8, 28)))
        self.assertEqual((w[1].train_start, w[1].train_end, w[1].test_start, w[1].test_end),
                         (date(2020, 3, 1), date(2020, 8, 28), date(2020, 8, 28), date(2020, 10, 27)))
        self.assertEqual((w[2].train_start, w[2].train_end, w[2].test_start, w[2].test_end),
                         (date(2020, 4, 30), date(2020, 10, 27), date(2020, 10, 27), date(2020, 12, 26)))

    def test_golden_anchored_same_boundaries_train_from_start(self):
        cfg = WFConfig(date(2020, 1, 1), date(2021, 1, 1), 180, 60, 60, anchored=True)
        w = compute_windows(cfg)
        self.assertEqual(len(w), 3)
        for win in w:
            self.assertEqual(win.train_start, date(2020, 1, 1))
        # test boundaries identical to rolling
        self.assertEqual([x.test_end for x in w], [date(2020, 8, 28), date(2020, 10, 27), date(2020, 12, 26)])

    def test_contiguous_non_overlapping_oos(self):
        cfg = WFConfig(date(2020, 1, 1), date(2021, 1, 1), 180, 60, 60, anchored=False)
        w = compute_windows(cfg)
        for prev, nxt in zip(w, w[1:], strict=False):
            self.assertEqual(prev.test_end, nxt.test_start)  # half-open ⇒ zero overlap

    def test_trailing_partial_window_dropped(self):
        # end just before the 2nd window would complete (needs ≥ 2020-10-27) → 1 window
        cfg = WFConfig(date(2020, 1, 1), date(2020, 10, 1), 180, 60, 60, anchored=False)
        self.assertEqual(len(compute_windows(cfg)), 1)

    def test_too_short_range_zero_windows(self):
        cfg = WFConfig(date(2020, 1, 1), date(2020, 3, 1), 180, 60, 60, anchored=False)
        self.assertEqual(len(compute_windows(cfg)), 0)
