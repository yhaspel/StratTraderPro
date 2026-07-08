"""Bars → DataFrame loader tests (M09 §10.1, §6.0)."""
from __future__ import annotations

from datetime import date

import pandas as pd
from django.test import TestCase

from apps.backtest.data import load_bars
from apps.backtest.exceptions import INSUFFICIENT_DATA, BacktestError

from ._fixtures import seed_bars


class LoaderTests(TestCase):
    def test_half_open_range_excludes_end_bar(self):
        seed_bars("X", date(2019, 11, 1), date(2020, 7, 1))
        end = date(2020, 6, 15)  # a seeded weekday
        df = load_bars("X", "1d", date(2020, 1, 1), end, warmup_bars=0)
        self.assertTrue((df.index < pd.Timestamp(end, tz="UTC")).all())
        self.assertGreaterEqual(df.index.min(), pd.Timestamp(date(2020, 1, 1), tz="UTC"))

    def test_warmup_rows_fetched_before_start(self):
        seed_bars("X", date(2019, 6, 1), date(2020, 7, 1))
        df = load_bars("X", "1d", date(2020, 1, 1), date(2020, 6, 1), warmup_bars=30)
        before = df.index[df.index < pd.Timestamp(date(2020, 1, 1), tz="UTC")]
        self.assertEqual(len(before), 30)  # exactly the requested warm-up count
        self.assertTrue(df.index.is_monotonic_increasing)

    def test_columns_and_dtypes(self):
        seed_bars("X", date(2019, 11, 1), date(2020, 7, 1))
        df = load_bars("X", "1d", date(2020, 1, 1), date(2020, 6, 1))
        self.assertEqual(list(df.columns), ["open", "high", "low", "close", "volume"])
        self.assertEqual(str(df["close"].dtype), "float64")
        self.assertEqual(str(df["volume"].dtype), "int64")

    def test_coverage_ok_with_holidays(self):
        # A full year with only US-holiday gaps stays above the 95% weekday floor.
        seed_bars("X", date(2019, 11, 1), date(2021, 2, 1))
        df = load_bars("X", "1d", date(2020, 1, 1), date(2021, 1, 1), warmup_bars=20)
        self.assertGreater(len(df), 240)

    def test_insufficient_data_raises(self):
        seed_bars("X", date(2020, 1, 1), date(2020, 3, 1))  # only 2 months seeded
        with self.assertRaises(BacktestError) as ctx:
            load_bars("X", "1d", date(2020, 1, 1), date(2021, 1, 1))
        self.assertEqual(ctx.exception.code, INSUFFICIENT_DATA)
