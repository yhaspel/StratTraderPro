"""M10.5 §7.3 / §10.1 — onboarding status endpoint tests."""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.m04_testutils import (
    auth_headers,
    create_broker_account,
    create_strategy,
    create_user,
    create_webhook_config,
)
from apps.orders.models import Fill, Order

URL = "/api/v1/onboarding/status/"


def _make_fill(user, account, strategy):
    order = Order.objects.create(
        user=user, strategy=strategy, broker_account=account,
        client_order_id="ob-c1", broker_order_id="ob-b1", symbol="AAPL",
        side=Order.Side.BUY, qty=Decimal("1"), status=Order.Status.FILLED,
    )
    Fill.objects.create(
        order=order, broker_account=account, qty=Decimal("1"), price=Decimal("100"),
        ts=timezone.now(), broker_exec_id="ob-x1",
    )


class OnboardingStatusTests(TestCase):
    def test_not_mfa_gated_returns_200_for_non_mfa_user(self):
        # Step 0 is "enroll MFA" — the endpoint must not 403 a non-MFA user.
        user = create_user(email="fresh@example.com", mfa=False)
        resp = self.client.get(URL, **auth_headers(user))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(
            data,
            {"mfa_enrolled": False, "broker_connected": False,
             "strategy_ready": False, "first_fill_seen": False, "complete": False},
        )

    def test_requires_auth(self):
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_mfa_enrolled_reflected(self):
        user = create_user(email="mfa@example.com", mfa=True)
        data = self.client.get(URL, **auth_headers(user)).json()["data"]
        self.assertTrue(data["mfa_enrolled"])
        self.assertFalse(data["complete"])

    def test_broker_and_strategy_and_fill_flags(self):
        user = create_user(email="stepwise@example.com", mfa=True)
        create_broker_account(user)
        strat = create_strategy(user)
        create_webhook_config(user, strat)
        data = self.client.get(URL, **auth_headers(user)).json()["data"]
        self.assertTrue(data["broker_connected"])
        self.assertTrue(data["strategy_ready"])
        self.assertFalse(data["first_fill_seen"])
        self.assertFalse(data["complete"])

    def test_complete_when_all_steps_done(self):
        user = create_user(email="done@example.com", mfa=True)
        account = create_broker_account(user)
        strat = create_strategy(user)
        create_webhook_config(user, strat)
        _make_fill(user, account, strat)
        data = self.client.get(URL, **auth_headers(user)).json()["data"]
        self.assertTrue(all(data.values()))

    def test_owner_scoped_no_leak(self):
        # Another user's broker/strategy/fill must not flip this user's flags.
        other = create_user(email="other@example.com", mfa=True)
        account = create_broker_account(other)
        strat = create_strategy(other)
        create_webhook_config(other, strat)
        _make_fill(other, account, strat)

        me = create_user(email="me@example.com", mfa=False)
        data = self.client.get(URL, **auth_headers(me)).json()["data"]
        self.assertEqual(
            data,
            {"mfa_enrolled": False, "broker_connected": False,
             "strategy_ready": False, "first_fill_seen": False, "complete": False},
        )

    def test_disabled_strategy_does_not_count(self):
        user = create_user(email="disabled@example.com", mfa=True)
        strat = create_strategy(user)
        create_webhook_config(user, strat)
        strat.is_enabled = False
        strat.save(update_fields=["is_enabled"])
        data = self.client.get(URL, **auth_headers(user)).json()["data"]
        self.assertFalse(data["strategy_ready"])
