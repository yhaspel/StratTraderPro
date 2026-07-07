"""M05 — TradeStation adapter (stubbed / recorded), OAuth PKCE + state, views.

Live OAuth + real sim fills are deferred (approval-gated); these tests exercise
the code paths with mocks and never hit the network.
"""
from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.brokers.base import (
    FutureContract,
    OptionContract,
    OrderRequest,
    OrderType,
    Side,
    TimeInForce,
)
from apps.brokers.errors import BrokerError, BrokerErrorCode
from apps.brokers.models import BrokerAccount
from apps.brokers.services import build_adapter, encrypt_key
from apps.brokers.tradestation import mapping, oauth
from apps.brokers.tradestation.adapter import TradeStationPaperAdapter
from apps.m04_testutils import auth_headers, create_user

TS_ON = override_settings(
    BROKER_TRADESTATION_ENABLED=True,
    TRADESTATION_CLIENT_ID="cid",
    TRADESTATION_CLIENT_SECRET="csecret",
)


def _ts_account(user, number="SIM12345"):
    return BrokerAccount.objects.create(
        user=user,
        broker=BrokerAccount.Broker.TRADESTATION,
        mode=BrokerAccount.Mode.PAPER,
        api_key_id_enc=b"",
        api_secret_enc=b"",
        ts_access_token_enc=encrypt_key("access-tok"),
        ts_refresh_token_enc=encrypt_key("refresh-tok"),
        account_number=number,
        status=BrokerAccount.Status.CONNECTED,
    )


class TSMappingTests(TestCase):
    def test_stock_symbol_unchanged(self):
        req = OrderRequest(symbol="AAPL", side=Side.BUY, qty=Decimal("1"))
        self.assertEqual(mapping.to_ts_symbol(req), "AAPL")

    def test_option_occ_to_ts(self):
        req = OrderRequest(
            symbol="AAPL240119C00150000", side=Side.BUY, qty=Decimal("1"),
            asset_class="OPTION",
            option=OptionContract(expiry="2024-01-19", strike=Decimal("150"), right="CALL"),
        )
        self.assertEqual(mapping.to_ts_symbol(req), "AAPL 240119C150")

    def test_future_canonical_to_ts(self):
        req = OrderRequest(
            symbol="ES", side=Side.BUY, qty=Decimal("1"), asset_class="FUTURE",
            future=FutureContract(root="ES", expiry="2026-12"),
        )
        self.assertEqual(mapping.to_ts_symbol(req), "ESZ26")

    def test_order_payload_stop_limit(self):
        req = OrderRequest(
            symbol="AAPL", side=Side.SELL, qty=Decimal("2"), order_type=OrderType.STP_LMT,
            limit_price=Decimal("149"), stop_price=Decimal("150"), time_in_force=TimeInForce.GTC,
        )
        payload = mapping.to_ts_order_payload(req, "coid-1", "SIM1")
        self.assertEqual(payload["OrderType"], "StopLimit")
        self.assertEqual(payload["TradeAction"], "SELL")
        self.assertEqual(payload["LimitPrice"], "149")
        self.assertEqual(payload["StopPrice"], "150")
        self.assertEqual(payload["TimeInForce"]["Duration"], "GTC")

    def test_from_ts_order(self):
        ack = mapping.from_ts_order(
            {"OrderID": "o1", "ClientOrderID": "coid-1", "Status": "FLL", "Symbol": "AAPL",
             "Quantity": "5", "FilledQuantity": "5"}
        )
        self.assertEqual(ack.broker_order_id, "o1")
        self.assertEqual(ack.status.value, "FILLED")


class TSOAuthTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_pkce_challenge_is_s256(self):
        import base64
        import hashlib

        verifier, challenge = oauth.generate_pkce()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)

    def test_state_single_use(self):
        state = oauth.issue_state("user-1")
        self.assertEqual(oauth.consume_state(state)["user_id"], "user-1")
        self.assertIsNone(oauth.consume_state(state))  # replay → gone

    @TS_ON
    def test_authorize_url_contains_pkce_and_state(self):
        _v, challenge = oauth.generate_pkce()
        url = oauth.build_authorize_url(state="st8", code_challenge=challenge)
        self.assertIn("code_challenge=", url)
        self.assertIn("state=st8", url)
        self.assertIn("client_id=cid", url)


class TSAdapterTests(TestCase):
    @TS_ON
    def test_build_adapter_returns_ts(self):
        user = create_user()
        acct = _ts_account(user)
        adapter = build_adapter(acct)
        self.assertIsInstance(adapter, TradeStationPaperAdapter)

    def test_build_adapter_disabled(self):
        user = create_user()
        acct = _ts_account(user)
        with override_settings(BROKER_TRADESTATION_ENABLED=False):
            with self.assertRaises(BrokerError) as ctx:
                build_adapter(acct)
        self.assertEqual(ctx.exception.code, BrokerErrorCode.DISABLED)

    @TS_ON
    def test_place_order_via_mock_client(self):
        user = create_user()
        acct = _ts_account(user)
        client = mock.Mock()
        client.place_order.return_value = {
            "OrderID": "TS-99", "ClientOrderID": "c1", "Status": "OPN", "Symbol": "AAPL",
            "Quantity": "1",
        }
        adapter = TradeStationPaperAdapter(acct, client=client)
        ack = adapter.place_order(OrderRequest(symbol="AAPL", side=Side.BUY, qty=Decimal("1")), "c1")
        self.assertEqual(ack.broker_order_id, "TS-99")
        client.place_order.assert_called_once()

    @TS_ON
    def test_get_account_matches_number(self):
        user = create_user()
        acct = _ts_account(user, number="SIMABC")
        client = mock.Mock()
        client.get_accounts.return_value = [
            {"AccountID": "SIMABC", "Balances": {"BuyingPower": "1000", "CashBalance": "500"}}
        ]
        adapter = TradeStationPaperAdapter(acct, client=client)
        account = adapter.get_account()
        self.assertEqual(account.account_number, "SIMABC")
        self.assertEqual(account.buying_power, Decimal("1000"))


class TSOAuthViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()

    def test_start_disabled_503(self):
        resp = self.client.get(
            "/api/v1/brokers/tradestation/oauth/start/", **auth_headers(self.user)
        )
        self.assertEqual(resp.status_code, 503)

    @TS_ON
    def test_start_returns_authorize_url(self):
        resp = self.client.get(
            "/api/v1/brokers/tradestation/oauth/start/", **auth_headers(self.user)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("authorize_url", resp.json()["data"])

    @TS_ON
    def test_callback_creates_account(self):
        state = oauth.issue_state(self.user.id)
        oauth.store_verifier(state, "verifier")
        with mock.patch(
            "apps.brokers.tradestation.views.exchange_code_for_tokens",
            return_value={"access_token": "at", "refresh_token": "rt", "scope": "Trade"},
        ), mock.patch(
            "apps.brokers.tradestation.views.TSClient"
        ) as ts_cls:
            ts_cls.return_value.get_accounts.return_value = [{"AccountID": "SIM777"}]
            resp = self.client.get(
                f"/api/v1/brokers/tradestation/oauth/callback/?code=abc&state={state}"
            )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            BrokerAccount.objects.filter(
                user=self.user, broker="TRADESTATION", account_number="SIM777"
            ).exists()
        )

    @TS_ON
    def test_callback_bad_state_redirects_error(self):
        resp = self.client.get(
            "/api/v1/brokers/tradestation/oauth/callback/?code=abc&state=nonexistent"
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("ts=error", resp["Location"])
