"""M01 Auth Foundation — unit + integration tests.

Tests run against SQLite in-memory with MD5 hasher (fast) and locmem email
backend. Rate-limiting is disabled by default (test settings).
"""
from __future__ import annotations

from datetime import timedelta
from smtplib import SMTPException
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.users.metrics import EMAIL_SEND_TOTAL
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
    send_verification_email,
)

User = get_user_model()


def _counter_value(template: str, result: str) -> float:
    """Read a live prometheus_client Counter child (they are process-global, so
    tests must assert on a DELTA, never on an absolute value)."""
    return EMAIL_SEND_TOTAL.labels(template=template, result=result)._value.get()

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
        # P1-4: refresh is delivered as an HttpOnly cookie, never in the body.
        self.assertNotIn("refresh", data)
        self.assertIn("stp_refresh", resp.cookies)
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
        self.assertNotIn("refresh", data)  # P1-4 — cookie, not body
        self.assertIn("user", data)
        self.assertFalse(data["mfa_required"])
        cookie = resp.cookies["stp_refresh"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")

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
        # Failures from the test client's own IP (127.0.0.1) so the per-IP lock
        # applies to the subsequent login POST from the same IP (P2-4).
        for _ in range(10):
            record_failed_login("test@example.com", ip="127.0.0.1")
        self.assertTrue(is_locked("test@example.com", "127.0.0.1"))
        resp = self.client.post(
            f"{API}auth/login/",
            {"email": "test@example.com", "password": GOOD_PW},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 423)
        self.assertEqual(resp.json()["error"]["code"], "ACCOUNT_LOCKED")

    def test_remote_attacker_cannot_lock_victim_from_one_ip_alone(self):
        # P2-4: an attacker flooding failures from their IP locks only that IP;
        # the victim logging in from a different IP is unaffected.
        _create_user()
        for _ in range(10):
            record_failed_login("test@example.com", ip="6.6.6.6")
        self.assertTrue(is_locked("test@example.com", "6.6.6.6"))   # attacker's IP locked
        self.assertFalse(is_locked("test@example.com", "1.2.3.4"))  # victim's IP is not
        resp = self.client.post(
            f"{API}auth/login/",
            {"email": "test@example.com", "password": GOOD_PW},
            content_type="application/json",
            REMOTE_ADDR="1.2.3.4",
        )
        self.assertEqual(resp.status_code, 200)  # victim logs in fine

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
        # P1-4: the rotated refresh comes back as a cookie, not in the body.
        self.assertNotIn("refresh", new_data)
        self.assertNotEqual(resp.cookies["stp_refresh"].value, pair["refresh"])
        self.assertIn("access", new_data)

    def test_refresh_via_cookie_only_rotates(self):
        # P1-4: a browser never sends a body — the HttpOnly cookie carries it.
        _create_user()
        login = self.client.post(
            f"{API}auth/login/",
            {"email": "test@example.com", "password": GOOD_PW},
            content_type="application/json",
        )
        first = login.cookies["stp_refresh"].value
        # No body: the persisted cookie is used by the test client automatically.
        resp = self.client.post(f"{API}auth/refresh/", content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertNotEqual(resp.cookies["stp_refresh"].value, first)

    def test_refresh_missing_token_401(self):
        resp = self.client.post(f"{API}auth/refresh/", content_type="application/json")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "TOKEN_INVALID")

    def test_refresh_reuse_revokes_family(self):
        user = _create_user()
        pair = issue_token_pair(user)
        old_refresh = pair["refresh"]
        # Rotate TWICE so `old_refresh` is two steps behind (past the P2-8
        # one-step grace) — then reusing it is genuine reuse.
        r1 = self.client.post(
            f"{API}auth/refresh/", {"refresh": old_refresh}, content_type="application/json",
        )
        new1 = r1.cookies["stp_refresh"].value
        self.client.post(
            f"{API}auth/refresh/", {"refresh": new1}, content_type="application/json",
        )
        resp = self.client.post(
            f"{API}auth/refresh/", {"refresh": old_refresh}, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertIn("reuse", resp.json()["error"]["message"].lower())
        self.assertTrue(RefreshTokenFamily.objects.first().is_revoked)

    def test_one_step_grace_does_not_revoke_family(self):
        # P2-8: presenting the JUST-rotated token again (a double-submit racing
        # the rotation) is tolerated once — a new pair is issued and the family
        # is NOT revoked.
        user = _create_user()
        pair = issue_token_pair(user)
        old_refresh = pair["refresh"]
        self.client.post(
            f"{API}auth/refresh/", {"refresh": old_refresh}, content_type="application/json",
        )
        grace = self.client.post(
            f"{API}auth/refresh/", {"refresh": old_refresh}, content_type="application/json",
        )
        self.assertEqual(grace.status_code, 200)  # grace, not reuse
        self.assertFalse(RefreshTokenFamily.objects.first().is_revoked)


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

    def test_logout_clears_refresh_cookie(self):
        _create_user()
        self.client.post(
            f"{API}auth/login/",
            {"email": "test@example.com", "password": GOOD_PW},
            content_type="application/json",
        )
        resp = self.client.post(f"{API}auth/logout/", content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        # delete_cookie expires the cookie (max-age 0 / empty value).
        self.assertEqual(resp.cookies["stp_refresh"].value, "")
        self.assertTrue(RefreshTokenFamily.objects.first().is_revoked)


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


# =========================================================================
# C1 — auth rate-limit key: per-email buckets, not one global "anon"
# =========================================================================
@override_settings(RATELIMIT_ENABLE=True)
class RateLimitKeyTests(TestCase):
    """C1: each submitted email must get its own login-rate-limit bucket.

    Before the fix, ``_email_keyer`` read ``request.data`` on the raw Django
    ``HttpRequest``, raised, and collapsed every email into the single
    ``"anon"`` bucket — so five attempts on one email throttled *everyone*.
    Login rate is 5/m.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _login(self, email):
        return self.client.post(
            f"{API}auth/login/",
            {"email": email, "password": "wrong-password"},
            content_type="application/json",
        )

    def test_two_emails_get_independent_buckets(self):
        # Exhaust email A's 5/m bucket; the 6th is limited.
        for _ in range(5):
            self.assertNotEqual(self._login("alice@example.com").status_code, 429)
        self.assertEqual(self._login("alice@example.com").status_code, 429)
        # Email B is a *different* bucket — its first request is NOT limited.
        # (Under the old bug both share "anon", so B would be the 7th and 429.)
        self.assertNotEqual(self._login("bob@example.com").status_code, 429)

    def test_reset_rate_limited_per_ip_across_emails(self):
        # P2-3: cycling a fresh email each time slips past the per-email limit,
        # but the per-IP limit (10/m) still stops an email-bomb from one IP.
        last = None
        for i in range(12):
            last = self.client.post(
                f"{API}auth/password/reset/",
                {"email": f"u{i}@example.com"},
                content_type="application/json",
            )
        self.assertEqual(last.status_code, 429)

    def test_email_keyer_returns_distinct_keys(self):
        from apps.users.views import _email_keyer

        class _Req:
            def __init__(self, body):
                self.body = body

        a = _email_keyer("grp", _Req(b'{"email": "a@example.com"}'))
        b = _email_keyer("grp", _Req(b'{"email": "b@example.com"}'))
        self.assertNotEqual(a, b)
        self.assertEqual(a, "a@example.com")
        # Case-insensitive; empty/garbage body falls back to "anon" (no raise).
        self.assertEqual(_email_keyer("grp", _Req(b'{"email": "A@Example.com"}')), "a@example.com")
        self.assertEqual(_email_keyer("grp", _Req(b"")), "anon")
        self.assertEqual(_email_keyer("grp", _Req(b"not json")), "anon")


# =========================================================================
# Transactional email delivery — failures must be VISIBLE, not swallowed
#
# The provider (Resend) rejects a send whenever DEFAULT_FROM_EMAIL is still the
# `onboarding@resend.dev` sandbox sender and the recipient is not the account
# owner — exactly the production configuration that made every new-user
# verification email vanish while /register happily returned 201. The send is
# still non-fatal (the endpoint must not 500 on a provider outage), but it now
# reports: a boolean to the caller, an auth_email_send_total{result="error"}
# increment, and a real 503 out of /auth/resend-verification/.
# =========================================================================
class EmailSendFailureTests(TestCase):
    """`fail_silently=False` send() raising == provider rejected the message."""

    @staticmethod
    def _boom(*_args, **_kwargs):
        raise SMTPException("provider rejected: sandbox sender, foreign recipient")

    def test_send_verification_email_returns_false_when_provider_rejects(self):
        user = _create_user(email="reject@example.com", verified=False)
        with patch.object(EmailMultiAlternatives, "send", self._boom):
            sent = send_verification_email(user, "raw-token")
        self.assertFalse(sent)
        self.assertEqual(len(mail.outbox), 0)

    def test_send_verification_email_returns_true_on_success(self):
        user = _create_user(email="ok@example.com", verified=False)
        self.assertTrue(send_verification_email(user, "raw-token"))
        self.assertEqual(len(mail.outbox), 1)

    def test_failed_send_increments_error_counter(self):
        user = _create_user(email="counted@example.com", verified=False)
        before = _counter_value("verify_email", "error")
        with patch.object(EmailMultiAlternatives, "send", self._boom):
            send_verification_email(user, "raw-token")
        self.assertEqual(_counter_value("verify_email", "error"), before + 1)

    def test_successful_send_increments_ok_counter(self):
        user = _create_user(email="counted-ok@example.com", verified=False)
        before = _counter_value("verify_email", "ok")
        send_verification_email(user, "raw-token")
        self.assertEqual(_counter_value("verify_email", "ok"), before + 1)

    def test_register_still_201_when_email_send_fails(self):
        """A provider outage must never cost the user their account."""
        with patch.object(EmailMultiAlternatives, "send", self._boom):
            resp = self.client.post(
                f"{API}auth/register/",
                {"email": "still@example.com", "display_name": "Still", "password": GOOD_PW},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(User.objects.filter(email="still@example.com").exists())

    def test_resend_verification_reports_503_when_send_fails(self):
        """Fail-before/pass-after: this returned a lying 200 before the fix."""
        _create_user(email="unverified@example.com", verified=False)
        with patch.object(EmailMultiAlternatives, "send", self._boom):
            resp = self.client.post(
                f"{API}auth/resend-verification/",
                {"email": "unverified@example.com"},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"]["code"], "EMAIL_SEND_FAILED")

    def test_resend_verification_200_when_send_succeeds(self):
        _create_user(email="unverified2@example.com", verified=False)
        resp = self.client.post(
            f"{API}auth/resend-verification/",
            {"email": "unverified2@example.com"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_verification_unknown_email_still_200(self):
        """Enumeration guarantee holds: unknown address is indistinguishable."""
        resp = self.client.post(
            f"{API}auth/resend-verification/",
            {"email": "ghost@example.com"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_verification_already_verified_still_200(self):
        _create_user(email="done@example.com", verified=True)
        resp = self.client.post(
            f"{API}auth/resend-verification/",
            {"email": "done@example.com"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
