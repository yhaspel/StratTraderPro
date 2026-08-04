# M11 — Execution Report (Hardening, Security, Load Test & Docs)

> Branch: `feature/m11-hardening-and-load-test` · **PR #32** (https://github.com/yhaspel/StratTraderPro/pull/32) · 2026-07-12.
> Tag `v0.11.0-rc.1` created locally on the merge commit, **not pushed** (operator convention).

## AC classification (buildable-now vs live-deferred)

| # | Tag | Criterion (short) | Status |
|---|-----|-------------------|--------|
| AC-11-1  | [CI]   | `pip-audit` + `pnpm audit` CI gates; findings resolved/waived; Dependabot triaged | ✅ **MET** (deps waivers doc) |
| AC-11-2  | [CI]   | OWASP ASVS L2 evidence doc | ✅ **MET** (asvs-l2-evidence.md + pentest tests) |
| AC-11-3  | [CI]   | Load test 100 WS + 20 rps, no 5xx, p95 ingest→submit ≤1.5s | ⚠️ **Deferred** — harness validated; full run needs a dedicated stack (Section B) |
| AC-11-4  | [CI]   | 50-user L1 flatten ≤10s, p99 ≤8s (closes deferred AC-08-11) | ⚠️ **Deferred** — `flatten_50.py` delivered; runs with AC-11-3 |
| AC-11-5  | [CI]   | Chaos: Redis kill → Celery recovers ≤60s, no dup orders | ⚠️ **Deferred** — `scripts/chaos/redis-kill.sh` (dedicated stack) |
| AC-11-6  | [CI]   | Chaos: streams kill → DEGRADED ≤60s, REST flatten, fill catch-up | ⚠️ **Deferred** — `scripts/chaos/streams-kill.sh` (dedicated stack) |
| AC-11-7  | [CI]   | Backup restore drill on scratch Postgres | ✅ **MET** — `scripts/restore-drill.sh` ran green (verify_chain ok) |
| AC-11-8  | [CI]   | GDPR export ZIP (creds/MFA redacted), 24h signed URL | ✅ **MET** (test_gdpr.py) |
| AC-11-9  | [CI]   | 30-day soft delete + cancel + nightly anonymize | ✅ **MET** (test_gdpr.py) |
| AC-11-10 | [LIVE] | Prod Railway + domains + Cloudflare WAF | 🔵 live (Section B) |
| AC-11-11 | [CI]   | axe-core a11y (0 critical/serious) on 6 page groups | ✅ **MET** (e2e/a11y/*, fixed real contrast defect) |
| AC-11-12 | [CI]   | Angular raw-initial bundle gate hard-fails | ✅ **MET** (520kB cap, proven-to-bite) |
| AC-11-13 | [CI]/[LIVE] | KEK + JWT rotation rehearsals timed; DB-pw rotation [LIVE] | ✅ **MET** ([CI] rehearsals; DB-pw [LIVE]) |
| **AC-11-14** | **[CI]** | **Service-role dispatch (§7.0)** | ✅ **MET** |
| AC-11-15 | [LIVE] | `SERVICE_ROLE` Railway cutover, delete start commands | 🔵 live (Section B; code+runbook shipped) |

Legend: ✅ met · ⏳ in progress · 🔵 live-deferred (documented, not a failure).

---

## §7.0 — Service-role dispatch (AC-11-14) — ✅ DONE & VERIFIED

**Delivered:**
- `docker/entrypoint.sh` (committed `0755`, `/usr/local/bin/`) — dispatches on required
  `SERVICE_ROLE` over seven roles (`web`, `web-dev`, `worker`, `worker-backtest`, `beat`,
  `streams`, `ws`). Unset/unrecognised → `exit 1` + loud message, **never** a `web`
  fallback. `web-dev` double-guarded (`.dev` settings **and** no `RAILWAY_ENVIRONMENT_NAME`).
  `STP_ENTRYPOINT_DRY_RUN=1` prints the un-expanded command template.
- `docker/entrypoint.expected` — 7 pinned `role|command` literals (source-attributed;
  `web` from Dockerfile CMD incl. both logfile flags, the rest from compose).
- `docker/backend.Dockerfile` — `COPY docker/entrypoint.sh` + `chmod 0755`; `CMD` → dispatcher
  (WSGI/Sentry comment block preserved).
- `docker-compose.yml` — six backend-image services converted `command:` → `SERVICE_ROLE:`;
  `ws` sets `PORT: 8788`. Exactly two `command:` keys remain (`frontend`, `ngrok`).
- `backend/config/test_entrypoint_dispatch.py` — 15 tests (string-equality per role, guards,
  mode). Runs in `backend-lint-test`.
- `scripts/verify_entrypoint_dispatch.sh` — deps-free gauntlet.
- `.github/workflows/ci.yml` — new `entrypoint-dispatch` job: shell gauntlet + build +
  `SERVICE_ROLE=web` gunicorn boot check + Day-6 unset-crashes drill.
- `docs/adr/103-service-role-dispatch.md`, `docs/ops/service-role-cutover.md`.

**Verified locally:**
- Dry-run: all 7 roles == pinned literals; unset/bogus/web-dev-misconfig exit non-zero.
- `docker run -e SERVICE_ROLE=web` → gunicorn answers `/healthz` 200; access log present.
- `docker compose up` → `backend`=runserver, `worker`/`worker-backtest`/`beat`=**celery**
  (not gunicorn), `streams`=run_broker_streams, `ws`=daphne:8788. `/healthz` + `/metrics` 200.

**[LIVE] carryover (AC-11-15):** operator sets `SERVICE_ROLE` + deletes start commands per
`docs/ops/service-role-cutover.md`.

**✅ UPDATE (2026-07-13) — cutover EXECUTED live, both environments** (`M11-COWORK-OPERATOR-REPORT.md`).
All ten backend-image services (staging + prod) now run via `SERVICE_ROLE`, verified by **process
identity in deploy logs** (backend→gunicorn, workers→celery, streams→run_broker_streams), not the
status badge. **Correction to my own claim:** I wrote "the merge does not flip the roles (a start
command overrides the CMD)" — that was **wrong for `backend`**, which never had a start command and
ran the image *default* `CMD`. §7.0 replaced that default with the dispatcher, so the merge's
Railway auto-deploy **crash-looped staging `backend` for ~2h** (`SERVICE_ROLE unset`) while Railway
showed "Online"; prod was latent. Remediated by setting `SERVICE_ROLE=web` on `backend` first; **no
prod downtime.** **Lesson: `backend` (any image-default-CMD service) must get `SERVICE_ROLE` set AT
the merge, not "later."** Still **outstanding to formally close AC-11-15:** the Grafana
`up{job=~"worker|beat|streams|worker-backtest"} == 1` + `celery_queue_depth` PromQL checks (no
Grafana session ran in the cutover).

---

## Decided autonomously
- **Dependency waivers vs upgrade** (AC-11-1): bumped DRF/simplejwt/daphne (applicable, in-series);
  waived django-allauth ×3 (N/A: Google-consumer only, fix is a 0.61→65 major jump out of scope) +
  weasyprint (trusted templates, no fix) + 20 frontend advisories (3 @angular N/A to a client-only
  SPA + patched only in v20; 17 dev/build tooling not shipped). All in `docs/security/dependency-waivers.md`.
- **GDPR endpoints are IsAuthenticated, not MFA-gated** — GDPR rights must be exercisable by any
  account; delete is a reversible 30-day soft delete with email confirmation. Impersonation tokens
  are write-blocked at the auth layer.
- **Terms flow seeded by an operator command** (`seed_terms`), not a data migration — avoids
  force-accepting a counsel-pending draft ToS on deploy. Flow proven by tests; live-able on demand.
- **Export FK fields serialized under their field name** (e.g. `"user": "<uuid>"`), redaction by
  field-name denylist (belt-and-braces with the allowlist).

## Blockers / parked
- **⚠️ Concurrent session in the working tree.** Four files carry another session's uncommitted,
  unrelated work — a transactional-email instrumentation feature: `backend/apps/users/{metrics.py,
  services.py,views.py,test_auth.py}` (adds `EMAIL_SEND_TOTAL`, `_send_templated`→bool, a
  resend-verification 503). **Deliberately excluded from every M11 commit** (guardrail: never commit
  work that isn't mine). My schema regen accidentally picked up their `views.py` change; I reverted
  that hunk so `docs/openapi/openapi.json` reflects only my 6 endpoints. My GDPR code calls
  `_send_templated` with the unchanged signature, so it is independent of their change. **The M11
  branch does not include these 4 files** — if the working tree still shows them at PR time, they
  stay unstaged.
- Local WeasyPrint PDF tests need `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` (env-only, CI installs
  the apt libs) — see the memory note.

---

# Section B — Manual user steps & follow-ups (the human to-do list)

### ✅ 1. `SERVICE_ROLE` cutover (AC-11-15) — **DONE live 2026-07-13, both envs** (`M11-COWORK-OPERATOR-REPORT.md`)
All ten backend-image services (staging + prod) set `SERVICE_ROLE` and (where present) deleted the
Custom Start Command; verified by **process identity in deploy logs**. Mapping: `backend`→**`web`**
(never `web-dev`), `celery-worker`→`worker`, `worker-backtest`→`worker-backtest`, `celery-beat`→`beat`,
`streams`→`streams`, `ws`→`ws`. **⚠️ My "inert until cutover" claim was wrong for `backend`** (it ran
the image *default* `CMD`, so the merge crash-looped staging `backend` for ~2h before remediation;
prod was latent, no downtime). **Still outstanding to formally close AC-11-15:** run the Grafana
`up{job=~"worker|beat|streams|worker-backtest"} == 1` + `celery_queue_depth` checks (no Grafana
session ran in the cutover). Procedure/correction: `docs/ops/service-role-cutover.md`.

### 2. Production bring-up (AC-11-10) — all operator
Register `strattraderpro.com`; create the `strattraderpro-prod` Railway project (12-service topology
per `docs/ops/prod-bringup.md`); Cloudflare account + DNS (`api.`/`app.`) + WAF + rate-limit +
bot-fight + origin-lock; then a 24h prod soak.

### 3. Cloudflare R2 (GDPR export + backups)
Create the R2 bucket + credentials; set `EXPORTS_BUCKET` + `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
+ `AWS_S3_ENDPOINT_URL` on backend + worker. Until set, `prod.py` keeps exports on FileSystemStorage
and marks `EXPORTS_STORAGE_READY=False`, so export jobs stay **PENDING** with an operator note (the
code path is proven against moto/FileSystemStorage). Code: `apps/users/tasks.py`, `config/settings/prod.py`.

### 4. Grafana Cloud — import the NEW burn-rate rules only
The stack is already live (M10). Import `ApiErrorBudgetFastBurn` + `ApiErrorBudgetSlowBurn` from
`infra/grafana/alerts/alert-rules.yaml`. **After import, assert every new rule has `isPaused == false`
via the Grafana API** — Grafana's converter pauses by default and a paused rule reports `health:ok`
forever (BUG-009). Then fire+receive on email + Telegram.

### 5. Load test + chaos full run (AC-11-3..6) — dedicated stack
On a throwaway compose (NOT the shared dev stack): apply migrations, enable the FakeBrokerAdapter seam
(`STP_LOADTEST_FAKE_BROKER=1` + `PYTHONPATH=/app/loadtest`, or add a `BROKER_FORCE_FAKE` env to
`build_adapter`), use a Redis cache backend (dev uses LocMemCache, which breaks cross-process
idempotency/streams-heartbeat), seed via `backend/loadtest/seed.py`, then run
`locust -f backend/loadtest/locustfile.py --headless -u 100 -r 20 --run-time 10m` and the chaos
scripts in `scripts/chaos/`. Exact commands + assertions in `docs/ops/{load-test-results,chaos-drill-logs}.md`.

### 6. Secret rotation [LIVE] part
Rotate the Railway **DB password**, measure downtime, log it in `docs/runbooks/secret-rotation.md`
(KEK + JWT rehearsals are already done + timed in the runbooks).

### 7. Lighthouse FCP-on-4G (AC-11-12 [LIVE] half)
Run against a deployed URL once prod/staging serves the SPA.

### 8. Legal
Counsel review + sign-off of `docs/legal/terms-of-service.md` + `privacy-policy.md`; then
`python manage.py seed_terms` to make the acceptance flow live. Minimum-viable ToS usable at beta meanwhile.

### 9. Restricted audit DB role (M10 carryover — `M10-cowork-followups.md` A6)
Verify actual state; provision if still open. (Not re-verified in this run — the shared dev DB uses
the app role.)

### 10. Merge + tag — ✅ done
Merged (`72ed231`), tag `v0.11.0-rc.1` created locally, **not pushed**. Railway deploys `main` on
merge — the additive `users.0005` migration ran. **Correction:** the entrypoint image was **NOT
inert for `backend`** (which runs the image default `CMD`) — the merge's auto-deploy crash-looped
staging `backend` until `SERVICE_ROLE=web` was set (step 1, now done). Command-bearing services
(worker/beat/worker-backtest/streams) *were* inert until their cutover. Set `SERVICE_ROLE=web` on
`backend` **at** the merge next time.

### 11. Sanity-check the autonomous decisions
- Bundle `maximumError` = **520kB** (over the 472.91 kB actual).
- Dependency waivers (`docs/security/dependency-waivers.md`) — django-allauth ×3 + weasyprint +
  20 frontend advisories, each with a rationale + revisit-by.
- CSP directive set (`default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`,
  report-only) — flip to enforce via `CSP_REPORT_ONLY=false` once reports are clean.
- **The 4 concurrent-session `users/` files** were excluded — reconcile with that session before merging their work.
