# StratTraderPro — Plan Progress Tracker

> **Purpose:** Track implementation progress across all milestones. Used by Claude Code instances in the IDE to understand what's been done, what's in progress, and what's next.
>
> **Last updated:** 2026-05-01 — M01 closed; ready for M02

---

## How to Read This File

Each phase has a status badge and a table of tasks. Statuses:
- ✅ **Done** — Completed and verified
- 🔄 **In Progress** — Currently being worked on
- ⏳ **Pending** — Not yet started
- ⚠️ **Blocked** — Waiting on external dependency
- 🚫 **Skipped** — Intentionally deferred or N/A

---

## Phase 00 — Scoping & Setup

**Status:** 🔄 In Progress
**Started:** 2026-04-16
**Completed:** —

### 00.1 Repository & Monorepo Structure

| # | Task | Status | Notes |
|---|------|--------|-------|
| 00.1.1 | Create monorepo directory layout (backend/, frontend/, docker/, docs/, etc.) | ✅ Done | Scaffolded locally — push to GitHub next |
| 00.1.2 | .gitignore (Python, Node, Angular, JetBrains, VS Code, .env*) | ✅ Done | |
| 00.1.3 | GitHub repo `yuval3000/strattraderpro` created | ⏳ Pending | Manual: `git init` → push to GitHub |
| 00.1.4 | Branch protection on `main` (1 review, CI green, no force-push) | ⏳ Pending | Manual: GitHub Settings → Branches |
| 00.1.5 | Issue templates (bug.yml, feature.yml, tech-debt.yml) | ✅ Done | |
| 00.1.6 | PR template with DoD checklist | ✅ Done | |
| 00.1.7 | Dependabot config (pip, npm, docker, weekly) | ✅ Done | |
| 00.1.8 | CODEOWNERS set to @yuval3000 | ✅ Done | |

### 00.2 Backend Scaffold (Django)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 00.2.1 | Django project config (settings/base.py, dev.py, prod.py, test.py) | ✅ Done | Split settings with django-environ |
| 00.2.2 | Empty app packages (users, strategies, webhooks, regime, sentiment, risk, brokers, orders, backtest, marketdata, audit, admin_portal) | ✅ Done | Each has apps.py + __init__.py |
| 00.2.3 | Custom User model (AbstractUser, email unique) | ✅ Done | apps/users/models.py |
| 00.2.4 | drf-spectacular OpenAPI at /api/schema/ | ✅ Done | |
| 00.2.5 | /healthz and /readyz endpoints | ✅ Done | Returns status + version + db/redis checks |
| 00.2.6 | structlog JSON logging with scrubber | ✅ Done | Scrubs authorization, sig, secret, password, token |
| 00.2.7 | Celery + celery-redbeat config | ✅ Done | CELERY_BROKER_URL and RESULT_BACKEND wired to Redis |
| 00.2.8 | i18n scaffolding (LANGUAGES, LOCALE_PATHS) | ✅ Done | |
| 00.2.9 | Requirements files (base.txt, dev.txt, prod.txt, test.txt) | ✅ Done | |
| 00.2.10 | manage.py + wsgi.py + asgi.py | ✅ Done | |

### 00.3 Frontend Scaffold (Angular)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 00.3.1 | Angular 19 standalone app scaffolded | ✅ Done | Created via ng new with --standalone |
| 00.3.2 | 3-layer directory structure (core/, abstraction/, features/) | ✅ Done | |
| 00.3.3 | Tailwind CSS configured with custom tokens | ✅ Done | src/styles/tokens.css |
| 00.3.4 | @ngx-translate wired with en.json | ✅ Done | |
| 00.3.5 | Placeholder landing page using translate pipe | ✅ Done | |
| 00.3.6 | environment.ts / environment.prod.ts with apiBase | ✅ Done | |
| 00.3.7 | app.config.ts with provideRouter, provideHttpClient | ✅ Done | |
| 00.3.8 | Auth interceptor skeleton | ✅ Done | |

### 00.4 Infrastructure (Docker)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 00.4.1 | Backend Dockerfile (Python 3.12-slim, multi-stage) | ✅ Done | |
| 00.4.2 | Frontend Dockerfile (Node 20 build → nginx:alpine) | ✅ Done | |
| 00.4.3 | docker-compose.yml (postgres, redis, backend, worker, beat, frontend, ngrok) | ✅ Done | |
| 00.4.4 | Makefile targets (up, down, logs, shell-be, shell-fe, test-be, test-fe) | ✅ Done | |
| 00.4.5 | nginx.conf for frontend prod | ✅ Done | |

### 00.5 Railway Staging

| # | Task | Status | Notes |
|---|------|--------|-------|
| 00.5.1 | Create Railway project `strattraderpro-staging` | ⏳ Pending | Manual: Railway dashboard |
| 00.5.2 | Configure services (backend, worker, beat, llm-worker, frontend) | ⏳ Pending | Manual: Railway dashboard |
| 00.5.3 | Add Postgres 16 + Redis 7 plugins | ⏳ Pending | Manual: Railway dashboard |
| 00.5.4 | Set environment variables | ⏳ Pending | Manual: Railway dashboard |
| 00.5.5 | Health check paths configured | ⏳ Pending | /healthz, /readyz |
| 00.5.6 | Railway CLI + service account token | ⏳ Pending | Store in GitHub Actions secrets |

### 00.6 CI/CD

| # | Task | Status | Notes |
|---|------|--------|-------|
| 00.6.1 | ci.yml (lint + test + build + trivy) | ✅ Done | |
| 00.6.2 | deploy-staging.yml (push to main → Railway) | ✅ Done | |
| 00.6.3 | Cache rules for pip and pnpm | ✅ Done | |

### 00.7 Observability

| # | Task | Status | Notes |
|---|------|--------|-------|
| 00.7.1 | sentry-sdk configured (backend + frontend) | ✅ Done | DSN from env var, never in repo |
| 00.7.2 | django-prometheus middleware + /metrics endpoint | ✅ Done | |
| 00.7.3 | OpenTelemetry distro auto-instrumentation | ✅ Done | Config in settings |
| 00.7.4 | Sentry JS SDK in Angular | ✅ Done | Skeleton in main.ts |
| 00.7.5 | Grafana Cloud account + System Health dashboard | ⏳ Pending | Manual: grafana.com signup |

### 00.8 Documentation

| # | Task | Status | Notes |
|---|------|--------|-------|
| 00.8.1 | README.md (quickstart ≤ 10 commands) | ✅ Done | |
| 00.8.2 | ADR-000 tech-stack.md | ✅ Done | |
| 00.8.3 | ADR-001 monorepo.md | ✅ Done | |
| 00.8.4 | ADR-002 railway-hosting.md | ✅ Done | |
| 00.8.5 | CONTRIBUTING.md | ✅ Done | |
| 00.8.6 | CHANGELOG.md | ✅ Done | |
| 00.8.7 | docs/runbooks/staging-deploy.md | ✅ Done | |
| 00.8.8 | docs/dev/local-setup.md | ✅ Done | |
| 00.8.9 | .env.example + .env.local.example | ✅ Done | |

### 00.9 Manual Steps Remaining

| # | Task | Status | Notes |
|---|------|--------|-------|
| 00.9.1 | Push to GitHub | ⏳ Pending | `git init && git remote add origin ...` |
| 00.9.2 | Enable branch protection | ⏳ Pending | GitHub Settings |
| 00.9.3 | Create Railway project + services | ⏳ Pending | Railway dashboard |
| 00.9.4 | Create Sentry project, get DSN | ⏳ Pending | sentry.io |
| 00.9.5 | Create Grafana Cloud account + dashboard | ⏳ Pending | grafana.com |
| 00.9.6 | Run `docker compose up` and verify local stack | ⏳ Pending | First real test |
| 00.9.7 | Trigger staging deploy and verify AC-00-* | ⏳ Pending | After Railway setup |
| 00.9.8 | Tag `v0.0.0-scaffold` | ⏳ Pending | After all ACs pass |

---

## Phase 01 — Auth Foundation

**Status:** ✅ Done — 2026-05-01
**Started:** 2026-04-17
**Completed:** 2026-05-01

**Tags:**
- `v0.1.0-auth` (commit `33c48ac`) — M01 baseline as planned in `01-auth-foundation.md`. Pushed.
- `v0.1.1-auth-metrics` — captures the post-baseline observability hardening: four Prometheus auth counters wired, Resend 422→500 hardening, gunicorn multi-process Prometheus mode, alert-rule instant-query fix. Pending user `git push origin v0.1.1-auth-metrics` after the matching CHANGELOG commit lands.

**Plan §17 exit-gate:** all items ✅ — see 01.11 below for the receipts.

> See `01-auth-foundation.md` for full spec.

### 01.1 Backend — Models & Migration

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.1.1 | User model (AbstractBaseUser, UUID PK, email-keyed) | ✅ Done | Replaces M00 AbstractUser scaffold |
| 01.1.2 | UserManager (create_user, create_superuser) | ✅ Done | |
| 01.1.3 | EmailVerificationToken (single-use, 24h TTL, stored hashed) | ✅ Done | |
| 01.1.4 | PasswordResetToken (single-use, 1h TTL, stored hashed) | ✅ Done | |
| 01.1.5 | RefreshTokenFamily (family rotation + reuse detection) | ✅ Done | current_jti field for reuse detection |
| 01.1.6 | FailedLoginAttempt (per-email sliding window) | ✅ Done | |
| 01.1.7 | AuthEvent (audit precursor) | ✅ Done | 12 event types |
| 01.1.8 | Migration 0001_initial | ✅ Done | Manually written, verified against SQLite |

### 01.2 Backend — Settings & Config

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.2.1 | Argon2id password hasher (primary) | ✅ Done | PASSWORD_HASHERS in base.py |
| 01.2.2 | Password policy (12 char min, letters+digits) | ✅ Done | LettersAndDigitsValidator |
| 01.2.3 | SimpleJWT (15min access, 30day refresh, HS256) | ✅ Done | Family rotation handled by custom logic |
| 01.2.4 | Anymail + Resend config | ✅ Done | Console backend in dev, locmem in test |
| 01.2.5 | Lockout settings (threshold, window, duration) | ✅ Done | Env-var overridable |
| 01.2.6 | Requirements updated (argon2-cffi, anymail, ratelimit) | ✅ Done | + hypothesis, freezegun in test |

### 01.3 Backend — Endpoints

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.3.1 | POST /api/v1/auth/register/ | ✅ Done | Rate-limited 3/min, 202 on duplicate (anti-enum) |
| 01.3.2 | POST /api/v1/auth/verify-email/ | ✅ Done | |
| 01.3.3 | POST /api/v1/auth/resend-verification/ | ✅ Done | Rate-limited 3/min |
| 01.3.4 | POST /api/v1/auth/login/ | ✅ Done | Rate-limited 5/min/email + 20/min/IP, lockout |
| 01.3.5 | POST /api/v1/auth/refresh/ | ✅ Done | Family rotation + reuse detection |
| 01.3.6 | POST /api/v1/auth/logout/ | ✅ Done | Revokes family |
| 01.3.7 | POST /api/v1/auth/password/reset/ | ✅ Done | Always 200 (anti-enum) |
| 01.3.8 | POST /api/v1/auth/password/reset/confirm/ | ✅ Done | Issues JWT on success |
| 01.3.9 | GET /api/v1/users/me/ | ✅ Done | |

### 01.4 Backend — Email Templates

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.4.1 | verify_email.html + .txt | ✅ Done | i18n via blocktrans |
| 01.4.2 | password_reset.html + .txt | ✅ Done | i18n via blocktrans |
| 01.4.3 | account_locked.html + .txt | ✅ Done | i18n via blocktrans |

### 01.5 Backend — Tests

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.5.1 | 24 auth unit tests | ✅ Done | All passing (0.29s) |
| 01.5.2 | 6 M00 regression tests | ✅ Done | Still passing |

### 01.6 Frontend — Core Layer

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.6.1 | Auth types (AuthUser, AuthTokenPair, ApiEnvelope) | ✅ Done | core/models/auth.models.ts |
| 01.6.2 | AuthApi service (typed HTTP calls) | ✅ Done | core/services/auth.api.ts |
| 01.6.3 | JWT interceptor (attach Bearer token) | ✅ Done | Scoped to apiBase |
| 01.6.4 | Refresh interceptor (401 → refresh, queue) | ✅ Done | Concurrent request queuing |
| 01.6.5 | Error interceptor (normalize to AppError) | ✅ Done | |
| 01.6.6 | Auth guard (canMatch, redirect to /login?next=) | ✅ Done | |
| 01.6.7 | Guest guard (redirect authed to /dashboard) | ✅ Done | |

### 01.7 Frontend — Abstraction Layer

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.7.1 | AuthStore (signal-based, localStorage refresh) | ✅ Done | abstraction/stores/auth.store.ts |
| 01.7.2 | AuthFacade (API + store + navigation) | ✅ Done | abstraction/facades/auth.facade.ts |

### 01.8 Frontend — Auth Pages

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.8.1 | Login page | ✅ Done | Reactive forms, error mapping, i18n |
| 01.8.2 | Register page | ✅ Done | Password hint, 12-char min |
| 01.8.3 | Verify email page | ✅ Done | Auto-verifies from ?token= |
| 01.8.4 | Resend verification page | ✅ Done | |
| 01.8.5 | Password reset page | ✅ Done | |
| 01.8.6 | Password reset confirm page | ✅ Done | Confirm password match |
| 01.8.7 | Auth routes (lazy-loaded) | ✅ Done | auth.routes.ts |
| 01.8.8 | i18n keys (auth.*) | ✅ Done | en.json |

### 01.9 Frontend — Wiring

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.9.1 | app.config.ts (interceptors, APP_INITIALIZER) | ✅ Done | Silent refresh on bootstrap |
| 01.9.2 | app.routes.ts (auth routes, authGuard on /dashboard) | ✅ Done | |
| 01.9.3 | SignalStore delegates to AuthStore | ✅ Done | |
| 01.9.4 | tsconfig.json baseUrl fix | ✅ Done | Required for path aliases |
| 01.9.5 | Frontend build green | ✅ Done | All pages lazy-loaded |

### 01.10 Documentation

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.10.1 | ADR-010 JWT rotation | ✅ Done | docs/adr/010-jwt-rotation.md |
| 01.10.2 | ADR-011 Email provider (Resend) | ✅ Done | docs/adr/011-email-provider.md |
| 01.10.3 | Runbook: user locked out | ✅ Done | docs/runbooks/user-locked-out.md |
| 01.10.4 | Runbook: password reset abuse | ✅ Done | docs/runbooks/password-reset-abuse.md |

### 01.11 Remaining (deferred to stack-up / manual)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01.11.1 | OpenAPI schema with request/response examples | ✅ Done | Envelope serializers + examples in apps/users/schema.py; views annotated |
| 01.11.2 | openapi-typescript type generation | ✅ Done | `npm run schema:types` → frontend/src/app/core/generated/schema.ts; snapshot at docs/openapi/openapi.json; `make schema` re-exports from live backend |
| 01.11.3 | Contract test (schema ↔ frontend parity) | ✅ Done | Compile-time type assertions in auth.models.contract.spec.ts; tsc --noEmit passes |
| 01.11.4 | E2E Playwright tests | ✅ Done | frontend/e2e/ with register/login/reset/refresh specs + `installAuthMock` fixture; runs against mocked backend by default (set E2E_BASE_URL for real stack) |
| 01.11.5 | Grafana Auth Health dashboard | ✅ Done | Live at https://yuval3000.grafana.net/d/stp-auth-health; 4 panels + 3 alert rules in folder `StratTraderPro Auth` (UID `cfkrwjgh3sxkwa`) routed to `auth-health-email` contact point → yuval3000@gmail.com. Dashboard JSON checked in at `infra/grafana/auth-health-dashboard.json` |
| 01.11.6 | Admin registration for new models | ✅ Done | AuthEvent, RefreshTokenFamily, FailedLoginAttempt |
| 01.11.7 | CHANGELOG update | ✅ Done | `[0.1.0-auth] 2026-05-01` documents M01 baseline; `[Unreleased]` documents the v0.1.1 patch (counters + Resend fix + multi-process + alert query fix) ahead of tagging |
| 01.11.8 | Tag v0.1.0-auth | ✅ Done | Pushed at commit `33c48ac` |
| 01.11.9 | Railway staging deploy (7 services) | ✅ Done | backend, frontend, Postgres, Redis, celery-worker, celery-beat, grafana-agent — all Online; project `17060567-b194-4926-a7c0-7f339e306bdf`, env `staging` |
| 01.11.10 | AC-01-1..13 staging verification | ✅ Done | AC-01-1, 3, 9, 10, 13 confirmed via curl pre-email-verification. AC-01-2 (`is_verified: true` in /login response), AC-01-4 (full JWT pair w/ correct TTLs), AC-01-5 (refresh rotates to new jti, same family_id), AC-01-6 (replaying rotated refresh → `Refresh token reuse detected — family revoked` 401, replaying refresh_v2 → `Refresh token family revoked` 401), AC-01-8 (200 for both known and unknown emails — anti-enum preserved) all confirmed via curl after user clicked verification link. AC-01-7/12 covered by unit tests (rate limit masks lockout under load test from one IP); AC-01-11 covered by frontend `auth.guard.spec.ts` |
| 01.11.11 | Prometheus auth counters wired (plan §12) | ✅ Done | `apps/users/metrics.py` — `auth_login_total{result}` (5 outcomes), `auth_refresh_total{result}` (4 outcomes), `auth_family_revocations_total`, `auth_password_reset_total{step}`. Incremented from `LoginView` (5 paths), `PasswordResetView`/`Confirm`, and `services.rotate_refresh`/`revoke_refresh`. Verified populating in Grafana Explore. |
| 01.11.12 | Resend 422 → 500 hardening | ✅ Done | `services._send_templated` wraps `msg.send` in try/except — provider failures (Resend test-sender restriction, SMTP timeout) are logged, the user/account is still created, response stays at the expected 201/202. Anti-enum semantics preserved. |
| 01.11.13 | Multi-process Prometheus mode | ✅ Done | `backend/gunicorn.conf.py` adds `child_exit` hook calling `multiprocess.mark_process_dead(worker.pid)`; `docker/backend.Dockerfile` sets `ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prom-multiproc` and `mkdir -p` the dir before workers boot. Verified: 8 consecutive `/metrics` scrapes return identical aggregated values (was bouncing 2/3/4 between workers before). |
| 01.11.14 | Alert rules fixed + family-revocation smoke test | ✅ Done | All three rules originally created with `queryType: ''` (range mode) → Grafana 11 `looks like time series data, only reduced data can be alerted on` error. Updated to `queryType: 'instant'` + `instant: true` so the threshold expression sees a scalar. End-to-end verified: triggered 3 family revocations → rule transitioned `Inactive → Pending(activeAt 19:11:40Z) → Firing(activeAt+5m, 19:16:40Z)` → email sent via `auth-health-email` contact point. Closes plan §5 family-revocation alert smoke test. |
| 01.11.15 | Tag v0.1.1-auth-metrics | ⏳ Pending | Awaiting user `git tag -a v0.1.1-auth-metrics && git push origin v0.1.1-auth-metrics` after the CHANGELOG commit lands |

---

## Phase 02 — MFA & User Profile

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `02-mfa-and-user-profile.md` for full spec.

---

## Phase 03 — Strategies & Webhook Config

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `03-strategies-and-webhook-config.md` for full spec.

---

## Phase 04 — Webhook Ingest & IBKR

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `04-webhook-ingest-and-ibkr.md` for full spec.

---

## Phase 05 — TradeStation & Order Lifecycle

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `05-tradestation-and-order-lifecycle.md` for full spec.

---

## Phase 06 — Market Data & Regime

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `06-market-data-and-regime.md` for full spec.

---

## Phase 07 — Sentiment Pipeline

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `07-sentiment-pipeline.md` for full spec.

---

## Phase 08 — Risk Engine & Kill Switches

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `08-risk-engine-and-kill-switches.md` for full spec.

---

## Phase 09 — Walk-Forward Backtester

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `09-walk-forward-backtester.md` for full spec.

---

## Phase 10 — Admin, Audit & Observability

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `10-admin-audit-observability.md` for full spec.

---

## Phase 11 — Hardening & Load Test

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `11-hardening-and-load-test.md` for full spec.

---

## Phase 12 — Beta & Sign-off

**Status:** ⏳ Pending
**Started:** —
**Completed:** —

> See `12-beta-and-signoff.md` for full spec.
