> **⚙️ SPENT ONE-SHOT — milestone shipped; not a work item.**
> This is the agent prompt that built a now-merged milestone. Moved out of the active plan on
> 2026-07-14 (OSS pivot) and kept for historical record only — **do not re-run.** The durable record
> of what shipped lives in `project-plan/PROGRESS.md` and the matching `M*-EXECUTION-REPORT.md`.

---

# ONE-SHOT PROMPT — Implement StratTraderPro Milestone M10 (Admin Portal, Audit Log & Observability, autonomous)

> Paste everything below the line into Claude CLI (UltraCode, Xhigh effort), running from the repo root
> `/Users/yuval3000/Documents/Claude/Projects/StratTraderPro`. It is self-contained and designed to run end-to-end
> **without human input**. Operator decisions already made: **admin-merge the PR autonomously**; on a hard blocker,
> **park it, document it, and finish everything else best-effort** (do not halt the run).

---

## MISSION

Implement **Milestone M10 — Admin Portal, Audit Log & Observability Polish** of StratTraderPro (Django + Angular trading-bot monorepo), end to end, on its own branch, through PR → review → merge → local main sync.

**The authoritative spec is `project-plan/10-admin-audit-observability.md`** (header marker: `REVIEWED & FROZEN 2026-07-09`). It defines scope, acceptance criteria AC-10-1…AC-10-12 (each tagged **[CI]** or **[LIVE]**), definition of done, implementation tasks §6.0–§6.6, data model, API contract, test plan §10, security, observability, i18n, documentation deliverables, rollback, risks, and the Exit Gate Checklist. Implement to that spec. Do **not** trust this prompt's summaries over the plan file or the code — read them yourself. Where this prompt and the plan disagree, **the plan wins**.

**Eight engineering decisions are frozen in the plan's header note — do NOT revisit them autonomously:** (1) `AuthEvent` migrate + drop with the EventType enum relocated; (2) high-volume events (webhook-received, sizing decisions) stay OUT of the hash chain; (3) hash chain computed in application code, Postgres triggers enforce append-only + linkage, no pgcrypto; (4) admin identity = existing `User.is_staff`; (5) per-action MFA codes, no 15-min step-up window; (6) feature flags = DB-backed model in `apps/admin_portal` + Redis + 30 s local cache, no new `apps/core`; (7) OTel wired code-side in full, live Tempo verification deferred; (8) `/admin/health` = native KPI cards + external Grafana links, no iframes.

The plan's "Duration: 5 working days" is a planning-calendar label, not a constraint on you. This is a large milestone — use maximum effort. Use subagents freely to parallelize (audit-backend / admin-backend / frontend / observability / docs implementers + a dedicated reviewer), but land everything in the **one** milestone PR.

## WHAT "AUTONOMOUS" MEANS HERE (non-negotiable)

- **Never stop to ask the user anything.** If a decision isn't covered by the plan or this prompt, choose the safest reversible option, proceed, and log it in the final report (Section B, "decided autonomously").
- **Anything that genuinely requires a human, an external credential, or a deployed environment → skip it, keep going, document it.** Expected **[LIVE]-deferred** set for M10 (the plan tags these): Grafana Cloud imports (6 updated dashboards + alert rules + contact points incl. creating the Telegram bot), sample-alert firing/receipt, Sentry→Tempo click-through + `SENTRY_AUTH_TOKEN` GitHub secret, `OTEL_EXPORTER_OTLP_ENDPOINT` + `METRICS_BASIC_AUTH_*` + `TASK_METRICS_PORT` env on Railway services, Railway postgres/redis exporter services, the restricted Railway DB role, staging perf SLAs (audit search @10M rows, verifier 24 h window), a pre-deploy Railway DB backup, and pushing the release tag.
- **Build everything that CAN be built without those externals.** M10 was specced for exactly this: every AC's [CI] portion is provable locally — SQLite lane + the new Postgres lane (`-m pg`) against the compose/CI Postgres, eager-Celery integration tests, WSGI-callable-level metrics tests, in-memory OTel span exporter, alert-rule files with a metric-name cross-check test.
- **Merge-deploys-migrations warning (top Section B item):** Railway auto-deploys `main` on merge, and this PR's `migrate` **drops `users_auth_event` after migrating it into the chained `audit_log`**. You cannot take the Railway backup (operator credential). Proceed — the data migration self-verifies (row-count parity + head-hash re-verification) and the pg-lane test proves it on fixtures — but the report must lead with: what was dropped, what proves the migration, and that no pre-deploy backup was taken.
- **Hard blocker policy = park and continue.** If a component cannot reach green, park it behind its flag/seam (`ADMIN_PORTAL_ENABLED`, OTLP-endpoint gating, etc.), record blocker + impact in the report, and complete the rest. If the OTel instrumentation pins will not resolve against `opentelemetry-distro[otlp]>=0.43b0` on Python 3.12, do **not** swap tracing stacks autonomously — park OTel behind `config/otel.py` no-op init with failing-marked tests, flag it as the top Section-A item, and keep the request-id correlation work (independent of OTel).
- **Keep a running report file** `project-plan/M10-EXECUTION-REPORT.md` updated as you go, so a partial report survives an interrupted run.

## GROUND TRUTH — read these first, in this order, before writing any code

1. `project-plan/PROGRESS.md` — canonical verified-against-code status (M00–M09 implemented + merged; M10 not started). Note the "M10 §6.5 observability carryover" PROGRESS.md line, plus the FIX-C1 worker/beat-scrape follow-up (recorded in `ONE-SHOT-M04-M08-FIXES.prompt.md` / the M04–M08 execution report) and the M09 CHANGELOG "live wiring is M10" note — M10 closes all three. Merge/PR/tag facts: `git log`/`git tag` + the two execution reports.
2. `project-plan/10-admin-audit-observability.md` — **the spec.** Read every section. The header records the eight frozen decisions.
3. `project-plan/README.md` — cross-cutting conventions: Definition of Done, i18n rules, branching, tags.
4. `CONTRIBUTING.md` — branch naming, PR process, squash-merge, conventional commits, ruff/bandit/pytest, Angular 19 rules (standalone components, `@if/@for`, `inject()`, facades-not-core-services, all strings via `ngx-translate`).
5. `.github/workflows/ci.yml` — the exact CI gates (see CI PARITY below). Note the `postgres:16-alpine` service + `DATABASE_URL` env already exist in `backend-lint-test` but are unused by SQLite tests — §6.0 wires the new pg lane to them.
6. `.github/pull_request_template.md` — the DoD checklist the PR must fill in.
7. `project-plan/M04-M08-EXECUTION-REPORT.md` + `project-plan/M09-EXECUTION-REPORT.md` — format precedent for your Section A/B report + the outstanding observability deferrals M10 absorbs.
8. Reuse targets you must read before implementing against them: `backend/apps/users/{models,services,mfa,permissions,serializers,views,views_m02,views_oauth,admin}.py` (AuthEvent + `record_event` + `serialize_user` + `_MFAToken` + `verify_mfa_code` + `IsAuthenticatedAndMFAEnforced`), `backend/apps/risk/{killswitch,views,models}.py` (L3 semantics — `trigger_halt`/`release_halt`/`is_blocked`; L3 never flattens, `killswitch.py:117`), `backend/apps/brokers/{views,models,services}.py`, `backend/apps/webhooks/tasks.py` + `backend/apps/orders/{services,views}.py` (`_csv_safe` CSV precedent), `backend/apps/dashboard/{consumers,events}.py`, `backend/config/{settings/base.py,settings/prod.py,settings/test.py,urls.py,wsgi.py,asgi.py,celery.py,task_metrics.py}` + `backend/gunicorn.conf.py` + `docker/backend.Dockerfile` (**prod is gunicorn WSGI, `config.wsgi`, gthread — Dockerfile:68**), `infra/grafana-agent/agent.yaml` + `infra/grafana/*.json` (six dashboards), `docker/nginx.conf.template` (`window.STP_CONFIG` envsubst), `frontend/src/app/core/{guards/auth.guard.ts,models/auth.models.ts,interceptors/*,services/ws.service.ts}`, `frontend/src/app/abstraction/{stores,facades}` (backtest + orders as the layer precedent, `orders.facade.ts` blob download), `frontend/src/app/features/auth/totp-input/totp-input.component.ts`, `frontend/src/app/features/strategies/webhook-config/webhook-config-modal.component.ts` (modal shell), `frontend/src/assets/i18n/en.json` (incl. the orphaned `nav.admin` key), `backend/apps/backtest/{i18n,metrics}.py` (backend i18n LABELS + Prometheus-only metrics-module conventions).

## PROJECT-SPECIFIC GUARDRAILS (hard-won; violating these wastes hours)

Carried over from M04–M09 (all still true):

- **Local CI-parity gauntlet is the merge bar.** `pytest` + `tsc` is NOT enough — CI also runs `ruff`, `bandit`, and a real Angular build. Green gauntlet before every push.
- **Angular template errors need `ngc`, not `tsc`:** `npx ngc --noEmit -p tsconfig.app.json` from `frontend/` before claiming the frontend compiles.
- **Frontend gate is `pnpm`** (`pnpm install --frozen-lockfile`, `pnpm build`); keep `pnpm-lock.yaml` in sync (M10 adds no frontend packages — keep it that way).
- **Settings star-import drops `_`-prefixed names:** name-import any private helper into `prod.py`/`dev.py` or prod crashes at boot; the prod-import smoke below catches this.
- **Prometheus:** module-level metrics in a per-app `metrics.py`; under multiproc gunicorn don't assert on `process_*`/`django_db_*`.
- **Match CI runtimes: Python 3.12, Node 20**; fresh 3.12 venv for the Day-1 spike regardless of the gitignored `.venv`.
- **Finder duplicates:** the working tree contains untracked junk files whose names contain `" 2"` (e.g. `backend/apps/backtest/* 2.py`, `project-plan/* 2.md`). **NEVER `git add -A` / `git add .`** — stage explicit paths only, and never commit any `" 2"` file.

New, M10-specific (from the reviewed plan — these encode its trickiest failure modes):

- **`AuditLog.occurred_at` must be `default=timezone.now`, NOT `auto_now_add`** — `emit()` assigns the timestamp once, hashes that exact value, inserts it. `auto_now_add` silently overwrites in `pre_save` → every row fails verification, and historical backfill becomes impossible.
- **Prod web tier is WSGI.** Both the `/metrics` exposition (§6.5a) and OTel init (§6.6) must be wired into `config/wsgi.py` (and mirrored in `config/asgi.py` for dev/daphne) — asgi-only wiring ships CI-green and prod-dark.
- **Impersonation write-block lives at the AUTHENTICATION layer** (`ImpersonationAwareJWTAuthentication` in `DEFAULT_AUTHENTICATION_CLASSES`) — a global permission class is silently dropped by every view that overrides `permission_classes`, which is all mutating views.
- **`is_staff` goes into `apps/users/services.serialize_user` + `CurrentUserSerializer.Meta.fields`** — `AuthTokenObtainSerializer.get_token` only adds JWT claims and does NOT feed the login response `user` object the frontend guard reads.
- **AuthEvent decommission is surgical** — relocate `EventType` to `apps/audit/events.py`; repoint 5 module imports + ~38 usages; replace the `strategies/views.py:213` `record_event("register", …)` shim with `emit("strategy.created", …)` and the `users/admin.py` `force_disable_mfa` raw create with `emit()`; update every test asserting `AuthEvent` rows. Skipping any item = app won't import.
- **`emit()` exception ordering:** `try:` OUTSIDE `with transaction.atomic():` — catching a trigger `RAISE` inside the block throws `TransactionManagementError`. Audit emission must never break the business action (`audit_events_dropped_total` on failure).
- **Migrations:** triggers via vendor-guarded `RunSQL` (no-op on SQLite); the data migration inlines a **frozen copy** of the hashing functions (never import app code) and declares `dependencies` on BOTH `audit.0002` and the latest `users` migration; `users` drops `AuthEvent` only after `audit.0003`.
- **Celery crontabs are UTC values** (`CELERY_TIMEZONE="UTC"`) with ET only in comments; verifier = `crontab(hour=8, minute=0)`. Explicit per-task route entries only — **no glob routes** (M09 rule); verifier + queue-depth beat tasks ride the default `celery` queue.
- **Register the `pg` pytest marker in `pytest.ini`**; pg-lane tests use `@skipUnless(connection.vendor == "postgresql")` + `config/settings/test_pg.py`; the new CI step runs them against the existing (currently unused) Postgres service container. **Do not weaken any existing CI gate** and keep the `TWS_*` grep-gate allowlist untouched.
- **Immutable flags stay as direct `settings.X` reads** (`MFA_ENABLED`, `KILL_SWITCHES_ENABLED`, `FILLS_INLINE`, `ADMIN_PORTAL_ENABLED`); only the mutable call sites listed in §6.4 move to `flags.is_enabled()`. Flag helper fails OPEN to the env default and must be safe before its table exists.
- **`HALT PLATFORM` confirm phrase is validated server-side** (400 `CONFIRM_PHRASE_MISMATCH`), and admin UI copy + runbook must state L3 blocks intake and does NOT flatten.
- **Secrets scrubbing:** audit scrubber key set = existing `SENSITIVE_KEYS` ∪ `{key, code, mfa_code}`; relocating `_scrub_sensitive` out of `base.py` requires updating `apps/users/tests.py:40-51` which imports it (it is not dead code).
- **Alert rules must reference real series** — the §6.5 reconciliation table names them; the cross-check test is the guard. Two gauges are NEW (`celery_queue_depth{queue}`, `sentiment_queue_oldest_age_minutes`) — build them, don't assume them.

## WORKFLOW — execute in this exact order

### 1. Branch (state-aware — the repo may have in-flight work)
- **Never absorb, commit, stash-drop, or discard work that isn't yours.** If the current branch has uncommitted changes beyond the two files named below, leave them exactly where they are; only switch branches if `git checkout main` succeeds without `-f`; if checkout is blocked, park-and-report per the blocker policy.
- `git checkout main && git pull origin main`. If the pull aborts because the working tree is dirty with the freeze edits to the two files named below, that is expected — those edits are yours; proceed to create the branch and commit them there (never stash-drop them).
- `git checkout -b feature/m10-admin-audit-observability`.
- **Freeze the spec as the first commit:** the reviewed plan exists in the working tree (uncommitted). Verify `project-plan/10-admin-audit-observability.md` contains the header marker `REVIEWED & FROZEN 2026-07-09`, then commit **exactly** `project-plan/10-admin-audit-observability.md` and `project-plan/ONE-SHOT-M10.prompt.md` (this file) as `docs(m10): freeze reviewed M10 plan + one-shot prompt` (precedent: M04–M09 prompts are committed). Explicit paths only — no `-A`, no `.`.

### 2. Plan
- Re-read the plan file in full. Extract every AC, §6 task, migration, endpoint, test, and Exit-Gate item into a work breakdown.
- Classify each AC/exit-gate item **[BUILDABLE NOW]** vs **[LIVE-DEFERRED]** (the plan's [CI]/[LIVE] tags do this for you — carry them into `project-plan/M10-EXECUTION-REPORT.md` immediately). You are accountable for every BUILDABLE item; LIVE-DEFERRED items become documented manual steps, not failures.
- Run the **Day-1 spike (§6.0)** and record outcomes before feature code: pg test lane wired (settings + marker + CI step), trigger prototype on compose Postgres (owner-role UPDATE/DELETE raise verified), OTel pins resolve + import, `python-ulid` pinned, metrics-dispatcher smoke behind gunicorn WSGI locally.

### 3. Implement (to the plan's §6.0–§6.6, §8, §9, §11–§15)
- Backend audit: `apps/audit` — models (`AuditLog` with `default=timezone.now`, `AuditVerifierState`), `events.py` taxonomy (relocated EventType + new namespaces), `hashing.py` (+ golden vectors), `scrub.py`, `services.emit()`, enforcement-trigger migration (vendor-guarded), data migration + `users` AuthEvent drop, `verifier.py` + beat task, `metrics.py`, `i18n.py` (CSV labels).
- Backend admin portal: `apps/admin_portal` — `IsAdminAndMFAEnforced` (unconditional), `ImpersonationAwareJWTAuthentication` (users app) swapped into `DEFAULT_AUTHENTICATION_CLASSES`, `ImpersonationSession` + `FeatureFlag` models, endpoints per §6.2 (users/audit-search+CSV/platform-killswitch delegating to `killswitch.trigger_halt`/`release_halt`/impersonation/flags/health), `flags.py` helper + `FEATURE_FLAGS_REGISTRY` + call-site refactor (§6.4's exact list), `health.py` aggregation, `metrics.py` (queue-depth gauge task), mounted under `/api/v1/admin/` gated by env-only `ADMIN_PORTAL_ENABLED`.
- Observability: §6.5a–g exactly — `config/metrics_endpoint.py` wired into `config/wsgi.py` + `config/asgi.py`, delete `_sentry_before_send`, FIX-C1 worker/beat scrape hooks in `config/celery.py`, sentiment age gauge, compose exporters + agent.yaml basic_auth + scrape jobs, Sentry `release=GIT_SHA` + frontend Sentry via extended `config.js`, six dashboard JSONs updated (SLO + last-incident panels), `infra/grafana/alerts/*.yaml` + cross-check test, conditional sourcemap-upload CI step (skips without secret).
- Correlation: `RequestIdMiddleware` (ULID), logging filter into the python-json-logger config, Celery header propagation, Sentry tags, `config/otel.py` init from wsgi+asgi+worker with the §6.6 span attributes.
- Frontend: `is_staff` plumbing (backend serializers → `AuthUser` → contract spec), `adminGuard`, lazy `ADMIN_ROUTES` (`/admin`, `/admin/users`, `/admin/users/:id`, `/admin/audit`, `/admin/flags`, `/admin/health`), `admin.api.ts` → `admin.store.ts` → `admin.facade.ts` → standalone components, HALT-PLATFORM typed-confirm modal (+ `app-totp-input`), impersonation banner, CSV blob download, `admin.*` + `audit.event.*` keys in `en.json`, `nav.admin` link on the dashboard header for staff, karma specs (store/facade/guard).
- Tests: the plan's §10 in full for BUILDABLE items — SQLite lane, pg lane (`-m pg`), eager integration, security matrix (§10.6 parametrized across every admin route), WSGI-callable metrics tests, OTel in-memory span exporter, alert-rule cross-check. Target ≥ 90% on new code.
- Docs: ADR-100/101/102, runbooks + oncall/postmortem/slo docs per §5/§14, `CHANGELOG.md` under `[Unreleased]`.
- Regenerate OpenAPI schema + frontend types (`make schema`, or `cd backend && python manage.py spectacular --file ../docs/openapi/openapi.json` then `cd frontend && pnpm run schema:types` — the repo-root `docs/openapi/openapi.json` is canonical).

### 4. Verify locally — CI-parity gauntlet (GREEN before pushing)

```bash
# ---- CI-MIRRORED gates (.github/workflows/ci.yml) ----
cd backend
export DJANGO_SETTINGS_MODULE=config.settings.test
ruff check .
bandit -r apps/ config/ -x tests -q --severity-level medium
python -m pytest --tb=short -q                     # SQLite lane
# NEW pg lane — CI runs it against the service container; locally use compose postgres:
docker compose up -d postgres
DJANGO_SETTINGS_MODULE=config.settings.test_pg \
  DATABASE_URL=postgres://stp_user:stp_local_pw@localhost:5433/strattraderpro \
  python -m pytest -m pg --tb=short -q
cd ../frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
docker compose up -d --build
for i in $(seq 1 30); do curl -sf http://localhost:8777/healthz && break; sleep 2; done
curl -sf http://localhost:8777/healthz
curl -sf -o /dev/null -w "%{http_code}" http://localhost:8777/metrics   # exposition alive post-move
docker build -f docker/backend.Dockerfile -t stp-backend:local .
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image \
  --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed stp-backend:local

# ---- LOCAL-ONLY extra guards (CI does NOT enforce — run anyway) ----
cd backend
python manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=config.settings.prod python -c "import config.settings.prod"   # star-import trap
cd ../frontend
npx ngc --noEmit -p tsconfig.app.json
pnpm run test:ci                                   # karma specs (CI does NOT run them — you must)
```

Also: prove the full migration path once on scratch Postgres (fresh DB → seed `AuthEvent` fixtures at an intermediate migration state → `migrate` to head → verifier passes, counts match — the pg-lane test automates this); run the §10.2 concurrency test; confirm the audit-emission overhead doesn't break the webhook tests' timing assumptions; verify `/metrics` basic auth 401/200 at the callable level; check the updated `agent.yaml` parses (`docker compose config` or the agent's `-config.check` if available). Fix everything until green. **Do not push a red tree.** Update the CI workflow only as the plan directs (add the pg-lane step + conditional sourcemap step; never weaken existing gates).

### 5. Commit, push, PR
- Conventional commits, logically grouped (`feat:`, `test:`, `docs:`, `chore:`); explicit paths staged every time (Finder-dupe rule).
- `git push -u origin feature/m10-admin-audit-observability`.
- `gh pr create --base main --title "feat(m10): admin portal, chained audit log & observability polish" --body-file <file>` — fill the **entire** PR-template DoD checklist; paste the AC coverage table (Met / Deferred-live, with proving test names) and the local gauntlet results; call out the `users_auth_event` drop explicitly in the PR description.
- `gh pr checks --watch` until GitHub CI is green; fix and re-push as needed (CI uses no live calls — a red job is yours to fix).

### 6. Independent review (on the open PR)
- Spawn a **reviewer subagent** (and/or run the `/security-review` and `engineering:code-review` skills) against `git diff main...HEAD`. Review focus: hash-chain correctness (golden vectors honest, canonicalization single-sourced, advisory-lock usage), migration safety (drop ordering, frozen inline hashing, dependencies), impersonation bypass attempts (mutating views, admin routes, WS, MFA-gated paths, CSV), admin authz matrix completeness, flag fail-open + immutable enforcement, secrets scrubbing (no `mfa_code`/secrets in audit rows or logs), WSGI/ASGI dual wiring actually present in both entries, alert-rule ↔ metric-name fidelity, i18n completeness, schema regen drift, no `" 2"` files staged.
- Address all MEDIUM+ findings, re-run the gauntlet, push fixes. Append the review narrative to the PR description (recorded self-review — the DoD explicitly allows this for the solo dev).

### 7. Merge + sync main
- `gh pr merge --squash --admin --delete-branch` (operator-approved).
- If `--admin` is blocked: leave the PR open, record the exact finishing command as a manual step, and continue.
- `git checkout main && git pull origin main`.

### 8. Close out
- Tag locally on the merge commit: `git tag -a v0.10.0-admin -m "M10 admin portal, audit log & observability"`. **Do NOT push the tag** (operator-gated convention; note for Section B: no tag-triggered workflow exists — Railway deploys `main` on merge, so the merge itself deployed staging/prod including the migrations).
- Update `project-plan/PROGRESS.md` (M10 row; close the "§6.5 observability carryover" line and mark FIX-C1 + the M09 backtest-alert "live wiring is M10" item resolved — the latter two are recorded in the M04–M08 execution report and CHANGELOG respectively) and `project-plan/plan-progress-tracker.md`, via a small `docs:` commit to main (push it).
- Finish `project-plan/M10-EXECUTION-REPORT.md` and print the same content as your final message.

## FINAL REPORT — exactly two top-level sections

### Section A — What was implemented
- Branch, PR URL, merge status (merged SHA / or "PR open" + reason), created-but-unpushed tag.
- AC coverage table: AC-10-1…AC-10-12, each **Met** (with the proving test) / **Deferred-live** (why) / **Not done** (why + impact).
- Inventory: models + all five migrations (incl. the AuthEvent drop), endpoints + error codes, authentication/permission classes, Celery tasks/beat entries, new metrics + gauges, feature-flag registry (immutable/dangerous sets), Angular routes/components/store/facade/guard, `en.json` key groups, new deps (backend pins; frontend must be zero), dashboards/alert files touched, ADRs/runbooks/docs, CHANGELOG/PROGRESS/tracker updates, CI workflow changes (pg lane + sourcemap step).
- Local gauntlet + GitHub CI results at merge; Day-1 spike outcomes; migration-proof evidence (fixture counts + head hash); coverage number on new code.
- Anything decided autonomously (one line + rationale each); any hard blocker hit, what was parked, and the risk it creates.

### Section B — Manual user steps & follow-ups (the human to-do list)
Actionable, grouped, each item = what / why / where. At minimum:
- **Deployed-migration notice (lead item):** merging deployed the `users_auth_event` → `audit_log` migration + table drop to staging/prod via Railway auto-deploy; no pre-deploy backup was taken (operator credential). What proves the migration (tests + in-migration assertions); how to spot-check row counts post-deploy.
- **Railway env/services:** set `METRICS_BASIC_AUTH_USERNAME/PASSWORD` (backend + agent), `TASK_METRICS_PORT` per worker/beat/streams service, `OTEL_EXPORTER_OTLP_ENDPOINT` when Tempo is ready, frontend service `SENTRY_*`/`GRAFANA_URL` vars for `config.js`; create postgres/redis exporter services; provision the restricted DB role (runbook appendix); create the `worker-backtest` service if still missing (M09 carryover).
- **Grafana Cloud:** import the six updated dashboards + `infra/grafana/alerts/*.yaml`; create contact points (email + Telegram bot + chat id) + notification policy; configure Tempo datasource + Sentry↔Tempo correlation; then run the AC-10-9 sample-alert test and the AC-10-10 click-through.
- **GitHub:** add `SENTRY_AUTH_TOKEN` secret to activate the sourcemap-upload step.
- **Staging verifications deferred:** audit-search p95 @10M rows, verifier 24 h-window timing, flag-flip E2E in the real UI ≤ 60 s, dashboards populated, `/metrics` basic auth live.
- **Ops notes:** granting `is_staff` happens via Django admin/shell (out-of-band of the audit chain — documented limitation, M11 candidate); monthly integrity spot-check calendar entry; the unpushed `v0.10.0-admin` tag.
- **If the PR couldn't be admin-merged:** the exact `gh pr merge` command left to run.
- Anything decided autonomously that the user should sanity-check.

---

*End of one-shot prompt.*
