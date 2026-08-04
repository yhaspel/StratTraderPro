"""M11 §7.8 — Terms of Service / Privacy acceptance flow tests."""
from __future__ import annotations

from django.test import TestCase

from apps.audit.models import AuditLog
from apps.m04_testutils import auth_headers, create_user
from apps.users.models import TermsAcceptance, TermsDocument

CURRENT_URL = "/api/v1/terms/current/"
ACCEPT_URL = "/api/v1/terms/accept/"


def _seed_docs(tos="1.0", privacy="1.0"):
    TermsDocument.objects.create(kind=TermsDocument.Kind.TERMS, version=tos)
    TermsDocument.objects.create(kind=TermsDocument.Kind.PRIVACY, version=privacy)


class TermsTests(TestCase):
    def test_current_requires_auth(self):
        self.assertEqual(self.client.get(CURRENT_URL).status_code, 401)

    def test_no_docs_means_no_acceptance_needed(self):
        user = create_user(email="nodocs@example.com")
        data = self.client.get(CURRENT_URL, **auth_headers(user)).json()["data"]
        self.assertFalse(data["needs_acceptance"])

    def test_new_user_needs_acceptance_when_docs_exist(self):
        _seed_docs()
        user = create_user(email="new@example.com")
        data = self.client.get(CURRENT_URL, **auth_headers(user)).json()["data"]
        self.assertTrue(data["needs_acceptance"])
        self.assertEqual(data["tos_version"], "1.0")
        self.assertEqual(data["privacy_version"], "1.0")

    def test_accept_records_and_clears_needs(self):
        _seed_docs()
        user = create_user(email="accept@example.com")
        resp = self.client.post(
            ACCEPT_URL,
            data={"tos_version": "1.0", "privacy_version": "1.0"},
            content_type="application/json",
            **auth_headers(user),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(TermsAcceptance.objects.filter(user=user).exists())
        self.assertTrue(
            AuditLog.objects.filter(user_id=user.id, event_type="terms.accepted").exists()
        )
        # Now the modal should no longer be required.
        data = self.client.get(CURRENT_URL, **auth_headers(user)).json()["data"]
        self.assertFalse(data["needs_acceptance"])

    def test_accept_stale_version_is_409(self):
        _seed_docs(tos="2.0", privacy="2.0")
        user = create_user(email="stale@example.com")
        resp = self.client.post(
            ACCEPT_URL,
            data={"tos_version": "1.0", "privacy_version": "1.0"},
            content_type="application/json",
            **auth_headers(user),
        )
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(TermsAcceptance.objects.filter(user=user).exists())

    def test_version_bump_re_requires_acceptance(self):
        _seed_docs(tos="1.0", privacy="1.0")
        user = create_user(email="bump@example.com")
        self.client.post(
            ACCEPT_URL,
            data={"tos_version": "1.0", "privacy_version": "1.0"},
            content_type="application/json",
            **auth_headers(user),
        )
        # New ToS version in force → needs re-acceptance.
        TermsDocument.objects.create(kind=TermsDocument.Kind.TERMS, version="2.0")
        data = self.client.get(CURRENT_URL, **auth_headers(user)).json()["data"]
        self.assertTrue(data["needs_acceptance"])
        self.assertEqual(data["tos_version"], "2.0")
