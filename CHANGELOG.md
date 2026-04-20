# Changelog

All notable changes to StratTraderPro will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- M01 Auth Foundation: registration, email verification, login, JWT access + refresh rotation, logout, password reset, account lockout, rate limiting, Argon2id hashing.
- `CustomUser` model keyed on email; `EmailVerificationToken`, `PasswordResetToken`, `RefreshTokenFamily`, `FailedLoginAttempt`, `AuthEvent` models.
- Angular auth pages: login, register, verify-email, resend-verification, password-reset, password-reset/confirm.
- Signal-based `AuthStore` and `AuthFacade`; JWT, refresh, and error HTTP interceptors; `authGuard` and `guestGuard`.
- Frontend unit tests: `AuthStore`, `refreshInterceptor`, `authGuard`, `LoginComponent` form validators.
- ADRs 010 (JWT rotation) and 011 (email provider).
- Runbooks: `user-locked-out.md`, `password-reset-abuse.md`.

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
