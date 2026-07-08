"""Celery route + beat settings tests (M09 §6.8).

The plan-mandated guard: the ``backtest`` queue route must be an **explicit
per-task entry** for ``run_backtest`` only — a ``apps.backtest.tasks.*`` glob
would drag the eviction task off the default queue and silently break retention
(eager tests can't catch routing, so this is a settings-level assertion)."""
from __future__ import annotations

from django.conf import settings
from django.test import SimpleTestCase


class CeleryRouteSettingsTests(SimpleTestCase):
    def test_run_backtest_routed_to_backtest_queue(self):
        routes = settings.CELERY_TASK_ROUTES
        self.assertEqual(routes["apps.backtest.tasks.run_backtest"]["queue"], "backtest")

    def test_no_glob_route(self):
        routes = settings.CELERY_TASK_ROUTES
        self.assertNotIn("apps.backtest.tasks.*", routes)
        self.assertNotIn("apps.backtest.*", routes)

    def test_eviction_stays_on_default_queue(self):
        # evict_expired_artifacts must NOT be routed to `backtest` — it stays on
        # the default `celery` queue so retention works with no backtest worker.
        routes = settings.CELERY_TASK_ROUTES
        self.assertNotIn("apps.backtest.tasks.evict_expired_artifacts", routes)

    def test_eviction_beat_entry_present(self):
        beat = settings.CELERY_BEAT_SCHEDULE
        self.assertIn("backtest-evict-artifacts", beat)
        self.assertEqual(
            beat["backtest-evict-artifacts"]["task"],
            "apps.backtest.tasks.evict_expired_artifacts",
        )

    def test_backtest_enabled_flag_present(self):
        self.assertTrue(hasattr(settings, "BACKTEST_ENABLED"))
