# Milestone 01 — Auth Foundation

> **Week:** 1
> **Duration:** 5 working days
> **Depends on:** M00 (Scoping & Setup)
> **Unlocks:** M02 (MFA) and every subsequent milestone (all downstream code runs in an authenticated context).

## 1. Purpose

Deliver a secure, complete authentication layer: registration, email verification, login, JWT access + refresh rotation, logout, password reset. MFA is explicitly deferred to M02 so this milestone remains tight. This is the only milestone that blocks every other user-facing feature.

## 2. In Scope

- `CustomUser` model replacing Django's default, keyed on email.
- Registration with email verification token.
- Login returning JWT access + refresh.
- Refresh rotation with reuse detection (revoke entire family).
- Password reset (forgot / confirm).
- Account lockout after N failed attempts.
- Argon2id password hashing.
- Rate limits on auth endpoints.
- Email sending via SMTP (Mailgun / Postmark / Resend — pick one; plan assumes Resend).
- Angular: login, register, verify-email, password-reset pages; `authFacade` + `authStore` (signal store); HTTP interceptors (JWT attach, 401 refresh, error).
- Protected-route guard; unauthenticated redirect to `/login`.
- Audit log for auth events (stub — full audit app lands in M10, here we just ensure rows are written to a minimal `AuthEvent` table that will later be folded in).

## 3. Out of Scope

- MFA / TOTP / backup codes (M02).
- OAuth / social login (post-MVP).
- Full append-only hash-chained audit log (M10).
- User profile beyond email + display name (M02).
- Admin role enforcement on views (M10).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-01-1 | A visitor can register with email + password + display name; receives a verification email within 60s. |
| AC-01-2 | Clicking the verification link marks the user verified and logs them in. |
| AC-01-3 | An unverified user attempting to log in receives a clear error with a "Resend email" CTA. |
| AC-01-4 | Successful login returns `{ access, refresh, user }`. Access token TTL 15 min, refresh 30 days. |
| AC-01-5 | Using a refresh token returns a new access + new refresh; old refresh is invalidated (rotation). |
| AC-01-6 | Re-using an already-rotated refresh token triggers **family revocation** — all tokens in that refresh family are revoked and the user forced to re-login. |
| AC-01-7 | 10 failed login attempts within 15 min lock the account for 15 min; lockout is per-email, not per-IP. |
| AC-01-8 | Password reset flow: request → email → token-gated new-password form → success → auto-login. |
| AC-01-9 | Passwords must be ≥ 12 chars, contain letters + digits, and pass Django's common-password checks; error messages localized. |
| AC-01-10 | Rate limits: register 3/min/IP, login 5/min/email + 20/min/IP, password reset 3/min/email. Breach returns 429 with Retry-After. |
| AC-01-11 | Angular guards: navigating to `/dashboard` without a token redirects to `/login?next=/dashboard`. |
| AC-01-12 | 401 response triggers the HTTP interceptor to attempt refresh; if refresh fails, user is logged out and routed to `/login`. |
| AC-01-13 | All auth strings in UI and emails go through translation (no hard-coded English). |

## 5. Definition of Done

Baseline DoD applies, plus:

- OpenAPI schema includes all auth endpoints with request/response examples.
- Frontend types for auth regenerated via `openapi-typescript`.
- At least one contract test ensures schema ↔ frontend type parity.
- No password, token, or hashed secret appears in any log (verified by test).
- Sentry release tagged `v0.1.0-auth`.
- Runbook `docs/runbooks/user-locked-out.md` exists.

## 6. Implementation Tasks

### 6.1 Backend — models (`apps/users/models.py`)

```python
class User(AbstractBaseUser, PermissionsMixin):
    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    email = EmailField(unique=True, db_index=True)
    display_name = CharField(max_length=64)
    is_active = BooleanField(default=True)
    is_verified = BooleanField(default=False)
    is_staff = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['display_name']

class EmailVerificationToken(TokenMixin): ...   # single-use, 24h TTL, one-per-user
class PasswordResetToken(TokenMixin): ...       # single-use, 1h TTL
class RefreshTokenFamily(Model): ...            # family_id, user_id, created_at, revoked_at
class FailedLoginAttempt(Model): ...            # email, ip, occurred_at — used for lockout window
class AuthEvent(Model): ...                     # user, event_type, ip, ua, ts, metadata_json — temporary precursor to AuditLog
```

`password` column inherits from `AbstractBaseUser`. Manager overrides `create_user`/`create_superuser`.

`settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher', ...]`.

### 6.2 Backend — endpoints (`apps/users/views.py`)

| Method | Path | Handler | Notes |
|--------|------|---------|-------|
| POST | `/api/v1/auth/register/` | `RegisterView` | Creates user, sends verification email, returns 201 w/ `{id,email}`. |
| POST | `/api/v1/auth/verify-email/` | `VerifyEmailView` | Body `{token}`; on success, sets `is_verified`, issues JWT pair, writes `AuthEvent`. |
| POST | `/api/v1/auth/resend-verification/` | `ResendVerificationView` | Idempotent; rate-limited. |
| POST | `/api/v1/auth/login/` | `LoginView` | Email + password; returns `{access,refresh,user}` OR 403 w/ `mfa_required=true` (field present but always false in M01). |
| POST | `/api/v1/auth/refresh/` | `RefreshView` | Rotates. |
| POST | `/api/v1/auth/logout/` | `LogoutView` | Revokes the provided refresh's family. |
| POST | `/api/v1/auth/password/reset/` | `PasswordResetView` | Always returns 200 (don't leak existence). |
| POST | `/api/v1/auth/password/reset/confirm/` | `PasswordResetConfirmView` | Token-gated; on success issues JWT. |
| GET  | `/api/v1/users/me/` | `CurrentUserView` | Returns user profile. |

JWT implementation: `djangorestframework-simplejwt` with customized `TokenObtainPairSerializer` to include `email`, `display_name`, `is_verified` in token claims. Custom `refresh` view implements **family rotation**:

1. Each refresh token carries `family_id`.
2. On use, mark the consumed refresh as rotated, issue a new one in the same family.
3. If a token with `rotated_at IS NOT NULL` is presented → revoke whole `family_id`.

Rate limits via `django-ratelimit` decorator + Redis backend.

Account lockout: middleware counts `FailedLoginAttempt` within a 15-min sliding window per email; at ≥10 returns 423 Locked; admin-adjustable via settings.

### 6.3 Backend — email

- Provider: **Resend** via `django-anymail` (simple, reliable, cheap).
- Templates in `apps/users/templates/email/`:
  - `verify_email.html` + `.txt`
  - `password_reset.html` + `.txt`
  - `account_locked.html` + `.txt` (notify user)
  - All wrapped in `{% blocktrans %}` with context vars.
- A `DEFAULT_FROM_EMAIL = 'StratTraderPro <no-reply@strattraderpro.com>'`.
- Dev mode uses `console` email backend.

### 6.4 Frontend — core

- `core/services/auth.api.ts` — typed HTTP calls.
- `core/interceptors/jwt.interceptor.ts` — attaches `Authorization: Bearer <access>`.
- `core/interceptors/refresh.interceptor.ts` — on 401, attempts `/auth/refresh/`; queues concurrent requests during refresh; on failure, calls `authFacade.logout()`.
- `core/interceptors/error.interceptor.ts` — normalizes error shape → `AppError`.
- `core/guards/auth.guard.ts` — `canMatch`: require authenticated.
- `core/guards/unverified-only.guard.ts` — redirect already-verified users away from verify pages.

### 6.5 Frontend — abstraction

- `abstraction/stores/auth.store.ts` — signal-based store with fields: `user`, `accessToken`, `refreshToken`, `status: 'idle'|'loading'|'error'|'authed'`, `error`.
- `abstraction/facades/auth.facade.ts` — orchestrates calls, handles navigation side-effects.

### 6.6 Frontend — presentation

Routes (lazy-loaded `auth.routes.ts`):
- `/login`
- `/register`
- `/verify-email` (reads `?token=`)
- `/resend-verification`
- `/password-reset`
- `/password-reset/confirm` (reads `?token=`)

Each page uses reactive forms; error mapping; translated copy; accessible labels; `autocomplete` attributes correct.

Disable the submit button while loading; show inline field errors; show a top banner for global errors.

### 6.7 Session & storage

- Store `access` in memory only (`AuthStore` signal).
- Store `refresh` in `httpOnly` cookie **if** set via Set-Cookie; OR fall back to `localStorage` if backend cannot set cookies for the frontend domain. **Prefer cookie approach** (subdomains `api.*` and `app.*` → `Domain=.strattraderpro.com`).
- On page load, the app attempts `/auth/refresh/` silently; if success → authed; else → anonymous.

### 6.8 Email and token templates (i18n)

All email templates and UI copy keys defined in `locale/en/LC_MESSAGES/django.po` and `src/assets/i18n/en.json`:

```
auth.login.title
auth.login.email
auth.login.password
auth.login.submit
auth.login.error.invalid
auth.login.error.locked
auth.login.error.unverified
auth.login.forgot
...
```

## 7. Tech Stack Notes

- **Argon2id** params tuned to ~250ms per hash on staging hardware (time=2, mem=64MB, parallelism=1).
- **djangorestframework-simplejwt** over `django-oauth-toolkit`: simpler, sufficient for single-tenant JWT.
- **Resend** over Postmark: cheaper, excellent DX, good deliverability; Mailgun is the fallback.
- **django-ratelimit** + Redis: works across multiple backend replicas.
- Frontend uses **signals + effects** for auth store; avoids RxJS `BehaviorSubject` since the skill prefers signals.

## 8. Data Model Changes

Migrations:
1. `users.0001_initial` — `User`, `EmailVerificationToken`, `PasswordResetToken`, `RefreshTokenFamily`, `FailedLoginAttempt`, `AuthEvent`.

All tables have `owner_id` or equivalent for RLS; RLS policies enabled even though only admin should ever query these.

## 9. API Contract Changes

Published OpenAPI paths per §6.2. All responses follow `{ data?: ..., error?: { code, message, details } }` envelope to keep frontend error handling consistent. Codes: `USER_EXISTS`, `INVALID_CREDENTIALS`, `EMAIL_NOT_VERIFIED`, `ACCOUNT_LOCKED`, `RATE_LIMITED`, `TOKEN_INVALID`, `TOKEN_EXPIRED`, `PASSWORD_WEAK`.

## 10. Test Plan

### 10.1 Unit tests (backend)

- `test_register_creates_user_and_sends_email`
- `test_register_duplicate_email_returns_409`
- `test_verify_email_happy_path`
- `test_verify_email_token_expired_rejected`
- `test_verify_email_token_single_use`
- `test_login_unverified_returns_email_not_verified`
- `test_login_wrong_password_increments_failed_counter`
- `test_login_10th_failure_locks_account`
- `test_login_after_lockout_expires_succeeds`
- `test_refresh_rotates_token`
- `test_refresh_reuse_revokes_family`
- `test_password_reset_does_not_leak_existence`
- `test_password_policy_rejects_common_passwords`
- `test_logging_no_password_or_token_in_logs` (parses captured logs)
- `test_email_templates_extracted_to_po_file`

Property tests (`hypothesis`):
- Random email strings conform to validator.
- Password policy accepts/rejects predictably.

### 10.2 Unit tests (frontend)

- `AuthStore` handles `login`/`logout`/`refresh` transitions.
- `RefreshInterceptor` queues concurrent 401s.
- `AuthGuard` redirects anonymous to `/login?next=`.
- Reactive form validators (email format, password strength).

### 10.3 Integration tests

- Full register → verify → login → refresh → logout flow against Postgres + Redis.
- Rate-limit returns 429 after N attempts.
- Resend email respects cooldown.

### 10.4 E2E (Playwright)

- `auth.register.spec.ts`: happy path, duplicate, weak password.
- `auth.login.spec.ts`: happy path, unverified, wrong password, locked, rate-limited banner.
- `auth.reset.spec.ts`: forgot → email console → confirm.
- `auth.refresh.spec.ts`: simulate access expiry via jwt clock mock.

### 10.5 Load test

- 20 logins/sec for 5 min: p95 < 300ms; no 5xx.

### 10.6 Security checks

- `bandit`: no MEDIUM+ on `apps/users`.
- OWASP ASVS L2 Auth section manual checklist: password storage, session mgmt, transport.
- CSRF exempt verified for JWT-only endpoints.
- Timing-safe password comparison inherent in Django's hasher.
- JWT `alg=HS256` with a 256-bit secret OR RS256 with a KMS-managed key (pick HS256 for MVP).

## 11. Security Considerations

- Do not reveal whether an email is registered during password reset (always 200).
- Verification token includes a random 32-byte secret; HMAC'd by server secret on issuance; stored hashed.
- Refresh tokens are long and stored hashed server-side.
- JWT secret rotation path: multiple secrets supported with a `kid`; rotate by redeploy.
- CSRF: JWT endpoints are exempt; cookie-based endpoints (if any) enforce CSRF.
- CORS preflight confirmed on `/auth/*`.
- Email enumeration mitigated on register (return 202 always, actual error only in edit-profile flows).

## 12. Observability

- Sentry auto-captures 5xx; PII scrubbed via `before_send`.
- Prometheus:
  - `auth_login_total{result="ok|bad_password|unverified|locked|rate_limited"}`
  - `auth_refresh_total{result}`
  - `auth_family_revocations_total`
  - `auth_password_reset_total{step}`
- OpenTelemetry spans on login & refresh endpoints with `user_id` (hashed) attribute.
- Grafana dashboard **Auth Health**:
  - Login success rate panel (alert < 95% over 5 min).
  - Family revocation rate panel (alert > 5/hour).
  - Rate-limit hits panel.

## 13. Translation & Localization

- Every user-facing string (UI copy, email bodies, error messages) has a translation key.
- Keys prefixed `auth.*` for easier later extraction.
- Email subjects translated.
- Templates support `LANGUAGE_CODE` context resolver; user's `profile.language` (set in M02) will switch when set, falls back to `en`.
- Verify: `manage.py makemessages -l en -a` produces no "fuzzy" entries after first run; `grep -rE '"[A-Z][a-z ]{3,}"' frontend/src/app` returns only keys, not literals.

## 14. Documentation Deliverables

- `/docs/adr/010-jwt-rotation.md` — family rotation rationale.
- `/docs/adr/011-email-provider.md` — Resend chosen.
- `/docs/runbooks/user-locked-out.md`
- `/docs/runbooks/password-reset-abuse.md`
- API docs auto-generated; human-facing user guide page "Create your account" in `frontend/src/assets/help/`.

## 15. Rollback Plan

- Migration `users.0001` is non-destructive; rollback = `migrate users zero`.
- Feature flag `AUTH_V1_ENABLED = True`; flipping off short-circuits new endpoints to 503.
- If a critical auth bug ships, deploy previous tag (`v0.0.x-scaffold`) via Railway one-click.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Email deliverability (verification in spam) | Med | High | DKIM/SPF/DMARC set up; sender warmed; test from 3 major providers. |
| JWT family rotation race condition (parallel tab refresh storm) | Med | Med | Server-side lock per family via Redis SETNX with TTL=10s. |
| Password policy annoys users | Med | Low | Ship helpful inline strength meter; allow passphrases. |
| Sentry captures PII | High | Med | Explicit `before_send` scrubber; unit test. |
| Lockout-by-email enables DoS (attacker spams bad passwords per email) | Med | Med | Pair with per-IP limit; 15-min auto-unlock is short; user can self-unlock via password reset email. |

## 17. Exit Gate Checklist

- [ ] AC-01-1 … AC-01-13 pass on staging.
- [ ] E2E suite green.
- [ ] Coverage ≥ 80% on `apps/users`.
- [ ] No PII leak in logs (test asserts).
- [ ] Email templates render in plain-text + HTML, no hardcoded strings.
- [ ] Grafana **Auth Health** dashboard live.
- [ ] ADRs 010, 011 committed.
- [ ] Runbooks for lockout + reset abuse written.
- [ ] Changelog updated.
- [ ] Tag `v0.1.0-auth`.

Proceed to **M02 MFA & User Profile**.
