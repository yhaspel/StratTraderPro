# Milestone 02 — MFA & User Profile

> **Week:** 2
> **Duration:** 5 working days
> **Depends on:** M01 (Auth Foundation)
> **Unlocks:** M03 (Strategies) and all broker-touching milestones (MFA is **required** before broker endpoints).

## 1. Purpose

Add TOTP-based MFA (Google Authenticator / Authy / 1Password / Bitwarden compatible), backup codes, and user profile management. Enforce MFA as a hard gate on any endpoint that touches brokers, risk config, strategies, or webhooks. Round out the profile surface (display name, timezone, language, notification prefs).

## 2. In Scope

- TOTP enrollment (QR code + manual secret), verification, disable.
- 10 single-use backup codes generated at enrollment; regenerable.
- MFA verification step on login for enrolled users.
- MFA enforcement middleware applied to all `/api/v1/brokers/*`, `/api/v1/orders/*`, `/api/v1/risk/*`, `/api/v1/strategies/*` routes.
- Profile: display_name, timezone (IANA), language (currently `en` only), default broker (placeholder), notification_email preference.
- Password change (authenticated, re-prompt current password).
- Sessions page: list active refresh-token families with device/UA hint; revoke one or revoke all.
- Angular: MFA setup wizard, MFA challenge on login, profile page, sessions page.

## 3. Out of Scope

- SMS or email-based 2FA (not recommended; TOTP only).
- WebAuthn / passkeys (post-MVP).
- Avatar upload (post-MVP).
- Multi-language UI (language field wired but only `en` available).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-02-1 | Authenticated user can enroll MFA: sees QR + secret, enters TOTP code, enrollment confirmed, 10 backup codes displayed once. |
| AC-02-2 | After enrollment, login returns `{ mfa_required: true, mfa_token }` instead of access+refresh. User submits TOTP code against `/auth/mfa/verify/` to receive full tokens. |
| AC-02-3 | Backup codes work exactly once each; consuming one marks it used. |
| AC-02-4 | Regenerating backup codes invalidates old set. |
| AC-02-5 | Disabling MFA requires current password + a current TOTP code. |
| AC-02-6 | Calling `/api/v1/brokers/` without MFA returns 403 `MFA_REQUIRED`. |
| AC-02-7 | User can update display_name, timezone (validated IANA), language; changes reflect in subsequent API responses and email templates. |
| AC-02-8 | Password change requires current password; success revokes all refresh-token families except the current. |
| AC-02-9 | Sessions page lists active families with "last used", "created", "IP (masked)", "user agent summary". Revoke-one works within 5s. |
| AC-02-10 | "Revoke all other sessions" button signs out every session except the current one. |
| AC-02-11 | TOTP time-window tolerates ±1 step (30s) to handle clock skew. |
| AC-02-12 | All MFA secrets stored encrypted at rest (Fernet with platform KEK). |

## 5. Definition of Done

Baseline DoD applies, plus:

- MFA enforcement middleware has a unit test per protected route path pattern.
- Backup codes never logged or emailed in plaintext after display.
- `AuthEvent` includes `MFA_ENROLLED`, `MFA_DISABLED`, `MFA_CHALLENGE_OK`, `MFA_CHALLENGE_FAIL`, `BACKUP_CODE_USED`.
- Recovery runbook `docs/runbooks/user-lost-mfa.md` committed with exact support steps.
- A/11y: QR has a text-equivalent; secret is copy-able; inputs have labels.

## 6. Implementation Tasks

### 6.1 Backend — MFA (`apps/users/mfa/`)

Models:
- `MFADevice(user, secret_encrypted, verified, enrolled_at)` — one per user.
- `BackupCode(user, code_hash, used_at)` — 10 per user.

Endpoints:
```
POST /api/v1/auth/mfa/enroll/         → { qr_png_b64, secret_b32 }
POST /api/v1/auth/mfa/enroll/confirm/ { code } → { backup_codes[] }
POST /api/v1/auth/mfa/verify/         { mfa_token, code } → { access, refresh }
POST /api/v1/auth/mfa/disable/        { current_password, code }
POST /api/v1/auth/mfa/backup-codes/regenerate/ { code } → { backup_codes[] }
```

Login flow (`LoginView` modified):
1. Validate email + password as before.
2. If `user.mfa_enabled`: create short-lived `mfa_token` (5 min, JWT with claim `purpose=mfa`), return `{ mfa_required: true, mfa_token }`.
3. Else: return `{ access, refresh, user }` as in M01.

MFA verify view validates `mfa_token`, then TOTP or backup code.

Secret encryption uses `cryptography.fernet` with a KEK from `settings.FERNET_KEK`. The KEK itself is stored only in Railway env vars.

TOTP: `pyotp.TOTP(secret, interval=30, digits=6)`; tolerance ±1 step.

Rate limit `/mfa/verify/` to 5/min/`mfa_token` to slow brute force.

### 6.2 Backend — Profile (`apps/users/profile/`)

Model update:
```python
class UserProfile(Model):
    user = OneToOneField(User, on_delete=CASCADE, related_name='profile')
    timezone = CharField(max_length=64, default='America/New_York')  # IANA
    language = CharField(max_length=8, default='en')
    notification_email = BooleanField(default=True)
    default_broker_id = UUIDField(null=True)   # FK populated in M04
    terms_version_accepted = CharField(max_length=32, null=True)
    created_at = DateTimeField(auto_now_add=True)
```

Endpoints:
```
GET   /api/v1/users/me/                 → user + profile
PATCH /api/v1/users/me/                 → update profile fields
POST  /api/v1/users/me/password/        → change password
GET   /api/v1/users/me/sessions/        → list refresh families
POST  /api/v1/users/me/sessions/revoke/ { family_id? | all=true }
```

`zoneinfo.available_timezones()` validates `timezone` input.

### 6.3 Backend — MFA enforcement middleware

Apply at DRF permission class level: `IsAuthenticatedAndMFAEnforced`.
```python
class IsAuthenticatedAndMFAEnforced(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated: return False
        if not request.user.mfa_enabled and view.mfa_required:
            self.message = "MFA_REQUIRED"
            return False
        return True
```

Views opt in via `mfa_required = True` class attribute (defaults to False). Broker/orders/risk/strategy viewsets set this True.

Auto-coverage test: iterate over URL patterns, assert that any path under protected prefixes has MFA enforcement.

### 6.4 Frontend — MFA setup wizard

Route: `/settings/security/mfa/setup`. Steps:

1. Intro: "Protect your trading account with MFA."
2. QR code display + manual secret + "I've added this to my authenticator" CTA.
3. Enter 6-digit code.
4. Backup codes: show, require click-to-confirm "I've saved these", provide .txt download.
5. Done.

Route: `/settings/security` — main security page with:
- MFA status (enabled/disabled) + enroll/disable CTA.
- Sessions list with revoke buttons.
- Password change form.
- Backup code regenerate CTA.

### 6.5 Frontend — login MFA challenge

Route: `/login/mfa` — displayed when login returns `mfa_required`. Form: 6-digit code input with auto-advance between digits; "Use a backup code instead" toggle.

Keep the `mfa_token` in memory (never in storage) for 5 min.

### 6.6 Frontend — profile

Route: `/settings/profile`:
- Display name
- Timezone (searchable IANA dropdown populated from `Intl.supportedValuesOf('timeZone')`)
- Language (currently single option)
- Email notifications toggle

## 7. Tech Stack Notes

- **`pyotp`** for TOTP.
- **`qrcode[pil]`** to render QR PNGs server-side; keep Base64 so the frontend doesn't need to parse `otpauth://` itself (or optionally send both).
- **`cryptography.fernet`** for secret-at-rest.
- Frontend TOTP input: custom 6-cell input component; pasted codes auto-distribute.

## 8. Data Model Changes

Migrations:
- `users.0002_mfa_and_profile` — `MFADevice`, `BackupCode`, `UserProfile`.

## 9. API Contract Changes

New paths enumerated in §6. Existing `/auth/login/` response schema gains `mfa_required` + `mfa_token` fields (nullable). Breaking change: clients must handle both shapes. Since M01 ships with only us consuming it, no deprecation needed — but we version the response under `/api/v1/`.

## 10. Test Plan

### 10.1 Unit tests

- TOTP correctness with `pyotp` known test vectors.
- Backup code hashing + single-use.
- Secret encryption/decryption roundtrip.
- `IsAuthenticatedAndMFAEnforced` returns 403 for non-MFA user on `mfa_required=True` view.
- Profile validation: rejects unknown IANA tz, rejects unsupported language, rejects overly long display_name.
- Password change revokes all other families but keeps current.

### 10.2 Integration

- Full login-with-MFA flow.
- Enroll → disable → re-enroll.
- Backup-code login path.
- Concurrent 401+refresh while MFA is in progress behaves correctly.
- Sessions list accurately reflects created/revoked.

### 10.3 E2E (Playwright)

- Enroll MFA via UI, use backup code.
- Login with Google-Authenticator-style pasted 6-digit code.
- Disable MFA; broker page denies action before enrollment.
- Revoke one session; the revoked session's next request redirects to login.

### 10.4 Load / Security tests

- Brute-force MFA verify: 50 wrong codes return 429 well before success chance reaches 1%.
- Clock skew test: ±30s still accepts.
- OWASP ASVS 2.8 (TOTP): confirmed.

## 11. Security Considerations

- TOTP secrets are encrypted at rest with a key that only lives in env. Key rotation procedure documented in runbook.
- Backup codes hashed with SHA-256 + salt; original displayed exactly once.
- MFA cannot be disabled without both password and TOTP — prevents cookie-theft from turning into account takeover.
- When admin support disables MFA for a user (recovery), the action is audit-logged and user receives an email.
- `mfa_token` is signed JWT with 5-min exp + `purpose=mfa`; only accepted by `/auth/mfa/verify/`.

## 12. Observability

- Prometheus: `mfa_enrollments_total`, `mfa_verifications_total{result}`, `mfa_backup_used_total`, `mfa_challenge_failures_total`.
- Alert: MFA challenge failure rate > 20% over 10 min (possible brute force).
- Sentry: capture exceptions in enrollment flow.
- Grafana panel added to Auth Health.

## 13. Translation & Localization

- All wizard copy, error messages, email subjects keyed: `mfa.*`, `profile.*`, `security.*`.
- Email sent on MFA enable/disable — translated via user's `profile.language`.
- Timezone dropdown uses locale-aware label formatting (`Intl.DateTimeFormat(locale, { timeZoneName: 'long' })`).
- Do **not** translate backup codes themselves — they are alphanumeric.
- Even though we only ship `en`, the pathway is complete: updating a user's `profile.language` changes `set_language` for subsequent responses and emails.

## 14. Documentation Deliverables

- `/docs/adr/020-totp-over-sms.md`.
- `/docs/runbooks/user-lost-mfa.md` — exact support recovery flow.
- `/docs/runbooks/mfa-kek-rotation.md`.
- User help page: "Set up two-factor authentication" in `frontend/src/assets/help/`.

## 15. Rollback Plan

- Migration `users.0002` is additive; rollback = `migrate users 0001`.
- Feature flag `MFA_ENABLED`; if disabled, `/auth/mfa/*` endpoints return 503 and login skips MFA branch.
- Support can disable MFA for any user via Django admin in emergency; action is audit-logged.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Users lose authenticator device + backup codes | Med | High | Clear recovery runbook; support can disable MFA after identity check. |
| Clock drift rejects valid codes | Med | Low | ±1 step tolerance; document in help page. |
| KEK leaked → all MFA secrets compromised | Low | High | KEK rotation doc; KEK only in Railway env; envelope encryption pattern so a new KEK re-wraps without decrypting secrets. |
| Enforcement gap — a route misses `mfa_required=True` | Med | High | Auto-coverage test over URLconf. |

## 17. Exit Gate Checklist

- [ ] AC-02-1 … AC-02-12 pass.
- [ ] 0 broker/risk/orders/strategies routes callable without MFA (verified by automated scan).
- [ ] Runbooks for lost MFA and KEK rotation committed.
- [ ] Auth Health dashboard updated with MFA panels.
- [ ] Changelog entry.
- [ ] Tag `v0.2.0-mfa`.

Proceed to **M03 Strategies & Webhook Config**.
