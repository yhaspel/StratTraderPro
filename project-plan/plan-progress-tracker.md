# StratTraderPro — Plan Progress Tracker

> **Purpose:** Track implementation progress across all milestones. Used by Claude Code instances in the IDE to understand what's been done, what's in progress, and what's next.
>
> **⚠️ Canonical quick-status now lives in [`PROGRESS.md`](./PROGRESS.md)** (verified against code, updated per development milestone — see the project-root `MEMORY.md` for the update rule). This file keeps the detailed per-task history tables; when the two disagree, trust `PROGRESS.md` + the code.
>
> **Last updated:** 2026-07-05 — **Broker pivot: M04 rescoped to Alpaca; M04A scrapped.** IBKR Web API consumer approval never cleared for the Interactive Israel account, and the gateway path's operational constraints (weekly dormancy re-auth, one session per Gateway boot) made it a dead end without M04A. Decision recorded in `docs/adr/041-alpaca-over-ibkr.md`; `04-webhook-ingest-and-ibkr.md` rewritten around `AlpacaAdapter` (filename kept); the M04A spec moved to `archived/04A-IBKR-Web-API.md` with a SCRAPPED banner. Phase 04 Phase B–F remain not-started and now target Alpaca.
>
> **Previous update:** 2026-05-08 — **M00 closed.** All ten AC-00-* criteria pass (two renegotiated and documented in `00-scoping-and-setup.md` and the `v0.0.0-scaffold` tag annotation: AC-00-1 — branch protection rule saved-not-enforced on free-tier private repo; AC-00-8 — `process_resident_memory_bytes` deferred because multi-process gunicorn excludes the prometheus_client `process_*` collector by design). Manual items 00.9.2 (branch protection), 00.9.4 (Sentry DSN — backend project live, both Railway envs configured, AC-00-7 verified), 00.9.6 (docker-compose smoke — all 7 services boot via `make up`, AC-00-2/3/4/5/8/9/10 verified via Chrome MCP), 00.9.7 (staging deploy verified — running 16+ hours, M01–M03 shipped through it), and 00.9.8 (`v0.0.0-scaffold` tag pushed, points to commit `264d90f`) all flipped to ✅. System Health dashboard 00.7.5b live at `https://yuval3000.grafana.net/d/stp-system-health`. Phase 10 carries forward three observability items as §6.5 carryover (move `/metrics` outside Django middleware, exporter wiring, Trading/Data/Backtest dashboards). Tag list on origin: `v0.0.0-scaffold`, `v0.1.0-auth`, `v0.1.1-auth-metrics`, `v0.2.0-mfa`, `v0.2.5-oauth-google`, `v0.3.0-strategies`. **Cleared to start M04.**

## Production Environment

| | |
|---|---|
| Project | `https://railway.com/project/17060567-b194-4926-a7c0-7f339e306bdf` |
| Backend | `https://backend-production-f3e8.up.railway.app` |
| Frontend | `https://frontend-production-c977f.up.railway.app` |
| Bootstrapped | 2026-05-02 |
| Runbook | `docs/runbooks/prod-bootstrap.md` |
| KEK rotation | `docs/runbooks/mfa-kek-rotation.md` |

Staging URLs remain at `backend-staging-4b6d.up.railway.app` and `frontend-staging-9011.up.railway.app`.

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

**Status:** ✅ Done — tag `v0.0.0-scaffold` pushed
**Started:** 2026-04-16
**Completed:** 2026-05-08

### 00.1 Repository & Monorepo Structure

| # | Task | Status | Notes |
|---|------|--------|-------|
| 00.1.1 | Create monorepo directory layout (backend/, frontend/, docker/, docs/, etc.) | ✅ Done | Scaffolded locally — push to GitHub next |
| 00.1.2 | .gitignore (Python, Node, Angular, JetBrains, VS Code, .env*) | ✅ Done | |
| 00.1.3 | GitHub repo `yhaspel/StratTraderPro` created | ✅ Done | Live at `github.com/yhaspel/StratTraderPro` (path differs from original plan of `yuval3000/strattraderpro`) |
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
| 00.5.1 | Create Railway project | ✅ Done | Project `17060567-b194-4926-a7c0-7f339e306bdf`; staging + prod environments both live |
| 00.5.2 | Configure services (backend, worker, beat, frontend) | ✅ Done | Verified during M01.11.9 (7 services Online on staging); prod bootstrapped 2026-05-02 |
| 00.5.3 | Add Postgres 16 + Redis 7 plugins | ✅ Done | |
| 00.5.4 | Set environment variables | ✅ Done | |
| 00.5.5 | Health check paths configured | ✅ Done | /healthz, /readyz |
| 00.5.6 | Railway CLI + service account token | ✅ Done | Stored in GitHub Actions secrets — staging deploy workflow (`deploy-staging.yml`) is green |

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
| 00.7.5a | Grafana Cloud account | ✅ Done | `yuval3000.grafana.net` live since M01.11.5 (2026-05-01); hosts Auth Health dashboard at `/d/stp-auth-health` and the `auth-health-email` contact point. Prometheus scraping `/metrics` from staging + prod backend services. |
| 00.7.5b | System Health dashboard (infra) | ✅ Done | Live at `https://yuval3000.grafana.net/d/stp-system-health`. Dashboard JSON checked in at `infra/grafana/system-health-dashboard.json` (15 panels across 6 rows). v0 had a Process Resources row; replaced with **Application Activity** (top-10 routes by request rate, top-10 by p95 latency, 4xx by view) on 2026-05-08 because multi-process gunicorn excludes the prometheus_client `process_*` collector — same constraint that drove the AC-00-8 renegotiation. Verified via Chrome MCP on 2026-05-08: Backend Health row populates with both `staging` and `production` UP, Application Activity shows real per-route data once user traffic flows, Django DB row populates after the `_wrap_db_engines_for_prometheus` helper rolled out (commit `9d9c4bd`). Postgres/Redis/Celery exporter row + M04 placeholder rows render "No data" gracefully (intentional). Panels-only in v1; alerting deferred. M10 §6.5 carries forward the exporter wiring + the Trading Ops / Data Pipelines / Backtest Ops dashboards (see Phase 10 carryover table). |

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
| 00.9.1 | Push to GitHub | ✅ Done | `github.com/yhaspel/StratTraderPro`, origin set |
| 00.9.2 | Enable branch protection | ✅ Done | Classic branch protection rule on `main` configured 2026-05-08: require PR before merging (0 required approvals so solo dev can self-merge), require Backend+Frontend+Trivy+E2E status checks, require branches up to date, require linear history, no force-push, no deletions. **Per AC-00-1 renegotiation, the rule is saved-but-not-enforced** on the personal-private free-tier repo until plan upgrade or repo public visibility — see CHANGELOG `[Unreleased]` entry under "Changed — Plan (M00 AC renegotiations)" and the v0.0.0-scaffold tag annotation. |
| 00.9.3 | Create Railway project + services | ✅ Done | Staging + prod both running |
| 00.9.4 | Create Sentry project, get DSN | ✅ Done | Backend Sentry project `strattraderpro-backend` live at `yuval3000.sentry.io`. `SENTRY_DSN` env var set on Railway backend service in both `staging` and `production` environments 2026-05-08; both backends redeployed and confirmed initializing the SDK. AC-00-7 verified via `railway run --service backend --environment staging python -c "..."` issuing a `capture_message` that landed in Sentry within seconds. Frontend Sentry project deferred (skeleton already wired in `frontend/src/main.ts` per M00.7.4; wire the DSN when frontend error capture becomes valuable). One known interaction surfaced during rollout: an `AttributeError: 'coroutine' object has no attribute 'headers'` on every `/metrics` scrape (allauth + ASGI + sentry-sdk's `SentryASGIMixin` mismatch) — mitigated immediately via a `before_send` filter in `prod.py` that drops the noisy event before it counts toward the 5K/month free-tier quota; underlying fix tracked as Phase 10 §6.5 carryover (10.6.5.a). |
| 00.9.5 | Create Grafana Cloud account + dashboard | ✅ Done | Account live at `yuval3000.grafana.net` (M01.11.5 — Auth Health dashboard). System Health dashboard added 2026-05-08 (see 00.7.5b). |
| 00.9.6 | Run `docker compose up` and verify local stack | ✅ Done | Smoke test 2026-05-08 via Chrome MCP against `localhost`. All 7 services boot via `make up` (now equivalent to `docker compose --profile tunnel up -d` after the Makefile change in commit `c5a084b`): postgres, redis, backend, worker, beat, frontend, ngrok. AC-00-2/3/4/5/8/9/10 all verified in one pass — `/healthz` `{"status":"ok"}`, `/readyz` `{"checks":{"db":"ok","redis":"ok"}}`, frontend renders the `app.status` translated key, OpenAPI schema returns 29 paths under title "StratTraderPro API", `/metrics` emits `django_http_requests_total_by_view_transport_method_total` plus `django_db_query_duration_seconds_bucket` (django_prometheus engine wrapper confirmed live locally), ngrok tunnel forwards to `http://backend:8777`. README §3 updated to reflect the new `make up` behavior. |
| 00.9.7 | Trigger staging deploy and verify AC-00-* | ✅ Done | Staging has been running for 16+ hours with M01–M03 all shipped through it. AC-00-3/4/5 verified against the public staging URLs `backend-staging-4b6d.up.railway.app` and `frontend-staging-9011.up.railway.app` throughout the M02/M2.5/M03 verification rounds; re-confirmed during the M00.9.6 smoke 2026-05-08. CI green on the latest commit (#85). |
| 00.9.8 | Tag `v0.0.0-scaffold` | ✅ Done | Pushed 2026-05-08 to commit `264d90f` (M00 initial scaffold). Annotation documents both the AC-00-1 (branch-protection enforcement) and AC-00-8 (`process_resident_memory_bytes`) renegotiations. Tag object SHA `49adcc91`. Verify with `git ls-remote --tags origin v0.0.0-scaffold`. |

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

**Status:** ✅ Done — tag `v0.2.0-mfa` pushed
**Started:** 2026-05-01
**Completed:** 2026-05-02 (implementation) / 2026-05-03 (final stabilization + tag)

> See `02-mfa-and-user-profile.md` for full spec.

### 02.1 Backend — MFA core

| # | Task | Status | Notes |
|---|------|--------|-------|
| 02.1.1 | Dependencies: pyotp, qrcode[pil], cryptography | ✅ Done | `backend/requirements/base.txt` |
| 02.1.2 | Settings: `MFA_ENABLED`, `FERNET_KEK` (dev default derived from SECRET_KEY), `MFA_TOKEN_TTL_MINUTES`, `MFA_TOTP_VALID_WINDOW`, `MFA_TOTP_ISSUER`, `MFA_BACKUP_CODE_COUNT` | ✅ Done | `config/settings/base.py` |
| 02.1.3 | Models: `MFADevice`, `BackupCode`, `UserProfile` + `User.mfa_enabled` derived property + `RefreshTokenFamily.{user_agent,ip,last_used_at}` + 9 new `AuthEvent.EventType` values | ✅ Done | `apps/users/models.py` |
| 02.1.4 | Migration `users.0002_mfa_and_profile` | ✅ Done | Renamed from auto-generated suffix. Applies cleanly. |
| 02.1.5 | Auto-create `UserProfile` via `post_save` signal | ✅ Done | `apps/users/signals.py`; `UsersConfig.ready` wires it |
| 02.1.6 | MFA service: Fernet wrap/unwrap, TOTP gen+verify (±1 window), QR PNG, backup codes (gen+consume), `mfa_token` (issue+decode) | ✅ Done | `apps/users/mfa.py` |
| 02.1.7 | Profile/sessions service helpers: `serialize_profile`, `serialize_session` w/ masked IP + UA summary, `list_user_sessions`, `revoke_other_sessions` | ✅ Done | `apps/users/services.py` |
| 02.1.8 | `IsAuthenticatedAndMFAEnforced` permission + `custom_exception_handler` mapping `PermissionDenied("MFA_REQUIRED")` → structured 403 | ✅ Done | `apps/users/permissions.py`, `apps/users/exception_handler.py` |
| 02.1.9 | MFA views: enroll, enroll/confirm, verify (rate-limited 5/min/mfa_token), disable, backup-codes/regenerate (password+TOTP per defense-in-depth) | ✅ Done | `apps/users/views_m02.py` |
| 02.1.10 | LoginView modified: enrolled users get `{mfa_required, mfa_token}` instead of token pair | ✅ Done | |
| 02.1.11 | Profile/sessions/password-change views under `/users/me/{update,password,sessions,sessions/revoke}/` | ✅ Done | |
| 02.1.12 | Scaffold MFA-protected pings: `/api/v1/{brokers,orders,risk,strategies}/ping/` with `mfa_required=True` | ✅ Done | `apps/{brokers,orders,risk,strategies}/views.py` + `urls.py` mounted in `config/urls.py` |
| 02.1.13 | MFA Prometheus counters: `auth_mfa_{enrollments,verifications,backup_used,challenge_failures}_total` | ✅ Done | `apps/users/metrics_m02.py` |
| 02.1.14 | Email templates: `mfa_enabled.{txt,html}`, `mfa_disabled.{txt,html}` | ✅ Done | |
| 02.1.15 | Admin: register `MFADevice`, `BackupCode`, `UserProfile`; bulk action "Force-disable MFA (audited; emails the user)" | ✅ Done | `apps/users/admin.py` |
| 02.1.16 | Tests: 36 new in `test_mfa.py` covering Fernet roundtrip, TOTP correctness (incl. ±step), backup-code single-use + regenerate wipe, full enroll/login/disable HTTP flow, MFA enforcement on all 4 protected prefixes, profile validation, password-change family revocation, sessions list/revoke. Total backend pytest: 66 passing. | ✅ Done | |

### 02.2 Frontend — Angular

| # | Task | Status | Notes |
|---|------|--------|-------|
| 02.2.1 | Domain models: `LoginResult` discriminated union, `UserProfile`, `Session`, `MFAEnrollResponse`, etc. | ✅ Done | `core/models/auth.models.ts` |
| 02.2.2 | API service: 11 new methods on `AuthApi` covering MFA, profile, sessions, password change | ✅ Done | `core/services/auth.api.ts` |
| 02.2.3 | `AuthStore` extended with `mfa_pending` status + in-memory-only `mfaToken` signal (never persisted) | ✅ Done | |
| 02.2.4 | `AuthFacade`: `verifyMfa`, `cancelMfa`; login routes to `/login/mfa` when `mfa_required=true` | ✅ Done | |
| 02.2.5 | New facades: `ProfileFacade`, `MfaFacade`, `SessionsFacade` | ✅ Done | |
| 02.2.6 | `TotpInputComponent` — 6-cell, paste-aware, keyboard-navigable | ✅ Done | `features/auth/totp-input/` |
| 02.2.7 | `MfaChallengeComponent` at `/login/mfa` with backup-code toggle | ✅ Done | |
| 02.2.8 | `MfaSetupComponent` 4-step wizard at `/settings/security/mfa/setup` (intro → QR → verify → backup codes) | ✅ Done | |
| 02.2.9 | `SecurityComponent` at `/settings/security` (MFA enable/disable + regenerate + sessions list + password change) | ✅ Done | |
| 02.2.10 | `ProfileComponent` at `/settings/profile` with searchable IANA timezone via `Intl.supportedValuesOf` | ✅ Done | |
| 02.2.11 | i18n keys: `mfa.*`, `security.*`, `profile.*` | ✅ Done | `assets/i18n/en.json` |
| 02.2.12 | Help page `assets/help/mfa.html` | ✅ Done | |

### 02.3 Documentation

| # | Task | Status | Notes |
|---|------|--------|-------|
| 02.3.1 | ADR-020 — TOTP over SMS | ✅ Done | `docs/adr/020-totp-over-sms.md` |
| 02.3.2 | Runbook — user lost MFA (with identity-check checklist + admin bulk action) | ✅ Done | `docs/runbooks/user-lost-mfa.md` |
| 02.3.3 | Runbook — KEK rotation (envelope-encryption pattern via `MultiFernet`) | ✅ Done | `docs/runbooks/mfa-kek-rotation.md` |
| 02.3.4 | CHANGELOG.md entry under `[Unreleased]` | ✅ Done | |
| 02.3.5 | Tag `v0.2.0-mfa` | ✅ Done | Pushed 2026-05-02 |
| 02.3.6 | Stabilization: ratelimit lambda for `/auth/mfa/verify/` was using DRF-only `request.data` (django-ratelimit wraps before DRF) — caused 500 in production despite green tests. Switched key to `"ip"`, added regression test with `@override_settings(RATELIMIT_ENABLE=True)`. | ✅ Done | Commit `7624262`. Found during M2.5 OAuth → MFA smoke test on staging. |

---

## Phase 02.5 — Google OAuth Sign-in / Sign-up

**Status:** ✅ Done — tag `v0.2.5-oauth-google` pushed
**Started:** 2026-05-02
**Completed:** 2026-05-03

> Inserted between M02 and M03 because users wanted a one-click sign-up
> path before the trading milestones land. M2.5 reuses the M01 JWT family
> pipeline and the M02 MFA gate — Google proves email control, not
> second-factor ownership. See `docs/adr/021-google-oauth-allauth.md` for
> the full decision rationale and account-linking semantics.

### 02.5.1 Backend — django-allauth bridge + JWT issuance

| # | Task | Status | Notes |
|---|------|--------|-------|
| 02.5.1.1 | Dependencies: `django-allauth` (state machine only), `dj-rest-auth` | ✅ Done | `backend/requirements/base.txt` |
| 02.5.1.2 | Settings: `INSTALLED_APPS` adds `django.contrib.sites`, `allauth.*`, Google provider; `AUTHENTICATION_BACKENDS` adds `allauth.account.auth_backends.AuthenticationBackend` alongside our `ModelBackend`; `AccountMiddleware` added; `SITE_ID = 1`; `LOGIN_REDIRECT_URL` points at our post-callback view; `ACCOUNT_AUTHENTICATION_METHOD="email"`, `ACCOUNT_EMAIL_VERIFICATION="none"` (we run our own); `GOOGLE_OAUTH_ENABLED`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `OAUTH_EXCHANGE_TTL_MINUTES` (default 5) | ✅ Done | `config/settings/base.py` |
| 02.5.1.3 | `OAuthExchangeCode` model — single-use sha256-hashed code, 5-min TTL, keeps JWT pair off the redirect URL | ✅ Done | `apps/users/models.py` |
| 02.5.1.4 | Migration `users.0003_oauth_exchange_code` | ✅ Done | Applies cleanly on staging + prod |
| 02.5.1.5 | Custom adapters: `AccountAdapter` blocks local signup (`is_open_for_signup=False` so allauth's parallel signup form is dead); `SocialAdapter.populate_user` sets `display_name` from Google's `name`, `is_verified=True`; `SocialAdapter.pre_social_login` auto-links by verified email via `sociallogin.connect()` | ✅ Done | `apps/users/social_adapters.py` |
| 02.5.1.6 | Three OAuth endpoints: `GET /api/v1/auth/oauth/google/start/` (302s to Google's authorize URL via allauth's stock `oauth2_login`), `GET /api/v1/auth/oauth/google/callback/` (allauth's stock callback — registered in Google Cloud Console), `POST /api/v1/auth/oauth/exchange/` (swaps single-use code for `{access, refresh, user}` OR `{mfa_required, mfa_token}`) | ✅ Done | `apps/users/views_oauth.py` |
| 02.5.1.7 | `OAuthPostCallbackView` — `LOGIN_REDIRECT_URL` target. Tears down allauth's session login, mints exchange code, 302s to frontend with `?exchange=<code>`. **Uses `SessionAuthentication` explicitly** because DRF's default `JWTAuthentication` doesn't read Django's session, which allauth's `complete_social_login` writes to. | ✅ Done | `apps/users/views_oauth.py` |
| 02.5.1.8 | URL stubs: `auth/oauth/google/{login,callback}/` mounted (allauth needs them for state-token URL reverse), `auth/account/{login,signup}/` redirect to frontend `/login` and `/register` (allauth bundled error templates reference `{% url 'account_login' %}`) | ✅ Done | `apps/users/urls.py` |
| 02.5.1.9 | MFA gate preserved — exchange returns `{mfa_required: true, mfa_token}` for users with `mfa_enabled=True`. Same response shape as password login, frontend's `/login/mfa` route handles both. | ✅ Done | |
| 02.5.1.10 | Audit events: `OAUTH_LOGIN_OK`, `OAUTH_USER_CREATED`, `OAUTH_LINKED`, `OAUTH_EXCHANGE_OK`, `OAUTH_EXCHANGE_FAIL` added to `AuthEvent.EventType` | ✅ Done | |
| 02.5.1.11 | Prometheus counters: `auth_oauth_login_total{result}`, `auth_oauth_exchange_total{result}` | ✅ Done | `apps/users/metrics_oauth.py` |
| 02.5.1.12 | Email templates: `oauth_account_created.{txt,html}`, `oauth_account_linked.{txt,html}` (latter so a real user notices an attacker linking their Google to a stolen account) | ✅ Done | |
| 02.5.1.13 | Tests: 24 in `apps/users/test_oauth.py` covering `OAuthExchangeCode` (issue, consume, single-use, expiry, replay rejection, inactive user); `SocialAdapter` (auto-link with verified email, refusal to link unverified, no-op on already-linked); `OAuthExchangeView` (happy path, MFA gate, invalid/expired/consumed code, audit events, feature-disabled 503); `OAuthGoogleStartView` (returns valid Google authorize URL with state token, refuses when disabled or unconfigured). Total backend pytest at HEAD: **91 passing**. | ✅ Done | |

### 02.5.2 Frontend — Angular

| # | Task | Status | Notes |
|---|------|--------|-------|
| 02.5.2.1 | `GoogleButtonComponent` — brand-compliant Google G logo SVG, white background per their brand guidelines | ✅ Done | `features/auth/google-button/` |
| 02.5.2.2 | "Continue with Google" rendered above the email/password form on `/login` and `/register`, OR divider, i18n key `oauth.or` | ✅ Done | |
| 02.5.2.3 | `OauthCallbackComponent` at `/oauth/callback` — handles `?exchange=<code>` (POSTs to exchange endpoint, routes to `/dashboard` or `/login/mfa`) or `?error=oauth_failed` (renders message + retry link) | ✅ Done | |
| 02.5.2.4 | `AuthFacade.startGoogleSignIn()` — uses absolute backend URL from `window.STP_CONFIG.backendUrl` (not the same-origin `/api/` proxy) so the Django session cookie set during `/start/` lives on the backend domain and survives the bounce back from Google | ✅ Done | `abstraction/facades/auth.facade.ts` |
| 02.5.2.5 | `AuthFacade.completeGoogleSignIn(code)` — exchange call, MFA-pending routing | ✅ Done | |
| 02.5.2.6 | i18n keys under `oauth.*` (button label, OR divider, callback messages, error states) | ✅ Done | `assets/i18n/en.json` |

### 02.5.3 Infrastructure & manual setup

| # | Task | Status | Notes |
|---|------|--------|-------|
| 02.5.3.1 | Google Cloud Console: existing `strattraderpro` project, OAuth consent screen configured, `StratTraderPro Web` OAuth 2.0 Web client created with 3 redirect URIs (localhost dev + staging + prod), `yuval3000@gmail.com` added as test user. App still in **Testing mode** — publish to In Production before opening sign-up to anyone outside the test-user list. | ✅ Done | Walkthrough in `docs/runbooks/google-oauth-setup.md` |
| 02.5.3.2 | `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET` set in Railway env for **both** staging and prod backend services | ✅ Done | Set 2026-05-02 via Railway dashboard. Never committed. |
| 02.5.3.3 | nginx runtime config injection: new `location = /config.js` block in `docker/nginx.conf.template` returns `window.STP_CONFIG = { backendUrl: '${BACKEND_URL}' }`, substituted at container start by the official nginx image's envsubst step. Frontend's `index.html` loads it before Angular bundles. Solves OAuth cookie-domain mismatch by giving the SPA the absolute backend URL at runtime. | ✅ Done | `docker/nginx.conf.template`, `frontend/src/index.html` |
| 02.5.3.4 | Smoke-test prod and staging: register, sign in via Google, MFA challenge correctly demanded for MFA-enrolled accounts, `/api/v1/auth/oauth/exchange/` returns `{access, refresh, user}` on success | ✅ Done | Verified via Chrome connector against staging on 2026-05-02; prod auth flow verified 2026-05-03 (signed in + `/users/me/` returned 200 with valid Bearer token). |

### 02.5.4 Stabilization fixes (post-implementation, pre-tag)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 02.5.4.1 | OAuth state-cookie loss (`PermissionDenied` at `verify_and_unstash_state`): fixed by returning allauth's stock 302 directly from `/start/` (top-level navigation, not XHR — the session cookie has to live on the backend domain), plus added `account_login` URL alias for allauth's bundled error templates | ✅ Done | Commit `71ccb62` |
| 02.5.4.2 | OAuth cookie-domain mismatch: routed `/start/` through backend's absolute URL via the new `window.STP_CONFIG` mechanism (see 02.5.3.3) | ✅ Done | Commit `cc35e37` |
| 02.5.4.3 | OAuth post-callback hit `?error=oauth_failed`: `OAuthPostCallbackView` was missing `authentication_classes = [SessionAuthentication]`, so DRF's default `JWTAuthentication` couldn't see the Django session that allauth's `complete_social_login` had just written. Added the override. | ✅ Done | Commit `cc6c03d` |
| 02.5.4.4 | Auth-guard let unauthenticated users into `/dashboard` when localStorage was wiped but the in-memory signal was stale (e.g. after refresh-interceptor's logout-on-401). Now requires both `store.isAuthenticated() && store.refreshToken()` — wiped persistence forces redirect to `/login`. | ✅ Done | Commit `542a11c`. `frontend/src/app/core/guards/auth.guard.ts` |
| 02.5.4.5 | nginx `Cache-Control: no-store` on `index.html` — every deploy serves the fresh bundle hash without `?cb=` query string. Hashed JS/CSS keep their immutable 1y cache. | ✅ Done | Commit `542a11c`. `docker/nginx.conf.template` |
| 02.5.4.6 | `/login` submit button stuck disabled after register: `register()` was calling `store.setLoading()` and navigating to `/resend-verification` without resetting status, so when the user came back to `/login` the button was permanently disabled (`form.invalid \|\| status === 'loading'`). Added `AuthStore.setIdle()` (no-op if authed/mfa_pending), call it in `register()` success path, and defensive `resetFormState()` calls in `LoginComponent` + `RegisterComponent` constructors as belt-and-suspenders for any future `startGoogleSignIn`-style leaks. Pinned with a regression test. | ✅ Done | Commit `24e0a80` |

### 02.5.5 Documentation

| # | Task | Status | Notes |
|---|------|--------|-------|
| 02.5.5.1 | ADR-021 — Google OAuth via django-allauth, with custom JWT bridge | ✅ Done | `docs/adr/021-google-oauth-allauth.md` (149 lines) |
| 02.5.5.2 | Runbook — Google OAuth setup (GCP project + consent screen + Web client + redirect URIs + test users + publishing flow + secret rotation + failure modes) | ✅ Done | `docs/runbooks/google-oauth-setup.md` (167 lines) |
| 02.5.5.3 | CHANGELOG.md entry under `[Unreleased]` covering all M2.5 surface area + the prod-bootstrap work that landed alongside | ✅ Done | |
| 02.5.5.4 | Tag `v0.2.5-oauth-google` | ✅ Done | Pushed 2026-05-03 |
| 02.5.5.5 | macOS Finder duplicate files cleanup (` 2.*` suffix on 10 files across `docs/` and `frontend/src/`) — harmless artifacts from earlier sync events, removed for tidiness | ✅ Done | Commit `c18172a` |

### Known follow-ups (deferred — slot into M03 or beyond)

- **Frontend env badge** still hardcodes "Platform scaffold — staging environment" via the `app.status` i18n key on both staging and prod. Needs an env-aware key swap (probably from build-time `environment.*.ts` since runtime `STP_CONFIG` already exists for the backend URL — could be extended).
- **Login error envelope handling**: when the backend returns 401 `INVALID_CREDENTIALS`, the refresh interceptor retries the call, the second response is parsed differently, and the user sees `auth.login.error.UNKNOWN` instead of "Invalid email or password". Pre-existing from M01, exists on both envs.
- **`DJANGO_SETTINGS_MODULE` is `config.settings.prod`** in BOTH staging and prod envs — only `RAILWAY_ENVIRONMENT_NAME` differentiates them. Acceptable today but worth a `staging.py` settings split if/when staging needs to diverge (wider CORS for testing, DEBUG toolbar, looser HSTS).

---

## Phase 03 — Strategies & Webhook Config

**Status:** ✅ Done — tag `v0.3.0-strategies` pushed (commit `a7f746c`)
**Started:** 2026-05-03
**Completed:** 2026-05-03

> See `03-strategies-and-webhook-config.md` for full spec.

### 03.1 Backend — models, migration, validators

| # | Task | Status | Notes |
|---|------|--------|-------|
| 03.1.1 | `Strategy`, `StrategyFile`, `WebhookConfig` models | ✅ Done | `apps/strategies/models.py`. Soft-delete via `is_enabled`. `unique_together = (owner, slug)` on Strategy and `(user, strategy)` on WebhookConfig. |
| 03.1.2 | Migration `strategies.0001_initial` | ✅ Done | Handwritten, applies cleanly, `makemigrations --check` clean. |
| 03.1.3 | Validators: 3-file bundle + JSON Schema (Draft 2020-12) | ✅ Done | `apps/strategies/validators.py` — stem regex, size limits, pine `//@version=` check, required webhook keys, path-traversal + null-byte rejection, XSS substring scan. |
| 03.1.4 | Services: secret encrypt/rotate, webhook URL builder, default schema/template, seed upserts | ✅ Done | `apps/strategies/services.py` — reuses M02 Fernet KEK. `rotate_secret()` is destructive + version-bumping. |
| 03.1.5 | Serializers: read, update, upload, webhook-config | ✅ Done | `apps/strategies/serializers.py`. `StrategyUploadSerializer.accept_untested_risk` enforces AC-03-5. |
| 03.1.6 | `jsonschema>=4.21,<5.0` added to `requirements/base.txt` | ✅ Done | |

### 03.2 Backend — views, URLs, permissions, metrics, admin

| # | Task | Status | Notes |
|---|------|--------|-------|
| 03.2.1 | `StrategiesListCreateView` (GET list + POST upload) | ✅ Done | Multipart parser. `STRATEGY_FILE_*` error codes returned via standard envelope. |
| 03.2.2 | `StrategyDetailView` (GET / PATCH / DELETE) | ✅ Done | Soft-delete on user strategies. System rows return `STRATEGY_SYSTEM_IMMUTABLE` 403 on modify/delete. |
| 03.2.3 | `StrategyFileDownloadView` (GET file bytes) | ✅ Done | Content-type per kind (text/plain or application/json). |
| 03.2.4 | `WebhookConfigView` (GET reveal-once / PUT update) | ✅ Done | First GET creates row + reveals secret. PUT validates schema (Draft 2020-12) and template-vs-schema. |
| 03.2.5 | `WebhookConfigRotateView` (POST rotate) | ✅ Done | Returns new secret + URL + version. Bumps Prometheus counter. |
| 03.2.6 | `WebhookConfigDryRunView` (POST validate against saved schema) | ✅ Done | Does NOT touch the M04 webhook ingest (which doesn't exist yet). |
| 03.2.7 | Permission helpers: `can_user_view`/`modify`/`delete` | ✅ Done | `apps/strategies/permissions.py`. System rows: only staff can edit via Django admin. |
| 03.2.8 | Prometheus metrics: uploads / rotations / count gauge | ✅ Done | `apps/strategies/metrics.py`. Wired in views. |
| 03.2.9 | Admin: Strategy + StrategyFile (inline) + WebhookConfig | ✅ Done | `apps/strategies/admin.py`. WebhookConfig admin has `has_add_permission=False`. |
| 03.2.10 | URLs mounted under `/api/v1/strategies/` | ✅ Done | `apps/strategies/urls.py` replaces the M02 ping stub. M02 sweep test updated to hit `/strategies/` instead. |
| 03.2.11 | Settings: `STRATEGIES_V1_ENABLED`, `STRATEGY_WEBHOOK_BASE_URL` | ✅ Done | Feature flag returns 503 from all endpoints when False. |

### 03.3 Backend — `load_strategies` management command

| # | Task | Status | Notes |
|---|------|--------|-------|
| 03.3.1 | Walks one level deep, idempotent via SHA-256 | ✅ Done | `apps/strategies/management/commands/load_strategies.py`. |
| 03.3.2 | `--dry-run` flag + grep-friendly summary | ✅ Done | Prints `seeded=N updated=M skipped=K errors=J`. Exit code non-zero on partial failure. |
| 03.3.3 | Adapts to real Trading Strategies layout | ✅ Done | Globs any `*.pine` + `*description*.txt`. Synthesizes default `_Webhook.json` when missing (uses `services.default_payload_template(slug)`). |
| 03.3.4 | Integration test with fixture directory | ✅ Done | `LoadStrategiesCommandTests` covers happy path, idempotent rerun, dry-run, webhook synthesis. |

### 03.4 Backend — tests

| # | Task | Status | Notes |
|---|------|--------|-------|
| 03.4.1 | Validator unit tests (10 test methods) | ✅ Done | Happy path + 9 rejection branches (filename mismatch, oversize, bad JSON, missing keys, path traversal, null byte, XSS sig, stem regex, schema-invalid, payload-mismatch). |
| 03.4.2 | View tests for AC-03-2..AC-03-12 | ✅ Done | 27 test methods spanning list/upload/detail/delete/webhook/rotation/dry-run/MFA enforcement/feature flag. |
| 03.4.3 | Multi-tenant isolation | ✅ Done | User A cannot see/modify/delete user B's strategies. |
| 03.4.4 | Secret-not-in-logs regression test | ✅ Done | `SecretLeakTests.test_rotation_log_does_not_contain_secret`. |
| 03.4.5 | Full backend pytest run | ✅ Done | **128/128 passing** (+37 from M03). M02 sweep test in `test_mfa.py` updated for the new `/strategies/` endpoint. |

### 03.5 Frontend — core + abstraction layer

| # | Task | Status | Notes |
|---|------|--------|-------|
| 03.5.1 | Domain models | ✅ Done | `core/models/strategies.models.ts` — `Strategy`, `WebhookConfig`, `WebhookRotateResponse`, `StrategyUploadPayload`. |
| 03.5.2 | API service | ✅ Done | `core/services/strategies.api.ts` — typed HTTP for all 8 endpoints. |
| 03.5.3 | Signal store | ✅ Done | `abstraction/stores/strategies.store.ts` — counts, upsert, remove, per-strategy webhook config cache, reveal-once secret wipe. |
| 03.5.4 | Facade | ✅ Done | `abstraction/facades/strategies.facade.ts` — load/upload/toggle/softDelete/loadWebhookConfig/updateWebhookConfig/rotateWebhookSecret/dryRunWebhook. |

### 03.6 Frontend — feature components + routes

| # | Task | Status | Notes |
|---|------|--------|-------|
| 03.6.1 | `StrategiesListComponent` at `/strategies` | ✅ Done | System badge + amber "User-uploaded" banner. Inline enable/disable toggle. Configure-webhook + Delete actions per row. |
| 03.6.2 | `StrategiesUploadComponent` at `/strategies/upload` | ✅ Done | 3-step wizard (single file). Live filename validation. Mandatory acknowledge checkbox before submit. |
| 03.6.3 | `WebhookConfigModalComponent` | ✅ Done | URL row + reveal-once secret + Rotate (with confirm) + JSON Schema editor + payload-template editor + Test (dry-run) + Copy TradingView template. Monaco lazy-imported via `import('monaco-editor')` so the chunk only loads on modal open; textarea fallback keeps it accessible regardless. |
| 03.6.4 | `StrategiesDetailComponent` at `/strategies/:id` | ✅ Done | Pine + description previews (escaped via Angular default text binding). |
| 03.6.5 | Lazy-loaded `STRATEGIES_ROUTES`, mounted in `app.routes.ts` | ✅ Done | All routes guarded by `authGuard`; backend enforces MFA. |
| 03.6.6 | i18n keys: `strategies.*` + `webhook.*` | ✅ Done | Added to `assets/i18n/en.json`. |
| 03.6.7 | Frontend test: store unit | ✅ Done | `strategies.store.spec.ts` — counts, upsert, remove, reveal-once wipe. |

### 03.7 Documentation

| # | Task | Status | Notes |
|---|------|--------|-------|
| 03.7.1 | ADR-030 — strategy 3-file contract | ✅ Done | `docs/adr/030-strategy-3-file-contract.md`. |
| 03.7.2 | ADR-031 — webhook HMAC rotation + reveal-once | ✅ Done | `docs/adr/031-webhook-hmac.md`. |
| 03.7.3 | Runbook — strategy import from Cowork | ✅ Done | `docs/runbooks/strategy-import-from-cowork.md`. |
| 03.7.4 | Help page — Upload your first strategy | ✅ Done | `frontend/src/assets/help/strategy-upload.html`. |
| 03.7.5 | Help page — Configure your TradingView alert | ✅ Done | `frontend/src/assets/help/tradingview-alert-config.html`. |
| 03.7.6 | CHANGELOG entry under `[Unreleased]` | ✅ Done | |

### 03.8 Deploy + seed + smoke test (post-implementation)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 03.8.1 | Monaco npm import → reverted to textarea-only | ✅ Done | `npm install monaco-editor` broke the production build because Angular 19's stock esbuild has no `.ttf` loader for Monaco's codicon CSS chain. Removed from `package.json`. Modal still works via the textarea editor (live JSON-validated). Decision documented in modal docstring + `reference_monaco_angular_esbuild.md` memory. CDN AMD loader is the official fallback path if Monaco UX becomes important in a later milestone. |
| 03.8.2 | `load_strategies` against real Trading Strategies path | ✅ Done | Path: `/Users/yuval3000/Claude Projects/Trading Strategies/Trading Strategies/top-strategies` — seeded 10 system strategies into staging Postgres on 2026-05-03. All 10 visible via `GET /api/v1/strategies/` and rendered in the list view. |
| 03.8.3 | Frontend smoke test on staging via Chrome MCP | ✅ Done | All 12 ACs walked through the deployed UI: list shows 10 system rows with **System** badges; webhook modal opens with URL + reveal-once secret + amber warning; Rotate increments V1→V2 with new 64-char secret; Copy TradingView template embeds the live secret in `sig`; dry-run validates good payloads (`"Payload validates against the saved schema."`); auth guard correctly redirects unauthenticated `/strategies` → `/login`; OAuth → MFA challenge → `/dashboard` flow works. |
| 03.8.4 | A11y audit (WCAG 2.1 AA via axe-core) | ✅ Done | Audited 4 surfaces: list (0 violations), upload wizard (0), detail (1 serious — fixed: `<pre>` blocks needed `tabindex=0` + `role=region` + `aria-labelledby`), webhook modal (1 critical — fixed: 4 form inputs needed `for=`/`id=` label pairing). Final: **0/0 across all 4 surfaces.** |
| 03.8.5 | Polish bug fixes (post-smoke-test) | ✅ Done | Two bugs found during smoke test, both fixed: (a) list view didn't re-fetch after webhook modal close so `has_webhook_config` was stale — `closeModal()` now calls `void this.facade.load()`; (b) dry-run 400 surfaced "Could not parse JSON: Http failure 400" instead of the real `STRATEGY_WEBHOOK_INVALID` message — `StrategiesFacade.dryRunWebhook` now catches `HttpErrorResponse`, unwraps the `appError` attached by the global error interceptor, and returns the structured envelope error. Modal `onTest()` restructured to disambiguate local JSON parse errors from server-side schema rejections. |
| 03.8.6 | CI gauntlet additions discovered the hard way | ✅ Done | Three CI failures recovered from in this milestone — each lesson saved to memory: NG5002/NG9 template errors (`feedback_angular_template_check.md` — must run `ngc`, not just `tsc`); ruff lint blocked Backend job (added to `feedback_local_ci_parity.md`); pnpm-lock.yaml drift (also in local-CI-parity memory; CI uses pnpm, NOT npm). |
| 03.8.7 | Tag `v0.3.0-strategies` | ✅ Done | Pushed to origin at commit `a7f746c` |

---

## Phase 04 — Webhook Ingest & Broker Adapter (Alpaca — rescoped 2026-07-05)

**Status:** 🚧 In Progress (Phase A — IBKR spike close-out complete; Phase B–F production code pending, now targeting **Alpaca** per ADR-041)
**Started:** 2026-05-09
**Completed:** —

> See `04-webhook-ingest-and-ibkr.md` for the full (rewritten) spec — filename kept for link stability.
> Debug loop for Day-1 spike close-out: `project-plan/debug-and-verifications/`.

### Phase A — Spike close-out (Day 1)

| # | Sub-task | Status | Notes |
|---|---|---|---|
| 04.A.1 | IB Gateway sidecar smoke test (STEPS 1-3, connect+place) | ✅ Done | Smoke (clientId 310) completed STEPS 1-3 cleanly during 2026-05-15 RTH after web-login re-auth cleared a 6-day paper-account dormancy. STEP 1 connect in 0.7 s (serverVersion 176); STEP 2 account summary 80 rows on `DUN167649`; STEP 3 order ack with `status=Filled brokerOrderId=5`. The web re-auth dormancy was the actual root cause of the morning's TimeoutError loop — config-render fixes (gotcha #7) plus TIF=DAY workaround (gotcha #8) were necessary but not sufficient until the account was reactivated via SSO. |
| 04.A.2 | RTH rerun (STEPS 4+5, fill+reconnect) | ✅ Done (with constraint) | STEP 4 fill captured during RTH: AAPL @ $299.15, qty=1, exchange ARCA, execId `0000e0d5.6a071c95.01.01`, commission $1.00. STEP 5 reconnect uncovered a new gnzsnz/ib-gateway:10.45.1e constraint: Gateway allows exactly one TWS-API session per process boot — reconnect (same clientId or rotated, 3-second or 30-second wait) silently drops every time after the first session disconnects. M04 plan §6.2 broker adapter must use container-per-session or Gateway-restart-on-disconnect. Documented in ADR-040 Findings A3 + ADR-041 (forthcoming production design). |
| 04.A.3 | ADR-040 finalized (Accepted) | ✅ Done | Status flipped to `Accepted (2026-05-15 — see Findings)`. New gotcha #7 captures the gnzsnz/ib-gateway:10.45.1e config-render trap and the sed-based Dockerfile fix; dead-end paths (JAVA_TOOL_OPTIONS clobber, vmoptions `-D` filter, `ENABLEAPI` invalid-for-Gateway) documented inline. Duplicate `## Consequences` header removed; no `TO BE FILLED IN` placeholders remain. |
| 04.A.4 | Spike artifacts promoted | ✅ Done | Runbook renamed `docs/runbooks/spike-ibkr-gateway.md` → `docs/runbooks/ib-gateway-reauth.md` and rewritten for production ops. Vestigial files (`docker/ib-gateway/entrypoint.sh`, `docker/ib-gateway/ibc-config.ini`) removed. Smoke script docstring updated to drop SPIKE framing. `docker/ib-gateway/README.md` gained a gnzsnz config-render callout. CI gate: `scripts/verify_ibgw_config.sh`. |
| 04.A.5 | Production env contract locked | ✅ Done | `docker-compose.yml` ib-gateway service has the full env contract. `backend/.env.example` documents the operator-facing subset. Railway setup commands generated in `project-plan/debug-and-verifications/railway-setup-commands.md` (manual user step). |

### Phase B–F — Production code (pending)

Following the rewritten M04 plan §6.1–§6.9 + §10–§14 (Alpaca). Not yet started.

### Decision (2026-07-05): scrap IBKR entirely; ship Phase B on Alpaca

The 2026-05-15 decision below chose "Gateway now, M04A (IBKR Web API OAuth) later." M04A's blocking prerequisite — IBKR developer-portal consumer approval — never cleared for the Interactive Israel account, which removed the durable IBKR path. Rather than build production code on the interim gateway transport (weekly dormancy re-auth, one session per Gateway boot), the first execution broker is now **Alpaca Trading API**: no application approval gate, free paper accounts, per-user API keys, REST + `trade_updates` WebSocket via `alpaca-py`.

- Full rationale + verified Alpaca facts: `docs/adr/041-alpaca-over-ibkr.md`.
- `BrokerAdapter` protocol unchanged — the M04A design invariant holds; only the concrete adapter changed.
- IBKR artifacts parked in-tree (ADR-040, `docker/ib-gateway/` behind a compose profile, re-auth runbook, spike script). `TWS_*` env scrub + credential rotation are M04 §6.9 tasks.
- The 2026-05-15 "carryover items to M04A" list below is void: dormancy heartbeat and Gateway-restart-reconnect have no Alpaca equivalent; M04A kickoff is cancelled.
- Open item for live trading later (M12+): confirm Alpaca live-account eligibility for Israeli residents (paper unaffected).

### Decision (2026-05-15): ship Phase B on TWS Socket API + Gateway sidecar; defer dormancy fix to M04A

After today's spike close-out surfaced two account-side constraints — (a) IBKR paper account silently disables headless TWS-API access after ~5–6 days without a web-portal touch, and (b) `gnzsnz/ib-gateway:10.45.1e` allows exactly one TWS-API session per Gateway process boot — we considered three paths forward before committing to Phase B:

1. Continue on TWS Socket API + Gateway as planned (M04 §6.1–§6.2), with **operator-side weekly web-portal login** as the interim dormancy mitigation (already documented in `docs/runbooks/ib-gateway-reauth.md`).
2. Add an automated browser-based "heartbeat web login" via Playwright on Celery beat (~1 day work).
3. Skip the gateway path entirely and ship Phase B directly on IBKR's Client Portal Web API with OAuth — i.e. fold **M04A** (already-scoped at `project-plan/04A-IBKR-Web-API.md`) forward into M04.

**Chosen:** Path 1. Rationale:

- `BrokerAdapter` protocol from M04 is unchanged in M04A by design (per `04A-IBKR-Web-API.md` §3). The transport (TWS Socket → REST/WebSocket) is rewritten in M04A, but everything else — contract modelling, order request/ack/fill domain, error handling, broker-status surfacing, observability, the WebSocket dashboard wiring — is identical and ships once. So days spent on TWS-API broker-adapter work in M04 are **not** thrown away when we migrate; the implementation under `apps/brokers/ibkr` is replaced by `apps/brokers/ibkr_webapi`, both implementing the same `BrokerAdapter` protocol.
- M04A's blocking prerequisite (IBKR developer-portal Web API enrollment + approval — §5 of that plan, 5–10 business-day lead time) hasn't been kicked off. Starting on Path 3 today would block the entire milestone behind IBKR approval timing we don't control.
- Path 2 (Playwright heartbeat) is brittle to IBKR portal UI changes and adds a Chromium-in-worker-image dependency. Reserved as a fallback if weekly-operator-login proves insufficient during M04 paper-trading.
- Today's `one-session-per-Gateway-boot` constraint shapes M04 §6.2 by forcing **container-per-session** or **Gateway-restart-on-disconnect** in the broker adapter. Both are workable on Railway (worker-per-deploy makes the former cheap). M04A removes this constraint entirely — REST/WebSocket has no equivalent — which is another reason M04A is the durable answer rather than the urgent answer.

**Tracking:** carryover items to M04A scope (not blocking M04 ship):

- §6.2 broker-adapter dormancy heartbeat is **not** built in M04. The runbook covers it operator-side.
- §6.2 broker-adapter must implement either container-per-session or Gateway-restart-on-disconnect for `reconnect`. Decision belongs in M04 implementation (probably the lighter Gateway-restart option for dev simplicity; revisit if production paper-trading reveals it's too slow).
- M04A kickoff (the developer-portal enrollment in `04A-IBKR-Web-API.md` §5.1) should happen as soon as M04 §6.2 lands, so IBKR's 5–10-day approval clock runs in parallel with the rest of M04 instead of gating M04A by itself.

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

### Carryover items from earlier milestones (slot into §6.5 Observability polish)

| # | Carryover | Source | Notes |
|---|---|---|---|
| 10.6.5.a | Move `/metrics` outside Django middleware chain | M00.9.4 Sentry rollout (2026-05-08) | Mount via `prometheus_client.exposition.make_asgi_app()` so allauth's `AccountMiddleware` no longer post-processes scrape responses. Currently mitigated via a `before_send` Sentry filter in `prod.py` that drops the noisy `AttributeError: 'coroutine' object has no attribute 'headers'` — once `/metrics` is outside Django, the filter can be removed. Underlying interaction is gunicorn UvicornWorker → ASGI → `sentry_sdk`'s `SentryASGIMixin` (unawaited coroutine) → allauth's sync `_should_check_dangling_login` (calls `.headers.get(...)`). Functional impact today is zero (grafana-agent scrapes succeed, `up=1`); the filter exists purely to protect Sentry quota (~240 events/hr would otherwise burn the free-tier 5K/month limit in ~21 hours). |
| 10.6.5.b | Postgres / Redis / Celery exporters | M00.7.5b System Health dashboard | Three exporters need scrape-target wiring before the dashboard's "exporter follow-up" row populates: postgres_exporter, redis_exporter, celery-exporter. Documented in `setup-guides/grafana-setup.md §7` and the dashboard's text panel. |
| 10.6.5.c | Trading Ops / Data Pipelines / Backtest Ops dashboards | M00.7.5b | Per AC-10-8, the full observability pass needs four dashboards beyond Auth Health + System Health. These wait on the milestones that emit the metrics they would plot. |

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
