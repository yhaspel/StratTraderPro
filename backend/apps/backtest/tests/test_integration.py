"""Full walk-forward integration (M09 §10.2) — eager Celery, real artifacts.

Requires WeasyPrint native libs (Pango/HarfBuzz) — present in CI (apt) and the
Docker image; locally set ``DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib``.
"""
from __future__ import annotations

import json
from datetime import date
from unittest import mock

from django.test import TestCase

from apps.backtest.models import BacktestRun
from apps.m04_testutils import auth_headers, create_user
from apps.strategies.models import Strategy

from ._fixtures import seed_bars

_BODY = {
    "symbols": ["AAA"], "start": "2020-01-01", "end": "2021-01-01", "tf": "1d",
    "train_window_days": 180, "test_window_days": 60, "step_days": 60,
    "mode": "rolling", "metric": "sharpe", "initial_cash": 100000,
    "param_grid": {}, "costs": {"slippage_bps": 5, "volume_participation_pct": 10},
    "sizing_mode": "fixed_qty_1", "retention_days": 90,
}


class FullWalkForwardTests(TestCase):
    def setUp(self):
        self.user = create_user(email="i@example.com", mfa=True)
        self.strategy = Strategy.objects.create(
            owner=None, slug="sma-cross-demo", name="SMA Cross Demo", is_system=True
        )
        seed_bars("AAA", date(2019, 9, 1), date(2021, 1, 15))

    def _post(self, **over):
        body = {**_BODY, "strategy": str(self.strategy.id), **over}
        return self.client.post(
            "/api/v1/backtest/runs/", data=json.dumps(body),
            content_type="application/json", **auth_headers(self.user),
        )

    def test_full_run_completes_with_artifacts_segments_summary_and_events(self):
        with mock.patch("apps.backtest.events.push_to_user") as push:
            resp = self._post()
        self.assertEqual(resp.status_code, 201, resp.content)
        run = BacktestRun.objects.get(id=resp.json()["data"]["id"])
        self.assertEqual(run.status, BacktestRun.Status.COMPLETED, run.error_message)
        self.assertEqual(run.stage, BacktestRun.Stage.REPORTING)
        self.assertEqual(run.pct, 100)
        # 3 walk-forward windows × 1 symbol (the §6.4 golden count).
        self.assertEqual(run.segments.count(), 3)
        # summary + hash written.
        self.assertIn("AAA", run.summary["symbols"])
        self.assertIn("pbo", run.summary["symbols"]["AAA"])
        self.assertEqual(len(run.metrics_hash), 64)
        # three artifacts.
        report = run.report
        self.assertIsNotNone(report.json)
        self.assertGreater(report.html_bytes, 0)
        self.assertTrue(bytes(report.pdf).startswith(b"%PDF"))
        # WS events emitted over the dashboard socket.
        event_types = [c.args[1] for c in push.call_args_list]
        self.assertIn("backtest.completed", event_types)
        self.assertTrue(any(t == "backtest.progress" for t in event_types))

    def test_reproducible_metrics_hash(self):
        h1 = BacktestRun.objects.get(id=self._post().json()["data"]["id"]).metrics_hash
        h2 = BacktestRun.objects.get(id=self._post().json()["data"]["id"]).metrics_hash
        self.assertEqual(h1, h2)
        self.assertTrue(h1)

    def test_list_detail_and_artifact_downloads(self):
        rid = self._post().json()["data"]["id"]
        lst = self.client.get("/api/v1/backtest/runs/?status=COMPLETED", **auth_headers(self.user))
        self.assertEqual(lst.status_code, 200)
        self.assertGreaterEqual(lst.json()["meta"]["total"], 1)
        det = self.client.get(f"/api/v1/backtest/runs/{rid}/", **auth_headers(self.user))
        self.assertEqual(len(det.json()["data"]["segments"]), 3)
        j = self.client.get(f"/api/v1/backtest/runs/{rid}/report.json", **auth_headers(self.user))
        self.assertEqual(j.status_code, 200)
        self.assertEqual(j["Content-Type"], "application/json")
        h = self.client.get(f"/api/v1/backtest/runs/{rid}/report.html", **auth_headers(self.user))
        self.assertEqual(h.status_code, 200)
        self.assertIn("text/html", h["Content-Type"])
        p = self.client.get(f"/api/v1/backtest/runs/{rid}/report.pdf", **auth_headers(self.user))
        self.assertEqual(p.status_code, 200)
        self.assertTrue(p.content.startswith(b"%PDF"))

    def test_missing_data_fails_run_with_code(self):
        resp = self._post(symbols=["NOBARS"])
        self.assertEqual(resp.status_code, 201)
        run = BacktestRun.objects.get(id=resp.json()["data"]["id"])
        self.assertEqual(run.status, BacktestRun.Status.FAILED)
        self.assertEqual(run.error_code, "BACKTEST_INSUFFICIENT_DATA")
        self.assertFalse(hasattr(run, "report") and run.report.json is not None)

    def test_cooperative_cancellation_ends_cancelled_no_report(self):
        # A run already flagged CANCELLING must exit cleanly as CANCELLED with no
        # report (the worker checks the flag between symbols/windows) — AC-09-9.
        from apps.backtest.models import BacktestReport
        from apps.backtest.tasks import run_backtest

        config = {
            "strategy_id": str(self.strategy.id), "strategy_slug": self.strategy.slug,
            "symbols": ["AAA"], "start": "2020-01-01", "end": "2021-01-01", "tf": "1d",
            "train_window_days": 180, "test_window_days": 60, "step_days": 60, "mode": "rolling",
            "metric": "sharpe", "initial_cash": 100000,
            "param_grid": {"fast": [5, 10, 15], "slow": [20, 30, 40, 50]},
            "costs": {"slippage_bps": 5, "per_order_usd": 0, "per_share_usd": 0, "volume_participation_pct": 10},
            "sizing_mode": "fixed_qty_1", "retention_days": 90,
        }
        run = BacktestRun.objects.create(
            user=self.user, strategy=self.strategy, config=config,
            status=BacktestRun.Status.CANCELLING,
        )
        run_backtest.apply(args=[str(run.id)])
        run.refresh_from_db()
        self.assertEqual(run.status, BacktestRun.Status.CANCELLED)
        self.assertFalse(BacktestReport.objects.filter(run=run).exists())
