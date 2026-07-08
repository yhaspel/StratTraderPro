"""seed_demo_strategy management command test (M09 §6.1)."""
from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase

from apps.backtest.strategies import get_adapter
from apps.strategies.models import Strategy


class SeedDemoStrategyTests(TestCase):
    def test_seed_creates_system_strategy_with_registered_adapter(self):
        call_command("seed_demo_strategy")
        s = Strategy.objects.get(slug="sma-cross-demo")
        self.assertTrue(s.is_system)
        self.assertIsNone(s.owner)
        self.assertIsNotNone(get_adapter(s.slug))  # slug matches a registered adapter
        self.assertEqual(s.files.count(), 3)  # pine + desc + webhook template

    def test_seed_is_idempotent(self):
        call_command("seed_demo_strategy")
        call_command("seed_demo_strategy")
        self.assertEqual(Strategy.objects.filter(slug="sma-cross-demo").count(), 1)
