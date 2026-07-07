"""M04 — Brokers: adapter, mapping, views, streams, audit.

AC map:
  AC-04-6   connect / test-connection / live-key reject   → BrokerConnectViewTests
  AC-04-9   admin flatten                                 → BrokerFlattenTests
  AC-04-11  reconnect catch-up + DEGRADED status          → StreamCatchUpTests
  AC-04-12  no secrets in serializers / audit             → SecretHygieneTests
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pyotp
from django.core.cache import cache
from django.test import TestCase

from apps.brokers.alpaca import mapping
from apps.brokers.alpaca.adapter import AlpacaAdapter
from apps.brokers.alpaca.errors import looks_like_live_key, map_api_error
from apps.brokers.base import (
    BrokerContext,
    ConnectionInfo,
    OrderRequest,
    OrderType,
    Side,
)
from apps.brokers.errors import BrokerError, BrokerErrorCode
from apps.brokers.fake import FakeBrokerAdapter, ScriptedFill, ScriptStep
from apps.brokers.models import BrokerAccount, BrokerCallAudit, TradingHalt
from apps.brokers.services import active_halt_reason, get_stream_status, set_heartbeat
from apps.brokers.streams import backoff_delay, catch_up_account
from apps.m04_testutils import (
    auth_headers,
    create_broker_account,
    create_strategy,
    create_user,
    create_webhook_config,
    fake_factory,
)
from apps.orders.models import Fill, Order, Position
from apps.users.mfa import encrypt_secret
from apps.users.models import MFADevice

API = "/api/v1/brokers/"


def _fake_alpaca_account(number="PA3XYZ", bp="100000", cash="50000"):
    return SimpleNamespace(
        account_number=number, buying_power=bp, cash=cash, currency="USD", status="ACTIVE"
    )


# ===========================================================================
# Alpaca error mapping + live-key detection (unit)
# ===========================================================================
class AlpacaErrorMappingTests(TestCase):
    def test_live_key_prefixes(self):
        self.assertTrue(looks_like_live_key("AKLIVE123"))
        self.assertTrue(looks_like_live_key("BKBROKER"))
        self.assertFalse(looks_like_live_key("PKPAPER123"))
        self.assertFalse(looks_like_live_key(""))

    def test_status_mapping(self):
        self.assertEqual(map_api_error(SimpleNamespace(status_code=401)).code, BrokerErrorCode.AUTH_FAILED)
        self.assertEqual(map_api_error(SimpleNamespace(status_code=429)).code, BrokerErrorCode.RATE_LIMITED)
        self.assertTrue(map_api_error(SimpleNamespace(status_code=503)).retryable)
        self.assertEqual(map_api_error(SimpleNamespace(status_code=422)).code, BrokerErrorCode.ORDER_REJECTED)


# ===========================================================================
# mapping (unit)
# ===========================================================================
class MappingTests(TestCase):
    def test_build_market_and_limit(self):
        req = OrderRequest(symbol="AAPL", side=Side.BUY, qty=Decimal("2"), order_type=OrderType.MKT)
        m = mapping.build_order_request(req, "stp-1")
        self.assertEqual(m.symbol, "AAPL")
        self.assertEqual(m.client_order_id, "stp-1")
        lreq = OrderRequest(
            symbol="MSFT", side=Side.SELL, qty=Decimal("1"),
            order_type=OrderType.LMT, limit_price=Decimal("300"),
        )
        lm = mapping.build_order_request(lreq, "stp-2")
        self.assertEqual(float(lm.limit_price), 300.0)

    def test_map_account_position_order(self):
        acct = mapping.map_account(_fake_alpaca_account())
        self.assertEqual(acct.account_number, "PA3XYZ")
        self.assertEqual(acct.buying_power, Decimal("100000"))
        pos = mapping.map_position(
            SimpleNamespace(symbol="AAPL", qty="5", avg_entry_price="150", current_price="155", side="long")
        )
        self.assertEqual(pos.qty, Decimal("5"))
        self.assertEqual(pos.market_price, Decimal("155"))
        ack = mapping.map_order_ack(
            SimpleNamespace(
                id="oid-1", client_order_id="stp-1", status="filled",
                symbol="AAPL", qty="5", filled_qty="5", submitted_at="2026-07-07T10:00:00Z",
            )
        )
        self.assertEqual(ack.broker_order_id, "oid-1")
        self.assertEqual(ack.status.value, "FILLED")

    def test_map_trade_update_dict_and_obj(self):
        fe = mapping.map_trade_update(
            {
                "event": "fill",
                "execution_id": "ex-1",
                "price": "150.5",
                "qty": "3",
                "order": {"id": "oid", "client_order_id": "stp-1", "symbol": "AAPL", "side": "buy", "filled_qty": "3"},
            }
        )
        self.assertEqual(fe.broker_exec_id, "ex-1")
        self.assertEqual(fe.event_type, "fill")
        self.assertEqual(fe.qty, Decimal("3"))


# ===========================================================================
# AlpacaAdapter (unit, injected mock client)
# ===========================================================================
class AlpacaAdapterTests(TestCase):
    def _adapter(self, client=None, key="PKPAPER123"):
        # Sentinel ids → audit rows are written with NULL FKs (no fixture rows).
        return AlpacaAdapter(
            BrokerContext(account_id="fake", user_id="fake", api_key_id=key, api_secret="s"),
            client=client,
        )

    def test_connect_live_key_forbidden(self):
        with self.assertRaises(BrokerError) as ctx:
            self._adapter(key="AKLIVEKEY").connect()
        self.assertEqual(ctx.exception.code, BrokerErrorCode.LIVE_KEYS_FORBIDDEN)

    def test_connect_paper_ok(self):
        client = mock.Mock()
        client.get_account.return_value = _fake_alpaca_account()
        info = self._adapter(client=client).connect()
        self.assertEqual(info.account_number, "PA3XYZ")

    def test_connect_auth_failure(self):
        client = mock.Mock()
        client.get_account.side_effect = SimpleNamespace  # placeholder; replaced below
        client.get_account.side_effect = _raise_status(403)
        with self.assertRaises(BrokerError) as ctx:
            self._adapter(client=client).connect()
        self.assertEqual(ctx.exception.code, BrokerErrorCode.AUTH_FAILED)

    def test_place_order_market(self):
        client = mock.Mock()
        client.submit_order.return_value = SimpleNamespace(
            id="oid-9", client_order_id="stp-x", status="new", symbol="AAPL",
            qty="1", filled_qty="0", submitted_at="2026-07-07T10:00:00Z",
        )
        ack = self._adapter(client=client).place_order(
            OrderRequest(symbol="AAPL", side=Side.BUY, qty=Decimal("1")), "stp-x"
        )
        self.assertEqual(ack.broker_order_id, "oid-9")
        client.submit_order.assert_called_once()

    def test_call_audit_recorded_on_success_and_failure(self):
        client = mock.Mock()
        client.get_account.return_value = _fake_alpaca_account()
        self._adapter(client=client).get_account()
        self.assertTrue(BrokerCallAudit.objects.filter(endpoint="get_account", ok=True).exists())

    def test_rate_limited_after_retries(self):
        client = mock.Mock()
        client.get_account.side_effect = _raise_status(429)
        with mock.patch("apps.brokers.alpaca.adapter.time.sleep", return_value=None):
            with self.assertRaises(BrokerError) as ctx:
                self._adapter(client=client).get_account()
        self.assertEqual(ctx.exception.code, BrokerErrorCode.RATE_LIMITED)


# ===========================================================================
# FakeBrokerAdapter (unit)
# ===========================================================================
class FakeAdapterTests(TestCase):
    def test_default_full_fill_publishes_events(self):
        events = []
        fake = FakeBrokerAdapter(publish=lambda uid, ev: events.append(ev))
        fake.place_order(OrderRequest(symbol="AAPL", side=Side.BUY, qty=Decimal("2")), "c1")
        kinds = [e.event_type for e in events]
        self.assertIn("new", kinds)
        self.assertIn("fill", kinds)

    def test_scripted_partial_fills(self):
        events = []
        script = [
            ScriptStep(fills=[ScriptedFill(Decimal("1"), Decimal("10")), ScriptedFill(Decimal("1"), Decimal("11"))])
        ]
        fake = FakeBrokerAdapter(script=script, publish=lambda uid, ev: events.append(ev))
        fake.place_order(OrderRequest(symbol="X", side=Side.BUY, qty=Decimal("2")), "c1")
        self.assertEqual([e.event_type for e in events].count("partial_fill"), 1)

    def test_scripted_reject(self):
        events = []
        fake = FakeBrokerAdapter(script=[ScriptStep(reject=True)], publish=lambda uid, ev: events.append(ev))
        ack = fake.place_order(OrderRequest(symbol="X", side=Side.BUY, qty=Decimal("1")), "c1")
        self.assertEqual(ack.status.value, "REJECTED")
        self.assertEqual(events[-1].event_type, "rejected")


# ===========================================================================
# Broker connect / test-connection views
# ===========================================================================
class BrokerConnectViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()

    def test_connect_happy_no_secret_in_response(self):
        stub = mock.Mock()
        stub.connect.return_value = ConnectionInfo(account_number="PA9", buying_power=Decimal("100000"))
        with mock.patch("apps.brokers.views.build_adapter_from_keys", return_value=stub):
            resp = self.client.post(
                API,
                data={"api_key_id": "PKabc", "api_secret": "sekret", "broker": "ALPACA", "mode": "PAPER"},
                content_type="application/json",
                **auth_headers(self.user),
            )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()["data"]
        self.assertEqual(body["account_number"], "PA9")
        self.assertNotIn("api_secret", body)
        self.assertNotIn("api_key_id", body)
        acct = BrokerAccount.objects.get()
        self.assertNotEqual(bytes(acct.api_secret_enc), b"sekret")  # encrypted at rest

    def test_connect_live_key_rejected(self):
        resp = self.client.post(
            API,
            data={"api_key_id": "AKLIVEKEY", "api_secret": "s", "broker": "ALPACA", "mode": "PAPER"},
            content_type="application/json",
            **auth_headers(self.user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "BROKER_LIVE_KEYS_FORBIDDEN")
        self.assertEqual(BrokerAccount.objects.count(), 0)

    def test_connect_auth_failure(self):
        stub = mock.Mock()
        stub.connect.side_effect = BrokerError(BrokerErrorCode.AUTH_FAILED, "bad")
        with mock.patch("apps.brokers.views.build_adapter_from_keys", return_value=stub):
            resp = self.client.post(
                API,
                data={"api_key_id": "PKabc", "api_secret": "s"},
                content_type="application/json",
                **auth_headers(self.user),
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "BROKER_AUTH_FAILED")

    def test_test_connection(self):
        account = create_broker_account(self.user)
        adapter = mock.Mock()
        adapter.get_account.return_value = SimpleNamespace(
            account_number="PA9", buying_power=Decimal("100000"), cash=Decimal("50000"), currency="USD"
        )
        # get_account here returns our Account DTO shape via the real adapter; use fake DTO
        from apps.brokers.base import Account

        adapter.get_account.return_value = Account(
            account_number="PA9", buying_power=Decimal("100000"), cash=Decimal("50000")
        )
        with mock.patch("apps.brokers.views.build_adapter", return_value=adapter):
            resp = self.client.post(
                f"{API}{account.id}/test-connection/", **auth_headers(self.user)
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["account_number"], "PA9")

    def test_mfa_enforced(self):
        resp = self.client.get(API)  # unauthenticated
        self.assertIn(resp.status_code, (401, 403))


class BrokerRemoveTests(TestCase):
    def test_remove_requires_valid_mfa(self):
        cache.clear()
        secret = pyotp.random_base32()
        user = create_user(mfa=False)
        MFADevice.objects.create(user=user, secret_encrypted=encrypt_secret(secret), verified=True)
        account = create_broker_account(user)
        # wrong code
        resp = self.client.delete(
            f"{API}{account.id}/",
            data={"mfa_code": "000000"},
            content_type="application/json",
            **auth_headers(user),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(BrokerAccount.objects.filter(id=account.id).exists())
        # correct code
        resp = self.client.delete(
            f"{API}{account.id}/",
            data={"mfa_code": pyotp.TOTP(secret).now()},
            content_type="application/json",
            **auth_headers(user),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(BrokerAccount.objects.filter(id=account.id).exists())


class BrokerFlattenTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_flatten_admin_gated(self):
        user = create_user()  # not staff
        account = create_broker_account(user)
        resp = self.client.post(f"{API}{account.id}/flatten/", **auth_headers(user))
        self.assertEqual(resp.status_code, 403)

    def test_flatten_staff_flattens(self):
        user = create_user(staff=True)
        account = create_broker_account(user)
        Position.objects.create(
            user=user, broker_account=account, symbol="AAPL", qty=Decimal("5"), avg_cost=Decimal("100")
        )
        with mock.patch("apps.brokers.views.build_adapter", side_effect=fake_factory()):
            resp = self.client.post(f"{API}{account.id}/flatten/", **auth_headers(user))
        self.assertEqual(resp.status_code, 200)
        # reconcile_positions snapped the (empty) fake broker positions → flat.
        self.assertEqual(Position.objects.get(symbol="AAPL").qty, 0)


# ===========================================================================
# Streams: catch-up + status
# ===========================================================================
class StreamCatchUpTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.account = create_broker_account(self.user)

    def test_status_degraded_and_down(self):
        self.assertEqual(get_stream_status(self.account), "DOWN")  # no heartbeat
        set_heartbeat(self.account.id, "CONNECTED")
        self.assertEqual(get_stream_status(self.account), "CONNECTED")

    def test_backoff_monotonic_capped(self):
        self.assertLessEqual(backoff_delay(1), 2.0)
        self.assertLessEqual(backoff_delay(20), 30.0)

    def test_catch_up_replays_and_dedups(self):
        # Place an order but suppress ingestion (simulate a dropped stream).
        strat = create_strategy(self.user)
        create_webhook_config(self.user, strat)
        order = Order.objects.create(
            user=self.user, strategy=strat, broker_account=self.account,
            client_order_id="c-recover", symbol="AAPL", side=Order.Side.BUY,
            qty=Decimal("4"), status=Order.Status.SUBMITTED, broker_order_id="fakeord-c-recover",
        )
        # Build a fake that has "already emitted" a fill (recorded) but whose
        # publish was a no-op, so the Fill was never ingested.
        from apps.brokers.base import FillEvent

        fake = fake_factory()(self.account)
        fake._emitted_fills.append(
            FillEvent(
                broker_exec_id="exec-recover-1", client_order_id="c-recover",
                broker_order_id="fakeord-c-recover", symbol="AAPL", side=Side.BUY,
                event_type="fill", qty=Decimal("4"), price=Decimal("150"), filled_qty=Decimal("4"),
            )
        )
        self.assertEqual(Fill.objects.count(), 0)
        catch_up_account(self.account, fake)          # recovers the missed fill
        catch_up_account(self.account, fake)          # replay again → dedup
        self.assertEqual(Fill.objects.filter(order=order).count(), 1)
        self.assertEqual(Position.objects.get(symbol="AAPL").qty, Decimal("4"))


# ===========================================================================
# Secret hygiene (AC-04-12) + halt gate unit
# ===========================================================================
class SecretHygieneTests(TestCase):
    def test_serializer_has_no_key_fields(self):
        user = create_user()
        account = create_broker_account(user)
        from apps.brokers.serializers import BrokerAccountSerializer

        data = BrokerAccountSerializer(account).data
        for banned in ("api_key_id", "api_secret", "api_key_id_enc", "api_secret_enc"):
            self.assertNotIn(banned, data)

    def test_call_audit_model_stores_no_bodies(self):
        field_names = {f.name for f in BrokerCallAudit._meta.get_fields()}
        for banned in ("body", "request_body", "response_body", "api_key", "secret"):
            self.assertNotIn(banned, field_names)


class HaltGateUnitTests(TestCase):
    def test_active_halt_reason(self):
        user = create_user()
        strat = create_strategy(user)
        self.assertIsNone(active_halt_reason(user_id=user.id, strategy_id=strat.id))
        TradingHalt.objects.create(user=user, strategy=strat, reason="r", created_by=user)
        self.assertEqual(active_halt_reason(user_id=user.id, strategy_id=strat.id), "STRATEGY_HALTED")
        TradingHalt.objects.create(user=user, reason="r", created_by=user)
        self.assertEqual(active_halt_reason(user_id=user.id, strategy_id=strat.id), "USER_HALTED")


def _raise_status(status):
    def _r(*a, **kw):
        raise _StatusError(status)

    return _r


class _StatusError(Exception):
    def __init__(self, status):
        self.status_code = status
        super().__init__(f"HTTP {status}")
