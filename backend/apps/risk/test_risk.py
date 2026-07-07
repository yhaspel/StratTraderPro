"""M08 — risk: sizing, kill switches, daily-loss, process_alert integration, API."""
from __future__ import annotations

import json
import time
from datetime import timedelta
from decimal import Decimal

import pyotp
from django.core.cache import cache
from django.test import TestCase
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
from apps.orders.models import Order, Position
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
        base = dict(requested_qty=Decimal("10"), side="BUY", symbol="AAPL",
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

    def test_sentiment_boost_respects_position_clamp(self):
        # The +10% sentiment boost must not breach max_position_pct (200 here).
        r = compute_size(self._inp(sentiment_polarity=0.9), self.profile)
        self.assertLessEqual(r.qty, Decimal("200"))

    def test_soft_stop_halves(self):
        normal = compute_size(self._inp(intraday_dd_pct=0.0), self.profile).qty
        stopped = compute_size(self._inp(intraday_dd_pct=6.0), self.profile).qty  # >5% soft stop
        self.assertLessEqual(stopped, normal)


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
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.account = create_broker_account(self.user)
        _profile(self.user, daily_loss_usd=Decimal("500"))

    def test_two_poll_breach_trips_l2(self):
        # A position deep underwater → daily loss below -$500.
        Position.objects.create(user=self.user, broker_account=self.account, symbol="AAPL",
                                qty=Decimal("100"), avg_cost=Decimal("100"), market_price=Decimal("90"))
        from unittest import mock

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self.assertFalse(killswitch.check_daily_loss(self.user))  # first poll
            tripped = killswitch.check_daily_loss(self.user)  # second poll → trip
        self.assertTrue(tripped)
        self.assertTrue(
            TradingHalt.objects.filter(user=self.user, level=TradingHalt.Level.L2, released_at__isnull=True).exists()
        )
        self.assertTrue(RiskEvent.objects.filter(type="DAILY_LOSS_BREACH").exists())

    def test_breach_event_not_duplicated_after_trip(self):
        # Once L2 is tripped, further polls must not re-emit the breach event/metric.
        Position.objects.create(user=self.user, broker_account=self.account, symbol="AAPL",
                                qty=Decimal("100"), avg_cost=Decimal("100"), market_price=Decimal("90"))
        from unittest import mock

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            killswitch.check_daily_loss(self.user)  # poll 1
            killswitch.check_daily_loss(self.user)  # poll 2 → trip
            killswitch.check_daily_loss(self.user)  # poll 3 → already tripped, no-op
            killswitch.check_daily_loss(self.user)  # poll 4 → no-op
        self.assertEqual(RiskEvent.objects.filter(type="DAILY_LOSS_BREACH").count(), 1)


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

        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self._post(valid_alert(symbol="AAPL", qty=1, idempotency_key="sz-1"))
        order = Order.objects.get()
        # clamped by max_position_pct: 100000*20%/100(price default) = 200
        self.assertEqual(order.qty, Decimal("200"))
        self.assertTrue(SizingDecision.objects.filter(order=order, result="OK").exists())

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


class RiskApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()

    def test_profile_get_creates_default(self):
        resp = self.client.get(f"{API}/profile/", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["permitted_asset_classes"], ["STOCK", "ETF"])

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

    def test_requires_mfa(self):
        self.assertIn(self.client.get(f"{API}/profile/").status_code, (401, 403))
