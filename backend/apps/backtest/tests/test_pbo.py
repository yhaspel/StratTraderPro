"""PBO / CSCV known-answer + property tests (M09 §5, §6.5)."""
from __future__ import annotations

import numpy as np
from django.test import SimpleTestCase

from apps.backtest.pbo import probability_of_backtest_overfitting


class PboTests(SimpleTestCase):
    def test_pure_noise_pbo_near_half(self):
        rng = np.random.default_rng(7)
        m = rng.normal(0, 0.01, (400, 20))
        pbo = probability_of_backtest_overfitting(m)
        self.assertIsNotNone(pbo)
        self.assertAlmostEqual(pbo, 0.5, delta=0.15)  # seeded, ±0.15 tolerance

    def test_planted_dominant_strategy_low_pbo(self):
        rng = np.random.default_rng(11)
        m = rng.normal(0, 0.01, (400, 20))
        m[:, 0] += 0.003  # one consistently dominant strategy
        pbo = probability_of_backtest_overfitting(m)
        self.assertLess(pbo, 0.1)

    def test_range_and_determinism(self):
        rng = np.random.default_rng(3)
        m = rng.normal(0, 0.02, (320, 15))
        a = probability_of_backtest_overfitting(m)
        b = probability_of_backtest_overfitting(m)
        self.assertEqual(a, b)  # deterministic
        self.assertGreaterEqual(a, 0.0)
        self.assertLessEqual(a, 1.0)

    def test_degenerate_few_combos_returns_none(self):
        rng = np.random.default_rng(1)
        self.assertIsNone(probability_of_backtest_overfitting(rng.normal(0, 1, (400, 5))))  # N < 10

    def test_degenerate_short_series_returns_none(self):
        rng = np.random.default_rng(1)
        self.assertIsNone(probability_of_backtest_overfitting(rng.normal(0, 1, (20, 20))))  # T < 2S

    def test_odd_block_count_rejected(self):
        rng = np.random.default_rng(1)
        with self.assertRaises(ValueError):
            probability_of_backtest_overfitting(rng.normal(0, 1, (300, 20)), s=15)
