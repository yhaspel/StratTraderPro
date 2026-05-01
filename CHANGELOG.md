# Changelog

All notable changes to StratTraderPro will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Known issues (open after 0.1.0-auth)
- `POST /api/v1/auth/register/` returns 500 (instead of 202) when Resend rejects the recipient — most commonly when using the test sender `onboarding@resend.dev`, which only delivers to addresses verified on the Resend account. Mitigation: verify a sending domain in Resend (DKIM/SPF) and switch `DEFAULT_FROM_EMAIL` to it. Code fix tracked separately: wrap the email send in a try/except, log the failure, return 202 either way (anti-enumeration is still preserved).

---

## [0.1.0-auth] — 2026-05-01

### Added (since the placeholder 2026-04-30 entry)
- **Railway staging deployment**: 7-service environment (`backend`, `frontend`, `Postgres`, `Redis`, `celery-worker`, `celery-beat`, `grafana-agent`) on a single Railway project, region us-east4. URLs: `https://frontend-staging-9011.up.railway.app`, `https://backend-staging-4b6d.up.railway.app`. Project: `https://railway.com/project/17060567-b194-4926-a7c0-7f339e306bdf`.
- **Grafana Cloud — Auth Health dashboard live** (`https://yuval3000.grafana.net/d/stp-auth-health`): four panels (login success rate, login outcomes, family revocations, rate-limit hits) and three alert rules wired to email contact point `auth-health-email` → yuval3000@gmail.com. Dashboard JSON checked in at `infra/grafana/auth-health-dashboard.json`.
- `infra/grafana-agent/` Docker config for the `grafana-agent` Railway service (Grafana Agent v0.43.4 in static mode, scraping `backend.railway.internal:8000/metrics` and remote-writing to `prometheus-prod-58-prod-eu-central-0.grafana.net`).
- `docker/nginx.conf.template` with `${BACKEND_URL}` envsubst for the frontend nginx — replaces the docker-compose-only `nginx.conf`.

### Changed
- `docker/backend.Dockerfile`: gunicorn now points at `config.asgi:application` (uvicorn worker requires ASGI; was running `config.wsgi` and 500'ing every request); honors `${PORT}`; runs `migrate --noinput` on boot.
- `docker/frontend.Dockerfile`: switched from baked-in nginx config to the official nginx image's envsubst template flow (`NGINX_ENVSUBST_FILTER=^BACKEND_URL$`), so `BACKEND_URL` resolves at container start.
- `backend/config/settings/prod.py`: `SECURE_SSL_REDIRECT` now defaults to False and is env-controlled — Railway terminates TLS at the edge and Django redirecting again caused infinite loops.
- `backend/config/settings/base.py` (in repo): no functional change, but staging-side `ALLOWED_HOSTS` now includes `backend.railway.internal` so the in-cluster Grafana Agent can scrape `/metrics` without 400.
- `setup-guides/grafana-setup.md` and `docs/runbooks/staging-deploy.md`: updated to reflect actual deployed config (stack slug `yuval3000`, Agent v0.43.4 not Alloy, scope `set:alloy-data-write`); added new troubleshooting rows for ASGI-mismatch, agent binary rename, and `up=0`-from-ALLOWED_HOSTS.

### Verified on staging
- Backend: `/healthz` 200; `/metrics` 200; `/api/schema/` 200 (also via frontend's nginx proxy at `/api/schema/`).
- Grafana Cloud Explore: `up{service="backend"} == 1` after the ALLOWED_HOSTS fix.
- AC-01-1 (register), AC-01-3 (unverified login), AC-01-9 (weak password), AC-01-10 (rate limits), AC-01-13 (auth.* i18n keys present) — all confirmed via curl against the live staging URL.
- AC-01-2/4/5/6/8/11 require manual click-through (verification email + browser auth flow) and are tagged for the next session's smoke test against staging.

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
