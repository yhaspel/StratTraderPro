"""M05 — order lifecycle: extended order types, asset classes, broker routing,
reconciliation, live-mode gate, and the Orders API (pagination/filters/CSV)."""
from __future__ import annotations

import json
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.brokers.models import BrokerAccount
from apps.m04_testutils import (
    auth_headers,
    create_broker_account,
    create_strategy,
    create_user,
    create_webhook_config,
    fake_factory,
    valid_alert,
)
from apps.orders.models import Order, Position, ReconEvent
from apps.orders.reconcile import reconcile_account


class _WebhookBase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.strategy = create_strategy(self.user)
        self.wc = create_webhook_config(self.user, self.strategy)
        self.url = f"/hooks/v1/{self.user.id}/{self.strategy.id}/"

    def post(self, body):
        return self.client.post(self.url, data=json.dumps(body), content_type="application/json")


class ExtendedOrderTypeTests(_WebhookBase):
    def _send(self, **overrides):
        create_broker_account(self.user)
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self.post(valid_alert(**overrides))
        return Order.objects.get()

    def test_stop_order(self):
        o = self._send(order_type="STP", stop_price=145.5, idempotency_key="stp-1")
        self.assertEqual(o.order_type, Order.OrderType.STP)
        self.assertEqual(o.stop_price, Decimal("145.5"))

    def test_stop_limit_order(self):
        o = self._send(order_type="STP_LMT", stop_price=145, limit_price=144, idempotency_key="sl-1")
        self.assertEqual(o.order_type, Order.OrderType.STP_LMT)
        self.assertEqual(o.stop_price, Decimal("145"))
        self.assertEqual(o.limit_price, Decimal("144"))

    def test_gtc_tif(self):
        o = self._send(tif="GTC", idempotency_key="gtc-1")
        self.assertEqual(o.time_in_force, Order.TimeInForce.GTC)

    def test_stop_missing_price_rejected(self):
        create_broker_account(self.user)
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self.post(valid_alert(order_type="STP", idempotency_key="stp-bad"))
        self.assertEqual(Order.objects.get().status, Order.Status.REJECTED)


class AssetClassTests(_WebhookBase):
    def test_option_accepted(self):
        create_broker_account(self.user)
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self.post(valid_alert(
                symbol="AAPL240119C00150000", asset_class="OPTION",
                option_expiry="2024-01-19", option_strike=150, option_right="CALL",
                idempotency_key="opt-1",
            ))
        o = Order.objects.get()
        self.assertEqual(o.asset_class, Order.AssetClass.OPTION)
        self.assertEqual(o.status, Order.Status.FILLED)

    def test_future_rejected_on_alpaca(self):
        # Real AlpacaAdapter rejects FUTURE before any network call.
        create_broker_account(self.user)
        self.post(valid_alert(symbol="ES", asset_class="FUTURE",
                              future_root="ES", future_expiry="2026-12", idempotency_key="fut-1"))
        o = Order.objects.get()
        self.assertEqual(o.status, Order.Status.REJECTED)
        self.assertEqual(o.reason, "ORDER_UNSUPPORTED_ASSET")


class BrokerRoutingTests(_WebhookBase):
    def test_alert_broker_override(self):
        create_broker_account(self.user, is_default=True)  # ALPACA default
        ts = BrokerAccount.objects.create(
            user=self.user, broker=BrokerAccount.Broker.TRADESTATION,
            mode=BrokerAccount.Mode.PAPER, api_key_id_enc=b"", api_secret_enc=b"",
            account_number="SIM1", status=BrokerAccount.Status.CONNECTED,
        )
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self.post(valid_alert(broker="TRADESTATION", idempotency_key="route-1"))
        o = Order.objects.get()
        self.assertEqual(o.broker_account_id, ts.id)

    def test_default_when_no_override(self):
        default = create_broker_account(self.user, is_default=True)
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self.post(valid_alert(idempotency_key="route-2"))
        self.assertEqual(Order.objects.get().broker_account_id, default.id)


class ReconciliationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.account = create_broker_account(self.user)

    def test_drift_then_heal_on_second_cycle(self):
        Position.objects.create(
            user=self.user, broker_account=self.account, symbol="AAPL",
            qty=Decimal("5"), avg_cost=Decimal("100"),
        )
        # Fake broker reports flat → our 5 shares is a drift.
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            events1 = reconcile_account(self.account)
            self.assertEqual([e.kind for e in events1], [ReconEvent.Kind.DRIFT])
            self.assertEqual(Position.objects.get(symbol="AAPL").qty, Decimal("5"))  # not healed yet
            events2 = reconcile_account(self.account)
        kinds = [e.kind for e in events2]
        self.assertIn(ReconEvent.Kind.DRIFT, kinds)
        self.assertIn(ReconEvent.Kind.HEAL, kinds)
        self.assertEqual(Position.objects.get(symbol="AAPL").qty, Decimal("0"))  # healed

    def test_no_drift_no_event(self):
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            events = reconcile_account(self.account)
        self.assertEqual(events, [])


class LiveModeGateTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.account = create_broker_account(self.user)

    def _mode(self, mode):
        return self.client.post(
            f"/api/v1/brokers/{self.account.id}/mode/",
            data={"mode": mode}, content_type="application/json", **auth_headers(self.user),
        )

    def test_live_rejected(self):
        resp = self._mode("LIVE")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "LIVE_TRADING_DISABLED")

    def test_paper_ok(self):
        resp = self._mode("PAPER")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["mode"], "PAPER")


class OrdersApiTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.account = create_broker_account(self.user)
        self.strategy = create_strategy(self.user)
        for i in range(30):
            Order.objects.create(
                user=self.user, strategy=self.strategy, broker_account=self.account,
                client_order_id=f"c-{i}", symbol="AAPL", side=Order.Side.BUY,
                qty=Decimal("1"), status=Order.Status.FILLED,
            )

    def test_pagination(self):
        resp = self.client.get("/api/v1/orders/", **auth_headers(self.user))
        body = resp.json()
        self.assertEqual(len(body["data"]), 25)
        self.assertEqual(body["meta"]["total"], 30)
        self.assertEqual(body["meta"]["num_pages"], 2)
        resp2 = self.client.get("/api/v1/orders/?page=2", **auth_headers(self.user))
        self.assertEqual(len(resp2.json()["data"]), 5)

    def test_broker_filter(self):
        resp = self.client.get("/api/v1/orders/?broker=TRADESTATION", **auth_headers(self.user))
        self.assertEqual(resp.json()["meta"]["total"], 0)
        resp = self.client.get("/api/v1/orders/?broker=ALPACA", **auth_headers(self.user))
        self.assertEqual(resp.json()["meta"]["total"], 30)

    def test_detail_with_fills(self):
        o = Order.objects.first()
        resp = self.client.get(f"/api/v1/orders/{o.id}/", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("fills", resp.json()["data"])

    def test_csv_export(self):
        resp = self.client.get("/api/v1/orders/export.csv", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("AAPL", resp.content.decode())

    def test_recon_events_endpoint(self):
        ReconEvent.objects.create(
            user=self.user, broker_account=self.account, symbol="AAPL",
            kind=ReconEvent.Kind.DRIFT, our_qty=Decimal("5"), broker_qty=Decimal("0"),
        )
        resp = self.client.get("/api/v1/reconciliation/events/", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["data"]), 1)
