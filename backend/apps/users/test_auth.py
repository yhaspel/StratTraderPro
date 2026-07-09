"""M01 Auth Foundation — unit + integration tests.

Tests run against SQLite in-memory with MD5 hasher (fast) and locmem email
backend. Rate-limiting is disabled by default (test settings).
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.users.models import (
    EmailVerificationToken,
    FailedLoginAttempt,
    PasswordResetToken,
    RefreshTokenFamily,
)
from apps.users.services import (
    is_locked,
    issue_token_pair,
    record_failed_login,
)

User = get_user_model()

# Consistent test password that meets policy.
GOOD_PW = "SecurePass123!"
WEAK_PW = "short1"
NO_DIGIT_PW = "AllLettersOnly!!!"
COMMON_PW = "password1234"  # Django's common-password list

API = "/api/v1/"


def _create_user(email="test@example.com", verified=True, password=GOOD_PW, **kw):
    user = User.objects.create_user(email=email, password=password, display_name="Tester", **kw)
    if verified:
        user.is_verified = True
        user.save(update_fields=["is_verified"])
    return user


# =========================================================================
# Registration
# =========================================================================
class RegisterTests(TestCase):

    def test_register_creates_user_and_sends_email(self):
        resp = self.client.post(
            f"{API}auth/register/",
            {"email": "new@example.com", "display_name": "Newbie", "password": GOOD_PW},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()["data"]
        self.assertEqual(data["email"], "new@example.com")
        self.assertTrue(User.objects.filter(email="new@example.com").exists())
        # Verification email sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Verify", mail.outbox[0].subject)
        # AuthEvent recorded
        self.assertTrue(AuditLog.objects.filter(event_type="auth.register").exists())

    def test_register_duplicate_email_returns_202(self):
        _create_user(email="dupe@example.com")
        resp = self.client.post(
            f"{API}auth/register/",
            {"email": "dupe@example.com", "display_name": "Dupe", "password": GOOD_PW},
            content_type="application/json",
        )
        # 202 — don't leak that the email exists.
        self.assertEqual(resp.status_code, 202)

    @override_settings(AUTH_PASSWORD_VALIDATORS=[
        {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
        {"NAME": "apps.users.validators.LettersAndDigitsValidator"},
    ])
    def test_register_weak_password_rejected(self):
        resp = self.client.post(
            f"{API}auth/register/",
            {"email": "weak@example.com", "display_name": "Weak", "password": WEAK_PW},
            content_type="application/json",
        )
        self.assertIn(resp.status_code, [400])
        self.assertEqual(resp.json()["error"]["code"], "PASSWORD_WEAK")


# =========================================================================
# Email verification
# =========================================================================
class VerifyEmailTests(TestCase):

    def test_verify_email_happy_path(self):
        user = _create_user(verified=False)
        _tok, raw = EmailVerificationToken.issue(user)
        resp = self.client.post(
            f"{API}auth/verify-email/",
            {"token": raw},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        user.refresh_from_db()
        self.assertTrue(user.is_verified)

    def test_verify_email_token_expired_rejected(self):
        user = _create_user(verified=False)
        tok, raw = EmailVerificationToken.issue(user)
        # Manually expire the token.
        tok.expires_at = timezone.now() - timedelta(hours=1)
        tok.save(update_fields=["expires_at"])
        resp = self.client.post(
            f"{API}auth/verify-email/",
            {"token": raw},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "TOKEN_INVALID")

    def test_verify_email_token_single_use(self):
        user = _create_user(verified=False)
        _, raw = EmailVerificationToken.issue(user)
        self.client.post(f"{API}auth/verify-email/", {"token": raw}, content_type="application/json")
        resp2 = self.client.post(
            f"{API}auth/verify-email/", {"token": raw}, content_type="application/json"
        )
        self.assertEqual(resp2.status_code, 400)


# =========================================================================
# Login
# =========================================================================
class LoginTests(TestCase):

    def test_login_happy_path(self):
        _create_user()
        resp = self.client.post(
            f"{API}auth/login/",
            {"email": "test@example.com", "password": GOOD_PW},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertIn("user", data)
        self.assertFalse(data["mfa_required"])

    def test_login_unverified_returns_email_not_verified(self):
        _create_user(verified=False)
        resp = self.client.post(
            f"{API}auth/login/",
            {"email": "test@example.com", "password": GOOD_PW},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "EMAIL_NOT_VERIFIED")

    def test_login_wrong_password_increments_failed_counter(self):
        _create_user()
        self.client.post(
            f"{API}auth/login/",
            {"email": "test@example.com", "password": "WrongPassword1"},
            content_type="application/json",
        )
        self.assertEqual(FailedLoginAttempt.objects.filter(email="test@example.com").count(), 1)

    def test_login_10th_failure_locks_account(self):
        _create_user()
        for _ in range(10):
            record_failed_login("test@example.com")
        self.assertTrue(is_locked("test@example.com"))
        resp = self.client.post(
            f"{API}auth/login/",
            {"email": "test@example.com", "password": GOOD_PW},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 423)
        self.assertEqual(resp.json()["error"]["code"], "ACCOUNT_LOCKED")

    def test_login_after_lockout_expires_succeeds(self):
        _create_user()
        cutoff = timezone.now() - timedelta(minutes=settings.AUTH_LOCKOUT_WINDOW_MINUTES + 1)
        for _ in range(10):
            attempt = FailedLoginAttempt.objects.create(email="test@example.com")
            # auto_now_add ignores passed values, so update directly
            FailedLoginAttempt.objects.filter(pk=attempt.pk).update(occurred_at=cutoff)
        self.assertFalse(is_locked("test@example.com"))


# =========================================================================
# Refresh / Reuse detection
# =========================================================================
class RefreshTests(TestCase):

    def test_refresh_rotates_token(self):
        user = _create_user()
        pair = issue_token_pair(user)
        resp = self.client.post(
            f"{API}auth/refresh/",
            {"refresh": pair["refresh"]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        new_data = resp.json()["data"]
        self.assertNotEqual(new_data["refresh"], pair["refresh"])
        self.assertIn("access", new_data)

    def test_refresh_reuse_revokes_family(self):
        user = _create_user()
        pair = issue_token_pair(user)
        old_refresh = pair["refresh"]
        # Legitimate rotation.
        self.client.post(
            f"{API}auth/refresh/",
            {"refresh": old_refresh},
            content_type="application/json",
        )
        # Reuse the OLD refresh.
        resp2 = self.client.post(
            f"{API}auth/refresh/",
            {"refresh": old_refresh},
            content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 401)
        self.assertIn("reuse", resp2.json()["error"]["message"].lower())
        # Family is revoked.
        family = RefreshTokenFamily.objects.first()
        self.assertTrue(family.is_revoked)


# =========================================================================
# Logout
# =========================================================================
class LogoutTests(TestCase):

    def test_logout_revokes_family(self):
        user = _create_user()
        pair = issue_token_pair(user)
        resp = self.client.post(
            f"{API}auth/logout/",
            {"refresh": pair["refresh"]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        family = RefreshTokenFamily.objects.first()
        self.assertTrue(family.is_revoked)


# =========================================================================
# Password reset
# =========================================================================
class PasswordResetTests(TestCase):

    def test_password_reset_does_not_leak_existence(self):
        resp = self.client.post(
            f"{API}auth/password/reset/",
            {"email": "nobody@example.com"},
            content_type="application/json",
        )
        # Always 200, even for unknown email.
        self.assertEqual(resp.status_code, 200)

    def test_password_reset_full_flow(self):
        user = _create_user()
        # Request reset.
        self.client.post(
            f"{API}auth/password/reset/",
            {"email": "test@example.com"},
            content_type="application/json",
        )
        self.assertEqual(len(mail.outbox), 1)
        # We can't parse the raw token from the email in tests, so issue manually:
        _, raw = PasswordResetToken.issue(user)
        new_pw = "BrandNewPass999!"
        resp = self.client.post(
            f"{API}auth/password/reset/confirm/",
            {"token": raw, "password": new_pw},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("access", data)
        # Old password no longer works.
        user.refresh_from_db()
        self.assertTrue(user.check_password(new_pw))
        self.assertFalse(user.check_password(GOOD_PW))

    @override_settings(AUTH_PASSWORD_VALIDATORS=[
        {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
        {"NAME": "apps.users.validators.LettersAndDigitsValidator"},
    ])
    def test_password_policy_rejects_no_digits(self):
        user = _create_user()
        _, raw = PasswordResetToken.issue(user)
        resp = self.client.post(
            f"{API}auth/password/reset/confirm/",
            {"token": raw, "password": NO_DIGIT_PW},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "PASSWORD_WEAK")


# =========================================================================
# Me
# =========================================================================
class MeTests(TestCase):

    def test_me_requires_auth(self):
        resp = self.client.get(f"{API}users/me/")
        self.assertEqual(resp.status_code, 401)

    def test_me_returns_user_data(self):
        user = _create_user()
        pair = issue_token_pair(user)
        resp = self.client.get(
            f"{API}users/me/",
            HTTP_AUTHORIZATION=f"Bearer {pair['access']}",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["email"], "test@example.com")
        self.assertEqual(data["display_name"], "Tester")


# =========================================================================
# AuthEvent audit
# =========================================================================
class AuthEventTests(TestCase):

    def test_login_records_auth_event(self):
        _create_user()
        self.client.post(
            f"{API}auth/login/",
            {"email": "test@example.com", "password": GOOD_PW},
            content_type="application/json",
        )
        self.assertTrue(AuditLog.objects.filter(event_type="auth.login_ok").exists())

    def test_failed_login_records_auth_event(self):
        _create_user()
        self.client.post(
            f"{API}auth/login/",
            {"email": "test@example.com", "password": "wrong"},
            content_type="application/json",
        )
        self.assertTrue(AuditLog.objects.filter(event_type="auth.login_fail").exists())


# =========================================================================
# Validators
# =========================================================================
class LettersAndDigitsValidatorTest(TestCase):

    def test_accept_mixed(self):
        from apps.users.validators import LettersAndDigitsValidator
        v = LettersAndDigitsValidator()
        v.validate("Hello12345!")  # should not raise

    def test_reject_digits_only(self):
        from django.core.exceptions import ValidationError

        from apps.users.validators import LettersAndDigitsValidator
        v = LettersAndDigitsValidator()
        with self.assertRaises(ValidationError):
            v.validate("123456789012")

    def test_reject_letters_only(self):
        from django.core.exceptions import ValidationError

        from apps.users.validators import LettersAndDigitsValidator
        v = LettersAndDigitsValidator()
        with self.assertRaises(ValidationError):
            v.validate("abcdefghijkl")
