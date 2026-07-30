"""Admin operations (AC-10-5 killswitch, disable/enable, audit search + CSV, flags, health)."""
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.brokers.models import TradingHalt
from apps.risk.killswitch import is_blocked
from apps.users.models import RefreshTokenFamily

from ._helpers import auth_client, make_user, totp


class KillSwitchTests(TestCase):
    def setUp(self):
        self.admin, self.secret = make_user("ksadmin@x.com", is_staff=True, mfa=True)
        self.client = auth_client(self.admin)
        self.victim, _ = make_user("ksvictim@x.com")

    def test_engage_requires_confirm_phrase(self):
        resp = self.client.post("/api/v1/admin/platform/killswitch/", {
            "engage": True, "reason": "test", "mfa_code": totp(self.secret), "confirm": "halt platform",
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "CONFIRM_PHRASE_MISMATCH")
        self.assertFalse(TradingHalt.objects.filter(level=TradingHalt.Level.L3, released_at__isnull=True).exists())

    def test_bad_mfa_rejected(self):
        resp = self.client.post("/api/v1/admin/platform/killswitch/", {
            "engage": True, "reason": "test", "mfa_code": "000000", "confirm": "HALT PLATFORM",
        }, format="json")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "MFA_REQUIRED")

    def test_engage_and_release_l3(self):
        resp = self.client.post("/api/v1/admin/platform/killswitch/", {
            "engage": True, "reason": "incident-42", "mfa_code": totp(self.secret), "confirm": "HALT PLATFORM",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["data"]["platform_halted"])
        self.assertEqual(is_blocked(self.victim.id), "PLATFORM_HALTED")
        self.assertTrue(AuditLog.objects.filter(event_type="admin.platform_halt_engaged").exists())

        rel = self.client.post("/api/v1/admin/platform/killswitch/", {
            "engage": False, "reason": "resolved", "mfa_code": totp(self.secret),
        }, format="json")
        self.assertEqual(rel.status_code, 200)
        self.assertIsNone(is_blocked(self.victim.id))
        self.assertTrue(AuditLog.objects.filter(event_type="admin.platform_halt_released").exists())

    def test_status_endpoint(self):
        resp = self.client.get("/api/v1/admin/platform/status/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("does NOT flatten", resp.json()["data"]["note"])


class UserAdminTests(TestCase):
    def setUp(self):
        self.admin, self.secret = make_user("uadmin@x.com", is_staff=True, mfa=True)
        self.client = auth_client(self.admin)
        self.target, _ = make_user("utarget@x.com")

    def test_disable_revokes_families_and_audits(self):
        RefreshTokenFamily.objects.create(user=self.target, current_jti="j1", ip="1.2.3.4",
                                          user_agent="a", last_used_at=None)
        resp = self.client.post(f"/api/v1/admin/users/{self.target.id}/disable/", {
            "mfa_code": totp(self.secret), "reason": "abuse",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertEqual(RefreshTokenFamily.objects.filter(user=self.target, revoked_at__isnull=True).count(), 0)
        self.assertTrue(AuditLog.objects.filter(event_type="admin.user_disabled", user=self.target).exists())

    def test_enable_restores(self):
        self.target.is_active = False
        self.target.save(update_fields=["is_active"])
        resp = self.client.post(f"/api/v1/admin/users/{self.target.id}/enable/", {
            "mfa_code": totp(self.secret), "reason": "cleared",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_user_list_and_detail(self):
        lst = self.client.get("/api/v1/admin/users/?q=utarget")
        self.assertEqual(lst.status_code, 200)
        self.assertGreaterEqual(lst.json()["meta"]["total"], 1)
        detail = self.client.get(f"/api/v1/admin/users/{self.target.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["email"], "utarget@x.com")


class AuditSearchExportTests(TestCase):
    def setUp(self):
        self.admin, self.secret = make_user("aadmin@x.com", is_staff=True, mfa=True)
        self.client = auth_client(self.admin)
        from apps.audit.services import emit

        self.u, _ = make_user("audituser@x.com")
        emit("order.submitted", user=self.u, entity_type="order", entity_id="o1")
        emit("strategy.secret_rotated", user=self.u, data_after={"secret": "shh"})

    def test_search_filters_by_event_type(self):
        resp = self.client.get("/api/v1/admin/audit/?event_type=order.submitted")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()["data"]
        self.assertTrue(all(r["event_type"] == "order.submitted" for r in rows))

    def test_csv_export_streams_with_header_and_scrub(self):
        resp = self.client.get("/api/v1/admin/audit/export.csv")
        self.assertEqual(resp.status_code, 200)
        body = b"".join(resp.streaming_content).decode()
        self.assertIn("Event type", body)  # translated header
        self.assertNotIn("shh", body)  # secret scrubbed at emit time


class FlagApiHealthTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        from apps.admin_portal import flags

        cache.clear()
        flags._bust_local()
        self.admin, self.secret = make_user("fadmin2@x.com", is_staff=True, mfa=True)
        self.client = auth_client(self.admin)

    def tearDown(self):
        from django.core.cache import cache

        from apps.admin_portal import flags

        cache.clear()
        flags._bust_local()

    def test_flag_flip_and_immutable(self):
        resp = self.client.post("/api/v1/admin/flags/BACKTEST_ENABLED/", {
            "enabled": False, "mfa_code": totp(self.secret),
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["data"]["enabled"])

        imm = self.client.post("/api/v1/admin/flags/MFA_ENABLED/", {
            "enabled": False, "mfa_code": totp(self.secret),
        }, format="json")
        self.assertEqual(imm.status_code, 400)
        self.assertEqual(imm.json()["error"]["code"], "FLAG_IMMUTABLE")

    def test_flag_list(self):
        resp = self.client.get("/api/v1/admin/flags/")
        self.assertEqual(resp.status_code, 200)
        names = {f["name"] for f in resp.json()["data"]}
        self.assertIn("ADMIN_PORTAL_ENABLED", names)

    def test_health(self):
        resp = self.client.get("/api/v1/admin/health/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("queue_depths", data)
        self.assertIn("verifier", data)

    def test_health_sentiment_backlog_is_an_object_not_a_scalar(self):
        """The admin UI renders `depth` out of this. It printed `[object Object]`
        for as long as the frontend model typed the field as a number, so pin the
        shape here rather than leaving it to a hand-check of the rendered page."""
        data = self.client.get("/api/v1/admin/health/").json()["data"]
        backlog = data["sentiment_backlog"]
        self.assertIsInstance(backlog, dict)
        self.assertEqual({"depth", "oldest_age_min", "alert"}, set(backlog))
        self.assertIsInstance(backlog["depth"], int)
        self.assertIsInstance(backlog["alert"], bool)

    def test_health_active_halts_is_an_object_and_flags_is_a_count(self):
        """Same class of drift: the SPA typed these as string lists."""
        data = self.client.get("/api/v1/admin/health/").json()["data"]
        self.assertEqual({"total", "platform"}, set(data["active_halts"]))
        self.assertIsInstance(data["flags_overridden"], int)

    def test_health_reports_whether_the_regime_source_is_configured(self):
        """`regime_source_configured` is the only in-app answer to "why is the
        Market Regime card empty?" — the daily task silently no-ops without both
        market-data keys."""
        with self.settings(FMP_API_KEY="", FRED_API_KEY=""):
            data = self.client.get("/api/v1/admin/health/").json()["data"]
            self.assertIs(data["regime_source_configured"], False)
        with self.settings(FMP_API_KEY="fmp-key", FRED_API_KEY="fred-key"):
            data = self.client.get("/api/v1/admin/health/").json()["data"]
            self.assertIs(data["regime_source_configured"], True)

    def test_health_regime_source_needs_both_keys(self):
        with self.settings(FMP_API_KEY="fmp-key", FRED_API_KEY=""):
            data = self.client.get("/api/v1/admin/health/").json()["data"]
            self.assertIs(data["regime_source_configured"], False)
