"""Retention eviction tests (M09 §10.2, AC-09-11)."""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.backtest.models import BacktestReport, BacktestRun, BacktestSegment
from apps.backtest.tasks import evict_expired_artifacts
from apps.m04_testutils import create_user
from apps.strategies.models import Strategy


class EvictionTests(TestCase):
    def setUp(self):
        self.user = create_user(email="e@example.com", mfa=True)
        self.strategy = Strategy.objects.create(owner=None, slug="sma-cross-demo", name="Demo", is_system=True)

    def _run_with_report(self, *, age_days: int, retention: int = 90):
        run = BacktestRun.objects.create(
            user=self.user, strategy=self.strategy, config={"symbols": ["AAA"]},
            status=BacktestRun.Status.COMPLETED, retention_days=retention,
            summary={"symbols": {"AAA": {"sharpe": 1.0, "pbo": 0.2}}},
        )
        BacktestSegment.objects.create(
            run=run, symbol="AAA", window_index=0,
            train_start="2020-01-01", train_end="2020-06-29",
            test_start="2020-06-29", test_end="2020-08-28",
            best_params={"fast": 10, "slow": 30}, oos_metrics={"sharpe": 1.3},
        )
        BacktestReport.objects.create(
            run=run, json={"x": 1}, html=b"<html></html>", pdf=b"%PDF-1.4",
            html_bytes=13, pdf_bytes=7, json_bytes=8,
        )
        # bypass auto_now_add to age the run
        BacktestRun.objects.filter(id=run.id).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )
        return run

    def test_expired_artifacts_evicted_metrics_kept(self):
        run = self._run_with_report(age_days=120, retention=90)
        result = evict_expired_artifacts()
        self.assertEqual(result["evicted"], 1)
        report = BacktestReport.objects.get(run=run)
        self.assertIsNone(report.json)
        self.assertIsNone(report.pdf)
        self.assertIsNone(report.html)
        self.assertEqual(report.pdf_bytes, 0)
        self.assertIsNotNone(report.evicted_at)
        # rows + summary + segments survive (AC-09-11 "rows keep metrics").
        run.refresh_from_db()
        self.assertIn("AAA", run.summary["symbols"])
        self.assertEqual(run.segments.count(), 1)

    def test_fresh_artifacts_not_evicted(self):
        run = self._run_with_report(age_days=10, retention=90)
        evict_expired_artifacts()
        report = BacktestReport.objects.get(run=run)
        self.assertIsNotNone(report.json)
        self.assertIsNone(report.evicted_at)

    def test_custom_retention_honored(self):
        run = self._run_with_report(age_days=200, retention=365)  # within 365d retention
        evict_expired_artifacts()
        self.assertIsNotNone(BacktestReport.objects.get(run=run).json)
