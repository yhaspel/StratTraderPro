"""Production-sizing parity (M09 §10.1, AC-09-12) — non-tautological.

Asserts the ``SizingInputs`` the replay constructs equals what live ``apply_sizing``
would construct for the same trade (via integration's own ``_atr14`` /
``_latest_regime_label`` / ``_latest_sentiment`` helpers), that ``_atr14`` is
bit-identical, and that qty matches through ``compute_size`` — with the compared
trade pinned to the fixture's final bar (``_atr14`` has no as-of parameter).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.backtest.replay_engine import atr14_from_bars, build_sizing_inputs
from apps.marketdata.services import upsert_bars
from apps.risk import integration
from apps.risk.models import RiskProfile
from apps.risk.sizing import SizingInputs, compute_size

from ._fixtures import bars_df

User = get_user_model()
SYMBOL = "AAPL"


def _rows():
    """20 bars with a constant true range of 2.5 → ATR-14 == 2.5 exactly."""
    out = []
    for i in range(20):
        close = 100.0 + i
        out.append((round(close - 0.5, 2), round(close + 1.0, 2), round(close - 1.5, 2), round(close, 2), 1_000_000))
    return out


class SizingParityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="p@example.com", password="SecurePass123!", display_name="P")
        self.profile, _ = RiskProfile.objects.get_or_create(user=self.user)
        rows = _rows()
        self.frame = bars_df(rows, start=date(2020, 1, 1))
        # Store the same bars in the DB (business-day ts) for the production _atr14 path.
        ts = pd.bdate_range("2020-01-02", periods=len(rows), tz="UTC")
        upsert_bars(SYMBOL, "1d", [
            {"ts": datetime(t.year, t.month, t.day, tzinfo=dt_timezone.utc),
             "open": r[0], "high": r[1], "low": r[2], "close": r[3], "volume": r[4]}
            for t, r in zip(ts, rows, strict=True)
        ])

    def test_atr14_identical(self):
        replay_atr = atr14_from_bars(self.frame, len(self.frame) - 1)
        prod_atr = integration._atr14(SYMBOL)
        self.assertIsNotNone(replay_atr)
        self.assertEqual(replay_atr, prod_atr)
        self.assertEqual(prod_atr, Decimal("2.5"))

    def test_sizing_inputs_match_except_documented_divergences(self):
        last_close = Decimal(str(self.frame["close"].iloc[-1]))  # production MKT price = last Bar.close
        equity = Decimal("100000")
        replay_atr = atr14_from_bars(self.frame, len(self.frame) - 1)

        replay_inp = build_sizing_inputs(
            symbol=SYMBOL, price=last_close, equity=equity, atr14=replay_atr,
            stop_distance=Decimal("2.0"), side="BUY",  # replay populates from adapter stops
        )
        prod_inp = SizingInputs(  # mirror apply_sizing's construction with integration helpers
            requested_qty=Decimal("5"), side="BUY", symbol=SYMBOL, price=last_close, equity=equity,
            regime_label=integration._latest_regime_label(),
            sentiment_polarity=integration._latest_sentiment(SYMBOL),
            intraday_dd_pct=0.0, atr14=integration._atr14(SYMBOL),
            stop_distance=None,  # production passes None
        )
        # Non-excepted fields are identical.
        for f in ("side", "symbol", "price", "equity", "atr14", "contract_multiplier", "lot_size"):
            self.assertEqual(getattr(replay_inp, f), getattr(prod_inp, f), f)
        # Documented divergences.
        self.assertIsNone(prod_inp.stop_distance)
        self.assertEqual(replay_inp.stop_distance, Decimal("2.0"))
        # Neutralised fields coincide with production (no regime/sentiment feed in the fixture).
        self.assertEqual(replay_inp.regime_label, "NEUTRAL")
        self.assertEqual(prod_inp.regime_label, "NEUTRAL")
        self.assertEqual(replay_inp.sentiment_polarity, 0.0)

        # qty matches through compute_size (ATR-based stop dominates → stop_distance-invariant).
        q_replay = compute_size(replay_inp, self.profile)
        q_prod = compute_size(prod_inp, self.profile)
        self.assertTrue(q_replay.ok and q_prod.ok)
        self.assertEqual(q_replay.qty, q_prod.qty)
        self.assertEqual(q_replay.qty, Decimal("160.0"))

    def test_requested_qty_is_unread_by_compute_size(self):
        inp = build_sizing_inputs(symbol=SYMBOL, price=Decimal("119"), equity=Decimal("100000"),
                                  atr14=Decimal("2.5"), stop_distance=None)
        a = compute_size(replace(inp, requested_qty=Decimal("0")), self.profile)
        b = compute_size(replace(inp, requested_qty=Decimal("999999")), self.profile)
        self.assertEqual(a.qty, b.qty)  # requested_qty must not influence the size
