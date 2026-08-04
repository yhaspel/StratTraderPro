"""ADR-062 — instance data-provider keys: encryption, resolution, API.

The acceptance that matters most: keys saved through the UI (DB rows) must
light up everything that used to need env vars — the clients' default key,
the regime pipeline's source gate — with NO env change and NO redeploy.
"""
from __future__ import annotations

import json
from unittest import mock

import httpx
from django.test import TestCase, override_settings

from apps.m04_testutils import auth_headers, create_user
from apps.marketdata import keys as keysvc
from apps.marketdata.fmp import FMPClient
from apps.marketdata.fred import FREDClient
from apps.marketdata.models import DataProviderKey

KEYS_URL = "/api/v1/marketdata/keys/"
FMP_KEY = "fmp-live-key-abcd1234efgh5678"
FRED_KEY = "fred-live-key-1234abcd5678efgh"


class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeHttp:
    """Injectable validation transport — returns a canned status or raises."""

    def __init__(self, status=200, transport_error=False):
        self.status = status
        self.transport_error = transport_error
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        if self.transport_error:
            raise httpx.ConnectError("boom")
        return _FakeResp(self.status)


@override_settings(FMP_API_KEY="", FRED_API_KEY="")
class KeyServiceTests(TestCase):
    def test_encrypt_decrypt_round_trip(self):
        blob = keysvc.encrypt_key(FMP_KEY)
        self.assertNotIn(FMP_KEY.encode(), bytes(blob))
        self.assertEqual(keysvc.decrypt_key(blob), FMP_KEY)

    def test_set_key_upserts_single_row_with_hint(self):
        keysvc.set_key("FMP", FMP_KEY)
        keysvc.set_key("FMP", FMP_KEY[:-4] + "wxyz")
        rows = DataProviderKey.objects.filter(provider="FMP")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().key_hint, "wxyz")

    def test_short_key_gets_no_hint(self):
        keysvc.set_key("FMP", "shortkey")
        self.assertEqual(DataProviderKey.objects.get(provider="FMP").key_hint, "")

    def test_resolve_prefers_ui_over_env(self):
        keysvc.set_key("FMP", FMP_KEY)
        with override_settings(FMP_API_KEY="env-key"):
            self.assertEqual(keysvc.resolve_key("FMP"), FMP_KEY)
            self.assertEqual(keysvc.key_source("FMP"), "ui")

    def test_resolve_falls_back_to_env(self):
        with override_settings(FMP_API_KEY="env-key"):
            self.assertEqual(keysvc.resolve_key("FMP"), "env-key")
            self.assertEqual(keysvc.key_source("FMP"), "env")

    def test_resolve_empty_when_unconfigured(self):
        self.assertEqual(keysvc.resolve_key("FRED"), "")
        self.assertIsNone(keysvc.key_source("FRED"))

    def test_clear_key_restores_env_fallback(self):
        keysvc.set_key("FRED", FRED_KEY)
        self.assertTrue(keysvc.clear_key("FRED"))
        self.assertFalse(keysvc.clear_key("FRED"))  # idempotent
        with override_settings(FRED_API_KEY="env-fred"):
            self.assertEqual(keysvc.resolve_key("FRED"), "env-fred")

    def test_clients_pick_up_ui_keys(self):
        """FMPClient()/FREDClient() with no explicit key resolve the UI key."""
        keysvc.set_key("FMP", FMP_KEY)
        keysvc.set_key("FRED", FRED_KEY)
        self.assertEqual(FMPClient().api_key, FMP_KEY)
        self.assertEqual(FREDClient().api_key, FRED_KEY)

    def test_clients_explicit_key_still_wins(self):
        keysvc.set_key("FMP", FMP_KEY)
        self.assertEqual(FMPClient(api_key="explicit").api_key, "explicit")

    def test_daily_source_configured_via_ui_keys_only(self):
        """THE acceptance: UI-stored keys (no env vars anywhere) make the
        regime pipeline's source gate pass, so the nightly task actually runs."""
        from apps.regime.tasks import _daily_source_configured

        self.assertFalse(_daily_source_configured())
        keysvc.set_key("FMP", FMP_KEY)
        self.assertFalse(_daily_source_configured())  # FRED still missing
        keysvc.set_key("FRED", FRED_KEY)
        self.assertTrue(_daily_source_configured())

    # -- validation -------------------------------------------------------
    def test_validate_fmp_ok(self):
        http = _FakeHttp(200)
        keysvc.validate_provider_key("FMP", FMP_KEY, http=http)
        url, params = http.calls[0]
        self.assertIn("/quote", url)
        self.assertEqual(params["apikey"], FMP_KEY)

    def test_validate_fmp_rejects_401_and_403(self):
        for status in (401, 403):
            with self.assertRaises(keysvc.ProviderKeyInvalid):
                keysvc.validate_provider_key("FMP", "bad", http=_FakeHttp(status))

    def test_validate_fmp_5xx_unreachable(self):
        with self.assertRaises(keysvc.ProviderUnreachable):
            keysvc.validate_provider_key("FMP", FMP_KEY, http=_FakeHttp(503))

    def test_validate_transport_error_unreachable_without_key_leak(self):
        with self.assertRaises(keysvc.ProviderUnreachable) as ctx:
            keysvc.validate_provider_key("FMP", FMP_KEY, http=_FakeHttp(transport_error=True))
        self.assertNotIn(FMP_KEY, str(ctx.exception))

    def test_validate_429_accepted(self):
        keysvc.validate_provider_key("FMP", FMP_KEY, http=_FakeHttp(429))
        keysvc.validate_provider_key("FRED", FRED_KEY, http=_FakeHttp(429))

    def test_validate_fred_400_is_invalid_key(self):
        with self.assertRaises(keysvc.ProviderKeyInvalid):
            keysvc.validate_provider_key("FRED", "bad", http=_FakeHttp(400))
        keysvc.validate_provider_key("FRED", FRED_KEY, http=_FakeHttp(200))


@override_settings(FMP_API_KEY="", FRED_API_KEY="")
class KeysApiTests(TestCase):
    def setUp(self):
        self.staff = create_user("admin@example.com", mfa=True, staff=True)
        self.user = create_user("user@example.com", mfa=True)
        self.no_mfa = create_user("nomfa@example.com", mfa=False)

    def _put(self, user, provider="fmp", key=FMP_KEY):
        return self.client.put(
            f"{KEYS_URL}{provider}/",
            data=json.dumps({"api_key": key}),
            content_type="application/json",
            **auth_headers(user),
        )

    def test_status_requires_auth(self):
        self.assertEqual(self.client.get(KEYS_URL).status_code, 401)

    def test_status_requires_mfa(self):
        resp = self.client.get(KEYS_URL, **auth_headers(self.no_mfa))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "MFA_REQUIRED")

    def test_status_regular_user_gets_no_admin_detail(self):
        keysvc.set_key("FMP", FMP_KEY)
        resp = self.client.get(KEYS_URL, **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertTrue(data["fmp"]["configured"])
        self.assertEqual(data["fmp"]["source"], "ui")
        self.assertNotIn("hint", data["fmp"])
        self.assertFalse(data["fred"]["configured"])
        self.assertIsNone(data["fred"]["source"])

    def test_status_staff_gets_hint_and_updated_by(self):
        with mock.patch.object(keysvc, "validate_provider_key"):
            self._put(self.staff)
        resp = self.client.get(KEYS_URL, **auth_headers(self.staff))
        data = resp.json()["data"]
        self.assertEqual(data["fmp"]["hint"], FMP_KEY[-4:])
        self.assertEqual(data["fmp"]["updated_by"], "admin@example.com")

    def test_put_requires_staff(self):
        resp = self._put(self.user)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(DataProviderKey.objects.exists())

    def test_put_env_source_visible_before_any_ui_key(self):
        with override_settings(FRED_API_KEY="env-fred"):
            resp = self.client.get(KEYS_URL, **auth_headers(self.user))
        data = resp.json()["data"]
        self.assertTrue(data["fred"]["configured"])
        self.assertEqual(data["fred"]["source"], "env")

    def test_put_validates_before_persist_bad_key(self):
        with mock.patch.object(
            keysvc, "validate_provider_key", side_effect=keysvc.ProviderKeyInvalid("no")
        ):
            resp = self._put(self.staff)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_API_KEY")
        self.assertFalse(DataProviderKey.objects.exists())

    def test_put_vendor_unreachable_502(self):
        with mock.patch.object(
            keysvc, "validate_provider_key", side_effect=keysvc.ProviderUnreachable("down")
        ):
            resp = self._put(self.staff)
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json()["error"]["code"], "PROVIDER_UNREACHABLE")
        self.assertFalse(DataProviderKey.objects.exists())

    def test_put_ok_persists_audits_and_never_echoes(self):
        from apps.audit.models import AuditLog

        with mock.patch.object(keysvc, "validate_provider_key") as validate:
            resp = self._put(self.staff)
        validate.assert_called_once_with("FMP", FMP_KEY)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(FMP_KEY, resp.content.decode())  # never echoed
        row = DataProviderKey.objects.get(provider="FMP")
        self.assertEqual(keysvc.decrypt_key(row.key_encrypted), FMP_KEY)
        self.assertEqual(row.updated_by, self.staff)
        audit = AuditLog.objects.filter(event_type="marketdata.provider_key_set").last()
        self.assertIsNotNone(audit)
        self.assertNotIn(FMP_KEY, json.dumps(audit.data_after))

    def test_put_non_ascii_rejected(self):
        resp = self._put(self.staff, key="key—with—dashes")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_put_unknown_provider(self):
        resp = self._put(self.staff, provider="bloomberg")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "UNKNOWN_PROVIDER")

    def test_delete_clears_ui_key_env_fallback_remains(self):
        from apps.audit.models import AuditLog

        keysvc.set_key("FRED", FRED_KEY)
        with override_settings(FRED_API_KEY="env-fred"):
            resp = self.client.delete(f"{KEYS_URL}fred/", **auth_headers(self.staff))
            self.assertEqual(resp.status_code, 200)
            data = resp.json()["data"]
            self.assertTrue(data["fred"]["configured"])  # env still provides one
            self.assertEqual(data["fred"]["source"], "env")
        self.assertFalse(DataProviderKey.objects.exists())
        self.assertTrue(
            AuditLog.objects.filter(event_type="marketdata.provider_key_removed").exists()
        )

    def test_delete_requires_staff(self):
        keysvc.set_key("FMP", FMP_KEY)
        resp = self.client.delete(f"{KEYS_URL}fmp/", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(DataProviderKey.objects.exists())
