# Milestone 11 — Hardening, Security, Load Test & Docs

> **Week:** 11
> **Duration:** 5 working days
> **Depends on:** M10
> **Unlocks:** M12 (Beta + Signoff)

## 1. Purpose

Prepare the platform for external users with a deliberate hardening pass: security review against OWASP ASVS L2 subset, load testing at 100-user scale, chaos drills, complete user- and ops-facing documentation, and all compliance-adjacent housekeeping (terms, privacy, GDPR export/delete). No new features are added — this week is purely about making what we have durable.

## 2. In Scope

- Security review checklist against OWASP ASVS L2 (selected controls appropriate to our scope).
- Dependency audit + upgrade (all HIGH+ CVEs resolved).
- Pentest-like manual probing (auth, authz, injection, SSRF, file upload, webhook spoof).
- Load test at 100 concurrent dashboards + 20 webhooks/sec + 50 users flatten-all simultaneously.
- Chaos drills: Redis kill, worker kill, broker disconnect storm, DB failover.
- DB backup verification with test restore to a scratch instance.
- GDPR / CCPA: data export endpoint (`/api/v1/users/me/export/`), account delete request flow.
- Versioned Terms + Privacy Policy; acceptance flow on first login post-deploy.
- Final runbook sweep; on-call escalation confirmed.
- Secret rotation rehearsal (DB password + KEK + JWT signing key).
- Production Railway environment created (staging has existed; prod spins up here).
- Custom domains + Cloudflare + WAF rules.
- Accessibility audit pass (axe-core + keyboard nav).
- Performance budget enforcement in CI (bundle size gates).

## 3. Out of Scope

- New features or model improvements.
- SOC 2 certification (post-launch).
- Live-trading enablement (v0.2+).
- External penetration-test engagement (noted in post-MVP plan).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-11-1 | All HIGH+ CVEs in dependencies resolved or documented with waiver. |
| AC-11-2 | OWASP ASVS L2 checklist items (see §6.1) show Pass / Documented Waiver for each applicable control. |
| AC-11-3 | Load test: 100 concurrent WS dashboards + 20 webhooks/sec for 10 min sustained; no 5xx; p95 order submit ≤ 1.5s. |
| AC-11-4 | 50-user simultaneous L1 flatten: all flatten orders submitted within 10s; p99 ≤ 8s. |
| AC-11-5 | Chaos drill: Redis killed mid-traffic — no data loss; Celery recovers within 60s; at-most-once semantics preserved for orders via idempotency. |
| AC-11-6 | Chaos drill: `run_broker_streams` service killed (Alpaca `trade_updates` gone) — broker status flips to DEGRADED within 30s; kill switch still works via REST path; missed fills recovered on restart (M04 AC-04-11 semantics under load). |
| AC-11-7 | Backup restore: a snapshot restored to a scratch DB reproduces last-known state; queryable via admin. |
| AC-11-8 | `/api/v1/users/me/export/` produces a ZIP with user's profile, strategies, orders, fills, audit events; delivered via signed URL expiring in 24h. |
| AC-11-9 | Account delete request marks account for 30-day soft delete then purges PII on schedule; user receives confirmation email. |
| AC-11-10 | Production Railway project stood up; custom domains `api.strattraderpro.com`, `app.strattraderpro.com` with Cloudflare WAF enforcing rate limits + basic bot protection. |
| AC-11-11 | Axe-core audit: 0 critical, 0 serious issues on auth, dashboard, strategies, backtest, risk, admin pages. |
| AC-11-12 | Bundle size budget: frontend initial bundle ≤ 400 KB gzipped (excluding lazy chunks); CI gate enforces. |
| AC-11-13 | Secret rotation rehearsal performed end-to-end on staging; runbook updated with measured times. |

## 5. Definition of Done

Baseline DoD applies, plus:

- Release candidate tag `v0.11.0-rc.1` tested on production for 24h soak.
- User-facing terms of service and privacy policy signed off by counsel (or drafted and flagged for review in §17 open items).
- Ops documentation complete: every runbook has a date-of-last-review in the frontmatter.

## 6. Implementation Tasks

### 6.1 OWASP ASVS L2 subset

Walk each applicable control, evidence by file/PR/test:

- V1 Architecture: ADRs complete (yes — committed in earlier milestones).
- V2 Authentication: Argon2, MFA, lockout, rate limits, secure reset — verify.
- V3 Session: JWT rotation, revocation, secure storage — verify.
- V4 Access Control: MFA enforcement + admin role checks — verify.
- V5 Validation: DRF serializers + jsonschema — verify; add fuzz tests.
- V7 Error / Logging: sensitive data scrubbing — verify with a grep + test.
- V8 Data Protection: at-rest encryption on creds + MFA secrets — verify.
- V9 Communications: TLS 1.3, HSTS, CSP — verify headers.
- V10 Malicious Code: dependency audit, no `eval`/`exec` on user input — verify (grep + CI).
- V11 Business Logic: kill switch test, daily loss test, sizing deterministic — verify.
- V12 Files and Resources: file upload validation (M03) — verify.
- V13 API: rate limits, CORS, webhook HMAC — verify.
- V14 Configuration: secrets in env only, debug off in prod — verify.

Output: a signed checklist committed at `/docs/security/asvs-l2-evidence.md`.

### 6.2 Dependency audit

- `pip-audit` (Python) + `pnpm audit` (Node) run in CI; M11 fails the build on HIGH+ unless waiver tag present.
- Upgrade all HIGH+ findings; document any unavoidable waivers.

### 6.3 Manual pentest-like probing

- Token rotation stress: parallel refreshes don't lose session.
- Authorization: user A tries to read user B's strategy/order/audit — 403 at every layer.
- Webhook replay attacks: tampered body with correct sig; swapped user UUID; old idempotency key.
- File-upload edge cases: polyglot PDF-as-pine file; filename traversal; zip bomb (shouldn't apply but confirm).
- SSRF via URL fields (none expected — confirm).
- Open redirect via `next` query param — verify allowlist.
- XSS in strategy description (display escaped).

### 6.4 Load test

Using Locust or k6 scripts:
- 100 WS dashboards: each subscribes, receives 5 events/min.
- 20 webhooks/sec: HMAC signed; 70% stocks, 20% ETFs, 10% options.
- 50 L1 kill-switch simultaneous triggers after a market-open simulation.

Capture:
- p50/p95/p99 latencies.
- Queue depths over time.
- DB CPU, memory, IOPS.
- Worker CPU utilization.
- WebSocket reconnect rate.

Tune based on results (worker count, pool sizes).

### 6.5 Chaos drills

Documented, scheduled, one per day:

- **Day 1:** Kill Redis for 90s; verify recovery, no orphaned orders.
- **Day 2:** Kill a worker mid-flatten; verify idempotent retry.
- **Day 3:** `run_broker_streams` crash-loops (Alpaca stream unavailable); verify kill-switch fallback via REST + fill catch-up on recovery.
- **Day 4:** Simulated TS 5xx storm; verify backoff + no duplicate orders.
- **Day 5:** DB failover (Railway + ad-hoc) — measure downtime & reconnect.

### 6.6 Backup & restore

- Automated daily backup retained 30d.
- Weekly `pg_dump` pushed to R2 retained 90d.
- Restore test: spin up scratch Postgres, restore latest dump, run verification queries; documented in runbook.

### 6.7 GDPR / CCPA

- `GET /api/v1/users/me/export/` → generates ZIP (profile, strategies, orders, fills, audit, backtests) via Celery; user receives email with signed URL (24h TTL).
- `POST /api/v1/users/me/delete/` → marks account `pending_delete_at=now+30d`; email confirmation; admin can cancel if requested within window.
- After 30 days a nightly job anonymizes/deletes per a retention policy doc (audit rows keep an anonymized user stub for integrity chain).

### 6.8 Terms & Privacy

- Draft `TermsOfService` + `PrivacyPolicy` (flag for counsel review).
- Versioned in DB as `TermsDocument(version, text, effective_from)`.
- `TermsAcceptance` model records user+version+accepted_at+ip.
- On first login post-version-update, UI modal requires re-acceptance.
- Live-trading version bump is its own document with extra disclaimers (scaffolded for v0.2).

### 6.9 Production Railway env

- Separate Railway project `strattraderpro-prod` with the same 6 services.
- Separate Postgres + Redis.
- DNS: `api.strattraderpro.com`, `app.strattraderpro.com`, `hooks.strattraderpro.com` (optional alias for webhooks).
- Cloudflare in front: TLS + WAF + rate-limit rules + bot-fight mode.
- Railway → Cloudflare orange-cloud; origin restricted to Cloudflare IPs.

### 6.10 Accessibility

- axe-core CLI run in CI over built frontend pages.
- Manual keyboard-only pass on every page.
- Focus rings visible; skip-link present.
- Color contrast: all text meets 4.5:1; interactive elements 3:1.

### 6.11 Performance budget

- Webpack-bundle-analyzer + CI gate.
- Initial bundle < 400 KB gzipped; lazy chunks ≤ 400 KB each.
- Dashboard first contentful paint ≤ 1.2s on throttled 4G (Lighthouse CI).

### 6.12 Secret rotation rehearsal

- Rotate DB password via Railway; verify zero downtime (if connection pool handles).
- Rotate Fernet KEK: envelope re-wrap all DEKs; test that broker/MFA secrets still decrypt.
- Rotate JWT HMAC secret: multi-kid support verified so active sessions survive.

## 7. Tech Stack Notes

- **Locust** chosen over k6 because Python; aligns with stack.
- **axe-core** is the de-facto a11y scanner; integrates with Playwright.
- **Cloudflare** free tier sufficient for our traffic; WAF rules + bot-fight mode enabled.
- GDPR export uses `zipfile` + `tempfile`; temporary files cleaned; R2 upload with SSE.

## 8. Data Model Changes

Migrations:
- `users.0003_delete_flow_and_terms` — `pending_delete_at`, `TermsDocument`, `TermsAcceptance`.

## 9. API Contract Changes

New:
```
GET  /api/v1/users/me/export/            → starts export job; returns job_id
GET  /api/v1/users/me/export/{job_id}/   → status; returns download URL when READY
POST /api/v1/users/me/delete/            → schedules deletion
POST /api/v1/users/me/delete/cancel/     → cancels pending deletion
GET  /api/v1/terms/current/              → current ToS + Privacy versions
POST /api/v1/terms/accept/               { tos_version, privacy_version }
```

## 10. Test Plan

### 10.1 Automated

- Dependency CI gate.
- `axe-core` CI gate.
- Bundle size CI gate.
- Load test tied to GitHub Actions weekly (not per commit).
- Chaos scenarios scripted (where feasible).

### 10.2 Manual

- OWASP ASVS L2 walkthrough with a partner (or self-review + 24h cooldown + re-check).
- Backup restore drill.
- Secret rotation drill.
- Terms acceptance UX walkthrough.

### 10.3 Regression

- Full existing Playwright suite must pass on prod-env-equivalent staging after hardening changes.

## 11. Security Considerations

- All changes in this milestone are defensive; no new attack surface.
- Terms acceptance protects us legally only if paired with clear UX and audit trail.
- Exported ZIP has no sensitive credentials (broker creds redacted; MFA secrets redacted).
- Account delete is 30d soft to allow users to reverse, and audit log retains anonymized stub only.

## 12. Observability

- All alerts verified end-to-end (fire + receive).
- SLO error budgets documented; burn alerts added for critical SLOs.
- Dashboards reviewed by operator; outdated panels retired.

## 13. Translation & Localization

- Terms of Service + Privacy Policy translated into `en` now; pot file prepared for future translations.
- Export ZIP `readme.txt` and emails translated via user's language.
- Delete-flow copy translated with careful phrasing (legal disclaimers).
- Cloudflare error pages localized (CF config) to at least English.

## 14. Documentation Deliverables

- `/docs/security/asvs-l2-evidence.md`.
- `/docs/security/pentest-report.md` — self-pentest notes.
- `/docs/ops/load-test-results.md`.
- `/docs/ops/chaos-drill-logs.md`.
- `/docs/ops/backup-restore.md`.
- `/docs/ops/secret-rotation.md`.
- `/docs/legal/terms-of-service.md` (draft; flagged for counsel).
- `/docs/legal/privacy-policy.md` (draft; flagged for counsel).
- Runbook sweep: every runbook has `Last reviewed: 2026-MM-DD` frontmatter.

## 15. Rollback Plan

- Hardening changes are largely config + CI. A problematic change can be rolled back per-PR.
- Production Railway env can be torn down and re-created if fundamentally broken — no user data yet.
- Cloudflare WAF rules can be bypassed in emergency via page rule toggles.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Load test reveals scaling bug too late to fix in week | Med | High | Run preliminary load test earlier, during M10. |
| Counsel review of ToS/Privacy delays launch | High | Med | Draft early; plan buffer in week 12; minimum viable ToS ready to use. |
| Cloudflare config change breaks prod | Low | High | Stage all rules in staging first; rollback plan documented. |
| GDPR export large ZIP exceeds memory | Low | Low | Stream to R2 directly; multipart upload. |

## 17. Exit Gate Checklist

- [ ] AC-11-1 … AC-11-13 pass.
- [ ] OWASP ASVS evidence doc complete.
- [ ] Load + chaos reports filed.
- [ ] Production env running and soaked 24h.
- [ ] Terms & Privacy drafted + acceptance flow live.
- [ ] Backup restore verified.
- [ ] Secret rotation drill logged.
- [ ] Tag `v0.11.0-rc.1`.

Proceed to **M12 Beta + Signoff**.
