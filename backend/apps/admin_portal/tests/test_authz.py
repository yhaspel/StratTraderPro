"""Admin authz security matrix (AC-10-4 / §10.6).

Every /api/v1/admin/* route × (anon → 401, non-staff → 403, staff-no-MFA → 403,
impersonation token → 403). Uses REAL JWT tokens so the impersonation-aware
authenticator actually runs.
"""
import uuid

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.admin_portal.impersonation import start_session

from ._helpers import make_user

_UID = uuid.uuid4()
_SID = uuid.uuid4()

# (method, path) for every admin route. Templated ids are arbitrary — auth/perm
# is checked before the object lookup.
ROUTES = [
    ("get", "/api/v1/admin/users/"),
    ("get", f"/api/v1/admin/users/{_UID}/"),
    ("post", f"/api/v1/admin/users/{_UID}/disable/"),
    ("post", f"/api/v1/admin/users/{_UID}/enable/"),
    ("post", f"/api/v1/admin/users/{_UID}/impersonate/start/"),
    ("post", f"/api/v1/admin/impersonation/{_SID}/stop/"),
    ("get", "/api/v1/admin/audit/"),
    ("get", "/api/v1/admin/audit/export.csv"),
    ("get", "/api/v1/admin/platform/status/"),
    ("post", "/api/v1/admin/platform/killswitch/"),
    ("get", "/api/v1/admin/flags/"),
    ("post", "/api/v1/admin/flags/BACKTEST_ENABLED/"),
    ("get", "/api/v1/admin/health/"),
]


class AdminAuthzMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plain, _ = make_user("plain@x.com")
        cls.staff_no_mfa, _ = make_user("staffnomfa@x.com", is_staff=True, mfa=False)
        cls.admin, _ = make_user("mxadmin@x.com", is_staff=True, mfa=True)
        cls.target, _ = make_user("mxtarget@x.com")

    def _call(self, client, method, path):
        return getattr(client, method)(path, data={}, format="json")

    def test_anonymous_is_401(self):
        client = APIClient()
        for method, path in ROUTES:
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual(self._call(client, method, path).status_code, 401)

    def test_non_staff_is_403(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.plain)}")
        for method, path in ROUTES:
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual(self._call(client, method, path).status_code, 403)

    def test_staff_without_mfa_is_403(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.staff_no_mfa)}")
        for method, path in ROUTES:
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual(self._call(client, method, path).status_code, 403)

    def test_impersonation_token_is_403(self):
        _, token = start_session(actor=self.admin, target=self.target, reason="debug")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        for method, path in ROUTES:
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual(self._call(client, method, path).status_code, 403)
