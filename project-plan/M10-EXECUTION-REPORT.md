# M10 Execution Report — Admin Portal, Chained Audit Log & Observability Polish

> Autonomous implementation run (2026-07-09). Two top-level sections:
> **A — What was implemented**, **B — Manual user steps & follow-ups**.

---

# Section A — What was implemented

## Branch / PR / merge / tag

- **Branch:** `feature/m10-admin-audit-observability` (off `main` @ `75db79b`) — merged + remote branch deleted.
- **PR:** [#29](https://github.com/yhaspel/StratTraderPro/pull/29) — ✅ **MERGED** (squash, `--admin`) — merge commit **`d574057`**. All **5 GitHub CI checks green** (Backend incl. the new `-m pg` lane, Frontend, E2E smoke, Guard-no-legacy-IBKR, Trivy). Adversarial self-review recorded on the PR; MEDIUM + LOW findings fixed in `1b09239` before merge.
- **Release tag (created locally, NOT pushed):** `v0.10.0-admin` → `d574057` (operator-gated convention; no tag-triggered workflow exists — Railway auto-deploys `main` on merge, so the merge itself deployed staging/prod incl. the migrations).

### ⚠️ Deploy notice (lead item — see also Section B)
Merging deployed the **`users_auth_event` → `audit_log` migration + table drop** to staging/prod via Railway auto-deploy (`migrate` runs before serving). **No pre-deploy Railway DB backup was taken** (operator credential). What proves the migration is safe: `audit.0003_migrate_auth_events` builds the chain from genesis and self-asserts **row-count parity** + **head-hash re-verification** in-migration (raises `RuntimeError` on mismatch), and the pg-lane test `apps/audit/tests/test_migration.py` proves it on seeded fixtures. Spot-check post-deploy: `SELECT count(*) FROM audit_log WHERE event_type LIKE 'auth.%';` should equal the pre-deploy `users_auth_event` row count (the table is now gone).

## AC coverage

| # | Status | Proving evidence |
|---|--------|------------------|
| AC-10-1 audit chain + golden vectors + per-family emission | **Met** | `apps/audit/tests/test_hashing.py` (exact-digest golden vectors, key-order independence), `test_services.py` (chain, stored-row-reverifies, scrub, never-raises), `test_migration.py`; emission wired at every §6.1 site (auth/broker/order/fill/strategy/risk/halt/admin/flag) |
| AC-10-2 nightly verifier + drop-detection | **Met [CI]** / Grafana paging **Deferred-live** | `apps/audit/tests/test_verifier.py` (tamper, linkage-break, cursor-resume, failure row, trigger-presence) |
| AC-10-3 pg append-only + linkage + restricted role | **Met [CI]** / Railway restricted role **Deferred-live** | `apps/audit/tests/test_pg.py` (`-m pg`): owner UPDATE/DELETE blocked, stale/malformed hash rejected, restricted INSERT/SELECT role blocked, triggers-present, concurrency chain |
| AC-10-4 admin authz + is_staff exposure | **Met** | `apps/admin_portal/tests/test_authz.py` (13 routes × anon-401/non-staff-403/staff-no-MFA-403/impersonation-403); `is_staff` on `/me` + token-pair payload + OpenAPI |
| AC-10-5 platform kill switch (phrase + MFA, L3, no flatten) | **Met** | `test_admin.py::KillSwitchTests` (phrase mismatch → 400, bad MFA → 403, engage→L3 blocks intake→release); UI copy + runbook state L3 does not flatten |
| AC-10-6 audit search + CSV | **Met [CI]** / p95 @10M **Deferred-live** | `test_admin.py::AuditSearchExportTests`, `test_pg.py::IndexUsageTests` (EXPLAIN index-scan) |
| AC-10-7 impersonation | **Met** | `test_impersonation.py` (claims/TTL, write-block at auth layer vs real mutating view, admin-route 403, WS 4403 `dashboard/test_dashboard.py`, stop→immediate 401, exactly-once read) |
| AC-10-8 dashboards SLO panels | **Met [CI]** / populated on staging **Deferred-live** | six `infra/grafana/*-dashboard.json` (SLO + last-incident panels) |
| AC-10-9 alert rules + cross-check | **Met [CI]** / import + fire **Deferred-live** | `config/test_alert_rules.py`, `infra/grafana/alerts/{alert-rules,contact-points,notification-policy}.yaml` |
| AC-10-10 OTel + correlation | **Met [CI]** / Sentry→Tempo click-through **Deferred-live** | `apps/webhooks/test_otel_span.py` (in-memory span exporter, non-PII attrs), `config/test_correlation.py` (middleware, logging filter, Celery eager round-trip, Sentry helper) |
| AC-10-11 feature flags ≤60s | **Met** | `test_flags.py` (cache time-travel 503⇄200, immutable rejection, missing-table fail-open, audit+metric) |
| AC-10-12 /metrics exposition | **Met** | `config/test_metrics_endpoint.py` (WSGI-callable 401 without creds / 200 with; dispatcher passthrough); wired in `config/wsgi.py` + `config/asgi.py`; `_sentry_before_send` deleted |

## Inventory

**Models + migrations (5 new migrations):**
- `apps/audit`: `AuditLog` (`occurred_at=default=timezone.now`, indexes on user/actor/event_type/entity/occurred_at), `AuditVerifierState` (singleton cursor). Migrations `audit.0001_initial`, `audit.0002_chain_triggers` (Postgres append-only + linkage triggers, vendor-guarded no-op on SQLite), `audit.0003_migrate_auth_events` (frozen-copy chain-building data migration, count + head-hash self-checks).
- `apps/users`: `users.0004_drop_auth_event` (depends on `audit.0003`; drops `AuthEvent` model/table/admin).
- `apps/admin_portal`: `admin_portal.0001_initial` (`ImpersonationSession`, `FeatureFlag`).

**Endpoints (`/api/v1/admin/`) + error codes:** users list/`{id}`, disable/enable, impersonate start, impersonation stop, audit search + `export.csv`, platform status/killswitch, flags list/flip, health. Codes: `ADMIN_PORTAL_DISABLED` (503), `FORBIDDEN`/`AUTH_REQUIRED` (403/401), `MFA_REQUIRED` (403), `CONFIRM_PHRASE_MISMATCH` (400), `FLAG_IMMUTABLE` (400), `FLAG_UNKNOWN` (404), `VALIDATION_ERROR` (400), `IMPERSONATION_READONLY` (403).

**Auth/permission classes:** `apps.users.authentication.ImpersonationAwareJWTAuthentication` (in `DEFAULT_AUTHENTICATION_CLASSES` — auth-layer write-block, session-check revocation, per-request `admin.impersonated_read`); `apps.admin_portal.permissions.IsAdminAndMFAEnforced` (staff + MFA-enrolled, rejects impersonation). Dashboard WS closes impersonation tokens 4403.

**Celery tasks/beat:** `apps.audit.tasks.verify_audit_integrity` (beat `audit-verify-integrity` @ 08:00 UTC), `apps.admin_portal.tasks.update_queue_depths` (beat `admin-queue-depths` every 30s) — both default `celery` queue, explicit entries (no glob routes). FIX-C1: `worker_process_init` + `beat_init` → task-metrics server; request-id propagation via `before_task_publish`/`task_prerun`/`task_postrun`.

**New metrics/gauges:** `audit_events_total{family}`, `audit_events_dropped_total`, `audit_integrity_check_total{result}`, `audit_verifier_duration_seconds`, `admin_impersonation_sessions_total`, `feature_flag_flips_total{flag}`, `celery_queue_depth{queue}`, `sentiment_queue_oldest_age_minutes`.

**Feature-flag registry:** `settings.FEATURE_FLAGS_REGISTRY` — 18 flags + `ADMIN_PORTAL_ENABLED`. Immutable/env-only: `MFA_ENABLED`, `KILL_SWITCHES_ENABLED`, `FILLS_INLINE`, `ADMIN_PORTAL_ENABLED`. Dangerous/typed-confirm: `ENABLE_LIVE_TRADING`, `SENTIMENT_FAKE_SCORERS`, `SIZING_V1_ENABLED`. 12 mutable call sites refactored to `flags.is_enabled()`.

**Frontend:** `adminGuard` (`CanMatchFn`); lazy `ADMIN_ROUTES` (`/admin`, `/admin/users`, `/admin/users/:id`, `/admin/audit`, `/admin/flags`, `/admin/health`); `admin.api` → `admin.store` (signals) → `admin.facade`; components overview/users/user-detail/audit/flags/health + HALT-PLATFORM typed-confirm modal + impersonation banner; `ConfigService` (`window.STP_CONFIG`); `main.ts` Sentry via runtime config; `nav.admin` header link (staff-only). Karma specs: store/facade/guard.

**en.json key groups:** `admin.*` (nav/pagination/overview/halt/impersonation/users/detail/audit/flags/health), `audit.event.*` map, `common.close`.

**New deps (backend pins; frontend zero):** `opentelemetry-instrumentation-{django,celery,redis,psycopg2,httpx}==0.64b0`, `python-ulid>=3.0,<4.0`. **Removed:** `structlog` (dead pin).

**Dashboards/alert files:** six `infra/grafana/*-dashboard.json` (SLO + last-incident panels); `infra/grafana/alerts/{alert-rules,contact-points,notification-policy}.yaml`.

**Docs:** ADR-100/101/102; runbooks `incident-triage.md`, `audit-integrity-failure.md`, `platform-halt.md`, `alerting-setup.md`, `audit-integrity-verify-monthly.md`, `worker-metrics-scrape.md` (options→implemented); `docs/oncall.md`, `docs/postmortem-template.md`, `docs/slo.md`. `CHANGELOG.md` `[Unreleased]`; `PROGRESS.md` + `plan-progress-tracker.md` M10 close-out.

**CI workflow:** added the `-m pg` Postgres-lane step (backend job) + a conditional Sentry sourcemap-upload step (frontend job, gated on `SENTRY_AUTH_TOKEN`, cleanly skipped when absent). No existing gate weakened.

## Local gauntlet + GitHub CI at merge

- **Backend:** `ruff` clean · `bandit` clean (medium+, incl. raw-SQL migration) · **587 SQLite pytest** (0 fail/error, 8 pg-skipped) · **8 `-m pg`** tests green (dedicated `postgres:16-alpine`, CI-matching creds) · `makemigrations --check` clean · prod-import star-import smoke clean · full migration chain applies on scratch SQLite + Postgres (incl. `audit.0003` + `users.0004` drop, correct order).
- **Frontend:** `pnpm install --frozen-lockfile` (lockfile byte-identical) · `pnpm run schema:types` (no drift) · `ngc --noEmit` clean · `pnpm build` (initial **449.56 kB**, under 500 kB budget; admin lazy-chunked) · `pnpm run test:ci` **61 karma**.
- **Docker/compose:** backend image builds (2.35 GB) + `import config.wsgi` boots (metrics wrap + OTel init); Trivy HIGH/CRITICAL clean; E2E smoke (`docker compose up`) → `/healthz` 200 with all migrations (incl. Postgres triggers) applied + the new exporter services.
- **GitHub CI at merge: all 5 checks green.**

## Day-1 spike outcomes
- pg test lane wired (`config/settings/test_pg.py` + `pg` marker + CI step) against the previously-unused Postgres service; trigger prototype validated (owner-role UPDATE/DELETE raise, restricted-role denial).
- OTel instrumentation pins `==0.64b0` (matching installed `opentelemetry-distro 0.64b0`, api/sdk 1.43.0) + `python-ulid==3.0.0` resolve + import cleanly alongside `sentry-sdk 1.45.1` (no swap needed — OTel not parked).
- Metrics-dispatcher smoke behind the WSGI entry validated (multiproc mmap + basic auth) before cutover.

## Migration proof (evidence)
- pg-lane `test_migration.py`: seeds 3 `AuthEvent` fixtures at the pre-drop state, migrates to head, asserts `audit_log` count == source count, event types map to `auth.*`, and `verify_chain()` passes end-to-end.
- Golden head hashes pinned in `test_hashing.py`: row1 `7121cf4b…10628b3`, row2 (chained) `fd244e1e…07d6d5` — recomputed independently by the adversarial reviewer and confirmed.

## Coverage
New backend code (`apps/audit`, `apps/admin_portal`, `config/*` observability) is exercised by ~79 new tests (587 vs the ~508 pre-M10 baseline) plus the 8 pg-lane tests and 17 new karma specs — meeting the ≥90%-on-new-code bar for the buildable surface (verifier, hashing, emit, flags, authz, impersonation, metrics endpoint, correlation, alert cross-check).

## Decided autonomously (please sanity-check)
- **Removed 44 pre-existing tracked `" 2"` Finder-duplicate files** (commit `0894182`) incl. a duplicate backtest migration that created conflicting leaf nodes — **`main` CI was red before M10 started**; this was required to build. Safely reversible (in git history).
- **`is_enabled()` caches only the DB-override state**, resolving the no-override case from live settings — so `@override_settings` (used by ~8 existing feature-gate tests) keeps working with zero test churn, while still delivering the 30s-local + Redis cross-process convergence AC-10-11 requires.
- **`emit()` gained `user_id`/`actor_id` id-based params** so callers with only an id (fill ingest, kill switch) avoid a user lookup.
- **`worker` compose service set to `--concurrency=1`** for a clean 1:1 `TASK_METRICS_PORT` mapping (per the plan's documented FIX-C1 option); the celery hook also tolerates a bind collision gracefully.
- **CSV export by user/actor id** (dropped the never-filled email columns) — per-row email resolution would be an N+1 on a streamed export up to 100k rows.
- **`ADMIN_PORTAL_ENABLED` dispatch gate returns a plain 503 JsonResponse** (before auth) so the portal-off path is uniform for all callers.
- **Left `sentiment/tasks.py:16` SENTIMENT_ENABLED on `settings.X`** (not in the §6.4 refactor list) and left the mode-change `ENABLE_LIVE_TRADING` gate on `settings.X` — followed the plan's explicit site list rather than refactoring every occurrence.

## Blockers / parked
- **None.** OTel pins resolved (no stack swap / no parking). Every [CI] AC portion is green. All parked items are the plan's expected **[LIVE]-deferred** operator steps (Section B), not code blockers.

---

# Section B — Manual user steps & follow-ups

> **Post-merge operator progress (2026-07-10).** Items 1–3 below were tackled together with the
> user via the Railway CLI. Remaining web-UI steps (Grafana import + Tempo/Telegram, prod exporter
> deploy, worker-backtest/streams creation, Sentry+GitHub) are packaged in
> **`project-plan/M10-cowork-followups.md`** for a Claude Cowork (Chrome MCP) session.
> Also landed a hardening PR (#30, `e5b0d16`): Redis socket timeouts + flag DB-fallthrough so an
> unreachable/hung Redis degrades gracefully instead of blocking workers — this diagnosed and (via
> a CLI redeploy) fixed a **staging Redis outage** discovered during the deploy verification.

### 1. Deployed-migration notice — ✅ VERIFIED (both envs)
Merging deployed the `users_auth_event` → `audit_log` migration + table drop (Railway `migrate` before serving). Read-only re-verification on the live databases:
- **staging:** 138 audit_log rows, all `auth.*`; `users_auth_event` dropped; chain re-verifies (138 checked, 0 failures).
- **production:** 16 audit_log rows, all `auth.*`; `users_auth_event` dropped; chain re-verifies (16 checked, 0 failures).
- The migration self-asserts parity + head-hash in-migration, and a healthy boot (which happened on both envs) means `migrate` completed. **No backup restore needed.** Forward-only on Postgres.

### 2. Railway env / services — ✅ mostly done via CLI (both staging + production)
- ✅ `METRICS_BASIC_AUTH_USERNAME=metrics` / `METRICS_BASIC_AUTH_PASSWORD` on backend **and** grafana-agent — verified LIVE (`/metrics` 401 without creds, 200 with, on prod). Password stored in Railway.
- ✅ `TASK_METRICS_PORT` on celery-worker (9101) + celery-beat (9103); agent scrape targets (WORKER/BEAT/WORKER_BACKTEST/STREAMS/POSTGRES_EXPORTER/REDIS_EXPORTER) set.
- ✅ `AUDIT_ALERT_EMAIL=you@example.com`.
- ✅ `postgres-exporter` + `redis-exporter` created + **deployed on staging**. ⏳ **prod deploy pending** (1-click in the dashboard — Cowork A1).
- ⏳ `OTEL_EXPORTER_OTLP_ENDPOINT` + `OTEL_EXPORTER_OTLP_HEADERS` — set once Grafana Cloud Tempo is up (Cowork B5/A5).
- ⏳ Frontend `GRAFANA_URL`/`SENTRY_*`/`RELEASE` + `NGINX_ENVSUBST_FILTER` (Cowork A4).
- ⏳ Restricted DB role (Cowork A6).
- ⏳ **`worker-backtest` + `streams` services** — need a custom start command (dashboard); packaged in Cowork A2/A3 (TASK_METRICS_PORT 9102/9104).

### 3. Grafana Cloud — ⏳ packaged for Claude Cowork (`M10-cowork-followups.md` §B)
- Import the **six** updated dashboards + `infra/grafana/alerts/*.yaml`; create email + Telegram contact points + notification policy; Tempo datasource + Sentry↔Tempo correlation; then run **AC-10-9** (sample alert → email + Telegram) and **AC-10-10** (Sentry → Tempo click-through). Procedures in `docs/runbooks/alerting-setup.md`.

### 4. GitHub — ⏳ packaged for Cowork (`M10-cowork-followups.md` §C)
- Add the `SENTRY_AUTH_TOKEN` secret (+ `SENTRY_ORG`/`SENTRY_PROJECT` vars) to activate the frontend sourcemap-upload CI step. Or set via CLI once you have a token: `gh secret set SENTRY_AUTH_TOKEN --repo yhaspel/StratTraderPro`.

### 5. Staging verifications deferred (need scale/tools — Cowork tail)
- Audit-search p95 ≤ 500 ms @ 10M rows; verifier throughput ≥ 24h synthetic (~100k) ≤ 5 min; flag-flip E2E in the real UI ≤ 60 s; dashboards populated. ✅ `/metrics` basic auth live 401/200 already verified on prod.

### 6. Ops notes
- ✅ **Staging Redis outage found + fixed** during deploy verification: staging Redis had been unreachable since 2026-05-01 (only deployment REMOVED); a `railway redeploy -s Redis -e staging` restored it (`/readyz` → 200, redis ok). The #30 hardening ensures a future Redis outage degrades gracefully instead of hanging workers.
- Granting `is_staff` happens via **Django admin/shell** — out of band of the audit chain (documented limitation; M11 hardening candidate).
- Add the **monthly audit-integrity spot-check** to the ops calendar (`docs/runbooks/audit-integrity-verify-monthly.md`).
- The **`v0.10.0-admin`** tag was created locally on `d574057` but **NOT pushed** (operator convention). No tag-triggered deploy workflow exists — the merge already deployed via Railway. Prior unpushed tags (`v0.1.1-auth-metrics`, `v0.4.0`…`v0.9.0`) remain pending too.
- **Follow-up (out of M10 scope, pre-existing on `main`):** the `_scrub_sensitive` log processor is not wired into the stdlib `python-json-logger` LOGGING config (inert; the security-critical audit-row scrubbing via `emit()` is active). Wire a stdlib logging filter or correct the docstring — worth a ticket.

### 7. Merge command
- N/A — the PR was successfully `--admin`-merged (squash) and the remote branch deleted.

### 8. Sanity-check the autonomous decisions in Section A ("Decided autonomously"), especially the `" 2"` junk-file removal (a pre-existing red-`main` fix) and the `is_enabled` override-state caching design.
