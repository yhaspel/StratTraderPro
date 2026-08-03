"""[screen] parser tests (M16 §10.1).

The fixture set deliberately mirrors REAL TradingView exports — UTF-8 BOM, CRLF
line endings, a Mozilla licence header before anything else, BBCode around the
block and the block sitting MID-prose. That is the #45 lesson: a synthetic-only
fixture set passes while real input is rejected.
"""
from __future__ import annotations

import pathlib
from unittest import TestCase

from apps.screener.criteria import (
    LIMIT_MAX,
    MAX_BLOCK_BYTES,
    MAX_BLOCK_LINES,
    MIN_HISTORY_DEFAULT,
    ScreenCriteriaError,
    decode_desc,
    parse,
    parse_or_raise,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return decode_desc((FIXTURES / name).read_bytes())


def block(*lines: str) -> str:
    return "[screen]\n" + "\n".join(lines) + "\n[/screen]"


def parse_block(*lines: str):
    return parse(block(*lines))


class RealExportFixtureTests(TestCase):
    """Parsing must survive the bytes TradingView actually produces."""

    def test_bom_crlf_licence_header_and_midprose_block(self):
        criteria, errors = parse(fixture("desc_minervini_real.txt"))
        self.assertEqual(errors, [])
        self.assertIsNotNone(criteria)
        self.assertEqual(criteria.criteria["market_cap"], {"gte": 2_000_000_000})
        self.assertEqual(criteria.criteria["price"], {"gte": 10, "lte": 1000})
        # `above_sma` is repeatable once per window and comes back sorted.
        self.assertEqual(criteria.derived["above_sma"], [50, 200])
        self.assertEqual(criteria.derived["sma_rising"], [200])
        self.assertEqual(criteria.derived["near_52w_high"], 25)
        self.assertEqual(criteria.derived["min_history"], MIN_HISTORY_DEFAULT)
        self.assertEqual(criteria.limit, 50)

    def test_real_export_without_block_is_not_an_error(self):
        criteria, errors = parse(fixture("desc_no_block.txt"))
        self.assertEqual(errors, [])
        self.assertIsNone(criteria)  # -> block_present: false, never a 400

    def test_stray_brackets_and_the_word_screening_do_not_trigger_a_block(self):
        criteria, errors = parse("mentions [screening] and array[0] and a lone [ bracket")
        self.assertEqual((criteria, errors), (None, []))

    def test_invalid_fixture_reports_every_bad_line_with_numbers(self):
        criteria, errors = parse(fixture("desc_invalid.txt"))
        self.assertIsNone(criteria)
        joined = " ".join(e["error"] for e in errors)
        self.assertIn("markt_cap", joined)          # unknown key, not a silent widen
        self.assertIn("inverted", joined)           # 1000..10
        self.assertIn("above_sma", joined)          # 100 is not a supported window
        self.assertIn("between 1 and 100", joined)  # 250%
        self.assertIn("ONE value", joined)          # sector: A|B
        self.assertEqual(len(errors), 5)
        for e in errors:
            self.assertIsInstance(e["line"], int)
            self.assertGreater(e["line"], 0)
        # Line numbers are absolute in the description so an author can jump there.
        self.assertEqual(sorted(e["line"] for e in errors), [5, 6, 7, 8, 9])

    def test_duplicate_block_fixture(self):
        criteria, errors = parse(fixture("desc_duplicate_block.txt"))
        self.assertIsNone(criteria)
        self.assertEqual(len(errors), 1)
        self.assertIn("duplicate_block", errors[0]["error"])

    def test_unclosed_block_is_an_error_not_a_silent_swallow(self):
        criteria, errors = parse(fixture("desc_unclosed.txt"))
        self.assertIsNone(criteria)
        self.assertEqual(len(errors), 1)
        self.assertIn("Unclosed", errors[0]["error"])


class GrammarTests(TestCase):
    def test_every_range_key_maps_both_halves(self):
        criteria, errors = parse_block(
            "market_cap: 1B..3B", "price: 5..10", "volume: 1M..2M",
            "beta: 0.5..2", "dividend: 0.1..5",
        )
        self.assertEqual(errors, [])
        self.assertEqual(criteria.vendor_params, {
            "marketCapMoreThan": 1_000_000_000, "marketCapLowerThan": 3_000_000_000,
            "priceMoreThan": 5, "priceLowerThan": 10,
            "volumeMoreThan": 1_000_000, "volumeLowerThan": 2_000_000,
            "betaMoreThan": 0.5, "betaLowerThan": 2,
            "dividendMoreThan": 0.1, "dividendLowerThan": 5,
            "isActivelyTrading": True, "isEtf": False, "limit": 50,
        })

    def test_suffixes_and_decimals(self):
        criteria, _ = parse_block("market_cap: >= 1.5B", "volume: >= 250K", "price: >= 2T")
        self.assertEqual(criteria.vendor_params["marketCapMoreThan"], 1_500_000_000)
        self.assertEqual(criteria.vendor_params["volumeMoreThan"], 250_000)
        self.assertEqual(criteria.vendor_params["priceMoreThan"], 2_000_000_000_000)

    def test_lowercase_suffix_and_case_insensitive_tags(self):
        criteria, errors = parse("[SCREEN]\nmarket_cap: >= 2b\n[/Screen]")
        self.assertEqual(errors, [])
        self.assertEqual(criteria.vendor_params["marketCapMoreThan"], 2_000_000_000)

    def test_negative_beta_is_allowed(self):
        criteria, errors = parse_block("beta: -1..0.5")
        self.assertEqual(errors, [])
        self.assertEqual(criteria.vendor_params["betaMoreThan"], -1)

    def test_comments_and_blank_lines_ignored(self):
        criteria, errors = parse_block("# a comment", "", "   ", "limit: 7", "# trailing")
        self.assertEqual(errors, [])
        self.assertEqual(criteria.limit, 7)

    def test_strict_operators_reject_bare_gt_with_a_helpful_message(self):
        _, errors = parse_block("price: > 10")
        self.assertIn("use '>=' or '<='", errors[0]["error"])

    def test_unknown_key_lists_the_allowlist(self):
        _, errors = parse_block("avg_volume: >= 1M")
        self.assertIn("Unknown key", errors[0]["error"])
        self.assertIn("volume", errors[0]["error"])

    def test_duplicate_scalar_key(self):
        _, errors = parse_block("limit: 10", "limit: 20")
        self.assertIn("duplicate_key", errors[0]["error"])

    def test_duplicate_same_sma_window(self):
        _, errors = parse_block("above_sma: 50", "above_sma: 50")
        self.assertIn("duplicate_key", errors[0]["error"])

    def test_missing_value_and_missing_colon(self):
        _, errors = parse_block("limit:", "just some prose")
        self.assertEqual(len(errors), 2)
        self.assertIn("no value", errors[0]["error"])
        self.assertIn("Expected 'key: value'", errors[1]["error"])

    def test_country_must_be_iso2_and_is_upcased(self):
        criteria, _ = parse_block("country: us")
        self.assertEqual(criteria.vendor_params["country"], "US")
        _, errors = parse_block("country: United States")
        self.assertIn("2-letter ISO", errors[0]["error"])

    def test_etf_true_flips_isetf(self):
        criteria, _ = parse_block("etf: true")
        self.assertIs(criteria.vendor_params["isEtf"], True)
        _, errors = parse_block("etf: yes")
        self.assertIn("true or false", errors[0]["error"])

    def test_limit_clamps_rather_than_erroring(self):
        hi, _ = parse_block("limit: 5000")
        lo, _ = parse_block("limit: 0")
        self.assertEqual(hi.limit, LIMIT_MAX)
        self.assertEqual(lo.limit, 1)
        self.assertEqual(hi.vendor_params["limit"], LIMIT_MAX)

    def test_near_52w_high_accepts_with_or_without_percent_and_bounds(self):
        with_pct, _ = parse_block("near_52w_high: 25%")
        without, _ = parse_block("near_52w_high: 25")
        self.assertEqual(with_pct.derived["near_52w_high"], 25)
        self.assertEqual(without.derived["near_52w_high"], 25)
        _, errors = parse_block("near_52w_high: 0%")
        self.assertIn("between 1 and 100", errors[0]["error"])

    def test_min_history_defaults_only_when_a_derived_key_is_present(self):
        with_derived, _ = parse_block("above_sma: 50")
        vendor_only, _ = parse_block("price: >= 10")
        self.assertEqual(with_derived.derived["min_history"], MIN_HISTORY_DEFAULT)
        self.assertEqual(vendor_only.derived, {})

    def test_min_history_override(self):
        criteria, _ = parse_block("above_sma: 50", "min_history: 300")
        self.assertEqual(criteria.derived["min_history"], 300)

    def test_oversized_block_rejected_before_parsing(self):
        big = ["# " + "x" * 200 for _ in range(MAX_BLOCK_LINES - 2)]
        _, errors = parse_block(*big)
        self.assertEqual(len(errors), 1)
        self.assertIn(str(MAX_BLOCK_BYTES), errors[0]["error"])

    def test_too_many_lines_rejected_before_parsing(self):
        _, errors = parse_block(*["# c"] * (MAX_BLOCK_LINES + 5))
        self.assertEqual(len(errors), 1)
        self.assertIn(str(MAX_BLOCK_LINES), errors[0]["error"])

    def test_parse_or_raise(self):
        with self.assertRaises(ScreenCriteriaError) as ctx:
            parse_or_raise(block("nope: 1"))
        self.assertEqual(len(ctx.exception.errors), 1)

    def test_decode_desc_replaces_invalid_utf8(self):
        self.assertIn("�", decode_desc(b"\xff\xfe bad bytes"))
        self.assertEqual(decode_desc(None), "")


class NumericOverflowTests(TestCase):
    """A huge literal must be a line-numbered error, never an exception.

    ``float("9"*400)`` returns ``inf`` WITHOUT raising, and ``int(inf)`` then
    raises ``OverflowError`` — not a ``ValueError``, so it used to escape the
    parser, the view and DRF's handler and surface as a 500, breaking AC-16-1's
    "never a 500" promise on every numeric key.
    """

    HUGE = "9" * 400

    def test_every_numeric_key_rejects_an_overflowing_literal(self):
        for line in (
            f"market_cap: >= {self.HUGE}",
            f"price: <= {self.HUGE}",
            f"volume: >= {self.HUGE}",
            f"beta: >= {self.HUGE}",
            f"dividend: >= {self.HUGE}",
            f"limit: {self.HUGE}",
            f"near_52w_high: {self.HUGE}%",
            f"min_history: {self.HUGE}",
            f"above_sma: {self.HUGE}",
            f"sma_rising: {self.HUGE}",
            f"price: 1..{self.HUGE}",
            f"market_cap: {self.HUGE}..{self.HUGE}",
        ):
            with self.subTest(line=line):
                criteria, errors = parse_block(line)
                self.assertIsNone(criteria)
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0]["line"], int)

    def test_a_finite_mantissa_that_overflows_only_after_the_suffix(self):
        criteria, errors = parse_block(f"market_cap: >= {'9' * 300}T")
        self.assertIsNone(criteria)
        self.assertEqual(len(errors), 1)

    def test_realistic_magnitudes_still_parse(self):
        criteria, errors = parse_block("market_cap: >= 4T", "volume: >= 500M")
        self.assertEqual(errors, [])
        self.assertEqual(criteria.vendor_params["marketCapMoreThan"], 4_000_000_000_000)


class BlockDetectionTests(TestCase):
    """A `[screen]` mention in prose is NOT a block opener (line-anchored)."""

    REAL = "[screen]\nlimit: 5\n[/screen]"

    def test_prose_mention_before_a_real_block(self):
        criteria, errors = parse(f"Add a [screen] block to your description.\n{self.REAL}")
        self.assertEqual(errors, [])
        self.assertEqual(criteria.limit, 5)

    def test_comment_mention_inside_the_block(self):
        criteria, errors = parse(
            "[screen]\n# add a [screen] block like this\nlimit: 7\n[/screen]"
        )
        self.assertEqual(errors, [])
        self.assertEqual(criteria.limit, 7)

    def test_mention_inside_a_pine_sample(self):
        criteria, errors = parse(f"[pine]// see [screen][/pine]\n{self.REAL}")
        self.assertEqual(errors, [])
        self.assertEqual(criteria.limit, 5)

    def test_indented_opening_tag_still_opens_a_block(self):
        criteria, errors = parse("   [screen]\nlimit: 9\n[/screen]")
        self.assertEqual(errors, [])
        self.assertEqual(criteria.limit, 9)

    def test_an_inline_block_is_treated_as_prose_not_a_block(self):
        # Matches the frontend renderer, which also requires a line-start
        # opener — if they disagreed, one layer would eat text the other kept.
        criteria, errors = parse("prose [screen]limit: 5[/screen] more prose")
        self.assertEqual((criteria, errors), (None, []))

    def test_two_real_blocks_are_still_a_duplicate(self):
        criteria, errors = parse(f"{self.REAL}\nprose\n{self.REAL}")
        self.assertIsNone(criteria)
        self.assertIn("duplicate_block", errors[0]["error"])


class GoldenMappingTests(TestCase):
    """The §6.1 table, exactly — one assertion per row plus the always-sent pair."""

    def test_full_table_golden(self):
        criteria, errors = parse_block(
            "market_cap: >= 2B", "price: 10..1000", "volume: >= 1M",
            "beta: <= 2", "dividend: >= 1", "sector: Technology",
            "industry: Semiconductors", "exchange: NASDAQ", "country: US",
            "etf: false", "above_sma: 200", "sma_rising: 200",
            "near_52w_high: 25%", "min_history: 260", "limit: 50",
        )
        self.assertEqual(errors, [])
        self.assertEqual(criteria.vendor_params, {
            "marketCapMoreThan": 2_000_000_000,
            "priceMoreThan": 10,
            "priceLowerThan": 1000,
            "volumeMoreThan": 1_000_000,
            "betaLowerThan": 2,
            "dividendMoreThan": 1,
            "sector": "Technology",
            "industry": "Semiconductors",
            "exchange": "NASDAQ",
            "country": "US",
            # Always sent: isActivelyTrading is spec'd unconditional, and A9
            # makes isEtf mirror it (false unless `etf: true`).
            "isActivelyTrading": True,
            "isEtf": False,
            "limit": 50,
        })
        self.assertEqual(criteria.derived, {
            "above_sma": [200], "sma_rising": [200],
            "near_52w_high": 25, "min_history": 260,
        })

    def test_a9_isetf_always_present_even_with_no_etf_key(self):
        criteria, _ = parse_block("price: >= 1")
        self.assertIn("isEtf", criteria.vendor_params)
        self.assertIs(criteria.vendor_params["isEtf"], False)

    def test_vendor_params_carry_no_derived_keys(self):
        criteria, _ = parse_block("above_sma: 200", "sma_rising: 200", "near_52w_high: 10%")
        for leaked in ("above_sma", "sma_rising", "near_52w_high", "min_history"):
            self.assertNotIn(leaked, criteria.vendor_params)


class LinearScanTests(TestCase):
    """§11 — the block is user input inside a 256KB description (#49)."""

    def test_large_description_with_no_block_stays_fast(self):
        import time

        text = ("prose [b]bold[/b] array[0] " * 12_000) + "\ntail"
        self.assertGreater(len(text), 250_000)
        start = time.monotonic()
        criteria, errors = parse(text)
        elapsed = time.monotonic() - start
        self.assertEqual((criteria, errors), (None, []))
        self.assertLess(elapsed, 1.0)

    def test_pathological_brackets_before_a_valid_block(self):
        # The bracket run gets its own line: the opening tag is line-anchored,
        # so a block glued to the end of 50k '[' is prose by definition. What
        # this pins is that the scan stays linear regardless.
        text = "[" * 50_000 + "\n" + block("limit: 3")
        criteria, errors = parse(text)
        self.assertEqual(errors, [])
        self.assertEqual(criteria.limit, 3)
