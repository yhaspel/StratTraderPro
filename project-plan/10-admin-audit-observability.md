# Milestone 10 — Admin Portal, Audit Log & Observability Polish

> **Week:** 10
> **Duration:** 5 working days (planning-calendar label, not a constraint)
> **Depends on:** M08 (merged PR #26 + remediation PR #27), M09 (merged PR #28)
> **Unlocks:** M11 (Hardening) — admin tooling is a prerequisite for safe load testing

> **REVIEWED & FROZEN 2026-07-09** — validated against the code at `main` (post-M09, post-remediation).
> Eight engineering decisions are settled and recorded here; do **not** revisit them autonomously:
>
> 1. **`AuthEvent` is migrated into `AuditLog` and then dropped** (model, table, `AuthEventAdmin`). It is NOT a stub — it is a fully-populated production table (`users_auth_event`, 26 event types, written via `apps/users/services.record_event`). `record_event()` keeps its signature and becomes a thin wrapper over the audit service; the `EventType` enum relocates to a module that survives the drop, and every reference is repointed per the surgical list in §6.1 ("AuthEvent decommission").
> 2. **High-volume machine events stay OUT of the hash chain** — webhook-received and sizing decisions remain in their dedicated tables (`AlertMessage`, `SizingDecision`), referenced by id from related audit rows. This is an explicit, documented deviation from master plan §6.11 (rationale: chain-lock contention on the ingest hot path + existing dedicated stores).
> 3. **Hash chain is computed in application code** (one canonical implementation, `apps/audit/hashing.py`); **Postgres triggers enforce** append-only (UPDATE/DELETE always raise, for every role) and chain linkage (INSERT with wrong `prev_hash` is rejected). No pgcrypto, no SQL-side canonicalization (dual-implementation JSON canonicalization is a false-integrity-page factory). Chain-head reads serialize via `pg_advisory_xact_lock` on Postgres; SQLite (tests/dev) uses the same Python path without the lock.
> 4. **Admin identity = the existing `User.is_staff` boolean** (already gates L3 kill switch + `BrokerFlattenView` + Django admin). No new `role` field.
> 5. **Sensitive admin actions use per-action MFA** (fresh TOTP/backup code via `apps/users/mfa.verify_mfa_code`, the proven M08 pattern). No 15-minute step-up window, no new session state.
> 6. **Feature flags = DB-backed `FeatureFlag` model in `apps/admin_portal`** + Redis + 30s process-local cache, falling back to the existing env-parsed `settings.<NAME>` defaults. No new `apps/core` app. Flags marked immutable in the registry are env-only forever (`MFA_ENABLED`, `KILL_SWITCHES_ENABLED`, `FILLS_INLINE`, `ADMIN_PORTAL_ENABLED`).
> 7. **OTel is wired code-side in full** (Django+Celery+redis+psycopg2+httpx instrumentation, OTLP export gated on `OTEL_EXPORTER_OTLP_ENDPOINT` being set); the live Sentry→Tempo click-through is a documented operator step, not a CI gate.
> 8. **`/admin/health` uses native KPI cards + external links to Grafana Cloud** (target=_blank precedent). No Grafana iframes, no tokens in iframe URLs.

## 1. Purpose

Wrap the system in operational visibility and control: an admin portal (platform kill switch, user management, audit search, system health, feature flags), a cryptographically-chained append-only audit log with a nightly integrity verifier, and an observability completeness pass (Sentry releases, metrics exposition fixed, worker/beat scrape, dashboards with SLO panels, alert rules as code, request/trace correlation). After M10, the operator can detect, investigate, and contain incidents.

M10 also **absorbs the documented carryovers**: PROGRESS.md "M10 §6.5 observability carryover" (move `/metrics` out of Django middleware — the fix named in `config/settings/prod.py:87-92` — wire postgres/redis/celery exporters, remaining dashboard panels), remediation follow-up **FIX-C1** (worker/beat metrics scrape), and the M09 note that backtest alert rules' "live wiring is M10".

## 2. In Scope

- `apps/audit` buildout: append-only `AuditLog` with application-computed hash chain, Postgres enforcement triggers, nightly integrity verifier with cursor, event taxonomy, i18n label map.
- Migration of `AuthEvent` (a fully-working M01 table — see frozen decision 1) into `AuditLog`, then dropping it; `record_event()` repointed.
- Audit emission wired into every privileged action (§6.1 event table): auth flows, broker connect/disconnect/mode, order submit + fill ingest, kill-switch engage/release (incl. auto-L2), strategy create/update/delete, webhook secret rotation, risk-profile change, user disable/enable, impersonation lifecycle + impersonated reads, flag flips, platform admin actions.
- `apps/admin_portal` buildout — admin-only API (all under `/api/v1/admin/`, gated on `is_staff` + MFA-enrolled; sensitive mutations additionally take a fresh `mfa_code`):
  - Platform kill switch (delegates to existing L3 in `apps/risk/killswitch.py`; **L3 blocks intake and does NOT flatten** — ADR-081, `killswitch.py:117`).
  - User list/search/detail, disable/enable (disable also revokes refresh-token families).
  - Read-only impersonation-for-debug (15-min purpose-scoped token, heavily audited).
  - Audit search with filters + CSV export.
  - System health aggregation (queue depths, broker stream status, HMM model age, sentiment backlog, DB/Redis, last verifier run, active halts).
  - Feature-flag registry + toggles.
- Frontend `/admin` area (lazy, `adminGuard`), incl. `is_staff` exposure on `/me` + token payload.
- Observability polish (§6.5): `/metrics` → multiprocess-aware `prometheus_client` exposition outside Django's urlconf, wired at the gunicorn **WSGI** entry (+ ASGI mirror for dev/daphne), with basic auth (removes the Sentry `before_send` mitigation); FIX-C1 worker/beat/streams scrape; `celery_queue_depth{queue}` + `sentiment_queue_oldest_age_minutes` gauges; postgres/redis exporters (compose + agent config; Railway = operator); Sentry `release=` tagging (backend) + frontend Sentry activation via runtime `config.js`; SLO panel + last-incident note on all six committed dashboards; alert rules committed as Grafana-provisioning files with a metric-name cross-check test.
- OTel tracing code-side (frozen decision 7) + `request_id` (ULID) correlation across web → Celery → logs → Sentry.
- SLO definitions (`docs/slo.md`), on-call doc, incident runbooks, postmortem template.

## 3. Out of Scope

- SOC 2 / audit certification readiness (post-MVP).
- User self-service data export (M11 adds GDPR basics; M11's export includes audit events — the M10 schema must not preclude per-user extraction, and anonymization keeps a stub row so the chain stays intact).
- Multi-admin RBAC beyond the existing `is_staff` boolean (no roles/permissions matrix).
- 15-minute MFA step-up window (frozen decision 5).
- Public (non-admin) feature-flag endpoint; user-facing UI stays reactive to backend error codes (`BROKER_DISABLED`, `BACKTEST_DISABLED`, …) as today.
- Master plan §9 "Business" dashboard (DAU, trades/user, P&L distribution) — deferred to M12 beta.
- Grafana OnCall / PagerDuty setup (email + Telegram contact points only; PagerDuty listed as fallback in risks).
- Audit table partitioning (plain indexed table now; documented threshold triggers a future partitioning task — §16).

## 4. Acceptance Criteria

Each AC is tagged **[CI]** (provable by tests/local gauntlet) or **[LIVE]** (needs staging/externals; becomes a documented operator step when run non-interactively).

| # | Criterion |
|---|-----------|
| AC-10-1 | **[CI]** Every action in the §6.1 event table writes an `AuditLog` row with `self_hash = SHA-256(prev_hash ‖ canonical_payload)` per ADR-100 (genesis `prev_hash` = 64 zeros). Golden-vector unit tests pin the canonical algorithm; integration tests prove emission for each event family. The high-volume exclusion (frozen decision 2) is documented in ADR-100. |
| AC-10-2 | **[CI]** Nightly Celery-beat verifier resumes from a persisted cursor, recomputes each row's hash, and on mismatch: increments `audit_integrity_check_total{result="fail"}`, emails the operator (Anymail/Resend), and writes an `audit.integrity_failure` row. It also asserts the Postgres enforcement triggers still exist (drop-detection). **[LIVE]** Grafana rule pages Telegram+email on the failure metric. |
| AC-10-3 | **[CI]** Append-only is enforced in Postgres by triggers that raise on UPDATE/DELETE **for every role, including the table owner**, and an INSERT whose `prev_hash` doesn't match the current chain head is rejected — proven by Postgres-lane tests (§10.2). A restricted role (INSERT+SELECT only) is created and privilege-tested in the CI Postgres. **[LIVE]** Provisioning the restricted role on Railway's single-role Postgres is an operator runbook step (`docs/runbooks/audit-integrity-failure.md` appendix). |
| AC-10-4 | **[CI]** All `/api/v1/admin/*` endpoints require `is_staff` + MFA-enrolled; non-admin (and impersonation-token) requests get 403 `FORBIDDEN` — parametrized test across every admin route. Admin logs in via the normal login+MFA flow. `is_staff` is exposed on `/me` and in the token-pair `user` payload; the frontend `/admin` routes sit behind `adminGuard` (backend remains authoritative). |
| AC-10-5 | **[CI]** Platform kill switch on `/admin`: engage requires typed confirm `HALT PLATFORM` (validated server-side, not just UI) + fresh `mfa_code`; release requires admin + fresh `mfa_code`. Both delegate to `apps/risk/killswitch.trigger_halt/release_halt` (level L3) — no parallel halt path. UI copy + runbook state that L3 blocks new order intake and does **not** flatten positions. |
| AC-10-6 | **[CI]** Audit search filters: user, actor, event type, entity type/id, date range; paginated; CSV export streams with `_csv_safe` guarding and translated headers. **[LIVE]** p95 ≤ 500 ms on 10M rows on staging-class hardware; the CI proxy is an EXPLAIN-based index-usage assertion on a seeded Postgres table (§10.2). |
| AC-10-7 | **[CI]** Impersonation: admin + fresh `mfa_code` + required reason mints a 15-min access-only token (`purpose="impersonation"`, `actor_id`, `session_id` claims; `user_id` = target). SAFE_METHODS only; `/api/v1/admin/*` and the dashboard WebSocket reject it; stop revokes immediately (session check, not just expiry); every impersonated request writes an audit row with `actor_id` (admin) + `user_id` (target). |
| AC-10-8 | **[CI]** All six committed dashboards (`infra/grafana/`: Trading Ops, System Health, Data Pipelines, Backtest Ops, Auth Health, Risk Ops) gain ≥1 SLO panel + a "last incident" text panel, and every panel references only series that are actually scrapeable after §6.5 (worker/beat scrape wired). **[LIVE]** Import + verify populated on staging. |
| AC-10-9 | **[CI]** Alert rules covering the reconciled master-plan §9 table (§6.5, incl. the three M09 backtest rules) are committed as Grafana-provisioning files, and a unit test cross-checks every referenced metric name against the codebase's exported metric names. A test asserts the rule set contains a **dead-man's switch** — at least one `absent()` rule and one `up == 0` rule, both `severity: critical` (BUG-008). **[LIVE]** Rules imported to Grafana Cloud, and **every rule in the StratTraderPro folder reports `isPaused: false`** via `GET /api/v1/provisioning/alert-rules` (BUG-009); **one of the real, committed rules** is driven to fire and is received on both email and Telegram. |

> **AC-10-9 was rewritten on 2026-07-11 because the original wording was structurally incapable of failing.** It read: *"Rules imported to Grafana Cloud; **a sample alert fires** and is received on both email and Telegram."* That was satisfied by creating a *temporary* rule and watching it page — which proves the notification pipeline and **nothing about the rules the platform actually depends on**. It passed while all 17 imported rules were `isPaused: true` and could never fire (Grafana's Prometheus-rule converter imports paused by default). A criterion that exercises a fresh copy of the thing is not a test of the thing. The `isPaused` assertion is the part that would have caught it.
| AC-10-10 | **[CI]** OTel tracing initialized (Django, Celery, redis, psycopg2, httpx) with OTLP export enabled only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; spans on the webhook→sizing→order path carry `user_id_hash`, `strategy_id`, `alert_id`, `broker` — asserted via an in-memory span exporter test; the Sentry `request_id`/`trace_id` tagging helper is unit-tested with a capturing transport; backend `sentry_sdk.init(release=GIT_SHA)`; frontend Sentry activated via runtime `window.STP_CONFIG` (dsn/environment/release). **[LIVE]** Real Sentry events carrying the tags + Sentry-issue → Grafana Tempo trace click-through verified on staging. |
| AC-10-11 | **[CI]** Feature-flag flips via admin API/UI take effect without redeploy within ≤ 60 s across web + workers (30 s process cache + Redis): integration test proves a gated endpoint toggles 503⇄200 in-process after a flip once caches expire (time-travel, not sleep). Immutable flags are rejected with `FLAG_IMMUTABLE`; every flip is audited and increments `feature_flag_flips_total{flag}`. |
| AC-10-12 | **[CI]** `/metrics` is served outside Django's URL conf by a multiprocess-aware `prometheus_client` exposition app wired into **`config/wsgi.py` (the gunicorn prod entry — `docker/backend.Dockerfile:68` runs `config.wsgi`, not ASGI) and mirrored in `config/asgi.py` for dev/daphne**, with basic auth enforced in prod settings (WSGI-callable-level test); the `_sentry_before_send` mitigation is deleted; worker, beat, and streams processes expose scrapeable metrics via `TASK_METRICS_PORT`; `celery_queue_depth{queue}` and `sentiment_queue_oldest_age_minutes` gauges exist and are exercised by tests. |

## 5. Definition of Done

Baseline DoD (project-plan/README.md) applies, plus:

- New runbooks: `incident-triage.md` (severity table mapping every §6.5 alert → runbook → escalation), `audit-integrity-failure.md`, `platform-halt.md`, `alerting-setup.md` (Grafana Cloud import, contact points, Telegram bot creation); `worker-metrics-scrape.md` updated from "options" to "implemented".
- `docs/oncall.md` (solo rotation: operator contact + alternate), `docs/postmortem-template.md`, `docs/slo.md` (SLOs + error budgets + backing series).
- Monthly integrity-verification spot-check added to the runbook calendar (precedent: `kill-switch-verify-monthly.md`).
- ADR-100, ADR-101, ADR-102 committed (§14).
- OpenAPI schema + frontend types regenerated (`make schema` → `docs/openapi/openapi.json` is canonical, then `pnpm run schema:types`).
- Admin pages are staff-only, so no `/frontend/src/assets/help/` user articles are required; operator docs live in the runbooks instead (explicit DoD exemption, mirroring the M05 TS-descope precedent).

## 6. Implementation Tasks

### 6.0 Day-1 spike (before feature code)

1. **Postgres test lane**: add `backend/config/settings/test_pg.py` (imports `test.py`, overrides `DATABASES` from `DATABASE_URL`); add a `pg` pytest marker + `@skipUnless(connection.vendor == "postgresql")` helper; add a CI step in `backend-lint-test` running `DJANGO_SETTINGS_MODULE=config.settings.test_pg python -m pytest -m pg` against the **already-provisioned but currently unused** `postgres:16-alpine` service container (`ci.yml` exports `DATABASE_URL=postgres://test_user:test_pass@localhost:5432/test_db` today; `config/settings/test.py` hardcodes SQLite, which is why it's unused). Register the marker in `pytest.ini` (`markers = pg: requires PostgreSQL`); default runs need no addopts change — the skip decorator handles SQLite.
2. **Trigger prototype** on local compose Postgres: BEFORE UPDATE/DELETE raise; BEFORE INSERT chain-linkage check + `pg_advisory_xact_lock`; confirm the raise fires for the table owner too.
3. **OTel resolver spike**: pin `opentelemetry-instrumentation-{django,celery,redis,psycopg2,httpx}` versions compatible with the existing `opentelemetry-distro[otlp]>=0.43b0`; import + init smoke; confirm no conflict with `sentry-sdk 1.x`.
4. Pin `python-ulid` for request IDs.
5. **Metrics-dispatcher smoke**: minimal `config/metrics_endpoint.py` behind the gunicorn WSGI entry locally (Dockerfile CMD parity), proving multiproc mmap visibility + basic auth before the real cutover (§6.5a).

Record spike outcomes before proceeding.

### 6.1 Audit log (`apps/audit`)

`apps/audit` is already in `INSTALLED_APPS` (`base.py:92`) with empty stubs — build it out:

**Model `AuditLog`** (per master plan Appendix B, adapted): `id` BigAutoField, `occurred_at` DateTimeField(`default=timezone.now`, db_index) — **NOT `auto_now_add`**: `emit()` assigns the timestamp once, hashes that exact value, and passes it to the INSERT. (`auto_now_add` would silently overwrite the hashed value in `pre_save`, making every stored row fail verification, and would also block historical backfill in the data migration.) `user` FK SET_NULL null, `actor` FK SET_NULL null (admin acting), `event_type` CharField(64) choices from taxonomy, `entity_type` CharField(64) blank, `entity_id` CharField(64) blank, `data_before` JSONField null, `data_after` JSONField null, `ip` GenericIPAddressField null, `ua` CharField(512) blank, `prev_hash` CharField(64), `self_hash` CharField(64). Indexes: `(user, occurred_at)`, `(actor, occurred_at)`, `(event_type, occurred_at)`, `(entity_type, entity_id, occurred_at)`, `occurred_at`. Table `audit_log`.

**Event taxonomy** (TextChoices, namespaced): `auth.*` (one per existing `AuthEvent.EventType` — 26 values, e.g. `auth.login_ok`, `auth.mfa_enrolled`), `broker.connect|disconnect|mode_change`, `order.submitted|fill_ingested`, `strategy.created|updated|deleted|secret_rotated`, `risk.profile_changed|halt_engaged|halt_released`, `admin.user_disabled|user_enabled|impersonation_started|impersonation_stopped|impersonated_read|platform_halt_engaged|platform_halt_released`, `flag.flipped`, `audit.integrity_failure|verifier_completed`.

**Hashing (`apps/audit/hashing.py`)** — the single canonical implementation (ADR-100):
- `canonical_payload(row) -> bytes`: JSON with sorted keys, `separators=(",", ":")`, of `{occurred_at (ISO-8601 UTC with microseconds), user_id, actor_id, event_type, entity_type, entity_id, data_before, data_after, ip, ua}`. `id` is excluded (unknown before insert on the Python path); chain order is defined by the serialized inserts, and the verifier walks in `id` order.
- `self_hash = sha256(prev_hash_hex_bytes + canonical_payload)`. Genesis `prev_hash` = `"0" * 64`.
- Golden vectors committed as fixtures (fixed inputs → exact hex digests) so any refactor that changes canonicalization fails loudly.

**Write path (`apps/audit/services.py`)** — explicit service call, matching the repo's service-layer convention (the repo has exactly one signal receiver; `push_to_user`/`record_event` are the established patterns — do NOT introduce a signals-based `audit_logger`):
- `emit(event_type, *, user=None, actor=None, entity_type="", entity_id="", data_before=None, data_after=None, request=None, metadata=None)` — assigns `occurred_at = timezone.now()` once and hashes that exact value; captures ip/ua from `request` like `record_event` does; scrubs sensitive keys from `data_before/after` — the audit scrubber's key set is the existing `SENSITIVE_KEYS` (`authorization`, `sig`, `secret`, `password`, `token`, `api_key`, `dsn` — `base.py:618`) **∪ `{key, code, mfa_code}`** (admin mutations post `mfa_code` in bodies that can land in diffs) — via a **relocated** scrubber `apps/audit/scrub.py` — move `_scrub_sensitive` + `SENSITIVE_KEYS` out of `base.py:618-626` and update `apps/users/tests.py:40-51`, which imports and tests the settings copy (it is NOT dead code). Exception ordering is exact — `try:` wrapping `with transaction.atomic(): <advisory lock → head read → hash → insert>` with the `except` OUTSIDE the atomic block (catching a trigger `RAISE` inside it throws `TransactionManagementError`); when called inside a business transaction this nests as a savepoint. On Postgres take `pg_advisory_xact_lock(hashtext('audit_log'))` before reading the chain head (`order_by("-id").first()`). Audit emission must never break the business action: on failure, log + `audit_events_dropped_total` (the enforcement triggers are the integrity backstop, not app exceptions).
- `apps/users/services.record_event` keeps its signature and delegates to `emit("auth." + event_type, ...)` with `email`/`metadata` folded into `data_after`.

**AuthEvent decommission (surgical list — skipping any item leaves the app unable to import):** relocate the `EventType` TextChoices to `apps/audit/events.py` (single taxonomy source); repoint the 5 module-level imports (`users/views.py:22`, `views_m02.py:48`, `views_oauth.py:49`, `services.py:25`, `admin.py:5`) and all ~38 `AuthEvent.EventType.*` usages. Two direct writers need special handling: `strategies/views.py:213` calls `record_event("register", …)` for strategy upload (an M03 shim) — replace with a proper `emit("strategy.created", …)`; `users/admin.py:60-70` `force_disable_mfa` does a raw `AuthEvent.objects.create(...)` — replace with `emit("auth.mfa_disabled", actor=request.user, …)`. Update every users-app test that asserts `AuthEvent` rows.

**Enforcement (migration `audit.0002_chain_triggers`, `RunSQL` with `state_operations=[]`, guarded by `connection.vendor == "postgresql"` inside a `RunPython`-dispatched SQL or `elidable=False` conditional — SQLite runs skip it):**
- `audit_log_block_mutation`: BEFORE UPDATE OR DELETE → `RAISE EXCEPTION 'audit_log is append-only'`. Fires for every role, including the owner — this is the primary enforcement on Railway's single-role Postgres.
- `audit_log_check_link`: BEFORE INSERT → take the same advisory lock, compare `NEW.prev_hash` to the current head's `self_hash` (or genesis when empty), `RAISE` on mismatch; also `RAISE` unless `self_hash ~ '^[0-9a-f]{64}$'`.
- Reverse migration recreates nothing (irreversible-safe: `reverse_sql` drops triggers with a loud comment; post-launch trigger removal is runbook-gated).

**Data migration (`audit.0003_migrate_auth_events`)**: iterate `users_auth_event` ordered by `(occurred_at, id)` in batches, map to `auth.*` taxonomy, build the chain from genesis with a **frozen inline copy of the hashing functions** (migrations must not import app code that can drift); assert row-count parity + final head hash re-verifies. Then **`users.00XX_drop_auth_event`** (dependency on `audit.0003`) removes the model; delete `AuthEventAdmin`; update users tests that assert `AuthEvent` rows to assert `AuditLog` rows.

**Verifier (`apps/audit/verifier.py` + `apps/audit/tasks.py`)** — nightly beat entry `crontab(hour=8, minute=0)` in **UTC values** (`CELERY_TIMEZONE="UTC"`, `base.py:509`; ≈ 04:00 ET per master Appendix C — repo convention is UTC crontabs with ET only in comments). Joins the existing static `CELERY_BEAT_SCHEDULE` in `base.py`; default `celery` queue — M09 rule: no glob routes:
1. Load cursor (`AuditVerifierState` singleton: `last_verified_id`, `last_verified_hash`, `run_at`, `result`).
2. Walk forward in `id` order, recompute `self_hash`, compare; also verify linkage `row.prev_hash == previous.self_hash`.
3. On Postgres, assert both triggers exist via `pg_trigger` catalog; missing trigger = failure.
4. Outcomes: `audit_integrity_check_total{result="ok"|"fail"}` (in `apps/audit/metrics.py` — Prometheus-only module, repo convention), email on failure via the Anymail path, `audit.integrity_failure` audit row (with suspect id range in `data_after`), advance cursor only on success.

**Emission call sites to wire** (verified locations): auth = via `record_event` repoint; broker connect `apps/brokers/views.py:75-129`, disconnect `:144-162`, mode change `:210-236`; order submitted in `apps/webhooks/tasks.py:process_alert` (~`:297`, after `place_order`, with `alert_id`/order ids in `data_after`); fill ingested in `apps/orders/services.py:ingest_fill_event` (~`:128`, dedup-aware — only on newly-applied fills); halts in `apps/risk/killswitch.py:trigger_halt/release_halt` (covers admin L3, user L1/L0, and auto-L2: `actor` = `created_by`/None, `user` = halt target); strategies `apps/strategies/views.py:138/242/263` + rotate `:373`; risk profile `apps/risk/views.py:54-61` (PUT — capture `data_before/after` diff of serializer fields); admin portal + flags per §6.2/§6.4.

### 6.2 Admin portal backend (`apps/admin_portal`)

Gating: `IsAdminAndMFAEnforced` permission (precedent `apps/users/permissions.py:22`) — overrides `has_permission` to require, **unconditionally** (not gated on the view's `mfa_required` attribute like the base class): authenticated + `is_staff` + `user.mfa_enabled` + not an impersonation token. Sensitive mutations additionally call `verify_mfa_code(request.user, mfa_code)` (`apps/users/mfa.py:207`) — marked ⚿ below. The whole app is gated by the env-only `ADMIN_PORTAL_ENABLED` flag (off → 503 `ADMIN_PORTAL_DISABLED`; §15).

```
GET  /api/v1/admin/users/?q=&is_active=&has_broker=&page=       search: email/display_name icontains
GET  /api/v1/admin/users/{id}/                                  profile + broker accounts + recent audit (last 20)
POST /api/v1/admin/users/{id}/disable/   ⚿ {mfa_code, reason}   is_active=False + revoke all RefreshTokenFamily rows
POST /api/v1/admin/users/{id}/enable/    ⚿ {mfa_code, reason}
POST /api/v1/admin/users/{id}/impersonate/start/ ⚿ {mfa_code, reason}  → {token, expires_at, session_id}
POST /api/v1/admin/impersonation/{session_id}/stop/             idempotent; sets ended_at

GET  /api/v1/admin/audit/?user=&actor=&event_type=&entity_type=&entity_id=&occurred_after=&occurred_before=&page=
GET  /api/v1/admin/audit/export.csv?<same filters>              streamed, _MAX_EXPORT cap, _csv_safe (orders precedent)

GET  /api/v1/admin/platform/status/                             active L3 halt (if any) + is_blocked summary
POST /api/v1/admin/platform/killswitch/  ⚿ {engage: bool, reason, confirm?, mfa_code}
     engage=true additionally requires confirm == "HALT PLATFORM" (server-side; 400 CONFIRM_PHRASE_MISMATCH)
     → delegates to killswitch.trigger_halt(user_id=None, level=L3, created_by_id=admin) / release_halt

GET  /api/v1/admin/flags/                                       registry + effective state + source (db|env-default)
POST /api/v1/admin/flags/{name}/         ⚿ {enabled, mfa_code}  immutable → 400 FLAG_IMMUTABLE

GET  /api/v1/admin/health/                                      aggregation, see below
```

Notes:
- **Disable semantics**: revoking refresh families kills sessions; simplejwt access tokens die at next auth check because `is_active=False`. Open positions are NOT auto-flattened — the endpoint response reminds the admin to engage an L1 halt with flatten if needed (documented in `platform-halt.md`).
- **Impersonation**: `ImpersonationSession` model (UUID id, actor FK, target FK, reason, started_at, expires_at = +15 min, ended_at null, ip, ua). Token = simplejwt `Token` subclass (precedent `_MFAToken`, `apps/users/mfa.py:169-204`): `token_type="access"`, claims `purpose="impersonation"`, `session_id`, `actor_id`; `user_id` = target so existing owner-scoped views Just Work; no refresh token. **The write-block is enforced at the AUTHENTICATION layer, not via a global permission** — a `DEFAULT_PERMISSION_CLASSES` entry would be silently dropped by every view that overrides `permission_classes`, which is ALL mutating views (`[IsAuthenticatedAndMFAEnforced]` across brokers/orders/risk/strategies/backtest, `[IsAuthenticated]` in users). Subclass `JWTAuthentication` as `apps/users/authentication.ImpersonationAwareJWTAuthentication` and set it as the project-wide `DEFAULT_AUTHENTICATION_CLASSES` entry (`base.py:216-218`): when the validated token carries `purpose="impersonation"` it (a) loads the `ImpersonationSession` and raises `AuthenticationFailed` if ended/expired (cached ~5 s → **stop revokes immediately**), (b) raises `PermissionDenied` for any non-SAFE_METHOD request, (c) attaches `request.impersonation` for downstream denies (`IsAdminAndMFAEnforced`, CSV exports) and emits `admin.impersonated_read` exactly once per request. `DashboardConsumer` (`apps/dashboard/consumers.py`) closes impersonation tokens with 4403.
- **Health aggregation (`apps/admin_portal/health.py`)**: Celery queue depths (Redis `llen` on `celery`, `backtest`), broker stream status counts (via `apps/brokers/services.get_stream_status` heartbeats), active HMM model age (`HMMModel.trained_at`), sentiment backlog (depth + oldest-age via the `queue_backlog()` logic, `apps/sentiment/tasks.py:82-91`), DB/Redis ping (readyz-style), last verifier run + result, active halts count, flags overridden-from-default count.
- All admin mutations emit audit rows (`actor` = admin, `user` = target where applicable) with `data_before/after`.

### 6.3 Frontend admin area (`/admin`)

- **Backend prerequisite**: add `is_staff` to `apps/users/services.serialize_user` (`services.py:343` — this builds the `user` object in every token-pair response; note `AuthTokenObtainSerializer.get_token` only adds JWT claims and does NOT feed the response payload) and to `CurrentUserSerializer.Meta.fields` (`serializers.py:113-118`, backs `/me`); frontend `AuthUser` gains `is_staff` (`core/models/auth.models.ts`); update `auth.models.contract.spec.ts`; regen schema types.
- **`adminGuard`** (`core/guards/admin.guard.ts`, `CanMatchFn` like `authGuard`): authenticated + `user.is_staff`, else redirect `/dashboard`. Backend 403 remains authoritative.
- **Routes** (lazy `ADMIN_ROUTES` group registered in `app.routes.ts` like `RISK_ROUTES`; every route `canMatch: [authGuard, adminGuard]`): `/admin` overview (KPI cards from `/admin/health/` + platform kill-switch card + active-halt banner), `/admin/users` (search table), `/admin/users/:id` (detail + disable/enable with inline MFA + recent audit), `/admin/audit` (filter form + paginated table + CSV export via the `orders.facade.ts` blob pattern), `/admin/flags` (registry list, toggles with inline MFA; `dangerous` flags additionally require typing the flag name; `immutable` rendered read-only), `/admin/health` (full cards + external Grafana links).
- **Layering**: `core/services/admin.api.ts` → `abstraction/stores/admin.store.ts` (signals) → `abstraction/facades/admin.facade.ts` → standalone OnPush components (`@if/@for`, `inject()`, Tailwind kit — no component library).
- **HALT PLATFORM modal**: net-new typed-confirm modal (shell precedent `webhook-config-modal.component.ts`; MFA input reuses `app-totp-input`). Input must equal `HALT PLATFORM` exactly; server re-validates.
- **Grafana links**: extend `docker/nginx.conf.template` `/config.js` (`window.STP_CONFIG`) with `grafanaUrl` (and Sentry fields, §6.5e); health page renders `<a target="_blank" rel="noopener">` per dashboard. Empty → links hidden.
- **Nav entry**: render the existing orphaned `nav.admin` key as a header link on the dashboard page, visible when `is_staff` (no global nav shell exists — do not build one).
- **Specs (karma)**: `admin.store.spec.ts`, `admin.facade.spec.ts` (spyObj pattern per `backtest.facade.spec.ts`), `admin.guard.spec.ts`.

### 6.4 Feature flags (`apps/admin_portal/flags.py`)

- **Registry** `settings.FEATURE_FLAGS_REGISTRY` (in `base.py`, defined after the flag settings): `{name: {"default": <the env-parsed settings value>, "description": str, "mutable": bool, "dangerous": bool}}` for the **18 real flags** + `ADMIN_PORTAL_ENABLED`: `MFA_ENABLED`*, `GOOGLE_OAUTH_ENABLED`, `STRATEGIES_V1_ENABLED`, `WEBHOOK_V1_ENABLED`, `BROKER_ALPACA_ENABLED`, `BROKER_TRADESTATION_ENABLED`, `ENABLE_LIVE_TRADING`†, `FILLS_INLINE`*, `ENABLE_REGIME_UI`, `SENTIMENT_ENABLED`, `LLM_WORKER_ENABLED`, `FINBERT_ENABLED`, `SENTIMENT_FAKE_SCORERS`†, `SENTIMENT_SPACY_NER`, `SENTIMENT_ALIAS_TAGGING`, `SIZING_V1_ENABLED`†, `KILL_SWITCHES_ENABLED`*, `BACKTEST_ENABLED`, `ADMIN_PORTAL_ENABLED`* (* = immutable/env-only; † = dangerous, typed-confirm in UI). There is **no `AUTH_V1_ENABLED`** — the original plan invented it; auth has no flag.
- **Model** `FeatureFlag` (in `admin_portal`): `name` unique (validated against registry), `enabled`, `updated_by` FK, `updated_at`, `note`.
- **Read helper** `is_enabled(name) -> bool`: registry check → 30 s process-local cache → Redis (`flag:{name}`, TTL 60 s) → DB row → registry default (the env value). Immutable flags short-circuit to the settings value. Fail-open to the env default on Redis/DB errors (never let flag plumbing take the platform down).
- **Flip path**: DB write + Redis set + local-cache bust + audit `flag.flipped` (before/after) + `feature_flag_flips_total{flag}`.
- **Call-site refactor** — replace `getattr(settings, "<NAME>", default)` gates with `is_enabled("<NAME>")` at exactly these verified sites: `webhooks/views.py:95`, `backtest/views.py:37` + `backtest/tasks.py:82`, `brokers/services.py:65`, `brokers/tradestation/views.py:32`, `brokers/views.py:49` (`_alpaca_enabled`), `strategies/views.py:74`, `risk/integration.py:91`, `sentiment/views.py:33` + `sentiment/routing.py:85` + `sentiment/scorers.py:177-185`, `users/views_oauth.py:88`. **Leave immutable-flag sites on `settings.X`** (`users/views_m02.py` MFA gates, `risk/killswitch.py:36`, `FILLS_INLINE` readers) — the helper would return the same value, but keeping direct settings reads makes their env-only nature visually obvious.
- Import-safety: `is_enabled` must be call-time only (no module-level flag reads), and safe before migrations run (`FeatureFlag` table may not exist during `migrate` — catch `ProgrammingError/OperationalError` → default).

### 6.5 Observability polish

a. **Metrics exposition (carryover, `prod.py:87-92` names this fix)** — CRITICAL topology fact: **prod serves gunicorn WSGI** (`docker/backend.Dockerfile:68`: `gunicorn config.wsgi:application --worker-class gthread`; the ASGI/uvicorn setup was deliberately reverted 2026-05-20 because sentry-sdk 1.x lacks async-aware DjangoIntegration — Dockerfile:47-63), and `infra/grafana-agent/agent.yaml` scrapes THAT service. Do **not** mount `/metrics` only in `config/asgi.py` — it would exist solely on the daphne `ws` service and go dark on the scraped backend. Build a small shared module `config/metrics_endpoint.py`: `prometheus_client` exposition (using `MultiProcessCollector` when `PROMETHEUS_MULTIPROC_DIR` is set, per-process registry otherwise) + basic-auth check (`METRICS_BASIC_AUTH_USERNAME/PASSWORD` env; unset → dev/test open, prod logs a loud warning). Wire it (1) into `config/wsgi.py` as a `PATH_INFO == "/metrics"` dispatcher in front of the Django WSGI app — same gunicorn process, so the multiprocess mmap files are readable — and (2) into the `config/asgi.py` http router for dev runserver/daphne parity. Remove `include("django_prometheus.urls")` from `config/urls.py:67`; keep the `django_prometheus` middlewares + DB engine wrappers (they *produce* the http/db series). **Delete `_sentry_before_send`** and its `before_send=` wiring (`prod.py:55-103,121`): under the WSGI revert the allauth/ASGI crash it filtered cannot occur, and `/metrics` no longer traverses Django middleware anyway. Update `agent.yaml` scrape with `basic_auth` (same target/path).
b. **FIX-C1 worker/beat scrape**: in `config/celery.py`, hook `worker_process_init` + `beat_init` signals → `config/task_metrics.start_task_metrics_server()` (guarded by `TASK_METRICS_PORT > 0`, `base.py:519`; streams already does this). Set distinct `TASK_METRICS_PORT` per compose service (`worker`, `worker-backtest`, `beat`, `streams`) + add agent scrape jobs; document Railway internal-DNS targets in the updated `worker-metrics-scrape.md`. Note: multiple prefork children can't share one port — run workers with `--concurrency=1` per existing compose convention, or bind port only in the first child (document the constraint; worker-backtest already runs concurrency=1).
c. **New series**: `celery_queue_depth{queue}` gauge — beat task (every 30 s, default queue, explicit route not needed) doing Redis `llen` on `celery` + `backtest`, module `apps/admin_portal/metrics.py`; `sentiment_queue_oldest_age_minutes` gauge set inside the existing backlog computation (`apps/sentiment/tasks.py:82-91`).
d. **Exporters**: add `postgres-exporter` (`prometheuscommunity/postgres-exporter`) + `redis-exporter` (`oliver006/redis_exporter`) services to `docker-compose.yml` + agent scrape entries. Railway deployment of both = **operator step** (runbook). "DB CPU > 80%" from §9 is not exposed by the exporter on managed Postgres — the committed rule alerts on saturation proxies (connection count, cache-hit ratio); actual CPU alerting is configured in the Railway dashboard (operator, documented).
e. **Sentry**: backend `sentry_sdk.init(..., release=GIT_SHA)` (`base.py:37-48` resolver; only when SHA ≠ "unknown"). Frontend: extend `/config.js` (nginx template envsubst) to `window.STP_CONFIG = {backendUrl, sentryDsn, sentryEnvironment, release, grafanaUrl}`; `main.ts` reads it at runtime instead of the hardcoded disabled skeleton (empty dsn → disabled; hashed user id set post-login, no email). Source-map upload: CI step gated on `secrets.SENTRY_AUTH_TOKEN` presence (cleanly skipped when absent — keeps CI green without the secret; wiring the secret is an operator step).
f. **Dashboards**: add ≥1 SLO panel + "last incident" text panel to each of the six committed JSONs; audit every panel's series against the post-§6.5 scrapeable set (many worker-emitted series were dark pre-FIX-C1).
g. **Alert rules as code** (`infra/grafana/alerts/*.yaml`, Grafana provisioning format + contact-point/notification-policy templates with env placeholders): reconciled table below. A pytest cross-checks each rule's referenced series against metric names exported by the codebase (static scan of `metrics.py` modules + known `django_prometheus`/exporter names).

| Source | Rule | Backing series |
|---|---|---|
| §9 | Webhook 5xx ratio > 1% warn / > 2% crit, 5 min | `django_http_responses_total_by_status_total` (+ by-view series for the hooks view; implementer verifies exact django_prometheus names from `/metrics`) |
| §9 | Broker stream silent > 2 min | `broker_stream_heartbeat_age_seconds` > 120 |
| §9 | Celery queue depth > 1000 | `celery_queue_depth{queue}` (new) |
| §9 | Kill switch triggered | `increase(killswitch_trigger_total[5m]) > 0` |
| §9 | Sentiment lag > 30 min | `sentiment_queue_oldest_age_minutes` (new) > 30 |
| §9 | HMM model age > 48 h | `regime_model_age_seconds` > 172800 (weekend mute-timing documented) |
| §9 | DB saturation | postgres-exporter proxies; Railway CPU alert = operator (see d) |
| M10 | Order submit p95 > 2 s, 10 min | `order_submit_latency_seconds` (defined in `webhooks/metrics.py`) |
| M10 | Flatten p99 > 5 s (page) | `killswitch_flatten_latency_seconds` |
| M10 | Audit integrity failure (page) | `audit_integrity_check_total{result="fail"}` (new) |
| M09 | Backtest queue wait / failure rate / artifact size | `backtest_queue_wait_seconds`, `backtest_failed_total`, `backtest_artifact_bytes` (CHANGELOG: "live wiring is M10") |

The original plan's "deploy rollback event" alert has no in-code signal — replaced by a Railway deploy-notification setup note in `alerting-setup.md` (operator).

**SLOs (`docs/slo.md`)**: webhook availability ≥ 99.9% (5xx ratio on the hooks view); order submit p95 ≤ 1.5 s (`order_submit_latency_seconds` — alert threshold 2 s is the page line, 1.5 s the SLO); dashboard API p95 ≤ 300 ms (django_prometheus by-view latency); kill-switch flatten p99 ≤ 5 s. Error budgets + burn guidance per SLO.

### 6.6 Correlation & context

- **`RequestIdMiddleware`** (new, `config/middleware.py`): honor inbound `X-Request-ID` else mint a ULID (`python-ulid`); store in a `contextvars.ContextVar`; echo response header.
- **Logging**: a `logging.Filter` injects `request_id` (+ `task_id` when in Celery) into every record; add to the existing `python-json-logger` LOGGING config (`base.py:629-655`). **structlog is pinned but unwired — do not adopt it in M10**; either leave the pin or drop it (drop, and note in CHANGELOG). The original plan's "structlog contextvars" wording is void.
- **Celery propagation**: `before_task_publish` copies `request_id` into task headers; `task_prerun` restores the contextvar; `task_postrun` clears.
- **Sentry**: tag every event `request_id` + `trace_id` (from the active OTel span context when tracing is on).
- **OTel init** (`config/otel.py`, called from **`config/wsgi.py` (the prod gunicorn entry — same trap as §6.5a: asgi-only wiring leaves the prod web tier untraced)** + `config/asgi.py` (dev/daphne mirror) + `worker_process_init`): instrument Django, Celery, redis, psycopg2, httpx; resource from `OTEL_SERVICE_NAME` (`base.py:663-666`); OTLP exporter only when `OTEL_EXPORTER_OTLP_ENDPOINT` set (empty default = no-op, keeping tests/dev clean). Span attributes on the webhook→order path: `user_id_hash` (sha256 of user UUID, first 16 hex — never raw id in trace backends), `strategy_id`, `alert_id`, `broker`. Grafana Cloud Tempo endpoint config + Sentry→Tempo correlation = operator steps in `alerting-setup.md`.

## 7. Tech Stack Notes

- **No pgcrypto**: hashes are computed in Python (frozen decision 3); triggers only compare strings and raise. `pg_advisory_xact_lock` serializes chain-head reads (fine at 10–50 users; excluded high-volume events keep the lock cold).
- **Grafana Cloud** (existing: agent remote_write via `infra/grafana-agent/`, datasource `grafanacloud-YOUR_ORG-prom`); metrics are **pushed by the agent**, not "scraped from Grafana Cloud".
- **Telegram Bot API** as a Grafana contact point (no backend Telegram code); email via existing Anymail/Resend for verifier direct-pages.
- **python-json-logger** stays the logging stack (structlog unwired — see §6.6).
- **python-ulid** new dependency (request IDs); OTel instrumentation pins per Day-1 spike.
- Feature flags deliberately simple — no LaunchDarkly-style targeting at 10–50 users.

## 8. Data Model Changes

Migrations (order matters):
- `audit.0001_initial` — `AuditLog`, `AuditVerifierState` (+ indexes).
- `audit.0002_chain_triggers` — Postgres-only enforcement triggers (vendor-guarded; no-op on SQLite).
- `audit.0003_migrate_auth_events` — chain-building data migration from `users_auth_event` (frozen inline hashing copy; count + head-hash assertions). `dependencies = [("audit", "0002_chain_triggers"), ("users", "<latest users migration>")]` — the explicit users dependency pins historical model state so `apps.get_model("users", "AuthEvent")` resolves. Historical `occurred_at` values insert directly (possible because the field is `default=timezone.now`, not `auto_now_add`).
- `users.00XX_drop_auth_event` — depends on `audit.0003`; removes model/table (+ code: model, `AuthEventAdmin`, direct references).
- `admin_portal.0001_initial` — `ImpersonationSession`, `FeatureFlag`.

Deploy sequencing note: all in one release is acceptable (Railway runs `migrate` before serving); the drop is preceded in the same `migrate` run by the completed data migration. Rollback = restore from backup (see §15/§16).

## 9. API Contract Changes

- New endpoints per §6.2 (all under `/api/v1/admin/`, mounted in `config/urls.py`; no collision with Django admin at `/admin/` — different path space and, on Railway, different service domains than the SPA's `/admin` route).
- `/me` + token-pair `user` payload gain `is_staff`.
- OpenAPI schema + frontend types regenerated (`make schema`, then `cd frontend && pnpm run schema:types`); repo-root `docs/openapi/openapi.json` is canonical.

## 10. Test Plan

Repo conventions: unittest-style per-app `test_*.py`, SQLite `:memory:` default, eager Celery, ≥ 90% coverage on new code (stricter documented bar).

### 10.1 Unit (SQLite lane)

- Hashing golden vectors (canonical payload bytes + digests pinned); chain build over fixtures; genesis handling.
- `emit()`: scrubbing (secrets never stored; scrubber relocated from `base.py` — `apps/users/tests.py:40-51` updated to the new import), ip/ua capture, hashed-timestamp-equals-stored-timestamp property, never-raises guarantee (`audit_events_dropped_total` on induced failure).
- `record_event` repoint: every existing users-app auth test updated to assert `AuditLog` rows (event_type `auth.*`).
- Verifier: detects synthetic tamper (mutate a row via direct ORM `update()` on SQLite where triggers don't exist — exactly why the Python verifier must catch it), cursor resume, linkage-break detection.
- Flags: default fallback, DB override, cache expiry (time-travel via `freezegun`-style or manual clock injection — no sleeps), immutable rejection, registry validation, missing-table safety.
- Impersonation: token mint/claims/TTL; authentication-layer matrix proven against a REAL mutating view that overrides `permission_classes=[IsAuthenticatedAndMFAEnforced]` (e.g. risk-profile PUT) — safe methods pass, unsafe → 403, admin routes → 403, MFA-gated → 403; session-stop immediate revocation.
- Request-id middleware + logging filter + Celery header propagation (eager-mode round trip).
- OTel: `InMemorySpanExporter` (opentelemetry-sdk) captures the eager webhook→order path; assert span attributes `user_id_hash`/`strategy_id`/`alert_id`/`broker` present and raw user id absent; Sentry `request_id`/`trace_id` tagging helper unit-tested with a capturing transport (no network).
- Alert-rule cross-check: parse `infra/grafana/alerts/*.yaml`, extract series names, assert each exists in the exported-metrics registry.
- Admin serializers/views (SQLite-compatible parts), CSV `_csv_safe`, health aggregation (fakes for Redis llen/heartbeats).

### 10.2 Postgres lane (new — `-m pg`, CI service container, local via compose Postgres)

- Triggers: UPDATE and DELETE raise **for the owner role**; INSERT with stale/wrong `prev_hash` rejected; malformed `self_hash` rejected.
- Concurrency: two threads emitting simultaneously produce a valid chain (advisory lock proof).
- Restricted role: `CREATE ROLE` with INSERT+SELECT only via raw psycopg2 as `test_user`; UPDATE/DELETE as that role → `InsufficientPrivilege`.
- Data migration: seed `AuthEvent` fixtures → run migration → chain verifies, counts match.
- Trigger-presence check (verifier's catalog query).
- Index-usage proxy for AC-10-6: seed ~50k rows, `EXPLAIN` the filtered search query, assert index scan (not seq scan).

### 10.3 Integration (eager Celery, SQLite unless marked pg)

- Admin platform kill-switch: engage (phrase + MFA) → `TradingHalt` L3 active + audit rows + webhook gate returns `PLATFORM_HALTED`; release → cleared + audited. Wrong phrase → 400, no halt.
- Disable user → families revoked, next authed call 401/403, audit row; enable restores.
- Impersonation E2E: start → GET target's orders OK (audited with actor/user), POST anything → 403, admin routes → 403, WS close 4403, stop → immediate 403 on next call.
- Flag flip → gated endpoint toggles 503⇄200 after cache expiry; flip audited + metered.
- Health endpoint composes all sections with fakes.
- Verifier beat entry registered (settings unit test, M09 precedent: assert route/queue/schedule).

### 10.4 E2E / staging (deferred-live checklist)

- Admin login → overview KPIs render; audit search + CSV export columns; flag flip reflected in admin UI ≤ 60 s; sample alert fires → Telegram + email; Sentry issue → Tempo trace link; dashboards populated.

### 10.5 Performance

- Verifier throughput: ≥ 24h of synthetic rows (≈100k) verified ≤ 5 min — pg-lane timing assertion with generous margin, exact SLA re-checked on staging.
- Audit search p95 ≤ 500 ms @ 10M rows — staging measurement (CI proxy = 10.2 index assertion).

### 10.6 Security

- Parametrized: every `/api/v1/admin/*` route × (anon → 401, non-staff → 403, staff-no-MFA-enrolled → 403, impersonation token → 403).
- JWT enforcement on admin endpoints (CSRF is N/A for JWT paths; Django-admin session paths retain CSRF as today).
- Impersonation cannot mutate anything, export CSVs (MFA-gated), or reach admin/flags.
- Secrets never in audit payloads (scrub test with webhook-secret rotation event).
- `/metrics` basic auth: tested at the WSGI-callable level (invoke the `config/metrics_endpoint.py` app / `config.wsgi` dispatcher directly — the Django test client routes the urlconf and cannot reach an out-of-urlconf mount): 401 without creds when configured, 200 + exposition payload with creds.
- bandit clean at medium+ (raw-SQL migration code included).

## 11. Security Considerations

- Impersonation is **read-only** (SAFE_METHODS + explicit denies), 15-min TTL, instant server-side revocation, reason mandatory, fully audited (actor + target). Frontend shows a persistent "impersonating" banner.
- Admin surface: `is_staff` + MFA-enrolled baseline; every mutating action takes a fresh `mfa_code` (frozen decision 5). `HALT PLATFORM` phrase validated server-side and intentionally not translated (locale-typo bypass prevention).
- Audit rows never store secrets (scrubber on `data_before/after`); webhook-secret rotation logs the event, never the secret.
- Integrity failure = high severity: runbook directs freezing audit-consumer trust + investigation before any release; the verifier email includes the suspect id range.
- Admin login from a new IP alerts via the existing `auth.login_ok` audit rows + a Grafana rule on distinct-IP admin logins (advisory; documented in `incident-triage.md`).
- `is_staff` grants API admin power — the runbook documents that granting it happens only via Django admin/shell (itself audited via `admin.user_*`? no — Django-admin edits are out of band; documented limitation + M11 hardening candidate).

## 12. Observability (meta — monitor the monitoring)

- New metrics: `audit_events_total{event_type_family}`, `audit_events_dropped_total`, `audit_integrity_check_total{result}`, `admin_impersonation_sessions_total`, `feature_flag_flips_total{flag}`, `celery_queue_depth{queue}`, `sentiment_queue_oldest_age_minutes` (all in per-app `metrics.py`, Prometheus-only modules; emitted from web/worker/beat — scrapeable only because §6.5b lands).
- Advisory (non-paging) Grafana rule: admin actions outside 07:00–23:00 operator-local (on `audit_events_total{event_type_family="admin"}`).
- The verifier reports its own duration (`audit_verifier_duration_seconds` histogram).

## 13. Translation & Localization

- Reality: `SUPPORTED_LANGUAGES = {"en"}` (`users/serializers.py:171`), single `en.json` locale file. M10 ships en-only strings through the existing frameworks — no new language.
- Frontend: `admin.*` keys in `en.json`; audit event types rendered via `('audit.event.' + type) | translate` map entries; dates via `DatePipe`, raw JSON stays ISO-8601.
- Backend CSV headers: `apps/audit/i18n.py` `LABELS`/`get_labels(lang)` (the `backtest/i18n.py` precedent), keyed by the requesting admin's `UserProfile.language`.
- `HALT PLATFORM` confirm phrase stays English by design (see §11).

## 14. Documentation Deliverables

- `docs/adr/100-audit-hash-chain.md` — app-computed chain, trigger enforcement, advisory lock, AuthEvent migrate+drop, high-volume exclusion (deviation from master §6.11), SQLite degradation.
- `docs/adr/101-feature-flags.md` — DB+Redis+local-cache design, registry, immutable/dangerous sets, fail-open rationale, why not `apps/core`.
- `docs/adr/102-observability-topology.md` — out-of-urlconf `/metrics` exposition at the WSGI entry (+ ASGI mirror) + basic auth, worker/beat scrape (FIX-C1 closure), exporters, OTel init strategy (WSGI+ASGI+worker), Sentry releases, alert-rules-as-code.
- Runbooks + docs per §5 (incident-triage, audit-integrity-failure, platform-halt, alerting-setup, worker-metrics-scrape update, oncall, postmortem-template, slo).
- `CHANGELOG.md` under `[Unreleased]`; `PROGRESS.md` M10 row + carryover lines closed; `plan-progress-tracker.md`.

## 15. Rollback Plan

- `ADMIN_PORTAL_ENABLED` (env-only, default true in prod after cutover): false → all `/api/v1/admin/*` return 503 `ADMIN_PORTAL_DISABLED`, frontend hides `/admin`; **audit emission is never gated** (writes continue); Django admin at `/admin/` (backend service) remains the manual fallback.
- Flags UI misfire → flip back via the API, or delete the `FeatureFlag` row (reverts to env default); immutable set can't be touched at runtime by construction.
- Audit triggers: dropping them post-launch is runbook-gated (never casual); migrations' reverse ops exist but the `AuthEvent` drop is practically forward-only — rollback = DB backup restore (Railway backup before deploy is a listed operator step).
- Metrics-exposition move: revert = re-add the `django_prometheus.urls` include (one-line), agent config is backward compatible (same path).

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Canonicalization drift → false integrity pages | Low | High | Single Python implementation + frozen migration copy + golden vectors + pg cross-checks; triggers compare, never compute. |
| Chain advisory lock contention | Low | Med | High-volume events excluded (frozen decision 2); `audit_verifier_duration_seconds` + insert-latency watched; escape hatch documented in ADR-100 (per-day sub-chains) if ever needed. |
| `AuthEvent` drop is forward-only | Med | Med | Data migration asserts counts + head hash; Railway DB backup immediately before deploy (operator step in report); model kept in git history. |
| Runtime flag misuse | Med | High | Immutable set env-only; dangerous set typed-confirm + MFA; every flip audited + metered; fail-open to env defaults. |
| Audit log bloats DB | Med | Low | Plain indexed table (M06 precedent); retention 7y per master §17; partitioning deferred with explicit trigger (≥ 50M rows or ≥ 10 GB) documented in ADR-100. |
| Railway single DB role limits REVOKE | High | Low | Triggers are the primary enforcement (role-independent); restricted-role runbook for when/if provisioned; CI proves both mechanisms. |
| Telegram outage breaks paging | Low | Med | Email contact point in the same notification policy; PagerDuty free tier documented as future fallback. |
| Admin account compromise | Low | Critical | MFA-enforced + per-action codes; new-IP advisory alert; all actions audited + chained. |
| Worker metrics port collisions (§6.5b) | Med | Low | concurrency=1 convention, per-service ports, documented constraint in runbook. |

## 17. Exit Gate Checklist

- [ ] AC-10-1 … AC-10-12 **[CI]** portions green in the local gauntlet + GitHub CI (including the new `-m pg` lane).
- [ ] **[LIVE]** items documented as operator steps: restricted Railway DB role, Grafana alert import + contact points (Telegram bot), sample-alert receipt, dashboard population, Sentry→Tempo click-through, Railway exporters + `SENTRY_AUTH_TOKEN`, staging perf SLAs (audit search @10M, verifier 24h window).
- [ ] `AuthEvent` gone: model, admin, table (post-migration), all tests updated.
- [ ] Six dashboards updated (SLO + last-incident panels); alert files + cross-check test committed.
- [ ] ADRs 100–102, all §5 docs/runbooks committed.
- [ ] OpenAPI + frontend types regenerated; contract spec updated for `is_staff`.
- [ ] CHANGELOG/PROGRESS/tracker updated.
- [ ] Tag `v0.10.0-admin` created locally on the merge commit (**not pushed** — operator-gated convention).

Proceed to **M11 Hardening + Load Test**.
