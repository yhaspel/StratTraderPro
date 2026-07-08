"""M04 — Orders: fill ingestion, position math, list APIs."""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.brokers.base import FillEvent, Side
from apps.m04_testutils import (
    auth_headers,
    create_broker_account,
    create_strategy,
    create_user,
    fake_factory,
)
from apps.orders.models import Fill, Order, Position
from apps.orders.services import ingest_fill_event, reconcile_positions


def _order(user, account, strategy, coid="c1", symbol="AAPL", side=Order.Side.BUY, qty="5"):
    return Order.objects.create(
        user=user,
        strategy=strategy,
        broker_account=account,
        client_order_id=coid,
        broker_order_id=f"b-{coid}",
        symbol=symbol,
        side=side,
        qty=Decimal(qty),
        status=Order.Status.SUBMITTED,
    )


def _fill(coid, exec_id, qty, price, event="fill", side=Side.BUY, symbol="AAPL"):
    return FillEvent(
        broker_exec_id=exec_id,
        client_order_id=coid,
        broker_order_id=f"b-{coid}",
        symbol=symbol,
        side=side,
        event_type=event,
        qty=Decimal(qty),
        price=Decimal(price),
        filled_qty=Decimal(qty),
    )


class IngestFillTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.strategy = create_strategy(self.user)
        self.account = create_broker_account(self.user)

    def test_single_fill_creates_fill_and_position(self):
        order = _order(self.user, self.account, self.strategy)
        ingest_fill_event(_fill("c1", "x1", "5", "150"), user_id=self.user.id)
        self.assertEqual(Fill.objects.count(), 1)
        pos = Position.objects.get(symbol="AAPL")
        self.assertEqual(pos.qty, Decimal("5"))
        self.assertEqual(pos.avg_cost, Decimal("150"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.FILLED)

    def test_dedup_on_broker_exec_id(self):
        _order(self.user, self.account, self.strategy)
        ingest_fill_event(_fill("c1", "x1", "5", "150"), user_id=self.user.id)
        ingest_fill_event(_fill("c1", "x1", "5", "150"), user_id=self.user.id)  # replay
        self.assertEqual(Fill.objects.count(), 1)
        self.assertEqual(Position.objects.get(symbol="AAPL").qty, Decimal("5"))

    def test_partial_fills_accumulate(self):
        order = _order(self.user, self.account, self.strategy, qty="10")
        ingest_fill_event(_fill("c1", "x1", "4", "100", event="partial_fill"), user_id=self.user.id)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PARTIAL)
        ingest_fill_event(_fill("c1", "x2", "6", "110", event="fill"), user_id=self.user.id)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.FILLED)
        pos = Position.objects.get(symbol="AAPL")
        self.assertEqual(pos.qty, Decimal("10"))
        # weighted avg = (4*100 + 6*110) / 10 = 106
        self.assertEqual(pos.avg_cost, Decimal("106"))

    def test_sell_reduces_position(self):
        _order(self.user, self.account, self.strategy, coid="buy", qty="5")
        ingest_fill_event(_fill("buy", "x1", "5", "150"), user_id=self.user.id)
        _order(self.user, self.account, self.strategy, coid="sell", side=Order.Side.SELL, qty="2")
        ingest_fill_event(_fill("sell", "x2", "2", "160", side=Side.SELL), user_id=self.user.id)
        self.assertEqual(Position.objects.get(symbol="AAPL").qty, Decimal("3"))

    def test_no_order_ignored(self):
        res = ingest_fill_event(_fill("missing", "x9", "1", "10"), user_id=self.user.id)
        self.assertTrue(res.get("ignored"))
        self.assertEqual(Fill.objects.count(), 0)

    def test_fills_ingested_metric_increments(self):
        # FIX-C1: fills_ingested_total was defined but never .inc()'d.
        from apps.brokers.metrics import FILLS_INGESTED_TOTAL

        before = FILLS_INGESTED_TOTAL.labels(broker="alpaca")._value.get()
        _order(self.user, self.account, self.strategy)
        ingest_fill_event(_fill("c1", "x1", "5", "150"), user_id=self.user.id)
        self.assertEqual(FILLS_INGESTED_TOTAL.labels(broker="alpaca")._value.get(), before + 1)

    def test_order_state_transition_metric_increments(self):
        # FIX-C1: order_state_transitions_total was defined but never .inc()'d.
        from apps.brokers.metrics import ORDER_STATE_TRANSITIONS_TOTAL

        before = ORDER_STATE_TRANSITIONS_TOTAL.labels(broker="alpaca", to="FILLED")._value.get()
        _order(self.user, self.account, self.strategy)
        ingest_fill_event(_fill("c1", "x1", "5", "150"), user_id=self.user.id)
        self.assertEqual(
            ORDER_STATE_TRANSITIONS_TOTAL.labels(broker="alpaca", to="FILLED")._value.get(), before + 1
        )

    def test_parse_ts_naive_returns_aware(self):
        # FIX-M1: django.utils.timezone.utc was removed in Django 5; a naive
        # timestamp must not raise (which dropped the fill as a poison message).
        from django.utils import timezone as djtz

        from apps.orders.services import _parse_ts

        aware = _parse_ts("2026-01-02 15:30:00")
        self.assertFalse(djtz.is_naive(aware))

    def test_option_buy_to_open_increases_position(self):
        # FIX-H5: BUY_TO_OPEN is a buy-side, not Order.Side.BUY — must increment.
        _order(self.user, self.account, self.strategy, coid="bto", side=Order.Side.BUY_TO_OPEN, qty="3")
        ingest_fill_event(_fill("bto", "o1", "3", "2.50"), user_id=self.user.id)
        self.assertEqual(Position.objects.get(symbol="AAPL").qty, Decimal("3"))

    def test_option_sell_to_close_decreases_position(self):
        # FIX-H5: SELL_TO_CLOSE reduces the position.
        _order(self.user, self.account, self.strategy, coid="bto", side=Order.Side.BUY_TO_OPEN, qty="3")
        ingest_fill_event(_fill("bto", "o1", "3", "2.50"), user_id=self.user.id)
        _order(self.user, self.account, self.strategy, coid="stc", side=Order.Side.SELL_TO_CLOSE, qty="2")
        ingest_fill_event(_fill("stc", "o2", "2", "3.00"), user_id=self.user.id)
        self.assertEqual(Position.objects.get(symbol="AAPL").qty, Decimal("1"))

    def test_through_zero_flip_resets_basis(self):
        # FIX-L1: long 5 @ 100, then sell 8 → short 3 whose basis is the flip
        # fill price (120), not the stale long average.
        _order(self.user, self.account, self.strategy, coid="buy", qty="5")
        ingest_fill_event(_fill("buy", "x1", "5", "100"), user_id=self.user.id)
        _order(self.user, self.account, self.strategy, coid="sell", side=Order.Side.SELL, qty="8")
        ingest_fill_event(_fill("sell", "x2", "8", "120", side=Side.SELL), user_id=self.user.id)
        pos = Position.objects.get(symbol="AAPL")
        self.assertEqual(pos.qty, Decimal("-3"))
        self.assertEqual(pos.avg_cost, Decimal("120"))

    def test_dedup_scoped_per_broker_account(self):
        # FIX-M2: the same broker_exec_id under two different accounts must both
        # persist — a global-unique constraint swallowed the second broker's fill.
        acct2 = create_broker_account(self.user, is_default=False, account_number="PATEST002")
        _order(self.user, self.account, self.strategy, coid="c1", qty="5")
        Order.objects.create(
            user=self.user, strategy=self.strategy, broker_account=acct2,
            client_order_id="c2", broker_order_id="b-c2", symbol="AAPL",
            side=Order.Side.BUY, qty=Decimal("5"), status=Order.Status.SUBMITTED,
        )
        ingest_fill_event(_fill("c1", "shared-exec", "5", "150"), user_id=self.user.id)
        ingest_fill_event(_fill("c2", "shared-exec", "5", "150"), user_id=self.user.id)
        self.assertEqual(Fill.objects.count(), 2)

    def test_reconcile_positions_snaps_to_broker(self):
        Position.objects.create(
            user=self.user, broker_account=self.account, symbol="AAPL", qty=Decimal("9"), avg_cost=Decimal("1")
        )
        fake = fake_factory()(self.account)  # broker reports no positions
        changed = reconcile_positions(self.account, fake)
        self.assertEqual(changed, 1)
        self.assertEqual(Position.objects.get(symbol="AAPL").qty, 0)


class OrderListApiTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.strategy = create_strategy(self.user)
        self.account = create_broker_account(self.user)
        _order(self.user, self.account, self.strategy, coid="a", symbol="AAPL")
        o = _order(self.user, self.account, self.strategy, coid="b", symbol="MSFT")
        o.status = Order.Status.FILLED
        o.save()

    def test_list_orders(self):
        resp = self.client.get("/api/v1/orders/", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["data"]), 2)

    def test_filter_by_status_and_symbol(self):
        resp = self.client.get("/api/v1/orders/?status=FILLED", **auth_headers(self.user))
        self.assertEqual(len(resp.json()["data"]), 1)
        resp = self.client.get("/api/v1/orders/?symbol=AAPL", **auth_headers(self.user))
        self.assertEqual(len(resp.json()["data"]), 1)

    def test_orders_isolated_per_user(self):
        other = create_user(email="other@example.com")
        resp = self.client.get("/api/v1/orders/", **auth_headers(other))
        self.assertEqual(len(resp.json()["data"]), 0)

    def test_requires_mfa(self):
        resp = self.client.get("/api/v1/orders/")
        self.assertIn(resp.status_code, (401, 403))


class PositionFillApiTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.account = create_broker_account(self.user)
        Position.objects.create(
            user=self.user, broker_account=self.account, symbol="AAPL",
            qty=Decimal("5"), avg_cost=Decimal("150"), market_price=Decimal("155"),
        )
        Position.objects.create(
            user=self.user, broker_account=self.account, symbol="FLAT",
            qty=Decimal("0"), avg_cost=Decimal("0"),
        )

    def test_positions_snapshot_excludes_flat(self):
        resp = self.client.get("/api/v1/positions/", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        symbols = [p["symbol"] for p in resp.json()["data"]]
        self.assertIn("AAPL", symbols)
        self.assertNotIn("FLAT", symbols)

    def test_positions_include_flat(self):
        resp = self.client.get("/api/v1/positions/?include_flat=true", **auth_headers(self.user))
        symbols = [p["symbol"] for p in resp.json()["data"]]
        self.assertIn("FLAT", symbols)

    def test_unrealized_pnl_computed(self):
        resp = self.client.get("/api/v1/positions/", **auth_headers(self.user))
        aapl = next(p for p in resp.json()["data"] if p["symbol"] == "AAPL")
        # (155 - 150) * 5 = 25
        self.assertEqual(Decimal(aapl["unrealized_pnl"]), Decimal("25"))
