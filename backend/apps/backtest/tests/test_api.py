"""Backtest API tests (M09 §10.2) — validation caps, error codes, owner-scoping."""
from __future__ import annotations

import json

from django.test import SimpleTestCase, TestCase, override_settings

from apps.backtest.exceptions import GRID_TOO_LARGE, BacktestError
from apps.backtest.models import BacktestRun
from apps.backtest.vbt_engine import make_combos
from apps.m04_testutils import auth_headers, create_user
from apps.strategies.models import Strategy

_VALID = {
    "symbols": ["AAA"], "start": "2020-01-01", "end": "2021-01-01", "tf": "1d",
    "train_window_days": 180, "test_window_days": 60, "step_days": 60,
    "mode": "rolling", "metric": "sharpe", "param_grid": {}, "sizing_mode": "fixed_qty_1",
}


class _ApiBase(TestCase):
    def setUp(self):
        self.user = create_user(email="a@example.com", mfa=True)
        self.demo = Strategy.objects.create(owner=None, slug="sma-cross-demo", name="Demo", is_system=True)

    def _post(self, user=None, **over):
        body = {**_VALID, "strategy": str(self.demo.id), **over}
        return self.client.post(
            "/api/v1/backtest/runs/", data=json.dumps(body),
            content_type="application/json", **auth_headers(user or self.user),
        )


class ValidationTests(_ApiBase):
    def test_no_adapter_returns_400(self):
        mystery = Strategy.objects.create(owner=None, slug="mystery", name="Mystery", is_system=True)
        r = self._post(strategy=str(mystery.id))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "BACKTEST_NO_ADAPTER")

    def test_step_not_equal_test_returns_400(self):
        r = self._post(step_days=30)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "VALIDATION_ERROR")

    def test_non_daily_tf_rejected(self):
        r = self._post(tf="1h")
        self.assertEqual(r.status_code, 400)

    def test_too_few_windows_rejected(self):
        r = self._post(end="2020-10-01")  # only 1 complete window
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "VALIDATION_ERROR")

    def test_too_many_symbols_rejected(self):
        r = self._post(symbols=[f"S{i}" for i in range(11)])
        self.assertEqual(r.status_code, 400)

    def test_param_grid_not_subset_rejected(self):
        r = self._post(param_grid={"fast": [7]})  # 7 not in adapter's declared fast values
        self.assertEqual(r.status_code, 400)


class ConcurrencyAndFlagTests(_ApiBase):
    def test_concurrency_cap_returns_409(self):
        for _ in range(2):
            BacktestRun.objects.create(
                user=self.user, strategy=self.demo, config={"symbols": ["AAA"]},
                status=BacktestRun.Status.RUNNING,
            )
        r = self._post()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "BACKTEST_LIMIT_CONCURRENT")

    @override_settings(BACKTEST_ENABLED=False)
    def test_flag_off_returns_503(self):
        r = self.client.get("/api/v1/backtest/runs/", **auth_headers(self.user))
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "BACKTEST_DISABLED")


class OwnerScopingTests(_ApiBase):
    def test_detail_is_owner_scoped(self):
        run = BacktestRun.objects.create(
            user=self.user, strategy=self.demo, config={"symbols": ["AAA"]}, status=BacktestRun.Status.RUNNING
        )
        other = create_user(email="b@example.com", mfa=True)
        r = self.client.get(f"/api/v1/backtest/runs/{run.id}/", **auth_headers(other))
        self.assertEqual(r.status_code, 404)

    def test_report_not_ready_returns_404(self):
        run = BacktestRun.objects.create(
            user=self.user, strategy=self.demo, config={"symbols": ["AAA"]}, status=BacktestRun.Status.COMPLETED
        )
        r = self.client.get(f"/api/v1/backtest/runs/{run.id}/report.pdf", **auth_headers(self.user))
        self.assertEqual(r.status_code, 404)


class CancelTests(_ApiBase):
    def test_cancel_active_run_sets_cancelling(self):
        run = BacktestRun.objects.create(
            user=self.user, strategy=self.demo, config={"symbols": ["AAA"]}, status=BacktestRun.Status.RUNNING
        )
        r = self.client.post(f"/api/v1/backtest/runs/{run.id}/cancel/", **auth_headers(self.user))
        self.assertEqual(r.status_code, 202)
        run.refresh_from_db()
        self.assertEqual(run.status, BacktestRun.Status.CANCELLING)

    def test_cancel_terminal_run_conflict(self):
        run = BacktestRun.objects.create(
            user=self.user, strategy=self.demo, config={"symbols": ["AAA"]}, status=BacktestRun.Status.COMPLETED
        )
        r = self.client.post(f"/api/v1/backtest/runs/{run.id}/cancel/", **auth_headers(self.user))
        self.assertEqual(r.status_code, 409)


class StrategyPickerTests(_ApiBase):
    def test_strategies_list_flags_adapter_availability(self):
        Strategy.objects.create(owner=None, slug="no-adapter", name="No Adapter", is_system=True)
        r = self.client.get("/api/v1/backtest/strategies/", **auth_headers(self.user))
        self.assertEqual(r.status_code, 200)
        by_slug = {row["slug"]: row["has_adapter"] for row in r.json()["data"]}
        self.assertTrue(by_slug["sma-cross-demo"])
        self.assertFalse(by_slug["no-adapter"])


class MakeCombosCapTests(SimpleTestCase):
    def test_grid_over_cap_raises(self):
        grid = {"a": list(range(30)), "b": list(range(30))}  # 900 > 500
        with self.assertRaises(BacktestError) as ctx:
            make_combos(grid)
        self.assertEqual(ctx.exception.code, GRID_TOO_LARGE)

    def test_grid_within_cap_ok(self):
        self.assertEqual(len(make_combos({"a": [1, 2], "b": [3, 4, 5]})), 6)
