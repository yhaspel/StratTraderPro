"""M02 — MFA, profile, sessions, password change tests."""
from __future__ import annotations

import pyotp
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.users.mfa import (
    decrypt_secret,
    encrypt_secret,
    generate_backup_codes,
    generate_totp_secret,
    verify_totp,
)
from apps.users.models import (
    BackupCode,
    MFADevice,
    RefreshTokenFamily,
    UserProfile,
)
from apps.users.models import (
    User as _UModel,  # noqa: F401 (mypy hint only)
)
from apps.users.services import issue_token_pair

User = get_user_model()
GOOD_PW = "SecurePass123!"
NEW_PW = "BrandNewPass999!"
API = "/api/v1/"


def _create_user(email="trader@example.com", verified=True, password=GOOD_PW):
    user = User.objects.create_user(email=email, password=password, display_name="Trader")
    if verified:
        user.is_verified = True
        user.save(update_fields=["is_verified"])
    return user


def _enroll_mfa(user, *, secret=None) -> str:
    """Helper: bypass HTTP and just stamp a verified MFADevice. Returns secret."""
    secret = secret or generate_totp_secret()
    MFADevice.objects.create(
        user=user, secret_encrypted=encrypt_secret(secret), verified=True,
    )
    return secret


def _auth(user) -> dict:
    pair = issue_token_pair(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {pair['access']}"}


# =========================================================================
# Encryption + TOTP unit
# =========================================================================
class FernetRoundtripTests(TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        secret = generate_totp_secret()
        blob = encrypt_secret(secret)
        self.assertNotIn(secret.encode("ascii"), blob)
        self.assertEqual(decrypt_secret(blob), secret)


class TOTPVerifyTests(TestCase):
    def test_verify_correct_code(self):
        secret = generate_totp_secret()
        code = pyotp.TOTP(secret, interval=30, digits=6).now()
        self.assertTrue(verify_totp(secret, code))

    def test_verify_wrong_code_rejected(self):
        secret = generate_totp_secret()
        self.assertFalse(verify_totp(secret, "000000"))

    def test_verify_rejects_non_digits(self):
        secret = generate_totp_secret()
        self.assertFalse(verify_totp(secret, "abc123"))

    def test_verify_strips_whitespace(self):
        secret = generate_totp_secret()
        code = pyotp.TOTP(secret, interval=30, digits=6).now()
        self.assertTrue(verify_totp(secret, f" {code[:3]} {code[3:]}"))


class BackupCodeTests(TestCase):
    def test_generate_creates_n_unused(self):
        user = _create_user()
        codes = generate_backup_codes(user, count=5)
        self.assertEqual(len(codes), 5)
        self.assertEqual(BackupCode.objects.filter(user=user, used_at__isnull=True).count(), 5)

    def test_regenerate_wipes_old(self):
        user = _create_user()
        generate_backup_codes(user, count=3)
        first_ids = set(BackupCode.objects.filter(user=user).values_list("id", flat=True))
        generate_backup_codes(user, count=3)
        second_ids = set(BackupCode.objects.filter(user=user).values_list("id", flat=True))
        self.assertFalse(first_ids & second_ids)

    def test_consume_marks_used_once(self):
        from apps.users.mfa import consume_backup_code
        user = _create_user()
        codes = generate_backup_codes(user, count=2)
        # First consume succeeds
        self.assertTrue(consume_backup_code(user, codes[0]))
        # Second consume of same code fails
        self.assertFalse(consume_backup_code(user, codes[0]))
        # Other codes still work
        self.assertTrue(consume_backup_code(user, codes[1]))

    def test_consume_normalizes_dashes(self):
        from apps.users.mfa import consume_backup_code
        user = _create_user()
        codes = generate_backup_codes(user, count=1)
        # Code already includes a dash; user can also paste without
        self.assertTrue(consume_backup_code(user, codes[0].replace("-", "")))


# =========================================================================
# MFA enroll + confirm (HTTP)
# =========================================================================
class MFAEnrollTests(TestCase):

    def test_enroll_returns_qr_and_secret(self):
        user = _create_user()
        resp = self.client.post(f"{API}auth/mfa/enroll/", **_auth(user))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("qr_png_b64", data)
        self.assertIn("secret_b32", data)
        self.assertTrue(data["secret_b32"].isalnum())

    def test_enroll_confirm_with_valid_code(self):
        user = _create_user()
        resp = self.client.post(f"{API}auth/mfa/enroll/", **_auth(user))
        secret = resp.json()["data"]["secret_b32"]
        code = pyotp.TOTP(secret, interval=30, digits=6).now()
        resp2 = self.client.post(
            f"{API}auth/mfa/enroll/confirm/",
            {"code": code},
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp2.status_code, 200)
        backup = resp2.json()["data"]["backup_codes"]
        self.assertEqual(len(backup), 10)
        user.refresh_from_db()
        self.assertTrue(user.mfa_enabled)
        # AuthEvent logged.
        self.assertTrue(AuditLog.objects.filter(event_type="auth.mfa_enrolled").exists())
        # Email sent.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Two-factor", mail.outbox[0].subject)

    def test_enroll_confirm_wrong_code_rejected(self):
        user = _create_user()
        self.client.post(f"{API}auth/mfa/enroll/", **_auth(user))
        resp = self.client.post(
            f"{API}auth/mfa/enroll/confirm/",
            {"code": "000000"},
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "MFA_CODE_INVALID")
        user.refresh_from_db()
        self.assertFalse(user.mfa_enabled)

    def test_enroll_when_already_enabled_rejected(self):
        user = _create_user()
        _enroll_mfa(user)
        resp = self.client.post(f"{API}auth/mfa/enroll/", **_auth(user))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "MFA_ALREADY_ENABLED")


# =========================================================================
# Login → MFA challenge flow
# =========================================================================
class LoginMFAFlowTests(TestCase):

    def test_login_mfa_user_returns_mfa_token(self):
        user = _create_user()
        _enroll_mfa(user)
        resp = self.client.post(
            f"{API}auth/login/",
            {"email": user.email, "password": GOOD_PW},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertTrue(data["mfa_required"])
        self.assertIn("mfa_token", data)
        # No tokens yet.
        self.assertNotIn("access", data)

    def test_login_non_mfa_user_returns_token_pair(self):
        _create_user()
        resp = self.client.post(
            f"{API}auth/login/",
            {"email": "trader@example.com", "password": GOOD_PW},
            content_type="application/json",
        )
        data = resp.json()["data"]
        self.assertFalse(data["mfa_required"])
        self.assertIn("access", data)

    def test_mfa_verify_with_totp_returns_tokens(self):
        user = _create_user()
        secret = _enroll_mfa(user)
        login = self.client.post(
            f"{API}auth/login/",
            {"email": user.email, "password": GOOD_PW},
            content_type="application/json",
        )
        mfa_token = login.json()["data"]["mfa_token"]
        code = pyotp.TOTP(secret, interval=30, digits=6).now()
        resp = self.client.post(
            f"{API}auth/mfa/verify/",
            {"mfa_token": mfa_token, "code": code},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertTrue(AuditLog.objects.filter(event_type="auth.mfa_challenge_ok").exists())

    def test_mfa_verify_with_backup_code(self):
        user = _create_user()
        _enroll_mfa(user)
        codes = generate_backup_codes(user, count=3)
        login = self.client.post(
            f"{API}auth/login/",
            {"email": user.email, "password": GOOD_PW},
            content_type="application/json",
        )
        mfa_token = login.json()["data"]["mfa_token"]
        resp = self.client.post(
            f"{API}auth/mfa/verify/",
            {"mfa_token": mfa_token, "code": codes[0], "is_backup_code": True},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        # Backup code now used.
        self.assertEqual(BackupCode.objects.filter(user=user, used_at__isnull=False).count(), 1)
        self.assertTrue(AuditLog.objects.filter(event_type="auth.backup_code_used").exists())

    def test_mfa_verify_wrong_code_rejected(self):
        user = _create_user()
        _enroll_mfa(user)
        login = self.client.post(
            f"{API}auth/login/",
            {"email": user.email, "password": GOOD_PW},
            content_type="application/json",
        )
        mfa_token = login.json()["data"]["mfa_token"]
        resp = self.client.post(
            f"{API}auth/mfa/verify/",
            {"mfa_token": mfa_token, "code": "000000"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "MFA_CODE_INVALID")
        self.assertTrue(AuditLog.objects.filter(event_type="auth.mfa_challenge_fail").exists())

    def test_mfa_verify_with_invalid_token(self):
        user = _create_user()
        _enroll_mfa(user)
        resp = self.client.post(
            f"{API}auth/mfa/verify/",
            {"mfa_token": "not-a-real-token", "code": "123456"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "TOKEN_INVALID")

    @override_settings(RATELIMIT_ENABLE=True)
    def test_mfa_verify_rate_limit_keyer_does_not_crash(self):
        """Regression test for prod 500 caused by `request.data` access in the
        ratelimit lambda — that's a DRF-only attribute, but django-ratelimit
        wraps the view BEFORE DRF, so it sees a raw Django request without
        `.data` and crashes.

        With key='ip' (the fix), this regression doesn't recur and the view
        returns 401 normally regardless of rate-limit state.
        """
        user = _create_user()
        _enroll_mfa(user)
        resp = self.client.post(
            f"{API}auth/mfa/verify/",
            {"mfa_token": "garbage-token", "code": "000000"},
            content_type="application/json",
        )
        # Pre-fix: 500. Post-fix: 401 with structured error.
        self.assertNotEqual(resp.status_code, 500)
        self.assertEqual(resp.status_code, 401)
        self.assertIn(resp.json()["error"]["code"], {"TOKEN_INVALID", "RATE_LIMITED"})


# =========================================================================
# MFA disable + regenerate
# =========================================================================
class MFADisableTests(TestCase):

    def test_disable_requires_password_and_code(self):
        user = _create_user()
        secret = _enroll_mfa(user)
        code = pyotp.TOTP(secret, interval=30, digits=6).now()

        # Wrong password
        bad = self.client.post(
            f"{API}auth/mfa/disable/",
            {"current_password": "nope", "code": code},
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(bad.status_code, 401)

        # Correct password + correct code → 200
        ok_resp = self.client.post(
            f"{API}auth/mfa/disable/",
            {"current_password": GOOD_PW, "code": code},
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(ok_resp.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.mfa_enabled)
        # Email sent.
        self.assertTrue(any("disabled" in m.subject.lower() for m in mail.outbox))

    def test_disable_with_wrong_code(self):
        user = _create_user()
        _enroll_mfa(user)
        resp = self.client.post(
            f"{API}auth/mfa/disable/",
            {"current_password": GOOD_PW, "code": "000000"},
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "MFA_CODE_INVALID")


class MFARegenerateBackupTests(TestCase):

    def test_regenerate_replaces_codes(self):
        user = _create_user()
        secret = _enroll_mfa(user)
        old = generate_backup_codes(user)
        old_ids = set(BackupCode.objects.filter(user=user).values_list("id", flat=True))

        code = pyotp.TOTP(secret, interval=30, digits=6).now()
        resp = self.client.post(
            f"{API}auth/mfa/backup-codes/regenerate/",
            {"current_password": GOOD_PW, "code": code},
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 200)
        new = resp.json()["data"]["backup_codes"]
        self.assertEqual(len(new), 10)
        # Old codes wiped.
        self.assertFalse(set(old) & set(new))
        new_ids = set(BackupCode.objects.filter(user=user).values_list("id", flat=True))
        self.assertFalse(old_ids & new_ids)


# =========================================================================
# Permission class
# =========================================================================
class IsAuthenticatedAndMFAEnforcedTests(TestCase):

    def test_non_mfa_user_blocked_on_protected_view(self):
        user = _create_user()
        resp = self.client.get(f"{API}brokers/ping/", **_auth(user))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "MFA_REQUIRED")

    def test_mfa_user_allowed(self):
        user = _create_user()
        _enroll_mfa(user)
        resp = self.client.get(f"{API}brokers/ping/", **_auth(user))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["app"], "brokers")

    def test_unauthenticated_returns_401(self):
        resp = self.client.get(f"{API}brokers/ping/")
        self.assertEqual(resp.status_code, 401)

    def test_all_protected_prefixes_have_mfa_gate(self):
        """Auto-coverage: no /brokers /orders /risk /strategies endpoint
        accepts a non-MFA user. Future viewsets must opt-in too.

        ``strategies`` was upgraded from a ping stub to a real viewset in
        M03 — list endpoint at ``/strategies/`` (no /ping/ suffix).
        """
        user = _create_user()
        scaffold_paths = (
            ("brokers", "ping/"),
            ("orders", "ping/"),
            ("risk", "ping/"),
            ("strategies", ""),  # M03 — real viewset, list at the prefix
        )
        for prefix, suffix in scaffold_paths:
            with self.subTest(path=prefix):
                resp = self.client.get(f"{API}{prefix}/{suffix}", **_auth(user))
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.json()["error"]["code"], "MFA_REQUIRED")


# =========================================================================
# Profile + sessions + password change
# =========================================================================
class ProfileTests(TestCase):

    def test_me_returns_profile_block(self):
        user = _create_user()
        resp = self.client.get(f"{API}users/me/", **_auth(user))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("profile", data)
        self.assertIn("timezone", data["profile"])

    def test_update_profile_fields(self):
        user = _create_user()
        resp = self.client.patch(
            f"{API}users/me/update/",
            {
                "display_name": "New Name",
                "timezone": "America/Los_Angeles",
                "language": "en",
                "notification_email": False,
            },
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.display_name, "New Name")
        prof = UserProfile.objects.get(user=user)
        self.assertEqual(prof.timezone, "America/Los_Angeles")
        self.assertFalse(prof.notification_email)

    def test_update_rejects_unknown_timezone(self):
        user = _create_user()
        resp = self.client.patch(
            f"{API}users/me/update/",
            {"timezone": "Mars/Olympus_Mons"},
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_update_rejects_unsupported_language(self):
        user = _create_user()
        resp = self.client.patch(
            f"{API}users/me/update/",
            {"language": "klingon"},
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 400)


class PasswordChangeTests(TestCase):

    def test_change_password_revokes_other_families(self):
        user = _create_user()
        # First family — not the current one (created for side effect: a second
        # RefreshTokenFamily row that should be revoked on password change).
        issue_token_pair(user)
        # Current family
        current = issue_token_pair(user)
        resp = self.client.post(
            f"{API}users/me/password/",
            {"current_password": GOOD_PW, "new_password": NEW_PW},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {current['access']}",
        )
        self.assertEqual(resp.status_code, 200)
        # Other families revoked
        revoked = RefreshTokenFamily.objects.filter(
            user=user, revoked_at__isnull=False, revoke_reason="password_changed",
        ).count()
        self.assertGreaterEqual(revoked, 1)
        # Current family still alive (best-effort — current_jti claim driven)
        # The exact survivor depends on access token's family_id claim;
        # at minimum, password_changed event must be logged.
        self.assertTrue(AuditLog.objects.filter(event_type="auth.password_changed").exists())
        # Old password no longer authenticates.
        user.refresh_from_db()
        self.assertTrue(user.check_password(NEW_PW))
        self.assertFalse(user.check_password(GOOD_PW))

    def test_wrong_current_password_rejected(self):
        user = _create_user()
        resp = self.client.post(
            f"{API}users/me/password/",
            {"current_password": "nope", "new_password": NEW_PW},
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 401)

    def test_weak_new_password_rejected(self):
        user = _create_user()
        resp = self.client.post(
            f"{API}users/me/password/",
            {"current_password": GOOD_PW, "new_password": "short"},
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "PASSWORD_WEAK")


class SessionsTests(TestCase):

    def test_list_sessions(self):
        user = _create_user()
        # Two families
        issue_token_pair(user)
        current = issue_token_pair(user)
        current_family = RefreshTokenFamily.objects.get(current_jti=_jti(current["refresh"]))
        resp = self.client.get(
            f"{API}users/me/sessions/",
            HTTP_AUTHORIZATION=f"Bearer {current['access']}",
        )
        self.assertEqual(resp.status_code, 200)
        sessions = resp.json()["data"]["sessions"]
        self.assertEqual(len(sessions), 2)
        # SEC-4: exactly one session is flagged "current", and it is the family
        # that issued this request (matched by family_id, not current_jti).
        current_flagged = [s for s in sessions if s["current"]]
        self.assertEqual(len(current_flagged), 1)
        self.assertEqual(current_flagged[0]["family_id"], str(current_family.family_id))

    def test_revoke_one_session(self):
        user = _create_user()
        target = issue_token_pair(user)
        current = issue_token_pair(user)
        target_family = RefreshTokenFamily.objects.get(current_jti=_jti(target["refresh"]))
        resp = self.client.post(
            f"{API}users/me/sessions/revoke/",
            {"family_id": str(target_family.family_id)},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {current['access']}",
        )
        self.assertEqual(resp.status_code, 200)
        target_family.refresh_from_db()
        self.assertTrue(target_family.is_revoked)

    def test_revoke_all_other_sessions(self):
        # SEC-4: revoke-all-other must revoke every family EXCEPT the caller's
        # own, and the caller's session must keep working. Families A/B/C.
        user = _create_user()
        fam_a = RefreshTokenFamily.objects.get(current_jti=_jti(issue_token_pair(user)["refresh"]))
        fam_b = RefreshTokenFamily.objects.get(current_jti=_jti(issue_token_pair(user)["refresh"]))
        current = issue_token_pair(user)
        fam_current = RefreshTokenFamily.objects.get(current_jti=_jti(current["refresh"]))

        resp = self.client.post(
            f"{API}users/me/sessions/revoke/",
            {"all": True},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {current['access']}",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["revoked"], 2)

        for fam in (fam_a, fam_b):
            fam.refresh_from_db()
            self.assertTrue(fam.is_revoked)
        fam_current.refresh_from_db()
        self.assertFalse(fam_current.is_revoked)  # caller's own family survives

    def test_password_change_preserves_current_session(self):
        # SEC-4: password change revokes other families but keeps the caller's.
        user = _create_user()
        fam_other = RefreshTokenFamily.objects.get(current_jti=_jti(issue_token_pair(user)["refresh"]))
        current = issue_token_pair(user)
        fam_current = RefreshTokenFamily.objects.get(current_jti=_jti(current["refresh"]))

        resp = self.client.post(
            f"{API}users/me/password/",
            {"current_password": GOOD_PW, "new_password": NEW_PW},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {current['access']}",
        )
        self.assertEqual(resp.status_code, 200)
        fam_other.refresh_from_db()
        fam_current.refresh_from_db()
        self.assertTrue(fam_other.is_revoked)
        self.assertFalse(fam_current.is_revoked)


class MfaStepUpThrottleTests(TestCase):
    """C3 — verify_mfa_code brute-force throttle (all three step-up callers use it)."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_throttled_after_max_failures_and_audits(self):
        from apps.users.mfa import verify_mfa_code
        user = _create_user()
        _enroll_mfa(user)
        # 5 bad codes are checked and fail; the 5th crosses the cap and audits.
        for _ in range(5):
            self.assertFalse(verify_mfa_code(user, "000000"))
        self.assertTrue(
            AuditLog.objects.filter(event_type="security.mfa_stepup_throttled").exists()
        )

    def test_sixth_attempt_rejected_pre_check(self):
        from apps.users.mfa import verify_mfa_code
        user = _create_user()
        secret = _enroll_mfa(user)
        for _ in range(5):
            verify_mfa_code(user, "000000")
        # Correct code is refused once the cap is hit (pre-verification rejection).
        good = pyotp.TOTP(secret, interval=30, digits=6).now()
        self.assertFalse(verify_mfa_code(user, good))

    def test_good_code_before_cap_resets_counter(self):
        from apps.users.mfa import verify_mfa_code
        user = _create_user()
        secret = _enroll_mfa(user)
        for _ in range(4):
            self.assertFalse(verify_mfa_code(user, "000000"))
        good = pyotp.TOTP(secret, interval=30, digits=6).now()
        self.assertTrue(verify_mfa_code(user, good))  # resets the counter
        # Counter reset: a fresh failure does not trip the throttle.
        self.assertFalse(verify_mfa_code(user, "000000"))
        self.assertFalse(
            AuditLog.objects.filter(event_type="security.mfa_stepup_throttled").exists()
        )


def _jti(refresh: str) -> str:
    """Decode a refresh JWT and return the ``jti`` claim. Test helper."""
    from rest_framework_simplejwt.tokens import RefreshToken
    return str(RefreshToken(refresh)["jti"])
