"""M04 — Webhook ingest + process_alert tests.

AC map (project-plan/04-webhook-ingest-and-ibkr.md §4):
  AC-04-1  valid alert accepted 200                     → WebhookAcceptTests
  AC-04-2  wrong/missing sig → 401 + audit row          → WebhookAuthTests
  AC-04-3  bad schema → 400 with detail                 → WebhookSchemaTests
  AC-04-4  duplicate idempotency_key → duplicate=true   → WebhookIdempotencyTests
  AC-04-5  halt gate → rejected reason + audit          → WebhookHaltTests
  AC-04-10 e2e webhook → position ≤5s (FakeBroker)      → WebhookEndToEndTests
"""
from __future__ import annotations

import json
import time
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.brokers.models import TradingHalt
from apps.m04_testutils import (
    create_broker_account,
    create_strategy,
    create_user,
    create_webhook_config,
    fake_factory,
    valid_alert,
)
from apps.orders.models import Order, Position
from apps.webhooks.models import AlertMessage


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.strategy = create_strategy(self.user)
        self.wc = create_webhook_config(self.user, self.strategy)
        self.url = f"/hooks/v1/{self.user.id}/{self.strategy.id}/"

    def post(self, body, **kw):
        return self.client.post(
            self.url, data=json.dumps(body), content_type="application/json", **kw
        )


class WebhookAcceptTests(_Base):
    def test_valid_alert_accepted(self):
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            create_broker_account(self.user)
            resp = self.post(valid_alert())
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["data"]["accepted"])
        self.assertEqual(AlertMessage.objects.filter(status="ACCEPTED").count(), 1)

    def test_no_broker_connected_rejects(self):
        resp = self.post(valid_alert())
        self.assertEqual(resp.status_code, 200)
        alert = AlertMessage.objects.get()
        self.assertEqual(alert.reject_reason, "NO_BROKER_CONNECTED")

    def test_feature_flag_off_returns_503(self):
        with override_settings(WEBHOOK_V1_ENABLED=False):
            resp = self.post(valid_alert())
        self.assertEqual(resp.status_code, 503)


class WebhookAuthTests(_Base):
    def test_wrong_sig_returns_401_no_order_audit_row(self):
        resp = self.post(valid_alert(sig="wrong-secret"))
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "WEBHOOK_SIG_BAD")
        self.assertEqual(Order.objects.count(), 0)
        # Audit row written for a KNOWN config (AC-04-2).
        row = AlertMessage.objects.get()
        self.assertEqual(row.status, "REJECTED")
        self.assertEqual(row.reject_reason, "SIG_BAD")
        self.assertNotIn("sig", row.body_json)  # secret never persisted

    def test_missing_sig_returns_401(self):
        body = valid_alert()
        body.pop("sig")
        resp = self.post(body)
        self.assertEqual(resp.status_code, 401)

    def test_non_ascii_sig_returns_401_not_500(self):
        # FIX-H6: a non-ASCII sig must yield a clean 401 + SIG_BAD audit, not a
        # TypeError→500 that skips the audit and pollutes the 5xx alert.
        resp = self.post(valid_alert(sig="é"))
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "WEBHOOK_SIG_BAD")
        self.assertEqual(AlertMessage.objects.get().reject_reason, "SIG_BAD")

    def test_unknown_user_strategy_generic_401_no_row(self):
        import uuid

        url = f"/hooks/v1/{uuid.uuid4()}/{uuid.uuid4()}/"
        resp = self.client.post(url, data=json.dumps(valid_alert()), content_type="application/json")
        self.assertEqual(resp.status_code, 401)
        # No oracle, and no unbounded rows for unknown targets.
        self.assertEqual(AlertMessage.objects.count(), 0)

    def test_rate_limit_before_body(self):
        with override_settings(WEBHOOK_RATE_LIMIT_PER_MIN=2):
            self.post(valid_alert(sig="x"))
            self.post(valid_alert(sig="x"))
            resp = self.post(valid_alert(sig="x"))
        self.assertEqual(resp.status_code, 429)

    def test_non_json_content_type_415(self):
        resp = self.client.post(self.url, data="notjson", content_type="text/plain")
        self.assertEqual(resp.status_code, 415)

    def test_oversize_body_413(self):
        with override_settings(WEBHOOK_MAX_BODY_BYTES=10):
            resp = self.post(valid_alert())
        self.assertEqual(resp.status_code, 413)


class WebhookSchemaTests(_Base):
    def test_bad_schema_returns_400_with_detail(self):
        # qty must be a number per the default schema.
        resp = self.post(valid_alert(qty="not-a-number"))
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertEqual(body["error"]["code"], "WEBHOOK_SCHEMA_INVALID")
        self.assertIn("detail", body["error"])
        self.assertEqual(AlertMessage.objects.get().status, "INVALID")


class WebhookIdempotencyTests(_Base):
    def test_duplicate_key_returns_duplicate_true_single_order(self):
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            create_broker_account(self.user)
            r1 = self.post(valid_alert(idempotency_key="dup-1"))
            r2 = self.post(valid_alert(idempotency_key="dup-1"))
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json()["data"].get("accepted"))
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()["data"].get("duplicate"))
        self.assertEqual(Order.objects.count(), 1)


class WebhookHaltTests(_Base):
    def test_user_halt_rejects(self):
        TradingHalt.objects.create(user=self.user, reason="test", created_by=self.user)
        resp = self.post(valid_alert())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["rejected"], "USER_HALTED")
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(AlertMessage.objects.get().reject_reason, "USER_HALTED")

    def test_strategy_halt_rejects(self):
        TradingHalt.objects.create(
            user=self.user, strategy=self.strategy, reason="test", created_by=self.user
        )
        resp = self.post(valid_alert())
        self.assertEqual(resp.json()["data"]["rejected"], "STRATEGY_HALTED")

    def test_released_halt_does_not_block(self):
        from django.utils import timezone

        TradingHalt.objects.create(
            user=self.user, reason="t", created_by=self.user, released_at=timezone.now()
        )
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            create_broker_account(self.user)
            resp = self.post(valid_alert())
        self.assertTrue(resp.json()["data"].get("accepted"))


class WebhookEndToEndTests(_Base):
    def test_alert_to_position_under_5s(self):
        create_broker_account(self.user)
        started = time.monotonic()
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            resp = self.post(valid_alert(symbol="AAPL", qty=3))
        elapsed = time.monotonic() - started
        self.assertEqual(resp.status_code, 200)
        self.assertLess(elapsed, 5.0)
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.FILLED)
        pos = Position.objects.get(symbol="AAPL")
        self.assertEqual(pos.qty, 3)

    def test_unsupported_asset_rejected(self):
        create_broker_account(self.user)
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self.post(valid_alert(symbol="BTC/USD"))
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.REJECTED)
        self.assertEqual(order.reason, "ORDER_UNSUPPORTED_ASSET")

    def test_limit_order_placed(self):
        create_broker_account(self.user)
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self.post(valid_alert(order_type="LMT", limit_price=150.25))
        order = Order.objects.get()
        self.assertEqual(order.order_type, Order.OrderType.LMT)
        self.assertEqual(str(order.limit_price), "150.2500")


class BrokerMisrouteTests(_Base):
    def test_unconnected_named_broker_rejected_no_order(self):
        # FIX-H9: an alert that names an unconnected broker must be rejected,
        # never silently rerouted to the default (AC-05-2).
        create_broker_account(self.user)  # only ALPACA connected
        resp = self.post(valid_alert(broker="TRADESTATION", idempotency_key="h9-1"))
        self.assertEqual(resp.status_code, 200)  # webhook accepts; the task rejects
        alert = AlertMessage.objects.get()
        self.assertEqual(alert.status, "REJECTED")
        self.assertEqual(alert.reject_reason, "BROKER_NOT_CONNECTED")
        self.assertEqual(Order.objects.count(), 0)

    def test_no_broker_specified_uses_default(self):
        default = create_broker_account(self.user)
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self.post(valid_alert(idempotency_key="h9-2"))
        self.assertEqual(Order.objects.get().broker_account_id, default.id)


class ProcessAlertValidationTests(_Base):
    """FIX-M16: numeric/date parse errors route through a clean reject, never a
    500 or an alert stranded in RECEIVED. Tested at the task layer because the
    webhook schema rejects some of these shapes before process_alert runs."""

    def _run(self, body):
        from apps.webhooks.tasks import process_alert

        create_broker_account(self.user)
        alert = AlertMessage.objects.create(
            user=self.user, strategy=self.strategy, body_json=body,
            idempotency_key=body.get("idempotency_key", ""),
            status=AlertMessage.Status.RECEIVED,
        )
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            process_alert.delay(str(alert.id))
        alert.refresh_from_db()
        return alert

    def test_nan_qty_rejected(self):
        alert = self._run({"action": "buy", "symbol": "AAPL", "qty": "NaN",
                           "order_type": "MKT", "idempotency_key": "nan-1"})
        self.assertEqual(alert.status, "REJECTED")
        self.assertEqual(Order.objects.get().reason, "INVALID_QTY")

    def test_infinity_qty_rejected(self):
        alert = self._run({"action": "buy", "symbol": "AAPL", "qty": "Infinity",
                           "order_type": "MKT", "idempotency_key": "inf-1"})
        self.assertEqual(alert.status, "REJECTED")
        self.assertEqual(Order.objects.get().reason, "INVALID_QTY")

    def test_bad_option_expiry_rejected(self):
        alert = self._run({"action": "buy", "symbol": "AAPL", "qty": 1, "order_type": "MKT",
                           "asset_class": "OPTION", "option_expiry": "not-a-date",
                           "option_strike": 150, "idempotency_key": "opt-1"})
        self.assertEqual(alert.status, "REJECTED")
        self.assertEqual(Order.objects.get().reason, "ORDER_INVALID_OPTION")

    def test_nan_limit_price_rejected(self):
        # FIX-M16 (review): non-finite limit_price parses but must be rejected.
        alert = self._run({"action": "buy", "symbol": "AAPL", "qty": 1, "order_type": "LMT",
                           "limit_price": "NaN", "idempotency_key": "nl-1"})
        self.assertEqual(alert.status, "REJECTED")
        self.assertEqual(Order.objects.get().reason, "ORDER_INVALID_LIMIT")

    def test_nan_option_strike_rejected(self):
        alert = self._run({"action": "buy", "symbol": "AAPL", "qty": 1, "order_type": "MKT",
                           "asset_class": "OPTION", "option_expiry": "2026-01-17",
                           "option_strike": "Infinity", "idempotency_key": "ns-1"})
        self.assertEqual(alert.status, "REJECTED")
        self.assertEqual(Order.objects.get().reason, "ORDER_INVALID_OPTION")

    def test_invalid_calendar_option_expiry_rejected_not_crash(self):
        # Security review: parse_date RAISES ValueError (not None) on a
        # well-formed-but-invalid calendar date — must reject cleanly, not crash
        # the task and strand the order at PENDING_SUBMIT.
        alert = self._run({"action": "buy", "symbol": "AAPL", "qty": 1, "order_type": "MKT",
                           "asset_class": "OPTION", "option_expiry": "2026-02-30",
                           "option_strike": 100, "idempotency_key": "ic-1"})
        self.assertEqual(alert.status, "REJECTED")
        self.assertEqual(Order.objects.get().reason, "ORDER_INVALID_OPTION")
