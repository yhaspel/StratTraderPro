# Milestone 10 — Admin Portal, Audit Log & Observability Polish

> **Week:** 10
> **Duration:** 5 working days
> **Depends on:** M08, M09
> **Unlocks:** M11 (Hardening) — admin tooling is a prerequisite for safe load testing

## 1. Purpose

Wrap the system in operational visibility and control: a proper admin portal with platform kill switch + user management + audit search, a cryptographically-chained audit log, full-stack Sentry + Prometheus + Grafana coverage with documented SLOs and alerts. After M10, operators have the tools to detect, investigate, and contain incidents.

## 2. In Scope

- `audit` app: append-only `AuditLog` with hash chain, nightly integrity verifier.
- Migration of the stub `AuthEvent` (from M01) into `AuditLog`.
- Admin-only endpoints + UI for:
  - Platform kill switch (L3 from M08).
  - User list, search, impersonation-for-debug (with heavy auditing), disable/enable.
  - Audit search UI with filters.
  - System health view (queue depths, model freshness, broker latencies).
  - Feature-flag dashboard.
- Sentry + Prometheus + Grafana completeness pass; SLO definitions; on-call rotation doc (even if solo).
- Alert wiring to email + Telegram (solo operator channel).
- Structured log correlation (`request_id` / `alert_id` propagated across services).

## 3. Out of Scope

- SOC 2 / audit certification readiness (post-MVP).
- Full user self-service data export (M11 adds GDPR basics).
- Multi-admin RBAC (single `role='admin'` flag in MVP).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-10-1 | Every privileged action (login, MFA change, broker connect, order submit/fill, kill-switch change, strategy upload, risk profile change, admin action) writes an `AuditLog` row with `self_hash` = SHA-256(prev_hash ‖ payload). |
| AC-10-2 | Nightly integrity job verifies the whole chain; mismatch pages admin and flags in dashboard. |
| AC-10-3 | DB privileges: the app role has only INSERT + SELECT on `audit_log`; UPDATE/DELETE denied; verified by integration test. |
| AC-10-4 | Admin user can log in via normal login + MFA; non-admin users accessing `/api/v1/admin/*` receive 403. |
| AC-10-5 | Platform kill switch accessible via `/admin` UI; engaging it requires typing `HALT PLATFORM` in a confirm field; disengaging requires admin + MFA. |
| AC-10-6 | Audit search supports filters: user, event type, entity type, date range; returns paginated results with CSV export. |
| AC-10-7 | Admin can impersonate a user read-only for debug; all reads during impersonation logged with `actor_id` admin + `user_id` target. |
| AC-10-8 | Grafana has the four core dashboards (Trading Ops, System Health, Data Pipelines, Backtest Ops) + Auth Health + Risk Ops; each has at least one SLO panel. |
| AC-10-9 | Alert rules cover all items in master plan §9; sample alert fires and is received in the on-call channel. |
| AC-10-10 | Correlated traces: clicking a Sentry issue jumps to the Grafana Tempo trace for the same request. |
| AC-10-11 | Feature-flag dashboard shows all flags + current state; flips take effect without redeploy. |

## 5. Definition of Done

Baseline DoD applies, plus:

- `/docs/runbooks/` expanded to cover the top 10 anticipated incidents.
- On-call rotation document written (solo: `oncall.md` with operator phone + alternate contact).
- Monthly integrity-verification run added to runbook calendar.
- Incident postmortem template committed.

## 6. Implementation Tasks

### 6.1 Audit log (`apps/audit`)

Model per master plan Appendix B. Key details:
- `self_hash` computed in a DB trigger as `sha256(prev_hash || canonical_json(row))`. The trigger lives in migration SQL and is protected from casual drop.
- Insert path via Django signal `audit_logger` that every privileged view/service emits to.
- Migration of `AuthEvent` data → `AuditLog` via data migration.
- DB privileges: post-migration script executes `REVOKE UPDATE, DELETE ON audit_log FROM app_user;`.

Integrity verifier (`apps/audit/verifier.py`) — nightly Celery task:
1. Scans chain from last-verified cursor.
2. Recomputes each `self_hash`; compares.
3. Any mismatch: emit `IntegrityFailure` event + page.

### 6.2 Admin portal (`apps/admin_portal`)

Endpoints (all admin-only):
```
GET  /api/v1/admin/users/?q&active&has_broker
GET  /api/v1/admin/users/{id}/
POST /api/v1/admin/users/{id}/disable/
POST /api/v1/admin/users/{id}/enable/
POST /api/v1/admin/users/{id}/impersonate/start/     → issues read-only token
POST /api/v1/admin/users/{id}/impersonate/stop/

GET  /api/v1/admin/audit/?filters...
GET  /api/v1/admin/audit/export.csv?filters...

GET  /api/v1/admin/platform/status/
POST /api/v1/admin/platform/killswitch/   { engage: true|false, reason }

GET  /api/v1/admin/feature-flags/
POST /api/v1/admin/feature-flags/{name}/  { enabled }

GET  /api/v1/admin/health/                → aggregated queue depths, broker status, freshness gauges
```

All endpoints require admin role; all write to audit.

### 6.3 Frontend admin area (`/admin`)

Lazy-loaded feature behind `adminGuard`. Pages:
- `/admin` — overview with KPI cards + platform kill switch.
- `/admin/users` — searchable table, click to detail.
- `/admin/users/:id` — profile + action buttons + recent audit.
- `/admin/audit` — full audit search with filters + CSV export.
- `/admin/flags` — feature-flag list with toggles.
- `/admin/health` — embedded Grafana panels (iframe with admin token).

### 6.4 Feature flags (`apps/core/flags.py`)

A simple Redis-backed flag store (read-through with 30s local cache) keyed by flag name. API + admin UI expose toggles. All known flags listed in `settings.FEATURE_FLAGS_REGISTRY` with defaults + descriptions.

Flags exposed:
- `AUTH_V1_ENABLED`, `MFA_ENABLED`, `STRATEGIES_V1_ENABLED`, `WEBHOOK_V1_ENABLED`, `BROKER_IBKR_ENABLED`, `BROKER_TRADESTATION_ENABLED`, `SIZING_V1_ENABLED`, `KILL_SWITCHES_ENABLED`, `ENABLE_REGIME_UI`, `SENTIMENT_ENABLED`, `LLM_WORKER_ENABLED`, `BACKTEST_ENABLED`, `ENABLE_LIVE_TRADING` (admin-only).

### 6.5 Observability polish

- **Sentry:** release-tagged; frontend source-maps uploaded on deploy; user context attached (hashed); tag critical transactions.
- **Prometheus:** expose at `/metrics` protected by basic auth; scrape from Grafana Cloud.
- **Grafana dashboards** finalized; each has an SLO panel + a "last incident" note.
- **OpenTelemetry:** traces from webhook → Celery → broker → fill; span attributes `user_id_hash`, `strategy_id`, `alert_id`, `broker`.
- **Alerts** (Alertmanager via Grafana):
  - Webhook 5xx > 1% over 5 min → email + Telegram.
  - Order submit latency p95 > 2s over 10 min.
  - Kill-switch flatten latency p99 > 5s.
  - Broker disconnected > 2 min.
  - Sentiment queue lag > 30 min.
  - HMM model age > 48h on market days.
  - DB CPU > 80% 10 min.
  - Audit integrity failure.
  - Deploy rollback event.

- **SLOs:**
  - Webhook availability ≥ 99.9%.
  - Order submit p95 ≤ 1.5s.
  - Dashboard API p95 ≤ 300ms.
  - Kill-switch flatten p99 ≤ 5s.

### 6.6 Correlation & context

- `request_id` middleware generates ULIDs; propagated through Celery `headers`; emitted in structlog context + OpenTelemetry.
- Sentry `tags={"request_id":...}` and `contexts={"trace_id":...}` so deep links to Tempo work.

## 7. Tech Stack Notes

- **PGCrypto** for `sha256()` in triggers.
- **Grafana Cloud** free tier covers our scale; OnCall add-on for paging.
- **Telegram Bot API** for solo-operator paging (cheap and reliable).
- **Structlog** contextvars for correlation-id threading.
- Feature flags are simple — no need for full LaunchDarkly-style system at 10–50 users.

## 8. Data Model Changes

Migrations:
- `audit.0001_initial` — `AuditLog` + DB trigger.
- `audit.0002_migrate_auth_event_data`.
- `admin_portal.0001_initial` — `ImpersonationSession`.
- `core.0001_feature_flags`.

## 9. API Contract Changes

Paths per §6.2 + §6.4.

## 10. Test Plan

### 10.1 Unit tests

- Audit trigger computes correct hash; insert with tampered `self_hash` still gets overwritten by trigger (defense in depth).
- Verifier detects synthetic tamper (manual UPDATE via a superuser connection) and flags.
- DB privileges: attempt UPDATE/DELETE with app role raises `InsufficientPrivilege`.
- Feature flags cache invalidation on flip.

### 10.2 Integration

- End-to-end: kill-switch engagement writes audit; integrity verifier passes.
- Admin impersonation issues a short-lived read-only token; token cannot be used to place orders; every fetch logged with `actor_id`.
- Sentry receives a deliberate error from staging; trace link works.

### 10.3 E2E

- Admin logs in → sees KPI dashboard.
- Admin searches audit by user & event type; CSV export contains expected columns.
- Flag flip: `BROKER_IBKR_ENABLED=false` via admin → IBKR option hidden in user UI within 60s.

### 10.4 Performance

- Audit search p95 ≤ 500ms on a DB with 10M rows (index coverage verified).
- Verifier scans 24h of rows in ≤ 5 min.

### 10.5 Security

- CSRF + JWT enforcement on admin endpoints.
- Non-admin role rejected.
- Impersonation does not grant write scopes.

## 11. Security Considerations

- Impersonation is **read-only**; write paths reject tokens flagged `impersonation=true`.
- Admin role is MFA-enforced for every sensitive action; sensitive actions require a recent MFA verification (within 15 min).
- Audit integrity failure is high-severity; runbook requires freezing writes to audit table until investigated.
- Admin access logged from distinct source IP triggers an email to the admin's recovery email.

## 12. Observability

- Meta: monitor the monitoring.
- `audit_integrity_check_total{result}`, `admin_impersonation_sessions_total`, `feature_flag_flips_total{flag}`.
- Alert on any admin action outside business hours (advisory only, not paging).

## 13. Translation & Localization

- Admin UI strings keyed `admin.*`.
- Audit event types rendered via translation map (`audit.event.ORDER_PLACED`, `audit.event.KILL_SWITCH_ENGAGE`).
- CSV export column headers translated per user's language.
- Dates in user-visible admin output formatted per user's locale; raw JSON retains ISO-8601.
- Confirmation dialog copy (`HALT PLATFORM`) kept in English by design to prevent locale-specific bypass typos.

## 14. Documentation Deliverables

- `/docs/adr/100-audit-hash-chain.md`.
- `/docs/adr/101-feature-flags.md`.
- `/docs/runbooks/incident-triage.md` — severity table + paging escalation.
- `/docs/runbooks/audit-integrity-failure.md`.
- `/docs/runbooks/platform-halt.md`.
- `/docs/oncall.md` — rotation + contacts (solo initially).
- `/docs/postmortem-template.md`.
- `/docs/slo.md` — formal SLO definitions + error budgets.

## 15. Rollback Plan

- Feature flag `ADMIN_PORTAL_ENABLED` — if false, all `/admin/*` endpoints return 503; admin activities can still occur via Django admin.
- Audit trigger rollback is non-trivial (would lose hash chain). Pre-prod we accept drop; post-launch: never rollback the trigger without writing a plan.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Audit log bloats DB | Med | Low | Monthly partitioning; retention 7y but partitions dropped only manually. |
| Admin account compromise | Low | Critical | MFA-enforced; alert on admin login from new IP; review all actions at sign-off. |
| False-positive integrity failure | Low | Med | Clear runbook; sentry context tags the suspect row range. |
| Telegram outage breaks paging | Low | Med | Secondary email channel; PagerDuty free tier as fallback. |

## 17. Exit Gate Checklist

- [ ] AC-10-1 … AC-10-11 pass.
- [ ] Audit integrity verified on staging.
- [ ] All six Grafana dashboards complete with SLO panels.
- [ ] Sample alert fires + received in Telegram.
- [ ] Admin UI exercised end-to-end.
- [ ] ADRs 100, 101 committed.
- [ ] Runbooks updated.
- [ ] Tag `v0.10.0-admin`.

Proceed to **M11 Hardening + Load Test**.
