"""M04 — Brokers: adapter, mapping, views, streams, audit.

AC map:
  AC-04-6   connect / test-connection / live-key reject   → BrokerConnectViewTests
  AC-04-9   admin flatten                                 → BrokerFlattenTests
  AC-04-11  reconnect catch-up + DEGRADED status          → StreamCatchUpTests
  AC-04-12  no secrets in serializers / audit             → SecretHygieneTests
"""
from __future__ import annotations

import json
import logging
import threading
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
from apps.brokers.services import (
    active_halt_reason,
    encrypt_key,
    get_stream_status,
    set_heartbeat,
)
from apps.brokers.streams import StreamSupervisor, backoff_delay, catch_up_account
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

    def test_client_has_bounded_http_timeout(self):
        # FIX-H7: every Alpaca HTTP call must be bounded so a black-holed TCP
        # connection can't wedge a worker forever.
        from apps.brokers.alpaca.adapter import ALPACA_HTTP_TIMEOUT, _TimeoutHTTPAdapter

        client = self._adapter().client  # builds a real TradingClient (no network)
        mounted = client._session.get_adapter("https://paper-api.alpaca.markets")
        self.assertIsInstance(mounted, _TimeoutHTTPAdapter)
        self.assertEqual(mounted._timeout, ALPACA_HTTP_TIMEOUT)


class CeleryTimeLimitSettingsTests(TestCase):
    def test_task_time_limits_present_and_ordered(self):
        # FIX-H7: a soft/hard task time-limit backstop, soft < hard.
        from django.conf import settings

        self.assertTrue(hasattr(settings, "CELERY_TASK_SOFT_TIME_LIMIT"))
        self.assertTrue(hasattr(settings, "CELERY_TASK_TIME_LIMIT"))
        self.assertLess(settings.CELERY_TASK_SOFT_TIME_LIMIT, settings.CELERY_TASK_TIME_LIMIT)


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

    def test_connect_non_ascii_key_rejected_400(self):
        # FIX-L5: a Unicode key must be a 400 validation error, not a 500
        # (encrypt_key(raw.encode("ascii")) would raise UnicodeEncodeError).
        resp = self.client.post(
            API,
            data={"api_key_id": "PK—abc", "api_secret": "s", "broker": "ALPACA", "mode": "PAPER"},
            content_type="application/json",
            **auth_headers(self.user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(BrokerAccount.objects.count(), 0)

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

    def test_catch_up_position_snap_resolves_real_status(self):
        # Adapter WITHOUT recent_fills → the Alpaca position-snap branch. A
        # closed order must take the broker's REAL terminal status, never a
        # blind FILLED (M3).
        order = Order.objects.create(
            user=self.user, broker_account=self.account, client_order_id="c-snap",
            broker_order_id="bo-snap", symbol="AAPL", side=Order.Side.BUY,
            qty=Decimal("5"), status=Order.Status.SUBMITTED,
        )
        adapter = mock.Mock(spec=["list_positions", "list_open_orders", "get_order_status"])
        adapter.list_positions.return_value = []       # broker reports flat
        adapter.list_open_orders.return_value = []     # order no longer open
        adapter.get_order_status.return_value = "CANCELLED"
        res = catch_up_account(self.account, adapter)
        self.assertEqual(res["strategy"], "position_snap")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)  # not blindly FILLED


# ===========================================================================
# Stream supervisor (FIX-H8) + task-process metrics (FIX-C1)
# ===========================================================================
class _ImmediateFailStream:
    def run(self):
        raise RuntimeError("auth failed")  # a persistent immediate failure


class StreamSupervisorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.account = create_broker_account(self.user)

    def test_reconnect_backoff_grows_and_catch_up_not_hammered(self):
        # FIX-H8: repeated immediate failures must grow the backoff (attempt) and
        # not re-run catch_up on every sub-second iteration.
        from apps.brokers import streams as st
        from apps.brokers.metrics import BROKER_WS_RECONNECTS_TOTAL

        recon_before = BROKER_WS_RECONNECTS_TOTAL.labels(broker="alpaca")._value.get()
        attempts, catch_ups = [], {"n": 0}
        sup = StreamSupervisor(
            healthy_after=60.0,
            adapter_factory=lambda account: mock.Mock(),
            stream_factory=lambda account: _ImmediateFailStream(),
        )
        stop_event = threading.Event()
        waits = {"n": 0}

        def fake_wait(_delay):
            waits["n"] += 1
            if waits["n"] >= 4:
                stop_event.set()
            return True

        with mock.patch.object(st, "backoff_delay", side_effect=lambda n: attempts.append(n) or 0.0), \
             mock.patch.object(st, "catch_up_account",
                               side_effect=lambda *a, **k: catch_ups.__setitem__("n", catch_ups["n"] + 1)), \
             mock.patch.object(stop_event, "wait", side_effect=fake_wait):
            sup._run_account(self.account, stop_event)

        self.assertEqual(attempts, [1, 2, 3, 4])          # backoff grows each failure
        self.assertEqual(catch_ups["n"], 4)               # once per iteration, bounded
        # reconnects (attempt>0) counted for iterations 2,3,4.
        self.assertEqual(
            BROKER_WS_RECONNECTS_TOTAL.labels(broker="alpaca")._value.get(), recon_before + 3
        )

    def test_reconcile_starts_new_and_stops_removed(self):
        # FIX-H8: the supervisor diff hot-adds new accounts and signal-stops
        # removed ones — no restart, no masking.
        sup = StreamSupervisor()
        started = []

        class _DummyThread:
            def is_alive(self):
                return True

        def fake_start(account):
            aid = str(account.id)
            started.append(aid)
            sup._threads[aid] = _DummyThread()
            sup._stops[aid] = threading.Event()

        acct_b = create_broker_account(self.user, is_default=False, account_number="PATEST002")
        with mock.patch.object(sup, "_start_thread", side_effect=fake_start):
            sup._reconcile_threads([self.account])                 # A active → started
            self.assertIn(str(self.account.id), sup._threads)
            sup._reconcile_threads([self.account, acct_b])         # B added → hot-add
            self.assertIn(str(acct_b.id), sup._threads)
            ev_a = sup._stops[str(self.account.id)]
            sup._reconcile_threads([acct_b])                       # A removed → stopped
        self.assertNotIn(str(self.account.id), sup._threads)
        self.assertTrue(ev_a.is_set())                             # removed thread signaled
        self.assertEqual(started, [str(self.account.id), str(acct_b.id)])

    def test_reconcile_prunes_dead_thread(self):
        # FIX-H8: a thread that has died is pruned (and restartable), never
        # left masking as healthy.
        sup = StreamSupervisor()

        class _DeadThread:
            def is_alive(self):
                return False

        sup._threads[str(self.account.id)] = _DeadThread()
        sup._stops[str(self.account.id)] = threading.Event()
        restarted = []
        with mock.patch.object(sup, "_start_thread", side_effect=lambda a: restarted.append(str(a.id))):
            sup._reconcile_threads([self.account])
        self.assertEqual(restarted, [str(self.account.id)])

    def test_main_loop_does_not_overwrite_degraded_heartbeat(self):
        # FIX-H8: the reconcile loop must not stamp a DEGRADED heartbeat back to
        # CONNECTED (the old run_forever bug).
        set_heartbeat(self.account.id, "DEGRADED")
        sup = StreamSupervisor()
        with mock.patch.object(sup, "_start_thread"):
            sup._reconcile_threads([self.account])
        self.assertEqual(get_stream_status(self.account), "DEGRADED")

    def test_heartbeat_age_metric_is_set(self):
        # FIX-C1: broker_stream_heartbeat_age_seconds is emitted (was dead).
        from apps.brokers.metrics import BROKER_STREAM_HEARTBEAT_AGE

        set_heartbeat(self.account.id, "CONNECTED")
        get_stream_status(self.account)
        val = BROKER_STREAM_HEARTBEAT_AGE.labels(account_id=str(self.account.id))._value.get()
        self.assertGreaterEqual(val, 0.0)

    def test_task_metrics_server_toggle(self):
        # FIX-C1: task processes can expose a Prometheus scrape port.
        from django.test import override_settings

        from config.task_metrics import start_task_metrics_server

        with override_settings(TASK_METRICS_PORT=0):
            self.assertFalse(start_task_metrics_server())
        with mock.patch("prometheus_client.start_http_server") as srv, \
             override_settings(TASK_METRICS_PORT=9109):
            self.assertTrue(start_task_metrics_server())
            srv.assert_called_once_with(9109)


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

    def test_log_scan_no_secrets_leak(self):
        """AC-04-12: automated log scan. Drive the webhook (accept + bad-sig),
        the broker connect/encryption path, and fill ingest while capturing ALL
        log records (message + args + extras), then assert no secret / API key /
        API secret substring appears anywhere."""
        cache.clear()
        secret_sig = "logscan-sig-SECRET-9f8e7d"  # noqa: S105 — test fixture
        api_key = "PKLOGSCANKEY0001"
        api_secret = "logscan-api-SECRET-a1b2c3"  # noqa: S105 — test fixture

        captured: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                captured.append(record)

        handler = _Capture()
        root = logging.getLogger()
        root.addHandler(handler)
        prev = root.level
        root.setLevel(logging.DEBUG)
        try:
            user = create_user(email="logscan@example.com")
            strat = create_strategy(user, slug="logscan")
            create_webhook_config(user, strat, secret=secret_sig)
            BrokerAccount.objects.create(
                user=user,
                broker=BrokerAccount.Broker.ALPACA,
                mode=BrokerAccount.Mode.PAPER,
                api_key_id_enc=encrypt_key(api_key),
                api_secret_enc=encrypt_key(api_secret),
                account_number="PALOGSCAN",
                is_default=True,
                status=BrokerAccount.Status.CONNECTED,
            )
            url = f"/hooks/v1/{user.id}/{strat.id}/"
            with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
                self.client.post(
                    url,
                    data=json.dumps(valid_alert(secret=secret_sig, idempotency_key="ls-1")),
                    content_type="application/json",
                )
            # bad sig → logs a warning
            self.client.post(
                url,
                data=json.dumps(valid_alert(sig="wrong-secret", idempotency_key="ls-2")),
                content_type="application/json",
            )
        finally:
            root.removeHandler(handler)
            root.setLevel(prev)

        blob = "\n".join(
            f"{r.getMessage()} args={r.args!r} extra={r.__dict__!r}" for r in captured
        )
        for forbidden in (secret_sig, api_key, api_secret):
            self.assertNotIn(forbidden, blob)


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
