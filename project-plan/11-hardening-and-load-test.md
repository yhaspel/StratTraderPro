# Milestone 11 — Hardening, Security, Load Test & Docs

> **⚠️ OSS pivot note (2026-07-14):** the operator / legal / beta / hosted-prod track in this shipped spec is **VOID** — see `project-plan/PIVOT-TO-OSS.md`. Void items below are struck through, not deleted (the closed exit gate is a record, not a live plan). The **engineering track shipped** and stands.

> **Week:** 11
> **Duration:** 5 working days (planning-calendar label, not an execution constraint)
> **Depends on:** M10 (Admin Portal, Chained Audit Log & Observability) — **merged** PR #29 `d574057`, tag `v0.10.0-admin` (created, unpushed); **operator track closed & live-verified 2026-07-11** (`8ecb292`)
> **Unlocks:** M12 (Beta + Signoff)
> **Status:** `REVIEWED & FROZEN 2026-07-12` (re-verified against `main` @ `8ecb292` after the M10 live bring-up)

## 0. Ground-truth reconciliation (read first)

This plan was reviewed against the **actual codebase at `main` after M10 merged**, not the pre-Alpaca-pivot master plan. The following corrections are baked into the sections below; they exist here as an explicit ledger so the implementer does not "fix" the plan back into its wrong assumptions:

1. **M10 is done.** `apps/audit` (chained `AuditLog`, `hashing.py`, `verifier.py`, `services.emit()`), `apps/admin_portal` (`/api/v1/admin/*`, `IsAdminAndMFAEnforced`, `FeatureFlag` + `flags.is_enabled()`), the `/admin` frontend, `infra/grafana/alerts/*.yaml`, and `docs/{slo,oncall,postmortem-template}.md` all exist now. M11 **verifies and extends** these; it does not build them.
2. **Kill-switch levels are L0–L3, not "L1–L4"** (ADR-081, `apps/risk/killswitch.py`). **L0** = per-strategy; **L1** = per-user global halt **+ flatten all of that user's positions** (AC-08-8, ≤5s p99); **L2** = daily-loss auto circuit breaker (same flatten action, un-releasable until next UTC-05 rollover); **L3** = platform, **blocks intake and does NOT flatten** (`killswitch.py:136`). The 50-user simultaneous scenario is an **L1** flatten and completes the **deferred M08 AC-08-11** load item.
3. **Webhook auth is a static bearer secret, NOT an HMAC-over-payload signature** (ADR-042). The `sig` field in the body is constant-time-compared (`hmac.compare_digest`) against a per-config Fernet-encrypted secret. TradingView **cannot compute HMACs**. Every "webhook HMAC" phrase from the original draft is corrected to "static `sig` bearer secret." Do not re-introduce an HMAC-verify.
4. **Idempotency** = body field `idempotency_key` → Redis `cache.add` (SETNX) key `idem:{user}:{sha256(key)}`, TTL `WEBHOOK_IDEMPOTENCY_TTL_SECONDS` (default 86400). Not a header. Replay protection + `WEBHOOK_RATE_LIMIT_PER_MIN` fixed-window counter + optional `WEBHOOK_IP_ALLOWLIST` already exist.
5. **Options ARE supported** (M05 extended M04 across Alpaca + TradeStation); futures are TradeStation-only. The load mix (stocks/ETFs/options) is valid. Crypto is not supported.
6. **Secret encryption is a single Fernet key today** (`Fernet(settings.FERNET_KEK)` in `apps/users/mfa.py`), shared by MFA TOTP, webhook `sig`, and broker API keys — **there is no `MultiFernet` in the code and no KEK/DEK envelope.** KEK rotation *temporarily* swaps in a `MultiFernet` (old+new keys) to re-encrypt each stored secret, then reverts to single-key once the old KEK is retired — the exact steps are in `docs/runbooks/mfa-kek-rotation.md`. Do not assume `MultiFernet` is already wired into settings.
7. **JWT is single-key HS256 (SimpleJWT); there is no `kid`/multi-key rotation today.** Signing-key rotation therefore invalidates in-flight access tokens (≤15 min TTL) — the rehearsal documents the drain, it does **not** "verify multi-kid," which does not exist. Building multi-kid is a feature and is **out of scope**.
8. **`users` migration is `0005_delete_flow_and_terms`** (0003 = oauth, 0004 = M10's `drop_auth_event`). Follow M10's convention: let `makemigrations` assign the number; do not hard-code if the tree has advanced.
9. **No object storage exists** (no R2/S3/`django-storages`/`boto3`). GDPR export + weekly `pg_dump` offload require an S3-compatible backend. Build against a storage abstraction testable locally (filesystem/MinIO/moto); the **real R2 bucket + credentials are an operator step**.
10. **No CSP, no `pip-audit`/`pnpm audit` in CI, no `axe-core`, no load-test tooling.** These are net-new (buildable). Trivy image-scan + weekly Dependabot already exist; there are ~5 open Dependabot PRs to resolve under §7.2.
11. **Frontend uses `pnpm` + Angular 19 + Karma + Playwright** (Playwright e2e is auth-only and **not in CI** today — only a `/healthz` docker-compose smoke). i18n is `ngx-translate` with a single `en.json`; there is **no `.pot`/second locale and no backend `locale/`**. Do not claim a pot file is "prepared."
12. **Bundle budget:** Angular's `initial` budget is **raw**, currently `warning 500kB / error 1MB`; M10 shipped **449.56 kB raw initial**. The original "≤400 KB gzipped" gate is ambiguous and (as raw) already breached — see §7.11 for the concrete, enforceable replacement.
13. **Prod web tier is gunicorn WSGI** (`config.wsgi`, gthread); `/ws/dashboard/` is served by a **separate daphne ASGI service**. `/metrics` is now wired into both `wsgi.py` and `asgi.py` with basic auth (`METRICS_BASIC_AUTH_*`, M10). Any cross-cutting hook must live in both entrypoints + worker init or it ships prod-dark.
14. **Railway topology is NOT "6 services."** Documented staging = 4 (backend, frontend, Postgres, grafana-agent). The real target set (derived from the docker-compose service set + `infra/grafana-agent/` + M10's exporters) is larger: backend, frontend, Postgres, Redis, worker, worker-backtest, beat, streams, ws (daphne), grafana-agent, postgres-exporter, redis-exporter. (`grafana-agent` is not a compose service — it deploys from `infra/grafana-agent/`.) §7.9 re-derives this; standing up prod is operator-heavy.
15. **`strattraderpro.com` is not registered/verified** and no Cloudflare account is wired — AC-11-10 is almost entirely operator/[LIVE].
16. **M10's operator track is CLOSED, not open** (verified live 2026-07-11, `PROGRESS.md` + `8ecb292`). Grafana Cloud has the 6 dashboards and **21 alert rules imported and unpaused**, email + Telegram contact points and the notification policy are live, Tempo/OTel and the Sentry↔Tempo join work, the postgres/redis exporters and every long-lived service are deployed, `METRICS_BASIC_AUTH_*` and `TASK_METRICS_PORT` are set in both envs, and **all 14 scrape targets are `up == 1`**. Earlier drafts of this plan (and the M10 execution report's Section B, written at merge time) treat these as pending — **they are not.** The only known M10 operator carryover is the **restricted audit DB role** (`M10-cowork-followups.md` A6 — verify at run time) and the unpushed tags. Consequence for M11: burn-rate alerts can actually be imported and fire-tested, and infra metrics are capturable.
17. **The M10 live bring-up found 11 defects that CI could not see** (`bugs/BUG-001`…`011`, 3 of them S1); all are FIXED except as noted. Two bear directly on M11: **BUG-011** (blank Railway start command → a Celery service silently ran gunicorn for two months) is the reason for **§7.0**, which is M11's first task; and **BUG-009** (every imported Grafana rule arrived `isPaused: true`, so the alerting stack could never fire) means **any alert rule M11 adds must be verified `isPaused == false` after import** — importing is not enabling. The governing lesson, from `bugs/README.md`: *a clean bill of health can be produced by the defect itself* — prefer end-to-end assertions over any component's self-report. Apply that to every AC below.
18. **CI is stronger than earlier drafts assumed.** `.github/workflows/ci.yml` has **six** jobs: `backend-lint-test` (ruff, bandit, SQLite lane, `-m pg` lane), `frontend-lint-test` (which now runs **Karma — `pnpm test:ci`, 67 specs — BUG-007**), `e2e-smoke`, `block-legacy-ibkr-creds` (the TWS grep gate), `block-unsubstituted-runtime-config` (`scripts/check_envsubst_filter.py`, BUG-004), and `image-scan` (Trivy). M11 **adds** gates; it weakens none of these six. Still absent (net-new for M11): `pip-audit`, `pnpm audit`, any Playwright/axe job, and any enforcing bundle gate.

## 1. Purpose

Prepare the platform for external users with a deliberate hardening pass: a security review against an OWASP ASVS L2 subset, load testing at ~100-user scale, chaos drills, complete user- and ops-facing documentation, and compliance-adjacent housekeeping (terms, privacy, GDPR export/delete). **No new product features** — this week makes what we already have durable. Net-new *code* here (CSP headers, GDPR export/delete, terms models, dependency/a11y/bundle CI gates, load-test harness) is defensive hardening and compliance plumbing, not feature work.

## 2. In Scope

- OWASP ASVS L2 subset walkthrough with per-control evidence (file / PR / test), committed as a signed checklist.
- Dependency audit + upgrade: add `pip-audit` (Python — **no severity threshold**; it fails on any advisory, suppressed only per-ID) and `pnpm audit --audit-level=high` (Node) CI gates; resolve findings or record an explicit waiver; clear the open Dependabot PRs.
- Manual pentest-like probing (auth, authz, injection, SSRF, file upload, webhook replay/spoof of the static `sig`, open-redirect).
- Add Content-Security-Policy + verify the rest of the security-header set (HSTS/Referrer-Policy/X-Content-Type-Options/Permissions-Policy).
- Load test against **local docker-compose with `FakeBrokerAdapter`** (deterministic; real Alpaca paper caps at ~200 req/min and cannot absorb 20 orders/sec): 100 concurrent WS dashboards + 20 webhooks/sec, plus the 50-user simultaneous **L1** flatten. A scaled-down canary runs weekly in CI.
- Chaos drills: Redis kill, worker kill mid-flatten, `run_broker_streams` kill (Alpaca `trade_updates` gone), Alpaca REST 5xx storm, DB failover.
- DB backup verification with a scripted test-restore to a scratch Postgres instance.
- GDPR / CCPA: personal-data export endpoint + async job, and a 30-day soft account-delete request flow.
- Versioned Terms of Service + Privacy Policy ~~(drafted, flagged for counsel)~~ **[VOID — OSS pivot; legal-doc drafting/counsel]**; acceptance flow on first login after a version bump.
- Final runbook sweep: every runbook gets a `Last reviewed:` frontmatter line; on-call escalation confirmed (extends M10's `docs/oncall.md`).
- Secret-rotation rehearsal on staging/local: DB password, Fernet KEK (via a temporary `MultiFernet` swap), JWT signing key.
- Accessibility audit: add `@axe-core/playwright` gate + manual keyboard pass over auth, dashboard, strategies, backtest, risk, and the M10 admin pages.
- Performance budget enforcement in CI (Angular raw-initial budget hard-fail; optional gzipped tracking).
- **Service-role dispatch in the image entrypoint (§7.0) — carried from M10, do first.** A blank Railway start command makes a service *silently become a web server* (BUG-011: `celery-worker`/`celery-beat` ran gunicorn for two months). Make `SERVICE_ROLE` required and fail loudly when it is unset, removing the dangerous default rather than merely version-controlling the value. (BUG-011 was fixed *live* by typing start commands into Railway; those text boxes are exactly what §7.0 replaces.)
- ~~**Operator-track (documented, not executed by the autonomous run):** the **`SERVICE_ROLE` cutover** (set the env on every Railway service, delete every Custom Start Command — AC-11-15), production Railway project, custom domains, Cloudflare + WAF, R2 bucket, Grafana Cloud import of the **new burn-rate rules** + unpause + fire/receive. (The exporters, contact points, and the 21 existing rules are **already live** — §0.16 — so this list is shorter than earlier drafts assumed.)~~ **[VOID — OSS pivot; hosted-prod / Cloudflare / R2 operator track. Note: the `SERVICE_ROLE` dispatch *code* (§7.0 / AC-11-14) still ships; only the Railway cutover is void.]**

## 3. Out of Scope

- New product features or model improvements.
- JWT multi-`kid` signing (a feature; would change the token contract).
- SOC 2 certification (post-launch).
- Live-trading enablement (v0.2+; `ENABLE_LIVE_TRADING=false` stays).
- External (third-party) penetration-test engagement — noted in the post-MVP plan.
- A real second-language locale / `.pot` catalog (only `en.json` keys are added this week).

## 4. Frozen decisions (do not revisit autonomously)

1. **Load test target = local docker-compose + `FakeBrokerAdapter`.** Full-scale (100 WS / 20 rps / 50-user L1) runs there; a reduced canary runs weekly in CI. A staging spot-check is a documented operator follow-up (staging lacks the ws/streams services today).
2. **GDPR export storage uses an S3-compatible abstraction** (`django-storages`[s3] / boto3). Tests run against MinIO or `moto`; **real Cloudflare R2 bucket + credentials are a Section-B operator step**. Signed-URL TTL = 24h.
3. **Account delete = 30-day soft delete.** `pending_delete_at = now + 30d`; a nightly job anonymizes on expiry. M10 shipped plain `SET_NULL` FKs on `AuditLog.user`/`actor` with **no** anonymization mechanism — **M11 designs anonymize-in-place itself:** keep the `User` row alive under its PK and scrub its PII fields in place so audit FKs keep resolving; never hard-`delete()` the `User` and never delete audit rows (the append-only trigger forbids it anyway).
4. **JWT signing-key rotation is documented as a drain, not multi-kid.** Rehearsal proves access tokens re-mint cleanly after `JWT_SIGNING_KEY` change within one 15-min TTL window; refresh handled by the existing `RefreshTokenFamily` re-issue path.
5. **KEK rotation temporarily introduces `MultiFernet`** (add new key, re-encrypt each secret, then revert to single-key once the old KEK retires), per `docs/runbooks/mfa-kek-rotation.md`. No `MultiFernet` is committed to `settings` and no DEK layer is introduced — the swap is a rotation-time-only edit.
6. **CSP ships report-only first, then enforce.** Add `django-csp` (or a static header via `SecurityMiddleware`); start `Content-Security-Policy-Report-Only`, capture violations, then flip to enforcing in the same PR only if the app pages are clean; otherwise leave report-only and document the flip as follow-up.
7. **Chaos "broker 5xx storm" targets Alpaca's REST path** (the only broker in the production hot path), injected via `FakeBrokerAdapter`/mock — **not** TradeStation (flag OFF, zero live traffic). The TradeStation retry/backoff code is covered by an adapter-level unit test instead.
8. ~~**Terms/Privacy are drafted in-repo and flagged for counsel.** A minimum-viable ToS is usable at beta; counsel sign-off is tracked as an open item, not a merge blocker.~~ **[VOID — OSS pivot; legal-doc drafting / counsel / beta. The terms-acceptance code (D4) still ships.]**
9. **`SERVICE_ROLE` dispatch removes the default; it does not merely version-control it** (§7.0, rejected alternative: `railway.json` config-as-code). Unset or unrecognised → `exit 1`, never a `web` fallback. The dispatcher is a committed `docker/entrypoint.sh` with a dry-run mode so it is testable in CI without docker-in-docker, and `docker-compose.yml` drives every service through it (no `command:` overrides) so the path that ships is the path that is tested. Do not "simplify" any part of this.

## 5. Acceptance Criteria

Each AC is tagged **[CI]** (provable by the autonomous run: unit/integration/local-compose/scripted) or **[LIVE]** (requires a deployed env, external credential, or human — becomes a documented Section-B step, not a failure).

| # | Tag | Criterion |
|---|-----|-----------|
| AC-11-1 | [CI] | `pip-audit` + `pnpm audit` run in CI and fail the job on findings; all current findings resolved or covered by a recorded waiver; open Dependabot PRs triaged (merged or documented). **Note the two tools gate differently and the spec must not pretend otherwise: `pnpm audit --audit-level=high` filters by severity; `pip-audit` has *no* severity threshold** — it fails on any known advisory, and its only suppression is `--ignore-vuln <ID>`. So the Python gate is "zero un-waived advisories", the Node gate is "zero un-waived HIGH+", and every waiver on either side is an entry in `docs/security/dependency-waivers.md` (ID, why, revisit-by date). |
| AC-11-2 | [CI] | OWASP ASVS L2 subset checklist (§7.1) shows Pass / Documented-Waiver for each applicable control, each with file/PR/test evidence, committed at `docs/security/asvs-l2-evidence.md`. |
| AC-11-3 | [CI] | Load test (local compose, `FakeBrokerAdapter`): 100 concurrent WS dashboards + 20 webhooks/sec sustained 10 min; **no 5xx**; p95 alert-ingest→order-submit ≤ 1.5s (measures the platform path, excludes real-broker latency by design). Results in `docs/ops/load-test-results.md`. |
| AC-11-4 | [CI] | 50-user simultaneous **L1** halt+flatten: all flatten orders submitted within 10s; **p99 ≤ 5s** (completes deferred M08 AC-08-11). **[RECONCILED 2026-07-14]** — was ≤8s here, which conflicted with `docs/slo.md`, M13 AC-13-10 and this doc's own line 14 (all ≤5s). Measured p99 = **0.20s** (paper) / **0.17s** (LIVE) clears the tighter 5s with ~25× margin, so the SLO number is adopted. Evidence: `docs/ops/load-test-results.md`. |
| AC-11-5 | [CI] | Chaos: Redis killed mid-traffic — Celery recovers within 60s; no orphaned/duplicate orders; at-most-once order semantics preserved via the `idempotency_key` SETNX guard + Alpaca `client_order_id`. |
| AC-11-6 | [CI] | Chaos: `run_broker_streams` killed (Alpaca `trade_updates` gone) — `GET /api/v1/brokers/{id}/status/` flips to DEGRADED within `BROKER_STREAM_HEARTBEAT_TTL` (default 45s) + margin (assert ≤ 60s); L1 flatten still works via the REST path (independent of the stream); missed fills recovered on restart via REST cursor, deduped on `broker_exec_id` (AC-04-11 semantics under load). |
| AC-11-7 | [CI] | Backup restore drill: a `pg_dump` restored into a scratch Postgres reproduces last-known state; scripted verification queries pass; procedure in `docs/ops/backup-restore.md`. (Railway PITR config + R2 retention are [LIVE].) |
| AC-11-8 | [CI] | `GET /api/v1/users/me/export/` starts a Celery job producing a ZIP (profile, strategies, orders, fills, **audit events for that user from `audit_log`**, backtests); broker creds + MFA secrets redacted; delivered via a signed URL expiring in 24h. Provable against MinIO/moto in tests; real R2 is [LIVE]. |
| AC-11-9 | [CI] | `POST /api/v1/users/me/delete/` sets `pending_delete_at = now + 30d`, sends a confirmation email, and is cancellable via `POST /api/v1/users/me/delete/cancel/` within the window; a nightly job anonymizes on expiry leaving an anonymized audit stub. |
| ~~AC-11-10~~ | ~~[LIVE]~~ | **[VOID — OSS pivot]** ~~Production Railway project stood up; custom domains `api.strattraderpro.com` / `app.strattraderpro.com` behind Cloudflare WAF (rate limits + bot-fight). **Entirely operator** (domain purchase, DNS, Cloudflare, prod infra). The run delivers the config/runbook, not the live env.~~ |
| AC-11-11 | [CI] | `@axe-core/playwright` audit: 0 critical, 0 serious on auth, dashboard, strategies, backtest, risk, and admin pages; runs as a CI job (new). Manual keyboard-nav pass documented. |
| AC-11-12 | [CI] | Angular initial **raw** budget enforced (CI `pnpm build` hard-fails on breach; confirm the `maximumError` actually fails the job). Threshold set to prevent regression from the current 449.56 kB (see §7.11). Lighthouse FCP ≤1.2s on throttled 4G is **[LIVE]** (needs a deployed URL). |
| AC-11-13 | [CI]/[LIVE] | Secret-rotation rehearsal performed end-to-end for KEK (temporary `MultiFernet` swap → revert, local/staging-shaped) and JWT signing key (drain); runbooks updated with measured times. DB-password rotation on Railway is [LIVE]. |
| AC-11-14 | [CI] | **Service-role dispatch (§7.0).** The backend image dispatches on `SERVICE_ROLE`; an **unset or unrecognised** value **exits non-zero with a loud message and never falls back to `web`** — proven by a dry-run test asserting exit≠0 + the message. All seven roles (`web`, `web-dev`, `worker`, `worker-backtest`, `beat`, `streams`, `ws`) resolve to their **pinned expected command literal** (string equality — an exit-0 check alone proves nothing). The six backend-image compose services drive through the dispatcher (no `command:` override), so the E2E smoke exercises the real entrypoint; a `docker run -e SERVICE_ROLE=web` boot check covers the production role. |
| AC-11-15 | [LIVE] | `SERVICE_ROLE` set on **every** Railway service in **both** environments, all **Custom Start Commands deleted** (the image becomes the single source of truth), staging first then production; post-cutover `up{job=~"worker\|beat\|streams\|worker-backtest"} == 1` and `celery_queue_depth` still fresh in both envs. Operator step — the run delivers the image, the compose parity, and `docs/ops/service-role-cutover.md`. |

## 6. Definition of Done

Baseline DoD (`project-plan/README.md` §"Definition of Done") applies — note it already lists `axe-core` a11y, dependency-scan-clean, and translation-keys-extracted, several of which M11 turns from nominal into enforced. Plus:

- All **[CI]** acceptance criteria green in the merged PR; every **[LIVE]** item documented in the execution report's Section B with the exact operator command/procedure.
- Release-candidate tag `v0.11.0-rc.1` **created locally, not pushed** (operator convention~~; a 24h prod soak is a Section-B [LIVE] step~~ **[VOID — OSS pivot; no hosted prod soak]**).
- ~~Terms of Service + Privacy Policy drafted and flagged for counsel (tracked as a risk row in §17),~~ **[VOID — OSS pivot; legal-doc drafting / counsel]** acceptance flow live and tested.
- Ops documentation complete: every runbook in `docs/runbooks/` (27 files at freeze — derive the live count, do not trust that number) carries a `Last reviewed:` frontmatter line dated **the run date or later**, on a normalized header template.

## 7. Implementation Tasks

> Ordering: **§7.0 first** (it is the structural fix for the worst defect M10 surfaced, and it touches the image every other task's compose/CI run depends on). The rest may proceed in parallel.

### 7.0 Service-role dispatch in the image entrypoint — **remove the silent-substitution default** (carried from M10 / BUG-011) → AC-11-14, AC-11-15

**Priority: do this first.**

#### What happened

The `celery-worker` and `celery-beat` Railway services had an **empty Custom Start
Command**, so they ran the image's default `CMD` — `migrate && gunicorn`. Both
services reported **Online** and had been running a *second copy of the Django web
server* since deploy. The default `celery` queue had no consumer and beat had never
fired a single scheduled task, in **both** environments, including
`apps.risk.tasks.daily_loss_watcher` (a risk control). Found 2026-07-11; see
`bugs/BUG-011-celery-worker-and-beat-are-not-running-celery.md`.

The root property is what matters: **a blank field silently substitutes a web
server.** The service does not fail — it succeeds at being the wrong thing.

**BUG-011 is already FIXED live** — by typing the correct start commands into the
Railway UI on both envs (all 14 scrape targets now `up == 1`). **Those text boxes are
precisely what §7.0 exists to delete.** The incident is closed; the *bug class* is not.

#### The fix (frozen design — do not "simplify" this)

Extract the dispatch into a committed **`docker/entrypoint.sh`** (mode `0755` — commit the
executable bit) and make it the image's **`CMD`** — `CMD ["/usr/local/bin/entrypoint.sh"]`,
**not `ENTRYPOINT`**, so `docker run <image> <cmd>` still overrides it for debugging.

**Where the script lives matters.** Every backend-image compose service bind-mounts
`./backend:/app`, so anything at `/app/entrypoint.sh` is **masked at runtime** and each
service dies with "no such file". And the Dockerfile's `COPY backend/ .` does not include
the repo's `docker/` directory. So: add an explicit
`COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh` and keep the script **outside
`/app`**.

**Each command has a specific source. There is no single file to "copy verbatim" from —
that is a trap:** `docker-compose.yml`'s `backend` service runs **`runserver`** (it is the
*dev* server, on `config.settings.dev`, paired with the `./backend:/app` bind mount), so
compose is **not** the source for the production `web` role. Take `web` from the
Dockerfile's current `CMD`; take the other six from compose:

| `SERVICE_ROLE` | Command | Source (copy exactly) |
|---|---|---|
| `web` | `python manage.py migrate --noinput && exec gunicorn config.wsgi:application --config /app/gunicorn.conf.py --bind 0.0.0.0:${PORT} --workers 3 --worker-class gthread --threads 4 --timeout 120 --access-logfile - --error-logfile -` | `docker/backend.Dockerfile` `CMD` — **including the two logfile flags; dropping them silences the web tier's access + error logs in every environment** |
| `web-dev` | `python manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8777` | `docker-compose.yml` `backend` — **dev only**. It must `exit 1` if `DJANGO_SETTINGS_MODULE` does not end in `.dev` **or if `RAILWAY_ENVIRONMENT_NAME` is set** (a deployed env, whatever the settings say). Two independent guards, because BUG-011 was an operator-config error and one env var is one text box away from being wrong. |
| `worker` | `exec celery -A config.celery worker -l info --concurrency=1` | compose `worker` |
| `worker-backtest` | `exec celery -A config.celery worker -Q backtest -l info --concurrency=1 --max-memory-per-child=2000000` | compose `worker-backtest` |
| `beat` | `exec celery -A config.celery beat -l info -S redbeat.RedBeatScheduler` | compose `beat` |
| `streams` | `exec python manage.py run_broker_streams` | compose `streams` |
| `ws` | `exec daphne -b 0.0.0.0 -p ${PORT:-8788} config.asgi:application` | compose `ws` (which hard-codes `8788`) |

**Port note (a live trap):** the image sets `ENV PORT=8777`, so `${PORT:-8788}` **never**
falls back — the `ws` service would bind 8777 while compose publishes `8788:8788`, and
`/ws/dashboard/` would be dead locally, silently breaking the 100-WS load test. Therefore
compose's `ws` service **must** set `PORT: 8788` in its `environment:`. On Railway, `ws`
inherits the injected `$PORT` and needs nothing. One variable, correct in both.

**Unset or unrecognised `SERVICE_ROLE` must `exit 1` with a loud message naming the
valid roles. It must NOT default to `web` (or to anything).** That single line is the
entire point: it converts a silent wrong-process into a crash. A crashed deploy is
visible in thirty seconds; a worker that is secretly gunicorn went unnoticed for two
months.

**Make it testable without a container:** honour `STP_ENTRYPOINT_DRY_RUN=1` by printing the
resolved command and exiting 0 instead of `exec`-ing it. That turns AC-11-14 into an
ordinary [CI] subprocess test with **no docker-in-docker**. Three details decide whether
that test is worth anything:

1. **It compares strings, not exit codes.** Asserting only "exit 0" passes for any
   dispatcher that prints anything at all — the worthless self-report BUG-009 is made of.
2. **Dry-run prints the command template *un-expanded*** (literal `${PORT}`, not the host's
   value). The script runs on a developer host where `PORT` is unset and inside a container
   where it is `8777` — an expanding dry-run would produce different output in the two
   places and the test would fail against a *correct* implementation, whereupon someone
   would "fix" it by weakening the assertion.
3. **The expected literals live in exactly one file**, `docker/entrypoint.expected` — seven
   `role|command` rows, **trailing newline required** (a `while read` loop silently drops a
   final unterminated line, which would skip `ws`). The pytest test and any shell gauntlet
   both read *that* file. Head it with a comment naming the source of each literal
   (`docker/backend.Dockerfile` `CMD` @ `8ecb292` for `web`; `docker-compose.yml` @ `8ecb292`
   for the rest). **Do not** assert against `docker-compose.yml` at test time — this very
   task removes those `command:` lines from it.

**Compose must go through the dispatcher too.** Replace the `command:` of the **six
backend-image services** (`backend` → `SERVICE_ROLE: web-dev`, `worker`, `worker-backtest`,
`beat`, `streams`, `ws`) with `SERVICE_ROLE: <role>` in `environment:`. If compose keeps
overriding `command:`, the dispatcher ships **untested** and the E2E smoke job proves
nothing about it — the same "guarding an artifact nobody runs" trap as the
`NGINX_ENVSUBST_FILTER` override in BUG-004. **Leave `frontend` (`ng serve`) and `ngrok`
alone** — different images, not roles; deleting `frontend`'s command breaks the E2E smoke.
(The exporters and `ib-gateway` have no `command:` at all.) So the correct end state is
"exactly two `command:` keys remain in `docker-compose.yml`" — assert *that*, not "zero".

`web-dev` exists so this conversion does **not** silently swap the developer's hot-reload
`runserver` for gunicorn (bind-mount edits would stop taking effect and Django-admin
statics would 404 locally). Because the E2E smoke therefore boots `web-dev` rather than
`web`, add a **direct boot check for the production role**: `docker run -e SERVICE_ROLE=web`
against the built image and assert gunicorn answers `/healthz`. Without it, the one role
that matters in production is proven only by a dry-run string comparison.

#### Why `railway.json` config-as-code is NOT sufficient (rejected 2026-07-11)

It is the tempting middle option and it does not fix the bug class. `railway.json`
version-controls the *value*, but the dangerous **default survives**: the image `CMD`
is still gunicorn. If the config isn't applied, is overridden in the UI, or a new
service is added and forgotten, the container silently becomes a web server again —
the identical failure, now with a config file that makes you *believe* it's covered.
It buys reviewability and no safety. Only removing the default removes the failure.

#### Acceptance

**[CI] (AC-11-14) — provable in the run:**

- Entrypoint dry-run test: all **seven** roles → the seven **pinned expected command
  literals** (string equality, not just exit 0); unset → exit≠0 + loud message; bogus role
  → exit≠0 + loud message; **never** resolves to `web` or any other role by default;
  `web-dev` → exit≠0 when `DJANGO_SETTINGS_MODULE` is not a `.dev` module.
- `docker/entrypoint.sh` is committed executable (`git ls-files -s` shows mode `100755`).
- `docker-compose.yml` carries `SERVICE_ROLE` per service and **no `command:` override** on
  the six backend-image services (only `frontend` and `ngrok` keep a `command:`); compose's
  `ws` sets `PORT: 8788`. The existing E2E smoke job (`docker compose up` → `/healthz`)
  therefore boots `web-dev`, `worker`, `beat`, `streams` and `ws` *through the dispatcher*
  and stays green.
- **Production-role boot check:** `docker run -e SERVICE_ROLE=web` on the built image →
  gunicorn starts and `/healthz` answers 200 (the E2E smoke only exercises `web-dev`).
- **These last two checks belong in CI, not only in the local gauntlet** — fold the
  dry-run/fixture test, the `100755` mode check and the `SERVICE_ROLE=web` boot check into a
  job (extend `image-scan`, which already builds the image, or add `entrypoint-dispatch`).
  A one-shot local proof that no future PR re-runs is not a gate.
- A drill in §7.5 (Day 6): clear `SERVICE_ROLE` on a compose service and confirm the
  container **crashes** rather than quietly serving HTTP. Note `worker`/`worker-backtest`/
  `beat`/`streams` carry `restart: on-failure`, so they will **crash-loop** rather than sit
  in `exited` — assert on `docker inspect -f '{{.State.ExitCode}}'` + the loud log line, not
  on `docker compose ps` status text.

**[LIVE] (AC-11-15) — operator cutover, `docs/ops/service-role-cutover.md`:**

- The runbook **must carry an explicit Railway-service → `SERVICE_ROLE` mapping table** for
  both environments (`backend` → **`web`**, never `web-dev`; `celery-worker` → `worker`;
  `celery-beat` → `beat`; `worker-backtest` → `worker-backtest`; `streams` → `streams`;
  `ws` → `ws`). The whole task is about making a name→process mapping unambiguous; do not
  leave the last mile to inference.
- Set `SERVICE_ROLE` on **every** Railway service in **both** environments.
- **Delete** every Custom Start Command (image = single source of truth).
- Staging first: confirm `up{job=~"worker|beat|streams|worker-backtest"} == 1` and
  `celery_queue_depth` stays fresh (proves beat → default queue → worker → metric,
  end-to-end). Then production. Roll back by re-typing the start command.

#### Interim mitigation already in place (why this can wait for M11, but not past it)

The exposure has already collapsed from *"silently broken forever"* to *"loudly broken
in five minutes"*: M10's dead-man's switch (`TargetDown`, `MetricsPipelineDown` —
BUG-008) fires within 5 minutes if worker/beat stop scraping, and a daily scheduled
audit re-asserts the whole beat→queue→worker loop. **That detection is a backstop, not
a fix.** The default is still wrong.

### 7.1 OWASP ASVS L2 subset

Walk each applicable control; evidence by file/PR/test. Output: `docs/security/asvs-l2-evidence.md` (signed checklist).

- **V1 Architecture** — ADRs 000–102 committed; confirm coverage.
- **V2 Authentication** — Argon2id hasher (`PASSWORD_HASHERS`), TOTP MFA (`pyotp`), custom lockout (`FailedLoginAttempt`, 10/15min per-email), `django-ratelimit` on login/register/reset — verify + add auth fuzz tests.
- **V3 Session** — SimpleJWT HS256 + custom `RefreshTokenFamily` rotation & reuse-detection; token blacklist app installed; access 15m / refresh 30d — verify revocation paths.
- **V4 Access Control** — `IsAuthenticatedAndMFAEnforced`, admin `IsAdminAndMFAEnforced` + `is_staff`, impersonation write-block at the authentication layer (M10) — verify the matrix.
- **V5 Validation** — DRF serializers + `jsonschema` on the webhook body + upload validators — verify; add fuzz/property tests on the webhook schema.
- **V7 Error / Logging** — audit `scrub.py` + the `SENSITIVE_KEYS` set; confirm no secrets in logs. **Known follow-up:** M10 flagged that `_scrub_sensitive` is not wired into the stdlib `python-json-logger` LOGGING config (the audit-row scrub *is* active) — wire the stdlib filter or correct the docstring here and grep-test it.
- **V8 Data Protection** — at-rest Fernet on MFA secrets, webhook `sig`, broker API keys — verify; confirm export redaction.
- **V9 Communications** — TLS/HSTS/`SECURE_*` in `prod.py`; **add CSP** (§4, decision 6); verify HSTS preload, Referrer-Policy, X-Content-Type-Options, Permissions-Policy.
- **V10 Malicious Code** — dependency audit gate (§7.2); grep-gate that no `eval`/`exec` runs on user input; keep the existing `TWS_*` legacy-cred grep gate untouched.
- **V11 Business Logic** — kill-switch L0–L3 tests, daily-loss (L2) two-poll confirm + auto-release, deterministic sizing — verify. Address the dead `RiskProfile.max_concurrent`/`leverage_cap`/`permitted_asset_classes` fields (remove or wire) flagged in the M04–M08 report.
- **V12 Files & Resources** — M03 upload validators (size caps, path-traversal, filename regex, Pine `//@version=` check, stored-XSS scan) — verify; add a polyglot/zip-bomb probe.
- **V13 API** — per-view `django-ratelimit` + the webhook fixed-window counter (there is **no** global DRF throttle — decide whether to add `DEFAULT_THROTTLE_*` or document the per-endpoint approach as the control), CORS allowlist, and the **static `sig` bearer secret** (ADR-042, **not** HMAC) — verify constant-time compare + replay guard.
- **V14 Configuration** — secrets in env only, `DEBUG=False` in prod, `METRICS_BASIC_AUTH_*` set (M10), no committed secrets — verify.

### 7.2 Dependency audit

- Add `pip-audit` (backend) and `pnpm audit --audit-level=high` (frontend) as CI steps in `.github/workflows/ci.yml`. **`pip-audit` has no severity gate** — it fails on any advisory; suppress only via explicit `--ignore-vuln <ID>` (each one a waiver entry). Do not invent a `--severity` flag, and do not "fix" a noisy Python gate by deleting it.
- Resolve all current findings; upgrade pins; document unavoidable waivers in `docs/security/dependency-waivers.md` (ID, why unavoidable, revisit-by date).
- Triage the ~5 open Dependabot PRs (node/nginx base images + GitHub Actions bumps, opened 2026-04-18): merge the safe ones or document why deferred. Keep `pnpm-lock.yaml` frozen-lockfile-clean.

### 7.3 Manual pentest-like probing

- Token-rotation stress: parallel refreshes don't lose the session or trip false reuse-detection.
- Authorization: user A reads user B's strategy/order/fill/audit → 403 at every layer (incl. the export endpoint and admin routes).
- Webhook replay/spoof of the **static `sig`**: tampered body with a valid old `sig`; swapped user/strategy UUID in the path; replayed `idempotency_key` (must dedupe, not double-order); wrong-secret → generic 401 (no existence oracle).
- File-upload edge cases: polyglot PDF-as-Pine; filename traversal; oversize; zip-bomb (confirm N/A).
- SSRF via any URL field (none expected — confirm; there is no server-side fetch of user URLs today).
- Open-redirect via a `next`-style param — **none exists today** (OAuth/email redirects are built from `FRONTEND_BASE_URL`, not client input); confirm and add a regression test asserting no user-controlled redirect target is introduced.
- Stored-XSS in strategy description (`description_short` is API-only/escaped; confirm no server-rendered sink).

### 7.4 Load test

Locust (Python, aligns with stack) scripts under `backend/loadtest/` (or `infra/loadtest/`), run against **local docker-compose with `FakeBrokerAdapter`**:

- 100 WS dashboards: each authenticates (JWT-in-querystring + MFA gate), subscribes to `/ws/dashboard/`, receives ~5 events/min.
- 20 webhooks/sec to `POST /hooks/v1/{user}/{strategy}/` with a valid static `sig` + unique `idempotency_key`; mix 70% stocks, 20% ETFs, 10% options.
- 50 simultaneous **L1** halt+flatten triggers after a market-open simulation.

Capture: p50/p95/p99 for ingest→submit and for flatten; Celery queue depths over time (reuse M10's `celery_queue_depth{queue}` gauge); WebSocket reconnect rate. **Infra metrics** (DB/Redis throughput, connections, memory) come from the `postgres-exporter` + `redis-exporter` services, which **exist in `docker-compose.yml` and are deployed on Railway** (§0.16) — scrape them locally during the run rather than deferring; only host-level CPU/IOPS on the Railway side remains [LIVE]. Under multiproc gunicorn do **not** assert on `process_*`/`django_db_*` (they are disabled) — read the app gauges. Tune worker count / pool sizes from results; record in `docs/ops/load-test-results.md`. Add a **scaled-down canary** (e.g. 10 WS / 2 rps / 60s) as a `workflow_dispatch` + weekly-cron GitHub Actions job (Playwright/Locust headless), gated to not run per-commit.

### 7.5 Chaos drills

Documented in `docs/ops/chaos-drill-logs.md`, scripted where feasible (compose `kill`/`pause`):

- **Day 1 (→AC-11-5):** Kill Redis ~90s; verify Celery recovery, idempotency guard holds, no orphaned orders.
- **Day 2:** Kill a worker mid-flatten; verify idempotent retry (no duplicate flatten orders).
- **Day 3 (→AC-11-6):** `run_broker_streams` crash-loop; verify DEGRADED within TTL+margin, L1 flatten via REST still works, fill catch-up on reconnect (dedupe on `broker_exec_id`).
- **Day 4:** **Alpaca REST 5xx storm** (injected via `FakeBrokerAdapter`/mock, since Alpaca is the only live-path broker); verify bounded retry/backoff and no duplicate orders. (TradeStation retry code covered by a separate adapter unit test — it carries no live traffic, flag OFF.)
- **Day 5:** DB failover (local: restart Postgres; staging: Railway) — measure reconnect/downtime; note the Railway-side measurement as [LIVE].
- **Day 6 (→AC-11-14):** **Role-removal drill.** Clear `SERVICE_ROLE` on a compose service (and set a bogus value on another); confirm each container **exits non-zero with the loud message** and does **not** quietly start serving HTTP. This is the drill that would have caught BUG-011 on day one.

### 7.6 Backup & restore

- Document the daily automated backup (Railway, 30d) and a weekly `pg_dump` → R2 (90d) — both **operator/[LIVE]** for the real buckets.
- **Buildable drill (AC-11-7):** a script (`scripts/restore-drill.sh` + a management command or SQL) that spins up a scratch Postgres, restores a `pg_dump`, and runs verification queries (row counts on key tables, audit-chain head re-verify). Runbook: `docs/ops/backup-restore.md`.

### 7.7 GDPR / CCPA

- `GET /api/v1/users/me/export/` → enqueues a Celery job (default `celery` queue) building a ZIP (profile, strategies, orders, fills, **per-user rows from `audit_log`**, backtests) via `zipfile`+`tempfile`, streamed to S3-compatible storage; returns `{job_id}`. **Redact** broker API keys + MFA secrets. `GET /api/v1/users/me/export/{job_id}/` → status + signed download URL (24h) when READY. Email the user the link (reuse `_send_templated`).
- `POST /api/v1/users/me/delete/` → `pending_delete_at = now+30d`, confirmation email; `POST /api/v1/users/me/delete/cancel/` within the window; admin can also cancel.
- Nightly beat job anonymizes/deletes expired accounts per a retention doc; audit rows keep an **anonymized actor stub** (chain integrity). Emit audit events for export-requested / delete-requested / delete-cancelled / anonymized.

### 7.8 Terms & Privacy

- ~~Draft `docs/legal/terms-of-service.md` + `docs/legal/privacy-policy.md` (flag for counsel).~~ **[VOID — OSS pivot; legal docs deleted, the acceptance code below stays (D4)]**
- `TermsDocument(kind, version, text, effective_from)` + `TermsAcceptance(user, tos_version, privacy_version, accepted_at, ip)` models (migration `users.0005_delete_flow_and_terms` — or the next free number via `makemigrations`).
- `GET /api/v1/terms/current/` → current ToS + Privacy versions; `POST /api/v1/terms/accept/ { tos_version, privacy_version }` records acceptance + IP + audit event.
- On first login after a version bump, the SPA shows a blocking modal requiring re-acceptance.
- All strings via `ngx-translate` keys in `en.json` (DoD: no hard-coded strings). ~~A live-trading ToS variant is scaffolded for v0.2, not built.~~ **[VOID — OSS pivot; beta/v0.2 legal scaffold]**

### 7.9 ~~Production Railway env — **[LIVE]/operator**~~ **[VOID — OSS pivot; hosted-prod bring-up is not an OSS deliverable, self-hosters run their own box]**

~~The autonomous run produces the **config + runbook**, not the live environment. Re-derive the real service set (not the stale "6"): `backend`, `frontend`, `postgres`, `redis`, `worker`, `worker-backtest`, `beat`, `streams`, `ws` (daphne), `grafana-agent`, `postgres-exporter`, `redis-exporter`. Runbook `docs/ops/prod-bringup.md` covers: separate `strattraderpro-prod` project, separate Postgres + Redis, DNS (`api.` / `app.` / optional `hooks.` `strattraderpro.com`), Cloudflare (TLS + WAF + rate-limit + bot-fight, orange-cloud, origin restricted to Cloudflare IPs), and env-var matrix (incl. M10's `METRICS_BASIC_AUTH_*`, `TASK_METRICS_PORT`, exporter targets, `SENTRY_*`). Domain purchase, Cloudflare account, and prod bring-up are operator steps.~~

### 7.10 Accessibility

- Add `@axe-core/playwright`; extend the (currently auth-only) Playwright suite with specs for dashboard, strategies, backtest, risk, and the M10 admin pages; add a CI job (Playwright is not in CI today).
- **The a11y specs must prove they reached the page.** Every target route is behind `IsAuthenticatedAndMFAEnforced`, so an unauthenticated spec silently redirects to `/login` — axe then scans the login page five times, reports 0 violations, and AC-11-11 goes green having tested nothing. Seed auth via the existing `frontend/e2e/helpers/mock-api.ts` (or a storage-state fixture) and **assert a page-identifying locator is visible *before* calling `AxeBuilder.analyze()`**. Same question as always: what would this evidence look like if the thing were broken?
- Manual keyboard-only pass on every page; document results.
- Focus rings visible; skip-link present; color contrast text ≥ 4.5:1, interactive ≥ 3:1.

### 7.11 Performance budget

- Enforce the Angular **raw initial** budget in CI: confirm `pnpm build` actually **fails** on `maximumError` (it currently only warns at 500kB / errors at 1MB). **Prove the gate bites** — temporarily set `maximumError` below the current 449.56 kB, observe a red build, then restore the real threshold and record both outcomes. An unproven gate is indistinguishable from no gate. Set `maximumError` to a regression-guard threshold above the current **449.56 kB** actual (e.g. `500kB`) so any real growth fails the build; keep lazy `admin`/`backtest` chunks out of the initial budget.
- Optionally add a small script to report **gzipped** initial size for tracking (informational, not a gate) to avoid the raw-vs-gzipped ambiguity of the original draft.
- Lighthouse-CI FCP ≤1.2s on throttled 4G is **[LIVE]** (needs a deployed URL) — document as a Section-B step.

### 7.12 Secret-rotation rehearsal

- **DB password** (Railway) — **[LIVE]**: rotate via Railway, verify pool re-connect, measure downtime; document.
- **Fernet KEK** — [CI-shaped]: rehearse the runbook's rotation — temporarily introduce `MultiFernet` (old+new keys), re-encrypt MFA/webhook/broker secrets, confirm all still decrypt, time it, then revert to single-key per the runbook's final step. **The M11 PR leaves the code at single-key `Fernet`** (the `MultiFernet` swap is a rotation-time-only edit, not a committed change). Record measured times in `docs/runbooks/mfa-kek-rotation.md`.
- **JWT signing key** — [CI-shaped]: rotate `JWT_SIGNING_KEY`; because signing is single-key HS256, in-flight access tokens (≤15m) are invalidated — prove clean re-mint within one TTL window and refresh-family re-issue; document the drain. **Multi-`kid` is explicitly out of scope.**

## 8. Tech Stack Notes

- **Locust** over k6 (Python, aligns with stack) for load; headless canary in CI.
- **`@axe-core/playwright`** integrates with the existing Playwright runner.
- **Cloudflare** free/Pro tier sufficient; WAF + bot-fight (operator).
- GDPR export: `zipfile`+`tempfile`, streamed to S3-compatible storage (MinIO/moto in tests, R2 in prod) with SSE; signed URL 24h.
- CSP via `django-csp` (report-only → enforce) or a static header on `SecurityMiddleware`.

## 9. Data Model Changes

Migrations:
- `users.0005_delete_flow_and_terms` (or next free number) — `User.pending_delete_at`, `TermsDocument`, `TermsAcceptance`.
- Possibly an `export_jobs` table (or reuse a generic async-job pattern) for export status — implementer's discretion; keep it minimal.

## 10. API Contract Changes

New (all under `/api/v1/`):
```
GET  /api/v1/users/me/export/            → starts export job; returns { job_id }
GET  /api/v1/users/me/export/{job_id}/   → status; signed download URL when READY (24h TTL)
POST /api/v1/users/me/delete/            → schedules 30-day soft delete
POST /api/v1/users/me/delete/cancel/     → cancels pending deletion (within window)
GET  /api/v1/terms/current/              → current ToS + Privacy versions
POST /api/v1/terms/accept/               { tos_version, privacy_version }
```
Regenerate OpenAPI (`make schema`) + frontend types (`pnpm run schema:types`); no drift. Note: an unrelated `GET /api/v1/orders/export.csv` already exists (trade CSV) — do not conflate with the GDPR export.

## 11. Test Plan

### 11.1 Automated (CI)
- **Entrypoint dispatch test (§7.0 / AC-11-14):** `docker/entrypoint.sh` under `STP_ENTRYPOINT_DRY_RUN=1` — **all seven** roles resolve to their pinned literal in `docker/entrypoint.expected` (string equality); unset and bogus roles exit non-zero with the loud message and never resolve to any role; `web-dev` exits non-zero on non-`.dev` settings or when `RAILWAY_ENVIRONMENT_NAME` is set. Pure subprocess test, no docker-in-docker. Plus the `100755` mode check and the `SERVICE_ROLE=web` container boot check (both in CI).
- `pip-audit` + `pnpm audit` gates.
- `@axe-core/playwright` a11y gate (new Playwright CI job).
- Angular raw-initial bundle gate (build hard-fail).
- Load-test canary (weekly cron + `workflow_dispatch`; not per-commit).
- Chaos scenarios scripted where feasible (compose kill/pause) with assertions.
- Backend unit/integration for export/delete/terms (SQLite lane + `-m pg` where triggers/indexes matter), storage against MinIO/`moto`, email via locmem backend.

### 11.2 Manual / drills
- OWASP ASVS L2 walkthrough (self-review + 24h cooldown + re-check, per solo-dev DoD).
- Backup-restore drill; secret-rotation drills (KEK, JWT).
- Terms-acceptance UX walkthrough; keyboard-nav pass.

### 11.3 Regression
- Full existing backend gauntlet (ruff, bandit, SQLite + pg lanes) + `ngc` + `pnpm build` + Karma + the auth Playwright suite must stay green after hardening changes.

## 12. Security Considerations

- All changes are defensive; adding CSP/GDPR/terms introduces no new *attack* surface, but the export endpoint is a new data-egress path — hence redaction + per-user authz tests are mandatory.
- Terms acceptance protects legally only with clear UX + an audit trail (both required here).
- Exported ZIP must contain **no** broker creds or MFA secrets (redaction test is an AC-gating test).
- Account delete is 30-day soft to allow reversal; audit log retains only an anonymized stub.

## 13. Observability

- **Verify/extend M10, don't rebuild.** M10 authored `docs/slo.md`, the six dashboards' SLO panels, and `infra/grafana/alerts/*.yaml`; **the Grafana Cloud stack is live** — 6 dashboards, 21 rules imported and **unpaused**, email + Telegram contact points, notification policy, all 14 targets `up` (§0.16). M11 adds **burn-rate alerts** on top.
- **Importing a rule does not enable it (BUG-009).** Grafana's Prometheus-rule converter imports `isPaused: true` by default, and a paused rule reports `health: ok` forever. Every rule M11 adds must be asserted **`isPaused == false` via the Grafana API after import** — and the burn-rate rules, being `> 0`-style self-filtering expressions, are also covered by the `MetricsPipelineDown`/`TargetDown` dead-man's switch M10 added. Do not accept a rule's own health field as evidence.
- Fire+receive (email + Telegram) is **[LIVE]** only in the sense that it runs against Grafana Cloud, which the operator drives — the contact points already exist, so this is a *do it*, not a *build it*: the run authors the rules + the verification procedure; the operator imports, unpauses, and fires.
- Add metrics for the new paths: export job count/duration, delete-request count, terms-acceptance count. Register them in a per-app `metrics.py` at module level (multiproc-safe).

## 14. Translation & Localization

- Terms/Privacy, export `readme.txt`, delete-flow copy, and all new UI strings added as **`en.json` keys** (no hard-coded strings). Backend user-facing labels via the existing i18n LABELS pattern.
- **No `.pot`/second locale is produced** (the app uses `ngx-translate` with a single `en.json`; there is no gettext extraction pipeline). A real second language is future work — do not claim a pot file is prepared.
- Cloudflare error-page localization is an operator/[LIVE] note.

## 15. Documentation Deliverables

- `docs/security/asvs-l2-evidence.md`, `docs/security/pentest-report.md`, `docs/security/dependency-waivers.md`.
- `docs/ops/load-test-results.md`, `docs/ops/chaos-drill-logs.md`, `docs/ops/backup-restore.md`, ~~`docs/ops/prod-bringup.md`~~ **[VOID — OSS pivot; hosted-prod bring-up doc]**, `docs/ops/service-role-cutover.md` (§7.0 / AC-11-15).
- `docs/runbooks/secret-rotation.md` (JWT + DB) and extend `docs/runbooks/mfa-kek-rotation.md`.
- ~~`docs/legal/terms-of-service.md`, `docs/legal/privacy-policy.md` (drafts; flagged for counsel).~~ **[VOID — OSS pivot; legal documents deleted (D7). The terms-acceptance code stays (D4).]**
- Runbook sweep: every `docs/runbooks/*.md` gets a `Last reviewed:` frontmatter line (most lack it today — derive the live count with `ls docs/runbooks/*.md | wc -l` rather than trusting a hard-coded number, and normalize the header template).
- ADR(s), next free number is **103** (102 = observability topology): CSP, GDPR export/delete design, the load-test target choice, and **service-role dispatch** (record the rejected `railway.json` alternative — §7.0).

## 16. Rollback Plan

- Hardening changes are largely config + CI + additive endpoints; a problematic change rolls back per-PR.
- The new `users.0005` migration is additive (nullable `pending_delete_at` + two new tables) — reversible; no destructive column drops.
- **§7.0 role cutover rolls back per-service in seconds:** re-type the Custom Start Command in Railway (that *is* today's state). The image change is inert for any service whose start command still overrides it, so the code can land ahead of the cutover with zero risk.
- Cloudflare/prod infra is not created by the run, so there is nothing to tear down there.

## 17. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Load test reveals a scaling bug late | Med | High | Run the local-compose load test early in the week; canary in CI thereafter. |
| ~~Counsel review of ToS/Privacy delays launch~~ **[VOID — OSS pivot; no counsel, no hosted launch]** | ~~High~~ | ~~Med~~ | ~~Draft early; minimum-viable ToS usable at beta; buffer in M12.~~ |
| GDPR export large ZIP exceeds memory | Low | Low | Stream to storage; chunked/multipart upload; temp-file cleanup. |
| Real R2 not provisioned in time | Med | Med | Build against MinIO/moto; R2 is a Section-B operator step; export degrades gracefully (job stays PENDING with a clear operator note). |
| JWT rotation invalidates active sessions (no multi-kid) | Med | Med | Document the 15-min drain; schedule rotation in a low-traffic window; multi-kid noted as future work. |
| CSP breaks app pages when enforced | Med | Med | Ship report-only first; flip to enforce only if violation reports are clean. |
| New Grafana burn-rate rules land **paused** and silently never fire (BUG-009 repeat) | High | High | Assert `isPaused == false` via the Grafana API after import; never trust a rule's `health` field. Covered by the §13 note + the operator cutover checklist. |
| Restricted audit DB role (M10 `M10-cowork-followups.md` A6) may still be unprovisioned | Med | Med | Verify at run time; it is the one known M10 operator carryover. ASVS V4/V8 evidence records actual state, not assumed state. |
| §7.0 cutover deletes a Railway start command and the `SERVICE_ROLE` env is missing on that service | Low | High | The whole point: the service **crashes visibly** instead of becoming a web server. Staging first; roll back by re-typing the start command. |

## 18. Exit Gate Checklist

- [ ] **§7.0 done first:** `SERVICE_ROLE` dispatcher shipped; unset/bogus role exits non-zero and never defaults to `web`; all **seven** roles match their pinned literal; the six backend-image compose services drive through it (no `command:` override); `SERVICE_ROLE=web` boots gunicorn; the checks live in CI (**AC-11-14**).
- [ ] All **[CI]** AC (AC-11-1…9, 11, 12, 13-partial, 14) green in the merged PR.
- [ ] All **[LIVE]** items (~~AC-11-10,~~ AC-11-15 role cutover, Lighthouse, DB-password rotation, burn-rate rule import + **unpause** + fire/receive~~, R2, prod bring-up~~ **[VOID refs struck — OSS pivot]**) documented in Section B with exact procedures.
- [ ] OWASP ASVS evidence doc complete; dependency gates live; every finding resolved or waived (`pip-audit`: zero un-waived advisories; `pnpm audit`: zero un-waived HIGH+).
- [ ] Load + chaos + backup-restore reports filed (chaos incl. the Day-6 role-removal drill).
- [ ] GDPR export/delete + Terms acceptance flow live and tested.
- [ ] a11y + bundle CI gates enforcing; the **six** existing CI jobs (Backend, Frontend incl. Karma, E2E smoke, both Guards, Trivy) still green and unweakened; runbook sweep done (frontmatter normalized).
- [ ] Secret-rotation rehearsals (KEK, JWT) logged with measured times.
- [ ] Tag `v0.11.0-rc.1` created locally (not pushed).

Proceed to **M12 Beta + Signoff**.
