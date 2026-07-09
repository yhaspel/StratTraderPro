"""Impersonation lifecycle + write-block (AC-10-7).

The write-block is proven against a REAL mutating view that overrides
``permission_classes=[IsAuthenticatedAndMFAEnforced]`` (risk-profile PUT) — a
global permission class would have been dropped by that override.
"""
from datetime import timedelta

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.admin_portal.impersonation import start_session, stop_session
from apps.audit.models import AuditLog

from ._helpers import make_user


class ImpersonationTokenTests(TestCase):
    def setUp(self):
        self.admin, _ = make_user("iadmin@x.com", is_staff=True, mfa=True)
        self.target, _ = make_user("itarget@x.com", mfa=True)

    def test_token_claims_and_ttl(self):
        session, token = start_session(actor=self.admin, target=self.target, reason="debug")
        decoded = AccessToken(token)
        self.assertEqual(decoded["purpose"], "impersonation")
        self.assertEqual(decoded["user_id"], str(self.target.id))  # target so owner views resolve
        self.assertEqual(decoded["actor_id"], str(self.admin.id))
        self.assertEqual(decoded["session_id"], str(session.id))
        ttl = decoded["exp"] - decoded["iat"]
        self.assertLessEqual(abs(ttl - 15 * 60), 5)

    def test_started_stopped_audited(self):
        session, _ = start_session(actor=self.admin, target=self.target, reason="debug")
        self.assertTrue(AuditLog.objects.filter(event_type="admin.impersonation_started").exists())
        stop_session(session, actor=self.admin)
        self.assertTrue(AuditLog.objects.filter(event_type="admin.impersonation_stopped").exists())


class ImpersonationRequestTests(TestCase):
    def setUp(self):
        self.admin, _ = make_user("iradmin@x.com", is_staff=True, mfa=True)
        self.target, self.tsecret = make_user("irtarget@x.com", mfa=True)
        self.session, self.token = start_session(actor=self.admin, target=self.target, reason="investigate")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_safe_read_works_and_is_audited(self):
        resp = self.client.get("/api/v1/risk/profile/")
        self.assertEqual(resp.status_code, 200)
        # Exactly one impersonated_read row per request (DRF memoizes request.user).
        self.assertEqual(
            AuditLog.objects.filter(
                event_type="admin.impersonated_read", actor=self.admin, user=self.target
            ).count(),
            1,
        )

    def test_write_is_blocked_at_auth_layer(self):
        resp = self.client.put("/api/v1/risk/profile/", {"risk_per_trade_pct": "2.0"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_admin_routes_rejected(self):
        self.assertEqual(self.client.get("/api/v1/admin/health/").status_code, 403)

    def test_stop_revokes_immediately(self):
        self.assertEqual(self.client.get("/api/v1/risk/profile/").status_code, 200)
        stop_session(self.session, actor=self.admin)
        # Next call on the same token → 401 (session check, not just token expiry).
        self.assertEqual(self.client.get("/api/v1/risk/profile/").status_code, 401)

    def test_expired_session_rejected(self):
        from django.utils import timezone

        self.session.expires_at = timezone.now() - timedelta(minutes=1)
        self.session.save(update_fields=["expires_at"])
        self.assertEqual(self.client.get("/api/v1/risk/profile/").status_code, 401)


class AdminPortalDisabledTests(TestCase):
    @override_settings(ADMIN_PORTAL_ENABLED=False)
    def test_all_admin_routes_503_when_disabled(self):
        admin, secret = make_user("dadmin@x.com", is_staff=True, mfa=True)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(admin)}")
        resp = client.get("/api/v1/admin/health/")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"]["code"], "ADMIN_PORTAL_DISABLED")
