# Changelog

All notable changes to StratTraderPro will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

---

## [0.1.0-auth] — 2026-04-30

### Added
- **M01 Auth Foundation**: registration, email verification, login, JWT access + refresh rotation, logout, password reset, account lockout, rate limiting, Argon2id hashing.
- Models: `User` (AbstractBaseUser, UUID PK, email-keyed), `EmailVerificationToken`, `PasswordResetToken`, `RefreshTokenFamily` (family rotation w/ reuse detection), `FailedLoginAttempt`, `AuthEvent` (audit precursor).
- Endpoints under `/api/v1/auth/`: `register`, `verify-email`, `resend-verification`, `login`, `refresh`, `logout`, `password/reset`, `password/reset/confirm`; plus `GET /api/v1/users/me/`.
- Email templates (i18n via `blocktrans`): `verify_email`, `password_reset`, `account_locked` (HTML + text).
- Anti-enumeration: register returns 202 on duplicate; password reset always returns 200.
- Rate limits: register 3/min/IP, login 5/min/email + 20/min/IP, password reset 3/min/email.
- Lockout: 10 failed attempts / 15 min sliding window → 15 min lock (env-configurable).
- OpenAPI: envelope serializers + request/response examples in `apps/users/schema.py`; `openapi-typescript` generation wired (`make schema`, `npm run schema:types`); compile-time contract tests.
- Angular: login, register, verify-email, resend-verification, password-reset, password-reset/confirm pages (lazy-loaded).
- Signal-based `AuthStore` + `AuthFacade`; JWT / refresh / error HTTP interceptors; `authGuard` and `guestGuard`; silent refresh on bootstrap via `APP_INITIALIZER`.
- Tests: 24 backend auth unit tests, frontend unit tests (`AuthStore`, `refreshInterceptor`, `authGuard`, form validators), Playwright E2E specs (`auth.register`, `auth.login`, `auth.reset`, `auth.refresh`) with mocked-backend fixture.
- Admin registrations for `AuthEvent`, `RefreshTokenFamily`, `FailedLoginAttempt`.
- ADR-010 (JWT family rotation), ADR-011 (Resend email provider).
- Runbooks: `user-locked-out.md`, `password-reset-abuse.md`.
- Setup guide: `setup-guides/grafana-setup.md` (Auth Health dashboard).

### Pending (gates `v0.1.0-auth` tag)
- Manual: Grafana Cloud **Auth Health** dashboard — see `setup-guides/grafana-setup.md`.
- Manual: AC-01-1 … AC-01-13 verification on Railway staging (depends on M00 staging setup).
- Manual: Sentry release tagged `v0.1.0-auth` after staging verification.
- Verify backend coverage ≥ 80% on `apps/users` via `make test-be` (run inside Docker; no local venv).

---

- Monorepo scaffold: backend (Django 5 + DRF), frontend (Angular 19 + signals), Docker, CI/CD.
- Health endpoints: `GET /healthz`, `GET /readyz`.
- OpenAPI schema at `GET /api/schema/` via drf-spectacular.
- Custom `User` model (AbstractUser, email unique).
- i18n scaffolding: `ngx-translate` (frontend) + Django locale (backend).
- docker-compose with Postgres 16, Redis 7, backend, worker, beat, frontend, ngrok.
- CI pipeline: lint, test, build, Trivy image scan.
- Deploy-to-staging workflow via Railway CLI.
- Observability: Sentry SDK, django-prometheus, OpenTelemetry skeleton.
- ADRs 000–002: tech stack, monorepo, Railway hosting.
- Tailwind CSS with custom design tokens.
- Makefile targets for common dev tasks.
- GitHub issue/PR templates, Dependabot, CODEOWNERS.
