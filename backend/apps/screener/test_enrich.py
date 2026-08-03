"""Derived-criteria math + deterministic ranking (M16 §10.1 / §10.5)."""
from __future__ import annotations

import json
from unittest import TestCase

from apps.screener import enrich


def bars(closes, highs=None, start_day=1):
    """Bars oldest-first with ISO dates; `highs` defaults to `closes`."""
    highs = highs if highs is not None else closes
    return [
        {"ts": f"2026-{1 + (start_day + i) // 28:02d}-{1 + (start_day + i) % 28:02d}",
         "open": c, "high": h, "low": c, "close": c, "volume": 1000 + i}
        for i, (c, h) in enumerate(zip(closes, highs, strict=True))
    ]


def ramp(n=300, base=100.0, step=0.1):
    return [base + i * step for i in range(n)]


class ComputeMetricsTests(TestCase):
    def test_sma_windows_match_an_independent_mean(self):
        closes = ramp()
        m = enrich.compute_metrics(bars(closes))
        self.assertAlmostEqual(m["sma_50"], sum(closes[-50:]) / 50)
        self.assertAlmostEqual(m["sma_200"], sum(closes[-200:]) / 200)

    def test_slope_samples_20_sessions_back(self):
        closes = ramp()
        m = enrich.compute_metrics(bars(closes))
        # SMA200 twenty sessions ago = mean of closes[-220:-20]
        self.assertAlmostEqual(m["sma_200_prev"], sum(closes[-220:-20]) / 200)
        self.assertGreater(m["sma_200"], m["sma_200_prev"])  # a ramp is rising

    def test_52w_high_uses_252_sessions_of_highs_not_closes(self):
        closes = ramp(300)
        highs = list(closes)
        highs[-260] = 999.0        # spike OUTSIDE the 252-session window
        highs[-10] = 500.0         # spike INSIDE it
        m = enrich.compute_metrics(bars(closes, highs))
        self.assertEqual(m["high_252"], 500.0)

    def test_pct_from_52w_high(self):
        closes = [100.0] * 251 + [80.0]
        m = enrich.compute_metrics(bars(closes))
        self.assertEqual(m["high_252"], 100.0)
        self.assertEqual(m["pct_from_52w_high"], 20.0)

    def test_short_series_yields_none_windows_not_an_exception(self):
        m = enrich.compute_metrics(bars(ramp(30)))
        self.assertEqual(m["n_bars"], 30)
        self.assertIsNone(m["sma_50"])
        self.assertIsNone(m["sma_200"])
        self.assertIsNotNone(m["high_252"])

    def test_empty_and_malformed_bars(self):
        self.assertIsNone(enrich.compute_metrics([]))
        self.assertIsNone(enrich.compute_metrics(None))
        self.assertIsNone(enrich.compute_metrics([{"ts": "2026-01-01", "close": "abc"}]))

    def test_newest_first_input_is_normalised(self):
        closes = ramp(260)
        ascending = enrich.compute_metrics(bars(closes))
        descending = enrich.compute_metrics(list(reversed(bars(closes))))
        self.assertEqual(ascending["close"], descending["close"])
        self.assertAlmostEqual(ascending["sma_200"], descending["sma_200"])


class PassesTests(TestCase):
    def setUp(self):
        self.rising = enrich.compute_metrics(bars(ramp()))

    def test_above_sma_passes_on_an_uptrend(self):
        self.assertTrue(enrich.passes(self.rising, {"above_sma": [50, 200]}))

    def test_above_sma_fails_on_a_downtrend(self):
        falling = enrich.compute_metrics(bars(ramp(step=-0.1)))
        self.assertFalse(enrich.passes(falling, {"above_sma": [200]}))

    def test_sma_rising_fails_when_flat_or_falling(self):
        falling = enrich.compute_metrics(bars(ramp(step=-0.1)))
        self.assertFalse(enrich.passes(falling, {"sma_rising": [200]}))

    def test_near_52w_high_boundary_is_inclusive(self):
        closes = [100.0] * 251 + [75.0]
        m = enrich.compute_metrics(bars(closes))
        self.assertTrue(enrich.passes(m, {"near_52w_high": 25}))   # exactly 25% off
        self.assertFalse(enrich.passes(m, {"near_52w_high": 24}))

    def test_uncomputable_window_is_a_fail_never_a_pass_by_default(self):
        short = enrich.compute_metrics(bars(ramp(30)))
        self.assertFalse(enrich.passes(short, {"above_sma": [200]}))
        self.assertFalse(enrich.passes(short, {"sma_rising": [200]}))

    def test_no_derived_criteria_passes_everything(self):
        self.assertTrue(enrich.passes(self.rising, {}))


class ResultRowTests(TestCase):
    VENDOR = {
        "symbol": "nvda", "companyName": "NVIDIA Corp", "exchangeShortName": "NASDAQ",
        "exchange": "NASDAQ Global Select", "sector": "Technology",
        "marketCap": 3_200_000_000_000, "price": 182.11, "volume": 41_000_000, "beta": 1.7,
    }

    def test_row_shape_and_symbol_upcasing(self):
        row = enrich.result_row(self.VENDOR, enrich.compute_metrics(bars(ramp())))
        self.assertEqual(row["symbol"], "NVDA")
        self.assertEqual(row["name"], "NVIDIA Corp")
        self.assertEqual(row["exchange"], "NASDAQ")  # short name preferred
        self.assertIs(row["above_sma_50"], True)
        self.assertIs(row["sma200_rising"], True)
        self.assertEqual(sorted(row), sorted([
            "symbol", "name", "exchange", "sector", "market_cap", "price", "volume",
            "beta", "pct_from_52w_high", "above_sma_50", "above_sma_200", "sma200_rising",
        ]))

    def test_unenriched_row_has_null_derived_columns_not_false(self):
        row = enrich.result_row(self.VENDOR, None)
        for key in ("pct_from_52w_high", "above_sma_50", "above_sma_200", "sma200_rising"):
            self.assertIsNone(row[key], key)

    def test_missing_vendor_fields_do_not_explode(self):
        row = enrich.result_row({"symbol": "X"}, None)
        self.assertEqual(row["name"], "")
        self.assertIsNone(row["market_cap"])


class RankTests(TestCase):
    def _rows(self):
        return [
            {"symbol": "BBB", "market_cap": 200, "pct_from_52w_high": 5.0},
            {"symbol": "AAA", "market_cap": 200, "pct_from_52w_high": 5.0},
            {"symbol": "CCC", "market_cap": 300, "pct_from_52w_high": 1.0},
        ]

    def test_ranks_by_pct_ascending_when_near_52w_high_present(self):
        ranked = enrich.rank(self._rows(), {"near_52w_high": 25})
        self.assertEqual([r["symbol"] for r in ranked], ["CCC", "AAA", "BBB"])

    def test_ranks_by_market_cap_descending_otherwise(self):
        ranked = enrich.rank(self._rows(), {})
        self.assertEqual([r["symbol"] for r in ranked], ["CCC", "AAA", "BBB"])

    def test_ties_always_break_on_symbol(self):
        ranked = enrich.rank(self._rows(), {})
        self.assertEqual([r["symbol"] for r in ranked[1:]], ["AAA", "BBB"])

    def test_rows_missing_the_sort_key_sort_last_deterministically(self):
        rows = self._rows() + [{"symbol": "ZZZ", "market_cap": None, "pct_from_52w_high": None}]
        self.assertEqual(enrich.rank(rows, {})[-1]["symbol"], "ZZZ")
        self.assertEqual(enrich.rank(rows, {"near_52w_high": 10})[-1]["symbol"], "ZZZ")

    def test_ranking_is_byte_identical_across_input_orders(self):
        """§10.5 — identical inputs (in any order) produce identical JSON."""
        rows = self._rows()
        a = json.dumps(enrich.rank(rows, {}), sort_keys=True)
        b = json.dumps(enrich.rank(list(reversed(rows)), {}), sort_keys=True)
        self.assertEqual(a, b)
