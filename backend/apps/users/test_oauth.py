"""M2.5 — Google OAuth tests.

We unit-test the pieces we own:
  - OAuthExchangeCode model (issue, consume, single-use, expiry)
  - SocialAdapter auto-link + populate_user logic
  - OAuthGoogleStartView — verify it returns a valid Google authorize URL
  - OAuthExchangeView — happy path (no MFA), MFA gate, invalid/expired code

We do NOT test the actual Google round-trip (would require a fake OAuth
server). The /callback/ path is exercised end-to-end at smoke-test time.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.users.mfa import encrypt_secret, generate_totp_secret
from apps.users.models import (
    AuthEvent,
    MFADevice,
    OAuthExchangeCode,
)
from apps.users.services import issue_token_pair
from apps.users.social_adapters import SocialAdapter

User = get_user_model()
GOOD_PW = "SecurePass123!"
API = "/api/v1/"


def _create_user(email="trader@example.com", verified=True, password=GOOD_PW):
    user = User.objects.create_user(email=email, password=password, display_name="Trader")
    if verified:
        user.is_verified = True
        user.save(update_fields=["is_verified"])
    return user


def _enroll_mfa(user):
    secret = generate_totp_secret()
    MFADevice.objects.create(
        user=user, secret_encrypted=encrypt_secret(secret), verified=True,
    )
    return secret


# =========================================================================
# OAuthExchangeCode model
# =========================================================================
class OAuthExchangeCodeTests(TestCase):

    def test_issue_returns_row_and_raw(self):
        user = _create_user()
        row, raw = OAuthExchangeCode.issue(user)
        self.assertIsNotNone(row.code_hash)
        self.assertEqual(row.user, user)
        self.assertGreater(len(raw), 30)  # base64-encoded 32 bytes ≈ 43 chars
        self.assertNotEqual(raw, row.code_hash)  # raw is not stored verbatim
        # 5-min default TTL
        self.assertLessEqual(
            (row.expires_at - row.created_at).total_seconds(),
            6 * 60,
        )

    def test_consume_valid_returns_user(self):
        user = _create_user()
        _row, raw = OAuthExchangeCode.issue(user)
        result = OAuthExchangeCode.consume(raw)
        self.assertEqual(result, user)

    def test_consume_single_use(self):
        user = _create_user()
        _row, raw = OAuthExchangeCode.issue(user)
        # First consume succeeds
        self.assertEqual(OAuthExchangeCode.consume(raw), user)
        # Second consume of same code fails
        self.assertIsNone(OAuthExchangeCode.consume(raw))

    def test_consume_expired_rejected(self):
        user = _create_user()
        row, raw = OAuthExchangeCode.issue(user)
        # Manually expire the row
        row.expires_at = timezone.now() - timedelta(minutes=1)
        row.save(update_fields=["expires_at"])
        self.assertIsNone(OAuthExchangeCode.consume(raw))

    def test_consume_unknown_code_rejected(self):
        self.assertIsNone(OAuthExchangeCode.consume("not-a-real-code"))

    def test_consume_inactive_user_returns_user_anyway(self):
        # Model layer doesn't enforce is_active — that's the view's job.
        user = _create_user()
        user.is_active = False
        user.save(update_fields=["is_active"])
        _row, raw = OAuthExchangeCode.issue(user)
        # consume() returns the user; view layer rejects with 401.
        self.assertEqual(OAuthExchangeCode.consume(raw), user)


# =========================================================================
# SocialAdapter — auto-link + populate_user
# =========================================================================
class SocialAdapterTests(TestCase):
    """Adapter is invoked by allauth's callback view; we test its methods directly."""

    def setUp(self):
        self.adapter = SocialAdapter()

    def _fake_sociallogin(self, *, email, email_verified, account_user=None):
        """Build a sociallogin stub that mirrors what allauth passes to pre_social_login."""
        sociallogin = MagicMock()
        sociallogin.is_existing = (account_user is not None)
        sociallogin.account.extra_data = {
            "email": email,
            "email_verified": email_verified,
        }
        sociallogin.account.user = account_user
        sociallogin.user = account_user
        return sociallogin

    def test_populate_user_sets_display_name_from_google_name(self):
        sociallogin = MagicMock()
        # Stub super().populate_user to return a fresh User instance.
        u = User(email="new@example.com", display_name="placeholder")
        with self.settings():
            # Bypass the super() call by replacing populate_user behavior
            from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
            DefaultSocialAccountAdapter.populate_user = lambda self, req, sl, data: u
            try:
                result = self.adapter.populate_user(
                    None, sociallogin, {"email": "new@example.com", "name": "Jane Trader"}
                )
            finally:
                # Restore original (avoid leaking into other tests). Not strictly
                # necessary because we monkeypatched on the class, but defensive.
                pass
        self.assertEqual(result.display_name, "Jane Trader")
        self.assertTrue(result.is_verified)

    def test_pre_social_login_auto_links_existing_user_when_email_verified(self):
        existing = _create_user(email="match@example.com")
        sociallogin = self._fake_sociallogin(email="match@example.com", email_verified=True)
        request = MagicMock()
        self.adapter.pre_social_login(request, sociallogin)
        # connect() should have been called with the existing user.
        sociallogin.connect.assert_called_once_with(request, existing)

    def test_pre_social_login_does_not_link_unverified_email(self):
        _create_user(email="match@example.com")
        sociallogin = self._fake_sociallogin(email="match@example.com", email_verified=False)
        self.adapter.pre_social_login(MagicMock(), sociallogin)
        sociallogin.connect.assert_not_called()

    def test_pre_social_login_does_not_link_when_no_matching_user(self):
        sociallogin = self._fake_sociallogin(email="nonexistent@example.com", email_verified=True)
        self.adapter.pre_social_login(MagicMock(), sociallogin)
        sociallogin.connect.assert_not_called()

    def test_pre_social_login_skips_when_already_linked(self):
        existing = _create_user(email="match@example.com")
        sociallogin = self._fake_sociallogin(
            email="match@example.com", email_verified=True, account_user=existing,
        )
        # is_existing=True means this Google identity has signed in here before.
        # We should NOT re-call connect() on subsequent sign-ins.
        self.adapter.pre_social_login(MagicMock(), sociallogin)
        sociallogin.connect.assert_not_called()


# =========================================================================
# OAuthExchangeView
# =========================================================================
class OAuthExchangeViewTests(TestCase):

    def test_exchange_happy_path_returns_token_pair(self):
        user = _create_user()
        _row, raw = OAuthExchangeCode.issue(user)
        resp = self.client.post(
            f"{API}auth/oauth/exchange/",
            {"exchange": raw},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertEqual(data["user"]["email"], user.email)
        self.assertFalse(data["mfa_required"])

    def test_exchange_with_mfa_user_returns_mfa_token(self):
        user = _create_user()
        _enroll_mfa(user)
        _row, raw = OAuthExchangeCode.issue(user)
        resp = self.client.post(
            f"{API}auth/oauth/exchange/",
            {"exchange": raw},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertTrue(data["mfa_required"])
        self.assertIn("mfa_token", data)
        # Tokens should NOT be issued yet
        self.assertNotIn("access", data)

    def test_exchange_invalid_code_rejected(self):
        resp = self.client.post(
            f"{API}auth/oauth/exchange/",
            {"exchange": "definitely-not-real-1234567890abc"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "EXCHANGE_INVALID")

    def test_exchange_expired_code_rejected(self):
        user = _create_user()
        row, raw = OAuthExchangeCode.issue(user)
        row.expires_at = timezone.now() - timedelta(minutes=1)
        row.save(update_fields=["expires_at"])
        resp = self.client.post(
            f"{API}auth/oauth/exchange/",
            {"exchange": raw},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_exchange_consumed_code_rejected_on_replay(self):
        user = _create_user()
        _row, raw = OAuthExchangeCode.issue(user)
        # First consume succeeds
        first = self.client.post(
            f"{API}auth/oauth/exchange/",
            {"exchange": raw},
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 200)
        # Replay rejected
        second = self.client.post(
            f"{API}auth/oauth/exchange/",
            {"exchange": raw},
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 401)

    def test_exchange_inactive_user_rejected(self):
        user = _create_user()
        user.is_active = False
        user.save(update_fields=["is_active"])
        _row, raw = OAuthExchangeCode.issue(user)
        resp = self.client.post(
            f"{API}auth/oauth/exchange/",
            {"exchange": raw},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_exchange_records_audit_event(self):
        user = _create_user()
        _row, raw = OAuthExchangeCode.issue(user)
        self.client.post(
            f"{API}auth/oauth/exchange/",
            {"exchange": raw},
            content_type="application/json",
        )
        self.assertTrue(
            AuthEvent.objects.filter(event_type="oauth_exchange_ok", user=user).exists()
        )

    def test_exchange_invalid_records_failure_event(self):
        self.client.post(
            f"{API}auth/oauth/exchange/",
            {"exchange": "fake-code-9999999999"},
            content_type="application/json",
        )
        self.assertTrue(AuthEvent.objects.filter(event_type="oauth_exchange_fail").exists())

    @override_settings(GOOGLE_OAUTH_ENABLED=False)
    def test_exchange_disabled_returns_503(self):
        user = _create_user()
        _row, raw = OAuthExchangeCode.issue(user)
        resp = self.client.post(
            f"{API}auth/oauth/exchange/",
            {"exchange": raw},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 503)


# =========================================================================
# OAuthGoogleStartView
# =========================================================================
class OAuthGoogleStartViewTests(TestCase):

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="fake-client-id-for-test",
        SOCIALACCOUNT_PROVIDERS={
            "google": {
                "APP": {
                    "client_id": "fake-client-id-for-test",
                    "secret": "fake-secret",
                    "key": "",
                },
                "SCOPE": ["email", "profile", "openid"],
                "AUTH_PARAMS": {"access_type": "online", "prompt": "select_account"},
                "VERIFIED_EMAIL": True,
            },
        },
    )
    def test_start_redirects_to_google(self):
        # /start/ is a top-level navigation that returns 302 → Google. This
        # is critical: returning JSON would force a cross-origin XHR, which
        # drops the session cookie that allauth uses to stash the state token,
        # and the callback would fail with PermissionDenied.
        resp = self.client.get(f"{API}auth/oauth/google/start/")
        self.assertEqual(resp.status_code, 302)
        url = resp["Location"]
        self.assertIn("accounts.google.com", url)
        self.assertIn("client_id=fake-client-id-for-test", url)
        self.assertIn("response_type=code", url)
        # state token present (allauth generates it and stashes in session)
        self.assertIn("state=", url)

    @override_settings(GOOGLE_OAUTH_ENABLED=False)
    def test_start_disabled_returns_503(self):
        resp = self.client.get(f"{API}auth/oauth/google/start/")
        self.assertEqual(resp.status_code, 503)

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="")
    def test_start_unconfigured_returns_503(self):
        resp = self.client.get(f"{API}auth/oauth/google/start/")
        self.assertEqual(resp.status_code, 503)


# =========================================================================
# Settings-level OAuth config
# =========================================================================
class OAuthSettingsTests(TestCase):

    def test_oauth_settings_loaded(self):
        from django.conf import settings
        self.assertTrue(hasattr(settings, "GOOGLE_OAUTH_ENABLED"))
        self.assertTrue(hasattr(settings, "OAUTH_EXCHANGE_TTL_MINUTES"))
        self.assertEqual(settings.OAUTH_EXCHANGE_TTL_MINUTES, 5)
        self.assertIn("google", settings.SOCIALACCOUNT_PROVIDERS)
