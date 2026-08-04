"""M11 §7.1 V9 — security response headers (CSP report-only + the header set)."""
from __future__ import annotations

from django.test import TestCase, override_settings


class SecurityHeadersTests(TestCase):
    def test_csp_report_only_present(self):
        resp = self.client.get("/healthz")
        self.assertIn("Content-Security-Policy-Report-Only", resp)
        self.assertIn("default-src 'none'", resp["Content-Security-Policy-Report-Only"])
        # Report-only ships first (frozen decision §4.6) — the enforcing header is absent.
        self.assertNotIn("Content-Security-Policy", {k for k in resp.headers if k == "Content-Security-Policy"})

    def test_permissions_policy_present(self):
        resp = self.client.get("/healthz")
        self.assertIn("Permissions-Policy", resp)
        self.assertIn("camera=()", resp["Permissions-Policy"])

    def test_nosniff_and_referrer_policy(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resp["Referrer-Policy"], "strict-origin-when-cross-origin")

    @override_settings(CSP_REPORT_ONLY=False)
    def test_flip_to_enforcing(self):
        # Prove the flip works: CSP_REPORT_ONLY=false emits the enforcing header.
        # (A fresh middleware instance reads the setting in __init__, so use a
        # sub-request through a rebuilt handler.)
        from django.test import Client

        resp = Client().get("/healthz")
        self.assertIn("Content-Security-Policy", resp)
