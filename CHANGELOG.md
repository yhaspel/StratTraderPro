# Changelog

All notable changes to StratTraderPro will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added — M00.7.5b (System Health dashboard)
- **`infra/grafana/system-health-dashboard.json`** — 15-panel Grafana Cloud dashboard, sibling to the M01 Auth Health board. Six rows: Backend Health (`up`, request rate by status class, p50/p95/p99 latency, 5xx rate %), Application Activity (top 10 routes by request rate, top 10 by p95 latency, 4xx responses by view), Django DB (ORM-side query duration percentiles + new connections/sec), and three placeholder rows — Postgres/Redis/Celery exporter follow-up (text-only explainer panel; exporters are M10 §6.5 work), M04 Webhook Ingest (HMAC failure rate / idempotency dedupe rate / ingest p95 latency, "No data" until M04 wires `webhook_ingest_total` and `webhook_ingest_latency_seconds`), M04 Broker Round-trip (order placement p95 by broker / `broker_connection_up`, "No data" until M04 broker adapters land). Multi-select `env` variable defaults to All so cross-env regressions stand out at a glance. UID `stp-system-health`, schemaVersion 39, panels-only (no alert rules in v1 — pinning thresholds deferred until a week of baseline data is collected). **Container CPU/memory deliberately omitted:** multi-process gunicorn (M01.11.13) disables prometheus_client's `process_*` collector, and Railway container metrics aren't scraped yet (M10 §6.5 work). Application Activity row replaces the abandoned Process Resources row from the v0 draft.
- **`setup-guides/grafana-setup.md` §7** — import procedure, variable reference, verification checklist for closing M00.7.5b, and explicit "what's deferred" note covering alert rules and the Trading Ops / Data Pipelines / Backtest Ops dashboards still owned by M10 AC-10-8.

### Changed — backend Django DB engine wrappers for /metrics
- **`backend/config/settings/base.py`** — added `_wrap_db_engines_for_prometheus()` helper that maps stock Django engines (`django.db.backends.postgresql`, `.sqlite3`, `.mysql`) to their `django_prometheus.db.backends.*` wrapper subclasses. Wrappers are transparent drop-ins (same DSN handling, same query behavior) but **emit two extra metrics**: `django_db_query_duration_seconds_bucket{alias, vendor}` (histogram) and `django_db_new_connections_total{alias, vendor}` (counter). Without the wrapper these series are simply not emitted — the System Health Django DB row stays empty no matter how much traffic flows through the system.
- **`backend/config/settings/dev.py`** + **`prod.py`** — both call `_wrap_db_engines_for_prometheus()` after their `DATABASES = {…}` override so the wrapper applies on top of `env.db("DATABASE_URL")` resolution. `test.py` deliberately untouched (sqlite-only, query duration metrics are noise in test runs).
- Backend redeploy on staging + prod required for the System Health Django DB row to populate.

### Changed — M00.7.5 split
- Tracker entry M00.7.5 ("Grafana Cloud account + System Health dashboard") split into 00.7.5a (Grafana account — ✅ Done since M01.11.5) and 00.7.5b (System Health dashboard — was the actual unfinished work). Top-of-tracker reconciliation note updated.
- `v0.3.0-strategies` tag attribution corrected: it points to commit `a4e1e8f` (the M03-completion commit). Subsequent `a7f746c` is the tracker-update bookkeeping commit.

### Added — M03 (Strategies & Webhook Config)
- **`strategies` Django app** fleshed out from M02 ping-stub to a full domain. New models: `Strategy` (system + user-owned, soft-delete via `is_enabled`), `StrategyFile` (per-strategy bytes for `.pine` / description / webhook template, sha256 + filename + size + BYTEA content), `WebhookConfig` (per-user/per-strategy HMAC secret Fernet-encrypted at rest, JSON-Schema-validated payload template, version counter for rotation). Migration `strategies.0001_initial` is destructive on rollback (greenfield — no prod data yet).
- **Strict 3-file upload contract** for user uploads: `<stem>.pine` + `<stem>_Description.txt` + `<stem>_Webhook.json`. Validator enforces stem regex `[A-Za-z0-9_-]{3,64}`, size limits (64 KB / 16 KB / 16 KB), `//@version=` declaration in pine, required webhook keys (`strategy`, `action`, `symbol`, `qty`, `order_type`), path-traversal rejection (null bytes, `../`, separators), substring XSS scan as defense-in-depth (`<script`, `javascript:`, `onerror=`, `onload=`). All in `apps/strategies/validators.py`. ADR-030 captures the rationale.
- **Strategies API surface** (all MFA-gated via M02 `IsAuthenticatedAndMFAEnforced` + `mfa_required=True`):
  - `GET    /api/v1/strategies/`  — list (system + own).
  - `POST   /api/v1/strategies/`  — multipart upload + acknowledge checkbox.
  - `GET    /api/v1/strategies/{id}/`  — detail.
  - `PATCH  /api/v1/strategies/{id}/`  — rename / toggle enabled.
  - `DELETE /api/v1/strategies/{id}/` — soft delete (sets `is_enabled=false`). System strategies refuse with `STRATEGY_SYSTEM_IMMUTABLE`.
  - `GET    /api/v1/strategies/{id}/files/{kind}/`  — download a stored file's bytes.
  - `GET    /api/v1/strategies/{id}/webhook-config/`  — fetch URL + JSON Schema + payload template; on first call the row is created and the secret is revealed once.
  - `PUT    /api/v1/strategies/{id}/webhook-config/`  — update schema + template (server-validates schema is valid Draft 2020-12, template matches schema).
  - `POST   /api/v1/strategies/{id}/webhook-config/rotate/`  — generate new secret, increment version, reveal once. Old secret is destroyed.
  - `POST   /api/v1/strategies/{id}/webhook-config/dry-run/`  — validate a payload against the saved schema without firing an order.
- **HMAC secret rotation + reveal-once UX** documented in ADR-031. Same Fernet KEK as MFA (`settings.FERNET_KEK`) so KEK rotation covers both surfaces. Plaintext secrets never appear in logs (regression test pins this).
- **`load_strategies` management command** — `python manage.py load_strategies <path>` walks one level deep, idempotent via SHA-256, `--dry-run` flag. Adapts to the real Trading Strategies project layout: globs for any `*.pine` and `*description*.txt`, synthesizes a default webhook template when no `_Webhook.json` exists. Exit code is non-zero on partial failure so CI catches it. Runbook at `docs/runbooks/strategy-import-from-cowork.md`.
- **Frontend strategies feature area** at `/strategies`, `/strategies/upload`, `/strategies/:id`. Lazy-loaded via `STRATEGIES_ROUTES`. List view renders system + user-uploaded with a "User-uploaded" amber banner ("Community-tested: No"), inline enable/disable toggle, per-row "Configure webhook" + "Delete" actions. Upload component is a 3-step single-file wizard (select files → review → acknowledge & submit) with mandatory accept-untested-risk checkbox. Webhook configuration modal hosts URL + reveal-once secret + Rotate (with confirm) + JSON Schema editor + payload-template editor + Test (dry-run) + Copy TradingView template buttons. Monaco editor lazy-imported via dynamic import so the chunk only loads on modal open; textarea fallback keeps the editor accessible regardless.
- **Frontend abstraction layer**: `core/services/strategies.api.ts` (typed HTTP client), `abstraction/stores/strategies.store.ts` (signal-based, with reveal-once secret cache that wipes on modal close), `abstraction/facades/strategies.facade.ts` (load/upload/toggle/softDelete/webhook CRUD/rotate/dry-run).
- **i18n keys** under `strategies.*` and `webhook.*` in `assets/i18n/en.json`. Help pages: `assets/help/strategy-upload.html` ("Upload your first strategy") and `assets/help/tradingview-alert-config.html` ("Configure your TradingView alert").
- **Settings**: new `STRATEGIES_V1_ENABLED` feature flag (returns 503 from all strategies endpoints when False — no-deploy rollback per plan §15) and `STRATEGY_WEBHOOK_BASE_URL` for the public webhook hostname (defaults to `https://api.strattraderpro.com/hooks/v1`; the receiver itself goes live in M04).
- **Prometheus**: `strategy_uploads_total{result}` (3 outcomes), `strategy_webhook_rotations_total`, `strategy_count_gauge{type=system|user}`. Wired in `apps/strategies/metrics.py`.
- **New error codes** in the response envelope: `STRATEGY_NOT_FOUND`, `STRATEGY_NAME_TAKEN`, `STRATEGY_FILE_MISMATCH`, `STRATEGY_FILE_TOO_LARGE`, `STRATEGY_WEBHOOK_INVALID`, `STRATEGY_SYSTEM_IMMUTABLE`, `WEBHOOK_SCHEMA_INVALID`.
- **Admin**: `Strategy`, `StrategyFile`, `WebhookConfig` registered. System rows are read-only for non-staff (AC-03-10). `WebhookConfig` admin disables creation (configs are minted via the API only).
- **37 new backend tests** in `apps/strategies/test_strategies.py` covering AC-03-1 through AC-03-12 + validator branches (path traversal, oversize, bad JSON, missing keys, XSS), rotation+version increment, system immutability, multi-tenant isolation, fixture-based `load_strategies` integration test (incl. webhook synthesis when missing), feature-flag 503, and a regression test that the rotation log line never contains the freshly minted secret. Total backend pytest: **128 passing** (+37). One M02 sweep test in `test_mfa.py::test_all_protected_prefixes_have_mfa_gate` updated to hit the real `/strategies/` endpoint instead of the deleted `/strategies/ping/` stub.
- **Frontend test**: `strategies.store.spec.ts` covers signal-derived counts, upsert, remove, and the reveal-once secret cache wipe.
- **Dependencies**: `jsonschema>=4.21,<5.0` added to `requirements/base.txt` (Draft 2020-12 validator).
- **Docs**: ADR-030 (3-file upload contract), ADR-031 (HMAC rotation + reveal-once), runbook (strategy import).

### Added — M2.5 (Google OAuth sign-in / sign-up)
- **Google OAuth via django-allauth** with a custom JWT bridge — allauth handles only the OAuth state machine (authorize URL, code exchange, userinfo fetch, account linking), and we hijack at the post-callback step to issue our own one-time exchange code, then bridge through the M01 JWT family pipeline + M02 MFA gate. Three endpoints: `GET /api/v1/auth/oauth/google/start/` returns the authorize URL as JSON, `GET /api/v1/auth/oauth/google/callback/` is allauth's stock callback (registered in Google Cloud Console), `POST /api/v1/auth/oauth/exchange/` swaps the exchange code for `{access, refresh, user}` OR `{mfa_required, mfa_token}`. Bridge code in `apps/users/views_oauth.py` (~280 lines) and `apps/users/social_adapters.py` (~80 lines).
- **`OAuthExchangeCode` model** — single-use sha256-hashed code, 5-minute TTL (configurable via `OAUTH_EXCHANGE_TTL_MINUTES`), keeps the JWT pair off the redirect URL so it doesn't leak through referer headers / server logs / browser history. Migration `users.0003_oauth_exchange_code` adds the table.
- **MFA still required after Google sign-in** — Google proves email control, MFA proves second-factor ownership. Same `{mfa_required, mfa_token}` response as password login. Documented in ADR-021.
- **Auto-link by verified email** — when a Google sign-in arrives for an email that already has a User, `SocialAdapter.pre_social_login` calls `sociallogin.connect()` to attach the SocialAccount to the existing User. The user keeps their MFA, sessions, profile, and password. Only happens when Google asserts `email_verified=true`. Notification email (`oauth_account_linked.{txt,html}`) fires so a real user notices.
- **Auto-create User on first Google sign-in** — `SocialAdapter.populate_user` pulls `display_name` from Google's `name` claim (falls back to local-part of email) and sets `is_verified=True` (Google verified the email at the OAuth provider). Welcome email (`oauth_account_created.{txt,html}`) sent.
- **Frontend**: "Continue with Google" button on `/login` and `/register` (brand-compliant Google G logo SVG, white background per their guidelines), `/oauth/callback` route component handles the `?exchange=<code>` redirect from backend (or `?error=oauth_failed`), POSTs to exchange endpoint, routes to `/dashboard` or `/login/mfa` based on response. `auth.facade` gained `startGoogleSignIn()` + `completeGoogleSignIn(code)` methods. New i18n keys under `oauth.*`.
- **Sentry-aware Sentry environment** — derived from `RAILWAY_ENVIRONMENT_NAME` so OAuth errors group under the right env (staging vs production).
- **5 new audit-log event types**: `OAUTH_LOGIN_OK`, `OAUTH_USER_CREATED`, `OAUTH_LINKED`, `OAUTH_EXCHANGE_OK`, `OAUTH_EXCHANGE_FAIL`. New Prometheus counters: `auth_oauth_login_total{result}`, `auth_oauth_exchange_total{result}`.
- **24 new tests** in `apps/users/test_oauth.py` covering: OAuthExchangeCode model (issue, consume, single-use, expiry, replay rejection, inactive user); SocialAdapter logic (auto-link with verified email, refusal to link unverified, no-op on already-linked); OAuthExchangeView (happy path, MFA gate, invalid/expired/consumed code, audit events, feature-disabled 503); OAuthGoogleStartView (returns valid Google authorize URL with state token, refuses when disabled or unconfigured). Total backend pytest count: 90, all green.
- **`docs/adr/021-google-oauth-allauth.md`** — captures the choice rationale (allauth for state machine + custom bridge for everything else), full flow diagram, account-linking semantics, MFA interaction, why exchange-code instead of JWT in URL fragment.
- **`docs/runbooks/google-oauth-setup.md`** — reproducible GCP setup: OAuth consent screen wizard, OAuth Web client creation with the three required redirect URIs (localhost dev + staging + prod), saving credentials, adding test users while in Testing mode, publishing to In Production for unrestricted sign-up, env var configuration in Railway, smoke test, secret rotation procedure, failure modes.

### Settings (M2.5)
- New env vars: `GOOGLE_OAUTH_ENABLED` (master kill-switch — `false` returns 503 from all OAuth endpoints), `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` (set in Railway env, never committed), `OAUTH_EXCHANGE_TTL_MINUTES` (defaults to 5).
- New `INSTALLED_APPS` entries: `django.contrib.sites`, `allauth`, `allauth.account`, `allauth.socialaccount`, `allauth.socialaccount.providers.google`. New middleware: `allauth.account.middleware.AccountMiddleware`. New auth backend: `allauth.account.auth_backends.AuthenticationBackend` (alongside our existing `ModelBackend`). `SITE_ID = 1`.
- Custom adapters wired via `SOCIALACCOUNT_ADAPTER` and `ACCOUNT_ADAPTER` to suppress allauth's parallel auth features (local signup form blocked via `is_open_for_signup=False` on `AccountAdapter`; email verification disabled via `ACCOUNT_EMAIL_VERIFICATION="none"` since we run our own).

### Manual setup follow-ups (Yuval)
- Google Cloud Console: existing `strattraderpro` project, OAuth consent screen configured, "StratTraderPro Web" OAuth 2.0 Web client created with 3 redirect URIs, `yuval3000@gmail.com` added as test user (1/100 cap). Client ID + Client Secret saved to password manager. App still in **Testing mode** — publish to Production after smoke-test (one click, no Google verification needed for our `email`+`profile` scopes).
- Railway: `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` need to be set in both staging and prod backend services.
- A duplicate empty `strattraderpro-495109` GCP project exists (created accidentally by me); Yuval to delete via GCP resource manager.

### Infrastructure — Production environment bootstrap
- **Production Railway environment** stood up alongside M02. Forked from staging via Railway's "Duplicate Environment" feature, giving us 7 fresh service instances (backend, frontend, celery-worker, celery-beat, Postgres, Redis, grafana-agent) with empty volumes and prod-unique URLs (`backend-production-f3e8.up.railway.app`, `frontend-production-c977f.up.railway.app`). The pre-existing empty `production` env that auto-created with the project (untouched for 4 weeks) was renamed to `production-archive-2026-04` rather than deleted, kept as a safety net.
- **Prod-grade secrets generated locally** and set in Railway env: `SECRET_KEY` (64-byte url-safe-base64 from `secrets.token_urlsafe`) and `FERNET_KEK` (32-byte url-safe-base64 from `os.urandom`). Different values than staging — no key reuse between environments. KEK is a hard requirement for M02 MFA: without it, every TOTP secret would be wrapped with a SECRET_KEY-derived dev fallback. Now every MFA enrollment in prod is wrapped with the prod-only KEK.
- **URL-bound vars auto-resolved** because the staging env was set up with Railway service references (`${{RAILWAY_PUBLIC_DOMAIN}}`, `${{frontend.RAILWAY_PUBLIC_DOMAIN}}`, `${{Postgres.DATABASE_URL}}`, etc). The duplicate carried these references over verbatim and Railway re-resolved them against the prod-env service IDs — `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `REDIS_URL`, `FRONTEND_BASE_URL`, and the frontend's `BACKEND_URL` were all correct on first deploy with zero edits. Yellow warning icons in the Variables panel are stale UX — the values resolve correctly to prod URLs.
- **Sentry environment derivation fixed** — `config/settings/prod.py` previously hardcoded `environment="production"` in `sentry_sdk.init`, meaning staging events would also tag as `production` (because staging also runs under `config.settings.prod`). Now reads `SENTRY_ENVIRONMENT`, defaulting to `RAILWAY_ENVIRONMENT_NAME` (Railway-injected). Staging events now tag `environment=staging`, prod events tag `environment=production` — they group separately on the Sentry dashboard.
- **Auth Health Grafana dashboard made env-aware** — `infra/grafana/auth-health-dashboard.json` gained an `Env` template variable that pulls available values via `label_values(auth_login_total, env)`. All 4 panel queries (`Login success rate`, `Login outcomes`, `Refresh family revocations`, `Rate-limit hits`) now filter by `env="$env"` so flipping the dropdown switches the dashboard between staging and prod views. The grafana-agent itself needed zero changes because `agent.yaml` already uses `${RAILWAY_ENVIRONMENT_NAME}` for both `cluster` and `env` external labels — prod metrics ship to the same Grafana Cloud workspace tagged `env=production`.
- **Smoke-tested end-to-end:** prod `/healthz` and `/readyz` both 200 (DB ok, Redis ok), frontend renders, login form reachable, `/api/v1/auth/login/` returns the structured `INVALID_CREDENTIALS` 401 envelope, all 5 MFA endpoints visible in `/api/docs/`. KEK validity proven on staging by the QR-code render path; same code on prod.
- **`docs/runbooks/prod-bootstrap.md`** committed — captures the full procedure (env duplicate → secret rotation → verification → observability check), failure modes, and rollback. Reproducible the next time we need a fresh env (DR, new region, separate tenant).

### Known follow-ups
- Frontend landing page still hardcodes "Platform scaffold — staging environment" via `app.status` i18n key. Will need an env-aware key swap (or ship from build-time `environment.*.ts`).
- Login error envelope handling: when the backend returns 401 `INVALID_CREDENTIALS`, the refresh interceptor retries the call, the second response is parsed differently, and the user sees `auth.login.error.UNKNOWN` instead of "Invalid email or password". Pre-existing from M01, exists on both envs. Tracked as a frontend ticket for next milestone.
- `DJANGO_SETTINGS_MODULE` is `config.settings.prod` in BOTH staging and prod envs — the only thing differentiating them is `RAILWAY_ENVIRONMENT_NAME`. Acceptable today (staging matches prod hardening) but worth a `staging.py` settings split if/when staging needs to diverge (e.g. wider CORS for testing, DEBUG toolbar, looser HSTS).

### Added — M02 (MFA & user profile)
- **TOTP-based MFA**, end-to-end. `pyotp.TOTP(interval=30, digits=6)` with ±1 step tolerance; secrets wrapped at rest with `cryptography.fernet` keyed by `settings.FERNET_KEK`. Endpoints: `POST /api/v1/auth/mfa/{enroll,enroll/confirm,verify,disable,backup-codes/regenerate}/`. `LoginView` now branches: enrolled users get `{ mfa_required: true, mfa_token }` (5-min purpose-scoped JWT) instead of an access+refresh pair, and complete login at `/auth/mfa/verify/`. `/verify/` is rate-limited at 5/min/mfa_token to slow brute force. ADR `docs/adr/020-totp-over-sms.md` captures the decision to ship TOTP-only.
- **10 single-use backup codes** generated at enrollment (sha256+per-row salt), regenerable via `/auth/mfa/backup-codes/regenerate/` (requires current password + TOTP — defense-in-depth). The login `/verify/` endpoint accepts either a TOTP code or a backup code via the `is_backup_code` flag.
- **`IsAuthenticatedAndMFAEnforced` permission class** in `apps/users/permissions.py`. Views opt in by setting `mfa_required = True`; the gate denies with structured `{"error":{"code":"MFA_REQUIRED",...}}` (mapped via the new `apps.users.exception_handler.custom_exception_handler` set as DRF `EXCEPTION_HANDLER`). Scaffold `/api/v1/{brokers,orders,risk,strategies}/ping/` endpoints opt in so AC-02-6 is exercised against real URLs; the auto-coverage test asserts every protected prefix denies a non-MFA user.
- **`UserProfile` model** (timezone, language, notification_email, default_broker_id placeholder, terms_version_accepted) auto-created on user creation via `post_save` signal. Endpoints: `GET /api/v1/users/me/` now returns the user + nested profile + `mfa_enabled` flag; `PATCH /api/v1/users/me/update/` validates timezone against `zoneinfo.available_timezones()` and rejects unsupported languages.
- **Authenticated password change** at `POST /api/v1/users/me/password/` — re-prompts current password, applies the same `_validate_password_or_raise` policy, revokes every other refresh-token family, leaves the current session alive.
- **Active sessions UI**: `GET /api/v1/users/me/sessions/` lists non-revoked refresh families with masked IP, summarized UA ("Chrome on macOS"), `last_used_at`, and a `current` flag computed from the access-token's `family_id` claim. `POST /api/v1/users/me/sessions/revoke/` accepts `{family_id}` for a single revoke or `{all: true}` to wipe everything except the current session. `RefreshTokenFamily` schema gained `user_agent`, `ip`, `last_used_at`; `services.issue_token_pair`/`rotate_refresh` now capture and refresh those.
- **Frontend Angular**: `/login/mfa` (custom 6-cell TOTP input with paste/auto-advance/keyboard nav, "Use a backup code instead" toggle); `/settings/security/mfa/setup` (4-step wizard: intro → QR + secret + copy → verify code → backup codes with download/copy/click-to-confirm); `/settings/security` (single page housing MFA enable/disable, regenerate backup codes, sessions list with per-row revoke + "sign out everywhere else", password change form); `/settings/profile` (display name, searchable IANA timezone dropdown via `Intl.supportedValuesOf('timeZone')`, language, email notifications). Auth store gained an `mfa_pending` status and an in-memory-only `mfa_token` signal (5-min lifetime, never persisted to localStorage).
- **MFA Prometheus counters** in `apps/users/metrics_m02.py`: `auth_mfa_enrollments_total`, `auth_mfa_verifications_total{result}`, `auth_mfa_backup_used_total`, `auth_mfa_challenge_failures_total`. Drives the planned "MFA challenge failure rate > 20% over 10 min" alert.
- **Email templates** `mfa_enabled.{txt,html}` and `mfa_disabled.{txt,html}` — sent on every enable/disable so a real user notices an attacker turning off their own MFA.
- **Audit events** added to `AuthEvent.EventType`: `MFA_ENROLLED`, `MFA_DISABLED`, `MFA_CHALLENGE_OK`, `MFA_CHALLENGE_FAIL`, `BACKUP_CODE_USED`, `BACKUP_CODES_REGENERATED`, `PASSWORD_CHANGED`, `PROFILE_UPDATED`, `SESSION_REVOKED`.
- **Runbooks** `docs/runbooks/user-lost-mfa.md` (support recovery flow with identity-check checklist + Django admin "Force-disable MFA" bulk action that emails the user and audit-logs the staff actor) and `docs/runbooks/mfa-kek-rotation.md` (envelope-encryption pattern using `MultiFernet` so the KEK can rotate without decrypting all secrets in one shot).
- **User help page** `frontend/src/assets/help/mfa.html` with setup steps, lost-phone flow, clock-skew tip, and rationale for MFA-gated broker actions.
- **Test suite**: 36 new tests in `apps/users/test_mfa.py` (Fernet roundtrip, TOTP correctness with ±1 step tolerance, backup-code single-use, full enroll/login/disable HTTP flow, regenerate, MFA enforcement against the four scaffold prefixes, profile validation rejecting unknown IANA tz and unsupported languages, password-change family revocation, sessions list/revoke). Total backend test count: 66, all green.

### Settings (M02)
- New env knobs: `MFA_ENABLED` (master kill-switch — when False, `/auth/mfa/*` returns 503 and login skips the MFA branch), `FERNET_KEK` (defaults to a deterministic dev key derived from `SECRET_KEY` so tests run unconfigured; prod must set a real `Fernet.generate_key()` in Railway env), `MFA_TOKEN_TTL_MINUTES`, `MFA_TOTP_VALID_WINDOW`, `MFA_TOTP_ISSUER`, `MFA_BACKUP_CODE_COUNT`. DRF gains a custom `EXCEPTION_HANDLER` that wraps `PermissionDenied("MFA_REQUIRED")` → `403 {"error":{"code":"MFA_REQUIRED",...}}` and `NotAuthenticated` → `401 {"error":{"code":"AUTH_REQUIRED",...}}`.

### Added — earlier
- `apps/users/metrics.py` with the four Prometheus counters required by plan §12: `auth_login_total{result}`, `auth_refresh_total{result}`, `auth_family_revocations_total`, `auth_password_reset_total{step}`. All four are now incremented from views/services on every relevant code path. The Auth Health dashboard panels and three alerts (login success rate < 95%, family revocations > 5/h, sustained 429s) now have data to chart against.
- `backend/gunicorn.conf.py` enabling `prometheus_client` multi-process mode. Each gunicorn worker mmaps its counter state into `/tmp/prom-multiproc` (set via `ENV PROMETHEUS_MULTIPROC_DIR` in `docker/backend.Dockerfile`); the `/metrics` handler aggregates across all workers and the `child_exit` hook calls `multiprocess.mark_process_dead` so dead-worker files don't inflate totals. Verified on staging: 8 consecutive `/metrics` scrapes return identical aggregated values (was bouncing 2/3/4 between workers before).

### Fixed
- `POST /api/v1/auth/register/` no longer returns 500 when Resend rejects delivery (Resend test-sender restriction, SMTP timeout, or any other backend-email failure). `_send_templated` now logs the exception and continues — the user/account is still created and the response is the expected 201/202. Anti-enumeration semantics preserved.
- Grafana alert rules `auth-login-success`, `auth-family-revocations`, `auth-rate-limit-spike` were initially created with range queries flowing into the threshold expression, which Grafana 11 errors on (`looks like time series data, only reduced data can be alerted on`). Switched all three to instant queries (`queryType: 'instant'`, `instant: true, range: false`) so the threshold expression sees a scalar; verified end-to-end by triggering 3+ family revocations and observing the rule transition Inactive → Pending(activeAt) → Firing(activeAt + 5m) → email delivered to `auth-health-email` contact point.

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
