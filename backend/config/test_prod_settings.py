"""M10.5 §7.6 — prod fail-closed settings + urlconf hardening (C2, H8, M1).

C2 and the prod key checks run at *module import* time, so they are exercised in
a clean subprocess that imports ``config.settings.prod`` with a controlled env —
the current test process already has settings loaded and cannot re-import them.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import Resolver404, resolve

BACKEND_DIR = Path(__file__).resolve().parent.parent

# A real 32-byte url-safe base64 Fernet KEK (NOT the SHA-derived dev default).
_REAL_KEK = base64.urlsafe_b64encode(b"m10_5-real-fernet-kek-32bytes!!!").decode("ascii")
_REAL_SECRET = "a-genuinely-random-prod-secret-key-000000000000"


def _import_prod(extra_env: dict[str, str], *, drop: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """Import config.settings.prod in a fresh interpreter with a controlled env."""
    env = {"PATH": os.environ.get("PATH", ""), "DJANGO_SETTINGS_MODULE": "config.settings.prod"}
    env.update(extra_env)
    for key in drop:
        env.pop(key, None)
    return subprocess.run(
        [sys.executable, "-c", "import config.settings.prod"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class ProdKeyFailClosedTests(SimpleTestCase):
    """C2 — prod refuses to boot on missing / insecure signing + KEK keys."""

    def test_missing_fernet_kek_raises(self):
        # Provide SECRET_KEY + DATABASE_URL explicitly (CI has no backend/.env, so
        # relying on it would raise on SECRET_KEY first). FERNET_KEK is the only
        # key left unset, so the prod boot must fail CLOSED specifically on it.
        res = _import_prod(
            {"SECRET_KEY": _REAL_SECRET, "DATABASE_URL": "sqlite:///prodtest.db"},
            drop=("FERNET_KEK",),
        )
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn("FERNET_KEK", res.stderr)

    def test_insecure_secret_key_rejected(self):
        res = _import_prod({
            "SECRET_KEY": "insecure-dev-key-change-in-prod",
            "FERNET_KEK": _REAL_KEK,
            "DATABASE_URL": "sqlite:///prodtest.db",
        })
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn("SECRET_KEY", res.stderr)

    def test_properly_configured_prod_imports(self):
        res = _import_prod({
            "SECRET_KEY": _REAL_SECRET,
            "FERNET_KEK": _REAL_KEK,
            "DATABASE_URL": "sqlite:///prodtest.db",
            "ALLOWED_HOSTS": "example.com",
        })
        self.assertEqual(res.returncode, 0, res.stderr)


class SchemaEndpointGatingTests(TestCase):
    """P3-5 — OpenAPI schema + docs are admin-gated when not DEBUG (test/prod)."""

    def test_schema_requires_admin(self):
        self.assertIn(Client().get("/api/schema/").status_code, (401, 403))

    def test_docs_requires_admin(self):
        self.assertIn(Client().get("/api/docs/").status_code, (401, 403))


class CspEnforcedInProdTests(SimpleTestCase):
    """P3-6 — prod enforces the CSP (not report-only)."""

    def test_prod_disables_csp_report_only(self):
        res = subprocess.run(
            [sys.executable, "-c", "import config.settings.prod as p; print('CSP', p.CSP_REPORT_ONLY)"],
            cwd=str(BACKEND_DIR),
            env={
                "PATH": os.environ.get("PATH", ""),
                "DJANGO_SETTINGS_MODULE": "config.settings.prod",
                "SECRET_KEY": _REAL_SECRET, "FERNET_KEK": _REAL_KEK,
                "DATABASE_URL": "sqlite:///prodtest.db", "ALLOWED_HOSTS": "example.com",
            },
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("CSP False", res.stdout)


class AdminUnmountTests(SimpleTestCase):
    """H8 — Django /admin/ is not exposed under non-DEBUG settings (test/prod)."""

    def test_admin_login_not_resolvable(self):
        # Test settings run DEBUG=False, so the urlconf must not mount /admin/.
        with self.assertRaises(Resolver404):
            resolve("/admin/login/")


class MetricsFailClosedTests(SimpleTestCase):
    """M1 — /metrics fails closed when auth is required but unconfigured."""

    @override_settings(
        METRICS_REQUIRE_AUTH=True,
        METRICS_BASIC_AUTH_USERNAME="",
        METRICS_BASIC_AUTH_PASSWORD="",
    )
    def test_unconfigured_metrics_denied_when_required(self):
        from config.metrics_endpoint import _auth_ok
        self.assertFalse(_auth_ok(""))

    @override_settings(METRICS_REQUIRE_AUTH=False)
    def test_unconfigured_metrics_open_in_dev(self):
        from config.metrics_endpoint import _auth_ok
        self.assertTrue(_auth_ok(""))
