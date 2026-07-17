"""M08 — risk: sizing, kill switches, daily-loss, process_alert integration, API."""
from __future__ import annotations

import json
import time
from datetime import timedelta
from decimal import Decimal

import pyotp
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.brokers.models import TradingHalt
from apps.m04_testutils import (
    auth_headers,
    create_broker_account,
    create_strategy,
    create_user,
    create_webhook_config,
    fake_factory,
    valid_alert,
)
from apps.orders.models import Fill, Order, Position
from apps.regime.models import RegimeObservation
from apps.risk import killswitch
from apps.risk.models import RiskEvent, RiskProfile, SizingDecision
from apps.risk.sizing import SizingInputs, compute_size
from apps.users.mfa import encrypt_secret
from apps.users.models import MFADevice

API = "/api/v1/risk"


def _profile(user, **kw):
    defaults = dict(permitted_asset_classes=["STOCK", "ETF"])
    defaults.update(kw)
    return RiskProfile.objects.create(user=user, **defaults)


class SizingTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.profile = _profile(self.user)

    def _inp(self, **kw):
        # requested_qty=0 ("unspecified") so these tests exercise the sizing MATH
        # without the RISK-3 requested-qty clamp (covered by its own tests below).
        base = dict(requested_qty=Decimal("0"), side="BUY", symbol="AAPL",
                    price=Decimal("100"), equity=Decimal("100000"), regime_label="BULL")
        base.update(kw)
        return SizingInputs(**base)

    def test_deterministic(self):
        r1 = compute_size(self._inp(), self.profile)
        r2 = compute_size(self._inp(), self.profile)
        self.assertEqual(r1.qty, r2.qty)
        self.assertTrue(r1.ok)

    def test_regime_crisis_zero(self):
        r = compute_size(self._inp(regime_label="CRISIS"), self.profile)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "REGIME_CRISIS")

    def test_regime_scaling(self):
        bull = compute_size(self._inp(regime_label="BULL"), self.profile).qty
        bear = compute_size(self._inp(regime_label="BEAR"), self.profile).qty
        self.assertGreater(bull, bear)  # BEAR scale 0.3 < BULL 1.0

    def test_strict_mode_side_mismatch(self):
        p = _profile(create_user(email="strict@example.com"), strict_mode=True)
        r = compute_size(self._inp(regime_label="BEAR", side="BUY"), p)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "REGIME_SIDE_MISMATCH")

    def test_position_clamp(self):
        # risk sizing would want more, clamp caps at max_position_pct.
        r = compute_size(self._inp(price=Decimal("100"), equity=Decimal("100000")), self.profile)
        # max_qty_by_pos = 100000 * 20% / 100 = 200
        self.assertLessEqual(r.qty, Decimal("200"))

    def test_sentiment_boost_and_cut(self):
        boosted = compute_size(self._inp(sentiment_polarity=0.8), self.profile).qty
        base = compute_size(self._inp(sentiment_polarity=0.0), self.profile).qty
        cut = compute_size(self._inp(sentiment_polarity=-0.6), self.profile).qty
        self.assertGreaterEqual(boosted, base)
        self.assertLessEqual(cut, base)

    def test_sentiment_cut_factor_is_half(self):
        # RISK-4 / AC-08-6 (OQ-1 ruling): long into sentiment < -0.5 ⇒ ×0.5, not ×0.70.
        # Use a smaller position so max_position_pct is not the binding constraint.
        base = compute_size(self._inp(regime_label="BEAR", sentiment_polarity=0.0), self.profile).qty
        cut = compute_size(self._inp(regime_label="BEAR", sentiment_polarity=-0.6), self.profile).qty
        self.assertEqual(cut, base * Decimal("0.5"))

    def test_leverage_cap_clamps_notional(self):
        # RISK-2: leverage_cap=1.0 caps notional at equity → qty ≤ equity/price.
        p = _profile(create_user(email="lev@example.com"), leverage_cap=Decimal("1.0"),
                     max_position_pct=Decimal("50"), risk_per_trade_pct=Decimal("5"))
        r = compute_size(self._inp(price=Decimal("100"), equity=Decimal("100000")), p)
        self.assertLessEqual(r.qty, Decimal("1000"))  # 100000 * 1.0 / 100

    def test_requested_qty_clamps_down(self):
        # RISK-3: a small requested_qty caps the computed size; it never sizes up.
        capped = compute_size(self._inp(requested_qty=Decimal("3")), self.profile).qty
        self.assertEqual(capped, Decimal("3"))

    def test_sentiment_boost_respects_position_clamp(self):
        # The +10% sentiment boost must not breach max_position_pct (200 here).
        r = compute_size(self._inp(sentiment_polarity=0.9), self.profile)
        self.assertLessEqual(r.qty, Decimal("200"))

    def test_soft_stop_halves(self):
        normal = compute_size(self._inp(intraday_dd_pct=0.0), self.profile).qty
        stopped = compute_size(self._inp(intraday_dd_pct=6.0), self.profile).qty  # >5% soft stop
        self.assertEqual(stopped, normal * Decimal("0.5"))

    def test_option_notional_uses_100x_multiplier(self):
        # P1-2: an option controls 100 shares — notional = qty × price × 100, so
        # the leverage-1.0 cap binds at qty=10, not the ~1000 it would with mult=1.
        p = _profile(create_user(email="opt@example.com"), leverage_cap=Decimal("1.0"),
                     max_position_pct=Decimal("100"), risk_per_trade_pct=Decimal("50"))
        r = compute_size(
            self._inp(price=Decimal("100"), equity=Decimal("100000"),
                      contract_multiplier=Decimal("100")), p)
        self.assertTrue(r.ok)
        self.assertEqual(r.qty, Decimal("10"))
        notional = r.qty * Decimal("100") * Decimal("100")  # qty × price × multiplier
        self.assertLessEqual(notional, Decimal("100000"))  # ≤ equity × leverage_cap

    def test_leverage_cap_binds_for_options(self):
        # The option ceiling is exactly 100× tighter than the equity ceiling.
        p = _profile(create_user(email="optlev@example.com"), leverage_cap=Decimal("1.0"),
                     max_position_pct=Decimal("100"), risk_per_trade_pct=Decimal("50"))
        opt = compute_size(self._inp(price=Decimal("100"), equity=Decimal("100000"),
                                     contract_multiplier=Decimal("100")), p).qty
        eq = compute_size(self._inp(price=Decimal("100"), equity=Decimal("100000"),
                                    contract_multiplier=Decimal("1")), p).qty
        self.assertEqual(eq, opt * Decimal("100"))

    def test_equity_sizing_unchanged(self):
        # Regression: default multiplier (1) reproduces pre-P1-2 sizing exactly.
        r = compute_size(self._inp(price=Decimal("100"), equity=Decimal("100000")), self.profile)
        self.assertEqual(r.qty, Decimal("200"))  # equity × 20% / price

    def test_hard_stop_rejects_at_threshold(self):
        # P1-8: at/above hard_stop_pct (default 10%) the order is rejected outright.
        r = compute_size(self._inp(intraday_dd_pct=11.0), self.profile)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "HARD_STOP")

    def test_hard_stop_boundary_is_inclusive(self):
        # Exactly at the threshold rejects (>=).
        r = compute_size(self._inp(intraday_dd_pct=10.0), self.profile)  # hard_stop 10%
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "HARD_STOP")

    def test_soft_stop_still_only_halves_below_hard(self):
        # Between soft (5%) and hard (10%): halve, don't reject.
        r = compute_size(self._inp(intraday_dd_pct=6.0), self.profile)
        self.assertTrue(r.ok)
        self.assertTrue(r.meta.get("soft_stop_applied"))


class KillSwitchEngineTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.strategy = create_strategy(self.user)

    def test_is_blocked_truth_table(self):
        self.assertIsNone(killswitch.is_blocked(self.user.id, self.strategy.id))
        h = killswitch.trigger_halt(user_id=self.user.id, level=TradingHalt.Level.L0,
                                    strategy_id=self.strategy.id, reason="t")
        self.assertEqual(killswitch.is_blocked(self.user.id, self.strategy.id), "STRATEGY_HALTED")
        # other strategy not blocked
        other = create_strategy(self.user, slug="other")
        self.assertIsNone(killswitch.is_blocked(self.user.id, other.id))
        killswitch.release_halt(h.id)
        # user global
        killswitch.trigger_halt(user_id=self.user.id, level=TradingHalt.Level.L1, reason="halt")
        self.assertEqual(killswitch.is_blocked(self.user.id, other.id), "USER_HALTED")

    def test_platform_halt_blocks_everyone(self):
        killswitch.trigger_halt(user_id=None, level=TradingHalt.Level.L3, reason="platform")
        other_user = create_user(email="u2@example.com")
        self.assertEqual(killswitch.is_blocked(other_user.id, None), "PLATFORM_HALTED")

    @override_settings(KILL_SWITCHES_ENABLED=False)
    def test_platform_halt_enforced_even_when_engine_disabled(self):
        # P1-7: the ops flag disables auto-tripping, NEVER the emergency stop.
        killswitch.trigger_halt(user_id=None, level=TradingHalt.Level.L3, reason="platform")
        self.assertEqual(killswitch.is_blocked(self.user.id, None), "PLATFORM_HALTED")

    @override_settings(KILL_SWITCHES_ENABLED=False)
    def test_user_halt_enforced_when_engine_disabled(self):
        killswitch.trigger_halt(user_id=self.user.id, level=TradingHalt.Level.L1, reason="halt")
        self.assertEqual(killswitch.is_blocked(self.user.id, self.strategy.id), "USER_HALTED")

    @override_settings(KILL_SWITCHES_ENABLED=False)
    def test_existing_l2_daily_loss_halt_enforced_when_engine_disabled(self):
        killswitch.trigger_halt(user_id=self.user.id, level=TradingHalt.Level.L2,
                                reason="DAILY_LOSS_BREACH", auto=True)
        self.assertEqual(killswitch.is_blocked(self.user.id, None), "USER_HALTED")

    @override_settings(KILL_SWITCHES_ENABLED=False)
    def test_flag_only_gates_auto_trip_not_enforcement(self):
        # With the engine off the watcher must not TRIP a new L2 halt...
        from apps.risk.tasks import daily_loss_watcher

        self.assertEqual(daily_loss_watcher(), {"skipped": "disabled"})
        # ...but an operator-created halt is still enforced (proven above).

    def test_l2_release_locked_until_next_day(self):
        h = killswitch.trigger_halt(user_id=self.user.id, level=TradingHalt.Level.L2,
                                    reason="daily loss", auto=True)
        self.assertFalse(killswitch.release_halt(h.id))  # locked same trading day
        self.assertTrue(TradingHalt.objects.get(id=h.id).is_active)

    def test_expired_l2_auto_released_next_trading_day(self):
        # AC-08-9: the watcher's sweep releases an L2 halt once the day rolls over.
        h = killswitch.trigger_halt(user_id=self.user.id, level=TradingHalt.Level.L2,
                                    reason="daily loss", auto=True)
        self.assertEqual(killswitch.release_expired_l2_halts(), 0)  # same day → still locked
        self.assertTrue(TradingHalt.objects.get(id=h.id).is_active)
        # simulate the halt having been created two days ago
        TradingHalt.objects.filter(id=h.id).update(created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(killswitch.release_expired_l2_halts(), 1)
        self.assertFalse(TradingHalt.objects.get(id=h.id).is_active)
        self.assertIsNone(killswitch.is_blocked(self.user.id, None))

    def test_flatten_latency_and_flat(self):
        account = create_broker_account(self.user)
        Position.objects.create(user=self.user, broker_account=account, symbol="AAPL",
                                qty=Decimal("10"), avg_cost=Decimal("100"))
        from unittest import mock

        t0 = time.monotonic()
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            killswitch.flatten_user(self.user.id, scope="USER")
        self.assertLess(time.monotonic() - t0, 5.0)  # AC-08-8 budget
        self.assertEqual(Position.objects.get(symbol="AAPL").qty, 0)


class DailyLossTests(TestCase):
    """FIX-B1: L2 fires on broker-truth *daily* P&L (equity − prev-day close),
    NOT lifetime unrealized P&L on open positions."""

    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.account = create_broker_account(self.user)
        _profile(self.user, daily_loss_usd=Decimal("500"))

    def _adapter(self, **kw):
        from unittest import mock

        return mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory(**kw))

    def test_two_poll_breach_trips_l2(self):
        # Broker-truth daily P&L: equity 99,000 vs prev-close 100,000 = −1,000 (< −500).
        with self._adapter(equity=Decimal("99000"), last_equity=Decimal("100000")):
            self.assertFalse(killswitch.check_daily_loss(self.user))  # first poll
            tripped = killswitch.check_daily_loss(self.user)  # second poll → trip
        self.assertTrue(tripped)
        self.assertTrue(
            TradingHalt.objects.filter(user=self.user, level=TradingHalt.Level.L2, released_at__isnull=True).exists()
        )
        self.assertTrue(RiskEvent.objects.filter(type="DAILY_LOSS_BREACH").exists())

    def test_check_daily_loss_uses_default_threshold_without_profile(self):
        # P0-1: a connected account with no explicit RiskProfile still gets
        # daily-loss protection via the conservative default threshold ($1000).
        user = create_user(email="np@example.com")
        create_broker_account(user)  # connected; NO RiskProfile
        self.assertFalse(RiskProfile.objects.filter(user=user).exists())
        with self._adapter(equity=Decimal("98500"), last_equity=Decimal("100000")):
            self.assertFalse(killswitch.check_daily_loss(user))  # −1500 < −1000, poll 1
            tripped = killswitch.check_daily_loss(user)  # poll 2 → trip
        self.assertTrue(tripped)
        self.assertTrue(
            TradingHalt.objects.filter(user=user, level=TradingHalt.Level.L2).exists()
        )

    def test_held_overnight_loss_flat_on_day_does_not_trip(self):
        # A swing position sitting at a loss but flat on the DAY (equity ==
        # last_equity) must NOT trip — the whole point of FIX-B1.
        with self._adapter(equity=Decimal("90000"), last_equity=Decimal("90000")):
            self.assertFalse(killswitch.check_daily_loss(self.user))
            self.assertFalse(killswitch.check_daily_loss(self.user))
        self.assertFalse(
            TradingHalt.objects.filter(user=self.user, level=TradingHalt.Level.L2).exists()
        )

    def test_broker_read_failure_does_not_trip_or_release(self):
        from unittest import mock

        failing = mock.Mock()
        failing.get_account.side_effect = RuntimeError("broker down")
        with mock.patch("apps.brokers.services.build_adapter", return_value=failing):
            # Fail-safe sentinel → skip the poll; never trip on a monitoring gap.
            self.assertIsNone(killswitch.user_daily_pnl(self.user))
            self.assertFalse(killswitch.check_daily_loss(self.user))
        self.assertFalse(
            TradingHalt.objects.filter(user=self.user, level=TradingHalt.Level.L2).exists()
        )

    def test_no_immediate_retrip_after_release_on_held_loser(self):
        # Day 1: −1,000 on the day → trips L2 after two polls.
        with self._adapter(equity=Decimal("99000"), last_equity=Decimal("100000")):
            killswitch.check_daily_loss(self.user)
            self.assertTrue(killswitch.check_daily_loss(self.user))
        halt = TradingHalt.objects.get(user=self.user, level=TradingHalt.Level.L2, released_at__isnull=True)
        # Roll the trading day over, then auto-release.
        TradingHalt.objects.filter(id=halt.id).update(created_at=timezone.now() - timedelta(days=2))
        cache.clear()
        self.assertEqual(killswitch.release_expired_l2_halts(), 1)
        # Day 2: the SAME loser is still held, but the broker's prev-close rolled
        # to yesterday's 99k → today it is flat → NO re-trip (old bug re-tripped).
        with self._adapter(equity=Decimal("99000"), last_equity=Decimal("99000")):
            self.assertFalse(killswitch.check_daily_loss(self.user))
            self.assertFalse(killswitch.check_daily_loss(self.user))
        self.assertIsNone(killswitch.is_blocked(self.user.id, None))

    def test_zero_usd_threshold_is_no_limit_not_trip_on_any_loss(self):
        # A 0 daily_loss_usd (unvalidated, user-settable) means "no USD limit",
        # NOT "halt on any down day" — else broker-equity pnl<=0 trips at the open.
        RiskProfile.objects.filter(user=self.user).update(daily_loss_usd=Decimal("0"))
        with self._adapter(equity=Decimal("99900"), last_equity=Decimal("100000")):  # -$100
            killswitch.check_daily_loss(self.user)
            self.assertFalse(killswitch.check_daily_loss(self.user))
        self.assertFalse(
            TradingHalt.objects.filter(user=self.user, level=TradingHalt.Level.L2).exists()
        )

    def test_breach_event_not_duplicated_after_trip(self):
        # Once L2 is tripped, further polls must not re-emit the breach event/metric.
        with self._adapter(equity=Decimal("99000"), last_equity=Decimal("100000")):
            killswitch.check_daily_loss(self.user)  # poll 1
            killswitch.check_daily_loss(self.user)  # poll 2 → trip
            killswitch.check_daily_loss(self.user)  # poll 3 → already tripped, no-op
            killswitch.check_daily_loss(self.user)  # poll 4 → no-op
        self.assertEqual(RiskEvent.objects.filter(type="DAILY_LOSS_BREACH").count(), 1)


class TradingDayTests(TestCase):
    """FIX-M8: the trading day is the US/Eastern calendar day (DST-correct)."""

    def test_est_and_edt_map_to_new_york_day(self):
        import datetime as _dt

        # 02:00 UTC in January = 21:00 EST the previous day → NY day is the 14th.
        est = _dt.datetime(2026, 1, 15, 2, 0, tzinfo=_dt.timezone.utc)
        self.assertEqual(killswitch.trading_day(est), _dt.date(2026, 1, 14))
        # 02:00 UTC in July = 22:00 EDT the previous day → NY day is the 14th.
        edt = _dt.datetime(2026, 7, 15, 2, 0, tzinfo=_dt.timezone.utc)
        self.assertEqual(killswitch.trading_day(edt), _dt.date(2026, 7, 14))


class DailyLossWatcherTests(TestCase):
    """FIX-M15: single-flight lock + market-hours gate on the 30s watcher."""

    def setUp(self):
        cache.clear()
        self.user = create_user()
        create_broker_account(self.user)
        _profile(self.user, daily_loss_usd=Decimal("500"))

    def test_overlap_guard_is_noop(self):
        from apps.risk.tasks import daily_loss_watcher

        cache.add("risk:daily_loss_watcher:lock", "1", timeout=45)  # a run is "in flight"
        self.assertEqual(daily_loss_watcher(), {"skipped": "locked"})

    def test_off_hours_skips_trip(self):
        from unittest import mock

        from apps.risk.tasks import daily_loss_watcher

        with mock.patch("apps.risk.killswitch.market_is_open", return_value=False):
            result = daily_loss_watcher()
        self.assertEqual(result.get("skipped"), "market_closed")

    def test_daily_loss_watcher_covers_accounts_without_explicit_profile(self):
        # P0-1: the watcher sweeps every connected LIVE account, even one whose
        # user has no RiskProfile — the L2 breaker must arm on live money.
        from unittest import mock

        from apps.brokers.models import BrokerAccount
        from apps.risk.tasks import daily_loss_watcher

        user = create_user(email="livenp@example.com")
        BrokerAccount.objects.create(
            user=user, broker=BrokerAccount.Broker.ALPACA, mode=BrokerAccount.Mode.LIVE,
            api_key_id_enc=b"x", api_secret_enc=b"x", account_number="LIVE9",
            status=BrokerAccount.Status.CONNECTED,
        )
        self.assertFalse(RiskProfile.objects.filter(user=user).exists())
        with mock.patch("apps.risk.killswitch.market_is_open", return_value=True), mock.patch(
            "apps.brokers.services.build_adapter",
            side_effect=fake_factory(equity=Decimal("98000"), last_equity=Decimal("100000")),
        ):
            daily_loss_watcher()  # poll 1 (releases its single-flight lock on exit)
            daily_loss_watcher()  # poll 2 → trip
        self.assertTrue(
            TradingHalt.objects.filter(user=user, level=TradingHalt.Level.L2).exists()
        )


class ProcessAlertSizingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.strategy = create_strategy(self.user)
        self.wc = create_webhook_config(self.user, self.strategy)
        self.url = f"/hooks/v1/{self.user.id}/{self.strategy.id}/"
        create_broker_account(self.user)
        RegimeObservation.objects.create(scope="MARKET", ts=timezone.now(), label="BULL",
                                          rule_bucket="RISK_ON", rule_score=80.0)

    def _post(self, body):
        return self.client.post(self.url, data=json.dumps(body), content_type="application/json")

    def test_sizing_applied_when_profile_exists(self):
        _profile(self.user)  # risk 1%, max_position 20%
        from unittest import mock

        # Request a large qty so the sizing clamp-down (not the RISK-3 requested
        # cap) is what governs the final size.
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(symbol="AAPL", qty=1000, idempotency_key="sz-1"))
        order = Order.objects.get()
        # clamped by max_position_pct: 100000*20%/100(price default) = 200
        self.assertEqual(order.qty, Decimal("200"))
        self.assertTrue(SizingDecision.objects.filter(order=order, result="OK").exists())

    def test_requested_qty_caps_order_qty(self):
        # RISK-3: an alert qty=1 with a profile is NOT inflated to 200 — capped at 1.
        _profile(self.user)
        from unittest import mock

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(symbol="AAPL", qty=1, idempotency_key="rq-1"))
        self.assertEqual(Order.objects.get().qty, Decimal("1"))

    def test_soft_stop_fires_on_real_intraday_drawdown(self):
        # RISK-1: intraday DD from equity vs last_equity trips the soft-stop (halves).
        # hard_stop raised to 20% so the 10% DD stays in soft-stop territory (P1-8).
        _profile(self.user, hard_stop_pct=Decimal("20"))
        from unittest import mock

        with mock.patch(
            "apps.brokers.services.build_adapter",
            side_effect=fake_factory(equity=Decimal("90000"), last_equity=Decimal("100000")),
        ):
            self._post(valid_alert(symbol="AAPL", qty=1000, idempotency_key="ss-1"))
        dec = SizingDecision.objects.get()
        self.assertTrue(dec.inputs.get("soft_stop_applied"))
        # 90000*20%/100 = 180 → ×0.5 soft-stop = 90.
        self.assertEqual(Order.objects.get().qty, Decimal("90"))

    def test_asset_class_not_permitted_rejects(self):
        # RISK-2: an asset class outside permitted_asset_classes is rejected.
        _profile(self.user, permitted_asset_classes=["OPTION"])
        from unittest import mock

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(symbol="AAPL", qty=1, idempotency_key="ac-1"))
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.REJECTED)
        self.assertEqual(order.reason, "SIZING_ASSET_CLASS_BLOCKED")

    def test_no_risk_profile_rejects_in_live_mode(self):
        # P0-1: a LIVE account with no RiskProfile fails closed (NO_RISK_PROFILE);
        # nothing reaches the adapter — the raw alert qty must not go out unsized.
        from unittest import mock

        from apps.brokers.fake import FakeBrokerAdapter
        from apps.brokers.models import BrokerAccount

        BrokerAccount.objects.filter(user=self.user).delete()
        BrokerAccount.objects.create(
            user=self.user, broker=BrokerAccount.Broker.ALPACA, mode=BrokerAccount.Mode.LIVE,
            api_key_id_enc=b"x", api_secret_enc=b"x", account_number="LIVE001",
            is_default=True, status=BrokerAccount.Status.CONNECTED,
        )
        self.assertFalse(RiskProfile.objects.filter(user=self.user).exists())
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()), \
                mock.patch.object(FakeBrokerAdapter, "place_order") as place:
            self._post(valid_alert(symbol="AAPL", qty=1000, idempotency_key="nrp-1"))
        place.assert_not_called()
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.REJECTED)
        self.assertEqual(order.reason, "NO_RISK_PROFILE")
        self.assertTrue(
            SizingDecision.objects.filter(order=order, reject_reason="NO_RISK_PROFILE").exists()
        )

    def test_process_alert_option_uses_100x_multiplier(self):
        # P1-2: an OPTION order is sized with the 100× multiplier end-to-end.
        _profile(self.user, permitted_asset_classes=["OPTION"],
                 max_position_pct=Decimal("100"), leverage_cap=Decimal("1.0"),
                 risk_per_trade_pct=Decimal("50"))
        from unittest import mock

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(
                symbol="AAPL", qty=1000, asset_class="OPTION",
                option_expiry="2026-12-18", option_strike=100, option_right="CALL",
                idempotency_key="opt-mult-1",
            ))
        dec = SizingDecision.objects.get()
        self.assertEqual(dec.inputs.get("contract_multiplier"), 100.0)
        # price 100 × mult 100, leverage cap 1.0, equity 100k ⇒ ≤ 10 contracts.
        self.assertEqual(Order.objects.get().qty, Decimal("10"))

    def test_hard_stop_rejects_and_halts_at_threshold(self):
        # P1-8: a hard-stop breach rejects the order AND trips an L2 daily halt.
        _profile(self.user)  # hard_stop 10%
        from unittest import mock

        with mock.patch(
            "apps.brokers.services.build_adapter",
            side_effect=fake_factory(equity=Decimal("88000"), last_equity=Decimal("100000")),
        ):  # 12% intraday drawdown ≥ 10%
            self._post(valid_alert(symbol="AAPL", qty=10, idempotency_key="hs-1"))
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.REJECTED)
        self.assertEqual(order.reason, "HARD_STOP")
        self.assertTrue(
            TradingHalt.objects.filter(
                user=self.user, level=TradingHalt.Level.L2, auto=True, released_at__isnull=True
            ).exists()
        )

    def test_paper_no_profile_places_verbatim_qty(self):
        # Regression: paper + no profile keeps M04 verbatim-qty behavior (sizing off).
        from unittest import mock

        self.assertFalse(RiskProfile.objects.filter(user=self.user).exists())
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(symbol="AAPL", qty=7, idempotency_key="pnp-1"))
        order = Order.objects.get()
        self.assertEqual(order.qty, Decimal("7"))
        self.assertNotEqual(order.status, Order.Status.REJECTED)
        self.assertFalse(SizingDecision.objects.exists())

    def test_max_concurrent_rejects_new_symbol(self):
        # RISK-2: at max_concurrent open positions, a new symbol is rejected.
        from apps.brokers.models import BrokerAccount
        _profile(self.user, max_concurrent=2)
        ba = BrokerAccount.objects.filter(user=self.user).first()
        Position.objects.create(user=self.user, broker_account=ba, symbol="MSFT", qty=Decimal("10"))
        Position.objects.create(user=self.user, broker_account=ba, symbol="TSLA", qty=Decimal("5"))
        from unittest import mock

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(symbol="AAPL", qty=1, idempotency_key="mc-1"))
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.REJECTED)
        self.assertEqual(order.reason, "SIZING_MAX_CONCURRENT")

    def test_crisis_rejects(self):
        _profile(self.user)
        RegimeObservation.objects.create(scope="MARKET", ts=timezone.now(), label="CRISIS",
                                         rule_bucket="PANIC", rule_score=10.0)
        from unittest import mock

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(symbol="AAPL", qty=1, idempotency_key="sz-2"))
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.REJECTED)
        self.assertEqual(order.reason, "REGIME_CRISIS")

    def test_no_profile_uses_raw_qty(self):
        from unittest import mock

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(symbol="AAPL", qty=7, idempotency_key="sz-3"))
        self.assertEqual(Order.objects.get().qty, Decimal("7"))  # M04 behavior preserved

    def test_sizes_off_equity_not_buying_power(self):
        # FIX-H1: buying_power is 2–4× levered; sizing must use equity.
        _profile(self.user)
        from unittest import mock

        with mock.patch(
            "apps.brokers.services.build_adapter",
            side_effect=fake_factory(buying_power=Decimal("200000"), equity=Decimal("100000")),
        ):
            self._post(valid_alert(symbol="AAPL", qty=1000, idempotency_key="eq-1"))
        # 100000*20%/100 = 200 (would be 400 if sized off buying_power).
        self.assertEqual(Order.objects.get().qty, Decimal("200"))

    def test_equity_read_failure_rejects_fail_closed(self):
        # FIX-H2: a broker hiccup must reject SIZING_NO_EQUITY, never size off a constant.
        _profile(self.user)
        from unittest import mock

        failing = mock.Mock()
        failing.get_account.side_effect = RuntimeError("broker down")
        failing.place_order.side_effect = AssertionError("must not place an order")
        with mock.patch("apps.brokers.services.build_adapter", return_value=failing):
            self._post(valid_alert(symbol="AAPL", qty=1, idempotency_key="ne-1"))
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.REJECTED)
        self.assertEqual(order.reason, "SIZING_NO_EQUITY")
        self.assertFalse(Fill.objects.exists())

    def test_market_order_without_price_rejects(self):
        # FIX-H3: no quote + empty Bar table → SIZING_NO_PRICE, never a fabricated $100.
        _profile(self.user)
        from unittest import mock

        with mock.patch(
            "apps.brokers.services.build_adapter", side_effect=fake_factory(quote_price=None)
        ):
            self._post(valid_alert(symbol="AAPL", qty=1, idempotency_key="np-1", order_type="MKT"))
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.REJECTED)
        self.assertEqual(order.reason, "SIZING_NO_PRICE")

    def test_limit_order_with_price_sizes(self):
        # FIX-H3: an LMT alert carries a trusted price even with no quote.
        _profile(self.user)
        from unittest import mock

        with mock.patch(
            "apps.brokers.services.build_adapter", side_effect=fake_factory(quote_price=None)
        ):
            self._post(valid_alert(symbol="AAPL", qty=1000, idempotency_key="lp-1",
                                   order_type="LMT", limit_price="100"))
        order = Order.objects.get()
        self.assertNotEqual(order.status, Order.Status.REJECTED)
        self.assertEqual(order.qty, Decimal("200"))

    def test_sizing_decision_records_equity_and_price(self):
        # FIX-L3: persist the two most safety-relevant inputs.
        _profile(self.user)
        from unittest import mock

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(symbol="AAPL", qty=1, idempotency_key="sd-1"))
        dec = SizingDecision.objects.get()
        self.assertEqual(dec.inputs.get("equity"), "100000")
        self.assertEqual(dec.inputs.get("price"), "100.00")

    def test_sizing_reject_emits_risk_event(self):
        # FIX-L6: a sizing reject emits a SIZING_REJECT risk event.
        _profile(self.user)
        RegimeObservation.objects.create(scope="MARKET", ts=timezone.now(), label="CRISIS",
                                         rule_bucket="PANIC", rule_score=10.0)
        from unittest import mock

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(symbol="AAPL", qty=1, idempotency_key="se-1"))
        self.assertTrue(RiskEvent.objects.filter(type="SIZING_REJECT").exists())


class RiskApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()

    def test_profile_get_returns_defaults_without_persisting(self):
        # RISK-3: GET returns defaults but must NOT create a row (a persisted
        # profile turns sizing on; merely viewing the page should not).
        resp = self.client.get(f"{API}/profile/", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["permitted_asset_classes"], ["STOCK", "ETF"])
        self.assertFalse(RiskProfile.objects.filter(user=self.user).exists())

    def test_profile_put_creates_row(self):
        # First write creates it lazily.
        self.assertFalse(RiskProfile.objects.filter(user=self.user).exists())
        self.client.put(f"{API}/profile/", data={"risk_per_trade_pct": 2.0},
                        content_type="application/json", **auth_headers(self.user))
        self.assertTrue(RiskProfile.objects.filter(user=self.user).exists())

    def test_profile_validation(self):
        # risk_per_trade_pct > 5 rejected (AC-08-2)
        resp = self.client.put(f"{API}/profile/", data={"risk_per_trade_pct": 9.0},
                               content_type="application/json", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 400)
        # soft >= hard rejected
        resp = self.client.put(f"{API}/profile/", data={"soft_stop_pct": 10, "hard_stop_pct": 5},
                               content_type="application/json", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 400)

    def test_profile_put_ok(self):
        resp = self.client.put(f"{API}/profile/", data={"risk_per_trade_pct": 2.0},
                               content_type="application/json", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(float(resp.json()["data"]["risk_per_trade_pct"]), 2.0)

    def test_killswitch_strategy_toggle(self):
        strat = create_strategy(self.user)
        resp = self.client.post(f"{API}/killswitches/",
                                data={"scope": "STRATEGY", "target_id": str(strat.id), "active": True},
                                content_type="application/json", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(killswitch.is_blocked(self.user.id, strat.id), "STRATEGY_HALTED")

    def test_killswitch_user_requires_mfa(self):
        secret = pyotp.random_base32()
        u = create_user(email="mfauser@example.com", mfa=False)
        MFADevice.objects.create(user=u, secret_encrypted=encrypt_secret(secret), verified=True)
        # without mfa_code → 403
        resp = self.client.post(f"{API}/killswitches/", data={"scope": "USER", "active": True},
                                content_type="application/json", **auth_headers(u))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "MFA_REQUIRED")
        # with valid code → 201
        resp = self.client.post(f"{API}/killswitches/",
                                data={"scope": "USER", "active": True, "mfa_code": pyotp.TOTP(secret).now()},
                                content_type="application/json", **auth_headers(u))
        self.assertEqual(resp.status_code, 201)

    def test_killswitch_platform_admin_only(self):
        resp = self.client.post(f"{API}/killswitches/", data={"scope": "PLATFORM", "active": True},
                                content_type="application/json", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 403)

    def test_killswitch_release_requires_mfa(self):
        # FIX-M14: releasing a USER halt is the dangerous direction — MFA required.
        secret = pyotp.random_base32()
        u = create_user(email="rel@example.com", mfa=False)
        MFADevice.objects.create(user=u, secret_encrypted=encrypt_secret(secret), verified=True)
        self.client.post(f"{API}/killswitches/",
                         data={"scope": "USER", "active": True, "mfa_code": pyotp.TOTP(secret).now()},
                         content_type="application/json", **auth_headers(u))
        # release WITHOUT a code → 403
        resp = self.client.post(f"{API}/killswitches/", data={"scope": "USER", "active": False},
                                content_type="application/json", **auth_headers(u))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "MFA_REQUIRED")
        # release WITH a valid code → success
        resp = self.client.post(f"{API}/killswitches/",
                                data={"scope": "USER", "active": False, "mfa_code": pyotp.TOTP(secret).now()},
                                content_type="application/json", **auth_headers(u))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["data"]["released"])

    def test_strategy_flatten_rejected(self):
        # FIX-H4: STRATEGY-scope flatten would liquidate the whole account → 400.
        strat = create_strategy(self.user)
        from unittest import mock

        with mock.patch("apps.risk.killswitch.flatten_user") as flatten:
            resp = self.client.post(
                f"{API}/killswitches/",
                data={"scope": "STRATEGY", "target_id": str(strat.id), "active": True, "flatten": True},
                content_type="application/json", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 400)
        flatten.assert_not_called()
        # ...but the plain L0 toggle (no flatten) still halts new orders.
        resp = self.client.post(
            f"{API}/killswitches/",
            data={"scope": "STRATEGY", "target_id": str(strat.id), "active": True},
            content_type="application/json", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(killswitch.is_blocked(self.user.id, strat.id), "STRATEGY_HALTED")

    def test_killswitch_foreign_strategy_rejected(self):
        # FIX-L2: a strategy the caller doesn't own must not reach TradingHalt.create.
        other = create_user(email="other@example.com")
        strat = create_strategy(other)
        resp = self.client.post(
            f"{API}/killswitches/",
            data={"scope": "STRATEGY", "target_id": str(strat.id), "active": True},
            content_type="application/json", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(TradingHalt.objects.filter(strategy_id=strat.id).exists())

    def test_requires_mfa(self):
        self.assertIn(self.client.get(f"{API}/profile/").status_code, (401, 403))
