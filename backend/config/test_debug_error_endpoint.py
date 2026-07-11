"""Gating tests for the deliberate-error endpoint (AC-10-10).

`/__debug__/boom/` exists solely to produce a real Sentry issue carrying the
request_id + trace_id tags, so the Sentry → Tempo click-through can be verified on
staging. It raises unconditionally, so the *gate* is the safety-critical part:
this is a trading platform, and an always-500 route must not be one stray
environment variable away from being live in production.
"""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from config.urls import _boom, _debug_error_endpoint_armed


class DebugErrorEndpointGateTests(SimpleTestCase):
    @override_settings(DEBUG_ERROR_ENDPOINT_ENABLED=False)
    def test_disabled_by_default(self):
        with mock.patch.dict("os.environ", {"RAILWAY_ENVIRONMENT_NAME": "staging"}):
            self.assertFalse(_debug_error_endpoint_armed())

    @override_settings(DEBUG_ERROR_ENDPOINT_ENABLED=True)
    def test_armed_on_staging_when_enabled(self):
        with mock.patch.dict("os.environ", {"RAILWAY_ENVIRONMENT_NAME": "staging"}):
            self.assertTrue(_debug_error_endpoint_armed())

    @override_settings(DEBUG_ERROR_ENDPOINT_ENABLED=True)
    def test_refuses_to_arm_in_production_even_when_enabled(self):
        for var in ("RAILWAY_ENVIRONMENT_NAME", "SENTRY_ENVIRONMENT"):
            with self.subTest(var=var):
                with mock.patch.dict("os.environ", {var: "production"}, clear=True):
                    self.assertFalse(_debug_error_endpoint_armed())

    @override_settings(DEBUG_ERROR_ENDPOINT_ENABLED=True)
    def test_production_check_is_case_insensitive(self):
        with mock.patch.dict("os.environ", {"RAILWAY_ENVIRONMENT_NAME": "PRODUCTION"}, clear=True):
            self.assertFalse(_debug_error_endpoint_armed())

    def test_boom_raises(self):
        with self.assertRaises(RuntimeError):
            _boom(None)
