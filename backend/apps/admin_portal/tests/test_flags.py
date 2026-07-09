"""Feature-flag helper tests (AC-10-11): resolution, cache time-travel,
immutable rejection, missing-table safety, audit + metric on flip."""
from unittest.mock import patch

from django.db.utils import ProgrammingError
from django.test import TestCase

from apps.admin_portal import flags
from apps.admin_portal.models import FeatureFlag
from apps.audit.models import AuditLog

from ._helpers import make_user


class FlagResolutionTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()  # LocMemCache is process-global; isolate the Redis layer
        flags._bust_local()
        self.admin, _ = make_user("fadmin@x.com", is_staff=True, mfa=True)

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()
        flags._bust_local()

    def test_default_when_no_db_row(self):
        # BACKTEST_ENABLED defaults True in the registry.
        self.assertTrue(flags.is_enabled("BACKTEST_ENABLED"))
        self.assertEqual(flags.source("BACKTEST_ENABLED"), "env-default")

    def test_db_override_takes_effect_after_flip(self):
        flags.set_flag("BACKTEST_ENABLED", False, actor=self.admin)
        self.assertFalse(flags.is_enabled("BACKTEST_ENABLED"))
        self.assertEqual(flags.source("BACKTEST_ENABLED"), "db")

    def test_immutable_flag_is_env_only(self):
        with self.assertRaises(flags.FlagImmutable):
            flags.set_flag("MFA_ENABLED", False, actor=self.admin)
        # And is_enabled short-circuits to settings regardless of any DB row.
        FeatureFlag.objects.create(name="MFA_ENABLED", enabled=False)
        self.assertTrue(flags.is_enabled("MFA_ENABLED"))  # settings.MFA_ENABLED default True

    def test_unknown_flag_raises_keyerror_on_flip(self):
        with self.assertRaises(KeyError):
            flags.set_flag("NOPE_ENABLED", True, actor=self.admin)

    def test_flip_is_audited_and_metered(self):
        from apps.admin_portal.metrics import FEATURE_FLAG_FLIPS

        before = FEATURE_FLAG_FLIPS.labels(flag="BACKTEST_ENABLED")._value.get()
        flags.set_flag("BACKTEST_ENABLED", False, actor=self.admin, note="rollback")
        self.assertTrue(
            AuditLog.objects.filter(event_type="flag.flipped", entity_id="BACKTEST_ENABLED").exists()
        )
        after = FEATURE_FLAG_FLIPS.labels(flag="BACKTEST_ENABLED")._value.get()
        self.assertEqual(after - before, 1)

    def test_local_cache_window_then_converge_via_time_travel(self):
        clock = [1000.0]
        with patch.object(flags, "_monotonic", lambda: clock[0]):
            # Prime the local cache with the current value (True).
            self.assertTrue(flags.is_enabled("BACKTEST_ENABLED"))
            # Simulate ANOTHER process flipping it: DB + Redis change, but this
            # process's 30s local cache is NOT busted.
            FeatureFlag.objects.create(name="BACKTEST_ENABLED", enabled=False)
            from django.core.cache import cache

            cache.set(flags._redis_key("BACKTEST_ENABLED"), False, 60)
            # Still True inside the 30s window.
            self.assertTrue(flags.is_enabled("BACKTEST_ENABLED"))
            # Advance past the local TTL → converges to False (≤ 30s, no sleep).
            clock[0] += flags.LOCAL_CACHE_TTL + 1
            self.assertFalse(flags.is_enabled("BACKTEST_ENABLED"))

    def test_missing_table_fails_open_to_default(self):
        flags._bust_local()
        with patch("apps.admin_portal.models.FeatureFlag.objects") as mgr:
            mgr.filter.side_effect = ProgrammingError("relation does not exist")
            # Must not raise; returns the env default.
            self.assertTrue(flags.is_enabled("BACKTEST_ENABLED"))
