# ONE-SHOT PROMPT — Implement StratTraderPro Milestone M11 (Hardening, Security, Load Test & Docs, autonomous)

> Paste everything below the line into Claude CLI (UltraCode, Xhigh effort), running from the repo root
> `/Users/yuval3000/Documents/Claude/Projects/StratTraderPro`. It is self-contained and designed to run end-to-end
> **without human input**. Operator decisions already made: **admin-merge the PR autonomously**; on a hard blocker,
> **park it, document it, and finish everything else best-effort** (do not halt the run). Two operator choices are
> pre-decided and baked in below: **(a) M11 has a hard M10-merged precondition** — verify it first and abort cleanly
> if unmet; **(b) the load test runs against local docker-compose with `FakeBrokerAdapter`**, not staging/live Alpaca.

---

## MISSION

Implement **Milestone M11 — Hardening, Security, Load Test & Docs** of StratTraderPro (Django + Angular trading-bot monorepo), end to end, on its own branch, through PR → review → merge → local main sync.

**The authoritative spec is `project-plan/11-hardening-and-load-test.md`** (header marker: `REVIEWED & FROZEN 2026-07-12`). It defines scope, the nine frozen decisions (§4), acceptance criteria AC-11-1…AC-11-15 (each tagged **[CI]** or **[LIVE]**), definition of done (§6), implementation tasks **§7.0–§7.12**, data model (§9), API contract (§10), test plan (§11), security, observability, i18n, documentation deliverables, rollback, risks, and the Exit Gate Checklist (§18). Implement to that spec. Do **not** trust this prompt's summaries over the plan file or the code — read them yourself. **Where this prompt and the plan disagree, the plan wins.** Where the plan and the actual code disagree, trust the code and note the discrepancy in the report.

M11 is **hardening, not features**. No new product capability is added. The net-new *code* (the `SERVICE_ROLE` entrypoint dispatcher, CSP headers, GDPR export/delete, Terms models + acceptance flow, `pip-audit`/`pnpm audit`/axe/bundle CI gates, Locust load harness, chaos/backup/rotation scripts) is defensive plumbing. Read §0 "Ground-truth reconciliation" of the plan before anything else — it is a ledger of **18** corrections against reality (kill-switch is L0–L3 not L1–L4; webhook auth is a **static `sig` bearer secret, not HMAC**; secret encryption is a **single Fernet key, no `MultiFernet` in code, no DEK layer**; JWT is **single-key HS256, no `kid`**; options are supported; no object storage exists; next `users` migration is **0005**; Railway is not "6 services"; `strattraderpro.com` is not owned; **M10's operator track is CLOSED, not open** — §0.16; **11 live-found defects** shape §7.0 and §13 — §0.17; **CI already runs Karma and an nginx-envsubst guard** — §0.18). Do not "fix" the plan back into those wrong assumptions.

**§7.0 is the first implementation task and it is not optional.** M10's live bring-up found that a **blank Railway start command silently substitutes a web server** — `celery-worker` and `celery-beat` ran gunicorn for two months, so the default Celery queue had no consumer and beat never fired a single scheduled task, including `apps.risk.tasks.daily_loss_watcher`, *a risk control*, in **both** environments (BUG-011, S1/P0). It was fixed live by typing start commands into the Railway UI; **§7.0 deletes those text boxes** by making `SERVICE_ROLE` a required dispatcher in the image entrypoint that **exits non-zero when unset rather than defaulting to `web`**. Ship it before anything else — every other task's compose/CI run rides on that image. It is gated by **AC-11-14** [CI] and **AC-11-15** [LIVE].

The plan's "Duration: 5 working days" is a planning-calendar label, not a constraint on you. Use maximum effort. Use subagents freely to parallelize (security-hardening / GDPR-and-terms backend / load-and-chaos harness / a11y-and-bundle frontend / docs implementers + a dedicated reviewer), but land everything in the **one** milestone PR.

## STEP 0 — HARD PRECONDITION (do this before branching; the one place you may abort)

M11 depends on M10 being merged to `main`. First get onto `main`:

```bash
git checkout main && git pull --ff-only origin main
git status --short          # expected: CLEAN
```

- **The tree is expected to be clean** and both M11 freeze files are **already committed on `main`** (as are the M12 plan files). HEAD at freeze time was `8ecb292` (*"docs(m10): close M10 — operator track live-verified …"*; its message says "§7.12", which was the section number **before** §7 was renumbered — the task is now **§7.0**, and the plan file is authoritative). If you nevertheless find dirty files, they are **not yours**: leave them exactly where they are. **Never `git add -A`/`git add .`, never stage, commit, stash-drop, or discard anything you did not author** (another session may have in-flight work, and the tree can carry untracked `" 2"` Finder duplicates that must never be committed).

Now verify M10 is actually merged (these four checks — and ONLY these — gate the abort):

```bash
grep -q "v0.10.0-admin" project-plan/PROGRESS.md && echo "PROGRESS ok"
test -f backend/apps/audit/models.py && test -f backend/apps/admin_portal/permissions.py && echo "apps ok"
test -f backend/apps/users/migrations/0004_drop_auth_event.py && echo "migration ok"
ls frontend/src/app/features/admin/admin.routes.ts && echo "admin ui ok"
```

- If any of **those four M10-presence checks** fails, **stop and abort with a one-paragraph report**: "M11 precondition unmet — M10 (`apps/audit`, `apps/admin_portal`, `users.0004_drop_auth_event`, `/admin` UI) is not on `main`. Re-run after M10 merges." Do **not** try to build M10 or work around it. This is the *only* sanctioned stop. (A `git`-mechanics failure — e.g. no network for the pull — is NOT an M10-precondition failure: report it honestly as such, don't mislabel it.)
- If all four checks pass, proceed. From here on the autonomy rules apply and you never stop again.

## WHAT "AUTONOMOUS" MEANS HERE (non-negotiable)

- **Never stop to ask the user anything** (after Step 0). If a decision isn't covered by the plan or this prompt, choose the safest reversible option, proceed, and log it in the final report (Section B, "decided autonomously").
- **Anything that genuinely requires a human, an external credential, or a deployed environment → skip it, keep going, document it.** The plan tags these **[LIVE]**. Expected **[LIVE]-deferred** set for M11: the **`SERVICE_ROLE` Railway cutover** (AC-11-15 — set the env on every service in both envs, **delete every Custom Start Command**, staging first; the *code* for it is [CI] and mandatory), production Railway project + custom domains + Cloudflare/WAF (AC-11-10, entirely operator — domain purchase, DNS, Cloudflare account), the **real Cloudflare R2 bucket + credentials** (GDPR export + weekly `pg_dump` offload — build/test against MinIO/`moto`, R2 is operator), Railway **DB-password rotation** + measured downtime, Lighthouse FCP-on-4G (needs a deployed URL), Grafana Cloud import of the **new burn-rate rules** + **unpause** + fire/receive, and pushing the `v0.11.0-rc.1` tag + the 24h prod soak.
- **What is NOT [LIVE] any more (do not re-defer these — plan §0.16):** M10's operator track **closed on 2026-07-11**. Grafana Cloud already has 6 dashboards, **21 rules imported and unpaused**, email + Telegram contact points and a notification policy; the **postgres/redis exporters are deployed** and live in `docker-compose.yml`; `METRICS_BASIC_AUTH_*` and `TASK_METRICS_PORT` are set in both envs; every long-lived service exists; **all 14 scrape targets are `up == 1`**. So: **scrape the exporters during the load test** instead of writing "infra metrics deferred to staging", and treat burn-rate alerting as *import an already-working pipeline*, not *build one*. The one known M10 carryover is the **restricted audit DB role** (`M10-cowork-followups.md` A6) — verify its actual state and report it, don't assume either way.
- **Build everything that CAN be built without those externals.** Every AC's [CI] portion is provable locally: the **`SERVICE_ROLE` entrypoint dispatcher + its dry-run test + compose parity** (AC-11-14), `pip-audit`/`pnpm audit` gates, the ASVS evidence doc, the OWASP manual-probe regression tests, the GDPR export/delete endpoints (storage via `moto`/MinIO, email via locmem), the Terms models + acceptance flow, the Locust load run against **local compose + `FakeBrokerAdapter`**, the chaos drills via compose `kill`/`pause` (incl. the Day-6 role-removal drill), the scripted backup-restore drill against a scratch Postgres, the KEK/JWT rotation rehearsals, the axe-core Playwright a11y gate, and the Angular raw-bundle gate.
- **Hard blocker policy = park and continue.** Named M11 fallbacks:
  - If `pip-audit`/`pnpm audit` surfaces an **unfixable upstream advisory** (no patched version), do **not** leave CI red — add a documented waiver entry (`docs/security/dependency-waivers.md` + the gate's ignore mechanism: `--ignore-vuln <ID>` for pip-audit, severity level / overrides for pnpm), record it in Section B, and keep going.
  - If a local S3-compatible store (MinIO) won't come up, build the export against **`moto`** in tests + a **filesystem `STORAGES` backend** for dev so the code path is exercised; real R2 wiring is Section B.
  - If **CSP** cannot be made *enforcing* without breaking app pages, ship it **report-only** (capture violations), document the flip-to-enforce as a follow-up — do not ship a CSP that breaks the SPA.
  - If the **load test** reveals a scaling bug you cannot fix within the run, capture the numbers, file the finding in `docs/ops/load-test-results.md` + Section B, tune what you safely can (worker count / pool sizes), and continue — a documented regression is not a merge blocker for the hardening PR unless it breaks an existing test.
  - Anything else that can't reach green: park behind its flag/seam, mark its tests `xfail`/skipped with a reason, and record blocker + impact.
- **Keep a running report file** `project-plan/M11-EXECUTION-REPORT.md` updated as you go, so a partial report survives an interrupted run.

## GROUND TRUTH — read these first, in this order, before writing any code

1. `project-plan/11-hardening-and-load-test.md` — **the spec.** Read every section, especially §0 (ground-truth reconciliation, 18 items), §4 (frozen decisions), the [CI]/[LIVE] tags on every AC (§5), and **§7.0–§7.12** (§7.0 first).
2. `project-plan/PROGRESS.md` — **canonical** verified-against-code status (M00–M10 merged; M10 = PR #29 `d574057`, tag `v0.10.0-admin`; **M10 closed 2026-07-11 with its operator track live-verified**). Its M11 row names **§7.0 (SERVICE_ROLE dispatch) as the first task**. Where PROGRESS.md and any execution report disagree, **PROGRESS.md wins** — it is maintained against the code.
3. `bugs/README.md` + `bugs/BUG-008`, `BUG-009`, `BUG-011` — **critical, and newer than every execution report.** The M10 live bring-up found **11 defects that CI could not see**, 3 of them S1. BUG-011 is the entire justification for §7.0 (read its "Resolution" and "Follow-up" sections — the start commands it set are what you are deleting). BUG-009 (every imported Grafana rule arrived **paused**, and a paused rule reports `health: ok` forever) governs §13: **assert `isPaused == false` after import; never trust a component's self-report.** BUG-008 (dead-man's switch) is why absence-of-signal is now alertable. The README's closing lesson — *a clean bill of health can be produced by the defect itself* — is the review standard for every AC you mark Met.
4. `project-plan/M10-EXECUTION-REPORT.md` — format precedent for your Section A/B, **but its Section B is stale**: it was written at merge time (2026-07-10) and marks Grafana/GitHub/exporter items ⏳ that were **completed on 2026-07-11** (see PROGRESS.md + `bugs/`). Read it for the two things it flags that M11's ASVS/pentest still owe — `_scrub_sensitive` is not wired into the stdlib `python-json-logger` LOGGING config, and the dead `RiskProfile.max_concurrent`/`leverage_cap`/`permitted_asset_classes` fields — and for the restricted-audit-DB-role carryover. Do not copy its ⏳ list into your Section B without re-verifying each item.
5. `project-plan/README.md` — cross-cutting conventions: the **Baseline Definition of Done** (§"Definition of Done" — note it already lists axe-core a11y + dependency-scan-clean + translation-keys, which M11 turns from nominal into enforced), i18n rules, branching, tag strategy.
6. `CONTRIBUTING.md` — branch naming (`feature/<milestone>-<short-name>`), PR process, squash-merge, conventional commits, ruff/bandit/pytest, Angular 19 rules (standalone components, `@if/@for`, `inject()`, facades-not-core-services, all strings via `ngx-translate`).
7. `.github/workflows/ci.yml` — the exact CI gates (see CI PARITY below). **It currently has six jobs: `backend-lint-test` (ruff, bandit, SQLite lane, `-m pg` lane), `frontend-lint-test` (`pnpm install --frozen-lockfile` → **`pnpm test:ci` Karma, 67 specs** → `pnpm build` → optional Sentry sourcemaps), `e2e-smoke` (docker-compose → `/healthz`), `block-legacy-ibkr-creds` (TWS grep), `block-unsubstituted-runtime-config` (`python3 scripts/check_envsubst_filter.py`), and `image-scan` (Trivy).** M11 **adds** steps (`pip-audit`, `pnpm audit`, an axe-core Playwright job, and confirms the bundle `maximumError` actually fails) and **weakens none of those six**. Note the load-test canary is a **separate** `workflow_dispatch`+weekly-cron workflow, NOT a per-commit gate.
8. `.github/pull_request_template.md` — the DoD checklist the PR must fill in.
9. `project-plan/M04-M08-EXECUTION-REPORT.md` + `project-plan/M09-EXECUTION-REPORT.md` — outstanding deferrals M11 absorbs (the 50-user L1 flatten load test = deferred AC-08-11; the open Dependabot PRs — **count them at run time with `gh pr list --author app/dependabot`, the "~5" in the plan is a freeze-time estimate**; unpushed release tags).
10. Reuse targets you must read before implementing against them:
   - **Webhook / broker path (for load + chaos):** `backend/apps/webhooks/views.py` (static `sig` `hmac.compare_digest`, `idempotency_key` SETNX, `WEBHOOK_RATE_LIMIT_PER_MIN`/`WEBHOOK_IP_ALLOWLIST`, path `/hooks/v1/<uuid>/<uuid>/`), `backend/apps/brokers/{fake,base,services,streams}.py` + `backend/apps/brokers/management/commands/run_broker_streams.py` (`FakeBrokerAdapter` in `fake.py`, `BrokerAdapter` Protocol in `base.py`, `BROKER_STREAM_HEARTBEAT_TTL=45`, catch-up on reconnect, dedupe on `broker_exec_id`), `backend/apps/risk/{killswitch,views,models}.py` (L0–L3; **L1** = per-user global halt+flatten; **L3** blocks intake, no flatten — `killswitch.py:136`).
   - **Auth / secrets (for ASVS + rotation):** `backend/apps/users/{models,services,mfa,authentication,permissions,serializers,views}.py` (Argon2 `PASSWORD_HASHERS`, `pyotp` TOTP, `Fernet(settings.FERNET_KEK)` single-key encrypt shared by MFA/webhook/broker, `FailedLoginAttempt` lockout, `django-ratelimit` login limits, `RefreshTokenFamily`, `_send_templated`), `backend/config/settings/{base,prod,test}.py` (`SIMPLE_JWT` single-key HS256, `SECURE_*`/HSTS in prod, no CSP, no global DRF throttle), `docs/runbooks/mfa-kek-rotation.md` (the `MultiFernet` swap-then-revert procedure).
   - **Audit / export (for GDPR):** `backend/apps/audit/{models,services,events}.py` (`AuditLog` chained rows, `emit()`, `occurred_at=default=timezone.now`), `backend/apps/orders/{models,views}.py` (`AssetClass` incl. `OPTION`; the existing `GET /api/v1/orders/export.csv` — do NOT conflate with GDPR export), `backend/apps/users/urls.py` (`users/me/*` endpoints).
   - **Frontend (for terms modal + a11y):** `frontend/src/app/features/auth/totp-input/*`, `frontend/src/app/features/strategies/webhook-config/webhook-config-modal.component.ts` (modal shell), `frontend/src/app/features/admin/*` (M10 pages the a11y audit must cover), `frontend/src/app/core/*` (guards/interceptors/models), `frontend/src/assets/i18n/en.json`, `frontend/angular.json` (budgets), `frontend/playwright.config.ts` + `frontend/e2e/*` (auth-only today — extend it).
   - **Infra / topology (for §7.0 above all):** `docker-compose.yml` — services `backend`@8777 (**runs `runserver` on `config.settings.dev` — it is the *dev* server, NOT the prod `web` role**), `postgres` (**published on host `5434`, not 5433 — 5433 is another project's DB**), `redis`, `worker`, `worker-backtest`, `beat`, `streams`, `ws`/daphne@8788, `frontend`, `postgres-exporter`, `redis-exporter` (+ `ngrok`, `ib-gateway` — not roles). **Read the plan's §7.0 table for which file each of the seven commands comes from — there is no single file to copy them all from.** All six backend-image services bind-mount `./backend:/app`, so the entrypoint script must live **outside `/app`** (`/usr/local/bin/`) or the mount masks it. `docker/backend.Dockerfile` (**prod is gunicorn WSGI, `config.wsgi`, gthread; its `CMD` is both the source of the `web` command AND the silent default §7.0 replaces** — preserve the long comment block above it explaining the WSGI/Sentry-ASGI decision; note `COPY backend/ .` does not carry `docker/`, so add an explicit `COPY docker/entrypoint.sh`), `backend/config/{wsgi,asgi}.py` (M10 wired `/metrics` + basic auth into both — any new cross-cutting hook goes in both + worker init), `backend/config/celery.py` (`worker_process_init` metrics hook — FIX-C1), `infra/grafana/alerts/*.yaml` + `infra/grafana/alerts/{contact-points,notification-policy}.yaml` + `docs/{slo,oncall,postmortem-template}.md` + `docs/runbooks/alerting-setup.md` (M10 outputs M11 extends — the alerting runbook already encodes the BUG-009 unpause check).

## PROJECT-SPECIFIC GUARDRAILS (hard-won; violating these wastes hours)

Carried over from M04–M10 (all still true):

- **Local CI-parity gauntlet is the merge bar.** `pytest` + `tsc` is NOT enough — CI also runs `ruff`, `bandit`, a real Angular build, the `-m pg` Postgres lane, Trivy, and the TWS grep gate. Green gauntlet before every push.
- **Angular template errors need `ngc`, not `tsc`:** `npx ngc --noEmit -p tsconfig.app.json` from `frontend/` before claiming the frontend compiles.
- **Frontend gate is `pnpm`** (`pnpm install --frozen-lockfile`, `pnpm build`); keep `pnpm-lock.yaml` in sync. M11 **does** add frontend dev-deps (`@axe-core/playwright`) — update the lockfile deliberately and keep `--frozen-lockfile` green.
- **Settings star-import drops `_`-prefixed names:** name-import any private helper into `prod.py`/`dev.py` or prod crashes at boot; the prod-import smoke below catches this.
- **Prometheus:** module-level metrics in a per-app `metrics.py`; under multiproc gunicorn **do not assert on `process_*`/`django_db_*`** (the load-test capture must read app gauges like `celery_queue_depth`, not process metrics).
- **Prod web tier is WSGI + a separate daphne ASGI `ws` service.** Any cross-cutting hook (new middleware, CSP, request-id) must be wired into `config/wsgi.py` **and** mirrored in `config/asgi.py` (and worker init if it applies to tasks) or it ships CI-green and prod-dark.
- **Match CI runtimes: Python 3.12, Node 20**; fresh 3.12 venv if needed regardless of the gitignored `.venv`.
- **Finder duplicates:** the working tree may contain untracked junk files whose names contain `" 2"` (e.g. `project-plan/* 2.md`, `backend/apps/*/* 2.py`). **NEVER `git add -A` / `git add .`** — stage explicit paths only, and never commit any `" 2"` file. **Never absorb, commit, stash-drop, or discard work that isn't yours** (another session may have in-flight changes).

New, M11-specific (these encode the plan's trickiest failure modes — read §0 of the plan for the full ledger):

- **§7.0 `SERVICE_ROLE`: the whole value is in the failure mode, so do not soften it.** The dispatcher must **`exit 1` on unset or unrecognised roles and must never fall back to `web`** (or to anything). A "helpful" default is the bug. Put the dispatch in a committed **`docker/entrypoint.sh`**, mode **`0755`** (commit the exec bit — a `Write` lands `644` and the `ENTRYPOINT` then dies with "permission denied"); honour **`STP_ENTRYPOINT_DRY_RUN=1`** (print the resolved command, exit 0) so AC-11-14 is an ordinary subprocess test with **no docker-in-docker**.
- **§7.0 command sources — read the plan's table, do NOT "copy all of them from compose".** That shortcut ships Django's **dev server** as the production web role: `docker-compose.yml`'s `backend` service runs **`runserver`** on `config.settings.dev`. The `web` command comes from **`docker/backend.Dockerfile`'s `CMD`** — *including* `--access-logfile - --error-logfile -`, which you will silently drop if you retype it from memory. There are **seven** roles: `web` (Dockerfile), `web-dev` (compose's `backend`, guarded to refuse non-`.dev` settings), and `worker` / `worker-backtest` / `beat` / `streams` / `ws` (compose). **`ws` port trap:** the image sets `ENV PORT=8777`, so `${PORT:-8788}` never falls back — compose's `ws` service must set `PORT: 8788` or daphne binds 8777, the published `8788:8788` maps to nothing, and the 100-WS load test cannot run.
- **§7.0 evidence must compare strings, not exit codes.** The dry-run test asserts each role resolves to its **pinned expected command literal**; a bare "exit 0" check passes for any dispatcher that prints anything at all. Pin the literals in the fixture (source: Dockerfile `CMD` @ `8ecb292` for `web`, compose @ `8ecb292` for the rest) — **do not assert against `docker-compose.yml` at test time, because this task deletes those `command:` lines.** Convert only the **six backend-image services**; leave `frontend` (`ng serve`), `ngrok`, the exporters and `ib-gateway` alone — deleting `frontend`'s command breaks the E2E smoke. Since compose's `backend` becomes `web-dev`, the smoke never boots the real `web` role: add a `docker run -e SERVICE_ROLE=web` check that gunicorn answers `/healthz`. Deleting the Railway Custom Start Commands is the **[LIVE]** half (AC-11-15) — document it, don't attempt it.
- **Alert rules land PAUSED unless you check (BUG-009).** Any burn-rate rule M11 adds must have an explicit post-import `isPaused == false` assertion in the runbook/verification procedure. A paused Grafana rule reports `health: ok` forever — its self-report is worthless. More generally: **for every AC you mark Met, ask what evidence would look identical if the thing were broken.** That question is what the last 11 bugs were made of.
- **Webhook auth is a STATIC `sig` bearer secret, NOT an HMAC** (ADR-042; TradingView cannot compute HMACs). The ASVS V13 evidence, the pentest doc, and the Locust script must all describe/exercise the static-secret + `idempotency_key` replay model. **Do not "harden" the webhook into an HMAC-over-payload verify** — that is a regression prior milestones explicitly warned against.
- **Kill-switch levels are L0–L3.** The 50-user simultaneous scenario (AC-11-4) is an **L1** halt+flatten (per-user global, ≤5s p99 single-user per AC-08-8) and completes the **deferred M08 AC-08-11**. **L3 blocks intake and does NOT flatten** — don't assert a platform-wide flatten.
- **Load test target = local docker-compose + `FakeBrokerAdapter`** (frozen decision §4.1). Real Alpaca paper caps ~200 req/min and cannot absorb 20 webhooks/sec — set the broker selection env so the load path resolves to `FakeBrokerAdapter`. AC-11-3's "p95 ingest→submit ≤ 1.5s" measures the **platform** path and deliberately excludes real-broker latency. Capture app-level metrics only (infra metrics need the [LIVE] exporters).
- **DEGRADED timing is TTL-bound:** `run_broker_streams` kill → status flips DEGRADED after `BROKER_STREAM_HEARTBEAT_TTL` (default 45s). AC-11-6 asserts **≤ 60s** (TTL + margin), not 30s. Fill catch-up on reconnect dedupes on `broker_exec_id`.
- **GDPR export storage is an abstraction, not R2-hardcoded.** Use Django `STORAGES` with an S3-compatible backend (`django-storages`[s3]/boto3); test against `moto`/MinIO; **real Cloudflare R2 bucket + creds are Section B.** Signed-URL TTL = 24h. **Redact broker API keys + MFA secrets** from the export (this redaction is an AC-gating test). Export must include the user's own rows from `audit_log`.
- **Account delete = 30-day soft delete, anonymize-in-place.** Set `pending_delete_at`; a nightly job scrubs PII on the live `User` row (keep its PK so `AuditLog.user`/`actor` FKs keep resolving). **Never hard-`delete()` the `User`; never delete `audit_log` rows** — the M10 append-only trigger will `RAISE`. Emit audit events for export/delete/cancel/anonymize.
- **`MultiFernet` is NOT in the code and must not be committed to `settings`.** Secret encryption is a single `Fernet(settings.FERNET_KEK)`. The KEK-rotation rehearsal follows `docs/runbooks/mfa-kek-rotation.md`: temporarily introduce `MultiFernet`, re-encrypt, **then revert** — the M11 PR leaves single-key `Fernet` in place. Record measured times.
- **JWT is single-key HS256, no `kid`.** The signing-key rotation deliverable is a **documented drain** (in-flight access tokens ≤15m expire, refresh via `RefreshTokenFamily`), NOT a multi-kid feature. Building multi-kid is out of scope (§3).
- **Migration number:** the next free `users` migration is **`0005_delete_flow_and_terms`** (0004 = M10's `drop_auth_event`). Let `makemigrations` assign the number if the tree advanced; keep it **additive** (nullable `pending_delete_at` + two new tables — reversible).
- **CSP ships report-only → enforce** (frozen decision §4.6). Add `django-csp` (or a static header on `SecurityMiddleware`); start `Content-Security-Policy-Report-Only`; flip to enforcing only if SPA pages are clean, else leave report-only + document.
- **`pip-audit` + `pnpm audit` are NEW CI steps, and they gate differently.** `pnpm audit --audit-level=high` filters by severity; **`pip-audit` has no severity threshold at all** — it fails on any known advisory and its only suppression is `--ignore-vuln <ID>`. Do not go looking for a `--severity` flag, and do not "fix" a noisy Python gate by deleting it: resolve, or waive per-ID with an entry in `docs/security/dependency-waivers.md`. Triage the open Dependabot PRs (count them with `gh pr list --author app/dependabot`); keep the lockfile frozen-clean. **axe-core runs via a NEW Playwright CI job** (Playwright isn't in CI today; the e2e suite is auth-only — extend it to dashboard/strategies/backtest/risk/admin). **Confirm the Angular `maximumError` actually fails `pnpm build`** (today it's `error 1MB`; set a regression-guard threshold above the current 449.56 kB raw initial — do NOT introduce an ambiguous "gzipped" gate).
- **Chaos "broker 5xx storm" targets Alpaca's REST path via `FakeBrokerAdapter`/mock** (frozen decision §4.7), NOT TradeStation (flag OFF, zero live traffic — cover its retry code with a unit test instead).
- **i18n:** all new strings are `en.json` keys (no hard-coded strings — DoD). **Do NOT produce a `.pot` file or a second locale** (the app uses `ngx-translate` with a single `en.json`; there is no gettext pipeline).

## WORKFLOW — execute in this exact order

### 1. Branch (after Step 0's precondition passed; state-aware)
- You are on `main` from Step 0 with a clean tree. **The M11 freeze files are already committed on `main`** — there is no freeze commit to make. Assert the marker and move on:

```bash
grep -q "REVIEWED & FROZEN 2026-07-12" project-plan/11-hardening-and-load-test.md && echo "spec frozen ok"
git checkout -b feature/m11-hardening-and-load-test
```

- If the marker is absent, you are looking at an older copy of the plan than this prompt was written against — say so in the report and proceed against the plan file as it actually reads (the plan still wins over this prompt).
- If the tree turns out to be dirty, the changes are **not yours**: leave them, and stage explicit M11 paths for every commit from here on — **never `-A`, never `.`**, never a `" 2"` Finder-duplicate file.

### 2. Plan
- Re-read the plan file in full. Extract every AC, §7 task, migration, endpoint, test, doc deliverable, and Exit-Gate item into a work breakdown.
- Classify each AC/exit-gate item **[BUILDABLE NOW]** vs **[LIVE-DEFERRED]** (the plan's [CI]/[LIVE] tags do this — carry them into `project-plan/M11-EXECUTION-REPORT.md` immediately). You are accountable for every BUILDABLE item; LIVE items become documented Section-B steps, not failures.
- Stand up the local test substrate early: `docker compose up -d postgres redis`; confirm `moto`/MinIO available for storage tests; confirm Locust installs in the 3.12 venv.

### 3. Implement (to the plan's §7.0–§7.12, §9, §10, §12–§15)

- **FIRST — service-role dispatch (§7.0 → AC-11-14 / AC-11-15).** Land this before the other workstreams start, because it changes the image and the compose file everything else runs on. Deliver: `docker/entrypoint.sh` (mode `0755`) dispatching on a **required** `SERVICE_ROLE` over the **seven** roles in the plan's §7.0 table — **each row names its own source file; `web` comes from the Dockerfile `CMD` (logfile flags included), not from compose, whose `backend` service is `runserver`**; **`exit 1` + a loud message naming the valid roles on unset/unrecognised — never a `web` fallback**; `web-dev` refuses to start on non-`.dev` settings; `STP_ENTRYPOINT_DRY_RUN=1` support; `docker/backend.Dockerfile` `CMD` → the dispatcher (keep the existing WSGI-vs-ASGI comment block); the **six backend-image** compose services switched from `command:` to `SERVICE_ROLE:` env (**+ `PORT: 8788` on `ws`**), leaving `frontend`/`ngrok`/exporters/`ib-gateway` untouched; `docker/entrypoint.expected` (the single pinned-literal fixture — 7 `role|command` rows, trailing newline, dry-run prints templates **unexpanded**) + the dry-run subprocess test asserting all seven against it, plus unset / bogus / `web-dev`-outside-dev; a `docker run -e SERVICE_ROLE=web` boot check (the smoke only covers `web-dev`); **all of these wired into a CI job** (extend `image-scan`, which already builds the image, or add `entrypoint-dispatch`) — a local-only proof no future PR re-runs is not a gate; the §7.5 Day-6 role-removal drill (assert on `docker inspect` exit code + the loud log line: those services carry `restart: on-failure` and will crash-loop rather than sit `exited`); `docs/ops/service-role-cutover.md` (the [LIVE] operator cutover: set `SERVICE_ROLE` everywhere, **delete every Custom Start Command**, staging → verify `up{job=~"worker|beat|streams|worker-backtest"} == 1` + fresh `celery_queue_depth` → production, roll back by re-typing the command); an ADR (next free number **103**) recording the design and the **rejected `railway.json` alternative**.
- **Security hardening (§7.1, §7.2, §7.3, §7.9-config):** ASVS L2 evidence doc `docs/security/asvs-l2-evidence.md`; add CSP (report-only→enforce) + verify the security-header set; wire `_scrub_sensitive` into the stdlib LOGGING config (M10 follow-up) with a grep-test; add `pip-audit` + `pnpm audit` CI steps + `docs/security/dependency-waivers.md`; resolve HIGH+ + triage Dependabot PRs; author the OWASP manual-probe regression tests (authz cross-user 403s, webhook static-`sig` replay/spoof, upload polyglot/traversal, no open-redirect) + `docs/security/pentest-report.md`; address the dead `RiskProfile` fields.
- **GDPR + Terms (§7.7, §7.8):** `users.0005_delete_flow_and_terms` (`pending_delete_at`, `TermsDocument`, `TermsAcceptance`); `GET /api/v1/users/me/export/` (+`/{job_id}/`) Celery job → ZIP (profile/strategies/orders/fills/**per-user `audit_log`**/backtests, creds+MFA redacted) → S3-compatible storage → 24h signed URL + email; `POST /api/v1/users/me/delete/` + `/cancel/` (30-day soft) + nightly anonymize-in-place job; `GET /api/v1/terms/current/` + `POST /api/v1/terms/accept/`; SPA blocking re-acceptance modal on version bump; all strings in `en.json`.
- **Load + chaos + backup (§7.4, §7.5, §7.6):** Locust scripts under `backend/loadtest/` (100 WS `/ws/dashboard/`, 20 webhooks/sec static-`sig` mix 70/20/10, 50-user L1 flatten) against local compose + `FakeBrokerAdapter`; a scaled-down canary as a `workflow_dispatch`+weekly-cron GH Actions workflow (not per-commit); chaos scripts (Redis kill, worker kill mid-flatten, `run_broker_streams` kill, Alpaca REST 5xx via fake, DB restart) with assertions; `scripts/restore-drill.sh` (scratch Postgres restore + verification queries incl. audit-chain head re-verify). Capture results into `docs/ops/{load-test-results,chaos-drill-logs,backup-restore}.md`.
- **a11y + bundle (§7.10, §7.11):** add `@axe-core/playwright` (dev-dep, update lockfile); add new axe specs under **`frontend/e2e/a11y/*.spec.ts`** (the exact path the gauntlet runs) covering dashboard/strategies/backtest/risk/admin. **Every one of those routes is behind `IsAuthenticatedAndMFAEnforced`** — an unauthenticated spec silently redirects to `/login`, axe scans the login page five times, reports zero violations, and AC-11-11 goes green having tested nothing. Seed auth (reuse `frontend/e2e/helpers/mock-api.ts` or a storage-state fixture) and **assert a page-identifying locator is visible before `AxeBuilder.analyze()`**. Add a new Playwright CI job (Playwright isn't in CI today); confirm the Angular raw-initial `maximumError` fails the build at the regression-guard threshold; keep admin/backtest lazy chunks out of the initial budget; manual keyboard-nav pass documented.
- **Secret rotation (§7.12):** rehearse KEK (`MultiFernet` swap→revert, timed), JWT signing-key drain (timed); `docs/runbooks/secret-rotation.md` + extend `mfa-kek-rotation.md`; DB-password rotation documented as [LIVE].
- **Observability (§13):** add burn-rate alerts on top of M10's `infra/grafana/alerts/*.yaml` (the Grafana stack is **live and unpaused** — you are extending a working pipeline, not building one); **every new rule's verification step must assert `isPaused == false` after import** (BUG-009); add metrics for export/delete/terms paths (module-level, per-app `metrics.py`). Import + fire/receive is the operator's [LIVE] half.
- **Docs (§15):** the ASVS/pentest/waiver/ops/legal docs above + `docs/ops/service-role-cutover.md` (§7.0) + `docs/ops/prod-bringup.md` (re-derived real service list, Cloudflare/domains/R2/env matrix — all operator), ADRs from **103** onward for service-role dispatch + CSP + GDPR design + load-test target; **runbook frontmatter sweep** (a `Last reviewed:` line dated the run date or later on every `docs/runbooks/*.md` — derive the live count with `ls docs/runbooks/*.md | wc -l`, ~27 at freeze; normalize the header); `CHANGELOG.md` under `[Unreleased]`.
- Regenerate OpenAPI schema + frontend types (`make schema`, or `cd backend && python manage.py spectacular --file ../docs/openapi/openapi.json` then `cd frontend && pnpm run schema:types`); no type drift.

### 4. Verify locally — CI-parity gauntlet (GREEN before pushing)

```bash
# ---- CI-MIRRORED gates (.github/workflows/ci.yml) ----
cd backend
export DJANGO_SETTINGS_MODULE=config.settings.test
ruff check .
bandit -r apps/ config/ -x tests -q --severity-level medium
python -m pytest --tb=short -q                     # SQLite lane
# pg lane (M10) — CI runs it against the service container; locally use compose postgres.
# NOTE the host port is 5434, NOT 5432/5433 (compose comment: "5433 is taken by another
# project's docker-db"). Pointing at 5433 silently tests against someone else's database.
(cd .. && docker compose up -d postgres)
DJANGO_SETTINGS_MODULE=config.settings.test_pg \
  DATABASE_URL=postgres://stp_user:stp_local_pw@localhost:5434/strattraderpro \
  python -m pytest -m pg --tb=short -q
# NEW M11 backend dependency gate (pin pip-audit in requirements/dev.txt AND install it — it is not preinstalled).
# pip-audit has NO severity flag: it fails on ANY advisory. Suppress only with explicit --ignore-vuln <ID>,
# and every ignored ID gets an entry in docs/security/dependency-waivers.md.
pip install pip-audit
pip-audit -r requirements/base.txt -r requirements/prod.txt
cd ../frontend
pnpm install --frozen-lockfile
pnpm audit --audit-level=high                        # NEW M11 frontend gate — this one DOES filter by severity
pnpm build                                           # MUST fail if initial bundle exceeds maximumError
pnpm run test:ci                                     # Karma, 67 specs — CI DOES run this (BUG-007 fixed it); keep it green
cd ..
python3 scripts/check_envsubst_filter.py             # CI guard job (BUG-004) — must stay green

# ---- E2E smoke: now boots web-dev / worker / beat / streams / ws THROUGH the §7.0 dispatcher ----
docker compose up -d --build
for i in $(seq 1 30); do curl -sf http://localhost:8777/healthz && break; sleep 2; done
curl -sf http://localhost:8777/healthz
curl -sf -o /dev/null -w "%{http_code}" http://localhost:8777/metrics   # M10 exposition still alive (basic-auth aware)
# after §7.0 exactly TWO command: keys may remain (frontend, ngrok). Anything else = a backend
# service still bypassing the dispatcher. (Do NOT `grep -c command: && echo WARN` — grep exits 0
# on match, which both inverts the meaning and aborts the script under `set -e`.)
left="$(docker compose config --format json | python3 -c 'import json,sys; print(" ".join(sorted(k for k,v in json.load(sys.stdin)["services"].items() if v.get("command"))))')"
[ "$left" = "frontend ngrok" ] || { echo "FAIL: unexpected command: overrides -> [$left]"; exit 1; }

# ---- a11y gate: run AFTER the stack is up, and point Playwright at it. Without E2E_BASE_URL the
# config spawns its own `npm run start` on :4444 and collides with compose's frontend. Specs MUST
# seed auth and assert a page-identifying locator before AxeBuilder.analyze(), or every one of them
# silently redirects to /login, axe finds 0 violations, and AC-11-11 goes green having tested nothing.
cd frontend
npx playwright install --with-deps chromium || npx playwright install chromium   # fall back to browser-only in a sandbox
E2E_BASE_URL=http://localhost:4444 pnpm exec playwright test e2e/a11y            # NEW M11 axe-core gate
cd ..

docker build -f docker/backend.Dockerfile -t stp-backend:local .
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image \
  --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed stp-backend:local

# ---- NEW M11 §7.0 entrypoint gate (AC-11-14) — also wire these into a CI job, not just here ----
# Compare the RESOLVED COMMAND against pinned literals. Asserting "exit 0" alone proves nothing:
# a dispatcher that prints "hello" and exits 0 would pass. (That is the BUG-009 failure mode.)
# docker/entrypoint.expected is a DELIVERABLE you create: 7 `role|command` rows, trailing newline
# required (a `while read` loop drops a final unterminated line — that would silently skip `ws`).
# Dry-run prints the command template UNEXPANDED (literal ${PORT}), so host and container agree.
test "$(git ls-files -s docker/entrypoint.sh | cut -d' ' -f1)" = "100755" || { echo "FAIL: entrypoint not committed executable"; exit 1; }
test "$(grep -c . docker/entrypoint.expected)" = "7" || { echo "FAIL: expected 7 pinned roles"; exit 1; }
while IFS='|' read -r role expected; do
  actual="$(STP_ENTRYPOINT_DRY_RUN=1 SERVICE_ROLE="$role" DJANGO_SETTINGS_MODULE=config.settings.dev ./docker/entrypoint.sh)" \
    || { echo "FAIL: role $role exited non-zero"; exit 1; }
  [ "$actual" = "$expected" ] || { echo "FAIL: role $role"; echo "  want: $expected"; echo "  got : $actual"; exit 1; }
done < docker/entrypoint.expected
# unset / bogus / web-dev-outside-dev must EXIT NON-ZERO and never resolve to any role:
STP_ENTRYPOINT_DRY_RUN=1 ./docker/entrypoint.sh                    && { echo "FAIL: unset role must exit non-zero"; exit 1; }
STP_ENTRYPOINT_DRY_RUN=1 SERVICE_ROLE=bogus ./docker/entrypoint.sh && { echo "FAIL: bogus role must exit non-zero"; exit 1; }
STP_ENTRYPOINT_DRY_RUN=1 SERVICE_ROLE=web-dev DJANGO_SETTINGS_MODULE=config.settings.prod ./docker/entrypoint.sh \
  && { echo "FAIL: web-dev must refuse non-dev settings"; exit 1; }
STP_ENTRYPOINT_DRY_RUN=1 SERVICE_ROLE=web-dev DJANGO_SETTINGS_MODULE=config.settings.dev RAILWAY_ENVIRONMENT_NAME=production ./docker/entrypoint.sh \
  && { echo "FAIL: web-dev must refuse a deployed env"; exit 1; }
# The production `web` role is NOT covered by the compose smoke (which runs web-dev) — boot it for
# real, on the compose network, with a REAL DSN. Passing an empty -e DATABASE_URL would defeat
# base.py's sqlite default and fail with ImproperlyConfigured against a CORRECT entrypoint.
NET="$(docker compose config --format json | python3 -c 'import json,sys; print(list(json.load(sys.stdin)["networks"])[0])')"
docker run -d --rm --name stp-web-check --network "$(basename "$PWD")_${NET}" \
  -e SERVICE_ROLE=web -e DJANGO_SETTINGS_MODULE=config.settings.dev \
  -e DATABASE_URL="postgres://stp_user:stp_local_pw@postgres:5432/strattraderpro" \
  -e REDIS_URL="redis://redis:6379/0" -p 8799:8777 stp-backend:local
for i in $(seq 1 30); do curl -sf http://localhost:8799/healthz && break; sleep 2; done
curl -sf http://localhost:8799/healthz || { docker logs stp-web-check; echo "FAIL: SERVICE_ROLE=web did not boot gunicorn"; docker rm -f stp-web-check; exit 1; }
docker rm -f stp-web-check
echo "entrypoint dispatch ok"

# ---- LOCAL-ONLY extra guards (CI does NOT enforce — run anyway) ----
cd backend
python manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=config.settings.prod python -c "import config.settings.prod"   # star-import trap
cd ../frontend
npx ngc --noEmit -p tsconfig.app.json
```

Also, as part of verification (these ARE the milestone's evidence — run them and capture output, don't just assert):
- **Entrypoint (§7.0):** all **seven** roles resolve to their pinned literal in `docker/entrypoint.expected` (string equality); **unset, bogus, and `web-dev`-outside-dev exit non-zero**; only `frontend` and `ngrok` still carry a `command:` in compose; the E2E smoke reaches `/healthz` (that proves **`web-dev`** boots through the dispatcher — the production `web` role is proven separately by the `docker run -e SERVICE_ROLE=web` boot check).
- **Load test:** run the full local-compose Locust scenario once (100 WS / 20 rps / 10 min sustained) + the 50-user L1 flatten; confirm no 5xx, p95 ingest→submit ≤ 1.5s, p99 flatten ≤ 8s; paste numbers into `docs/ops/load-test-results.md`. **Run Locust headless + backgrounded and poll for completion** (`locust --headless -u 100 -r 20 --run-time 10m ... --csv=... &` then wait on the CSV/exit) so a per-command timeout doesn't kill it mid-run; if the execution sandbox can't sustain a 10-min foreground op, run the shortest window that still demonstrates steady-state (≥ 2 min), record the actual duration, and note the deviation in Section B. If docker `kill`/`pause` chaos can't run in the sandbox at all, park those drills with captured reasoning and document them as sandbox-unrunnable in Section B (do not fail the milestone on a sandbox limitation).
- **Chaos:** run each scripted drill; confirm recovery/idempotency/DEGRADED-≤60s/fill-catch-up assertions; log to `docs/ops/chaos-drill-logs.md`.
- **Backup restore:** run `scripts/restore-drill.sh` end-to-end on a scratch Postgres; verification queries pass.
- **GDPR export/delete + Terms:** integration tests green (storage via `moto`/MinIO, email via locmem); redaction test proves no creds/MFA in the ZIP; delete keeps the `User` PK + audit rows (append-only trigger not tripped).
- **Rotations:** KEK swap→revert and JWT drain rehearsals produce measured times in the runbooks.

Fix everything until green. **Do not push a red tree.** Update the CI workflow only as the plan directs (add `pip-audit`, `pnpm audit`, the axe job, the load canary workflow; confirm the bundle gate; never weaken existing gates; keep the TWS grep gate).

### 5. Commit, push, PR
- Conventional commits, logically grouped (`feat:`, `test:`, `docs:`, `chore:`, `ci:`); explicit paths staged every time (Finder-dupe rule).
- `git push -u origin feature/m11-hardening-and-load-test`.
- `gh pr create --base main --title "feat(m11): hardening, security, load test & docs" --body-file <file>` — fill the **entire** PR-template DoD checklist; paste the AC coverage table (Met / Deferred-live, with proving test names) and the local gauntlet + load/chaos/backup/rotation results; call out the new `users.0005` migration and the new CI gates explicitly.
- `gh pr checks --watch` until GitHub CI is green; fix and re-push as needed (CI uses no live calls — a red job is yours to fix; a `pip-audit`/`pnpm audit` red = resolve or waiver).

### 6. Independent review (on the open PR)
- Spawn a **reviewer subagent** (and/or run the `/security-review` and `engineering:code-review` skills) against `git diff main...HEAD`. Review focus: **§7.0 entrypoint** — no `web` fallback on unset/bogus (the single most important line in the diff); the `web` command matches the **Dockerfile `CMD`** including `--access-logfile - --error-logfile -` (compose's `backend` is `runserver` and is **not** the source); `ws` binds 8788 in compose; the dry-run test compares **resolved command strings against pinned literals**, not just exit codes; the **six backend-image** compose services have no `command:` left while `frontend` and `ngrok` keep theirs (exactly two `command:` keys remain); `entrypoint.sh` is committed `100755` and lives outside `/app`; the `web-dev` role is double-guarded (`.dev` settings **and** no `RAILWAY_ENVIRONMENT_NAME`). Then: **GDPR export redaction** (no broker creds / MFA secrets / other users' data in the ZIP; per-user authz), **delete safety** (no hard `User.delete()`, no `audit_log` deletion, append-only trigger intact, FKs still resolve after anonymize), **static-`sig` model preserved** (no accidental HMAC rewrite), **CSP not breaking pages** (report-only if unsure), **no `MultiFernet` committed to settings**, **migration additive + reversible**, **new CI gates don't weaken the six existing jobs** and both Guards (TWS grep + nginx envsubst) are intact, **no secrets in logs** (scrubber wired), **i18n completeness** (no hard-coded strings, no `.pot`), schema regen drift, and no `" 2"` files staged.
- Ask the reviewer the BUG-009 question explicitly, on every AC marked Met: **"what would this evidence look like if the thing were broken?"** If the answer is "the same", the evidence is worthless — replace it with an end-to-end assertion.
- Address all MEDIUM+ findings, re-run the gauntlet, push fixes. Append the review narrative to the PR description (recorded self-review — the DoD explicitly allows this for the solo dev).

### 7. Merge + sync main
- `gh pr merge --squash --admin --delete-branch` (operator-approved).
- If `--admin` is blocked: leave the PR open, record the exact finishing command as a Section-B manual step, and continue.
- `git checkout main && git pull origin main`.

### 8. Close out
- Tag locally on the merge commit: `git tag -a v0.11.0-rc.1 -m "M11 hardening, security, load test & docs"`. **Do NOT push the tag** (operator-gated convention; note for Section B: no tag-triggered workflow exists — Railway deploys `main` on merge, so the merge itself deployed staging/prod including the additive `users.0005` migration **and the new entrypoint image — which is inert until the operator sets `SERVICE_ROLE` and deletes the start commands, since an existing start command still overrides `CMD`. Say this plainly in Section B: the merge does NOT flip the roles.**).
- Update `project-plan/PROGRESS.md` (M11 row → implemented; note the 50-user L1 load test closes deferred AC-08-11, and that §7.0 discharges the BUG-011 follow-up **in code** with the Railway cutover still pending as AC-11-15) and `project-plan/plan-progress-tracker.md`, via a small `docs:` commit to main (push it). Also flip `bugs/BUG-011`'s "Follow-up" section to point at the shipped entrypoint.
- Finish `project-plan/M11-EXECUTION-REPORT.md` and print the same content as your final message.

## FINAL REPORT — exactly two top-level sections

### Section A — What was implemented
- Branch, PR URL, merge status (merged SHA / or "PR open" + reason), created-but-unpushed tag `v0.11.0-rc.1`.
- AC coverage table: AC-11-1…**AC-11-15**, each **Met** (with the proving test/artifact) / **Deferred-live** (why + what's needed) / **Not done** (why + impact).
- Inventory: **the `SERVICE_ROLE` dispatcher** (`docker/entrypoint.sh` + `docker/entrypoint.expected`, the seven roles, the unset/bogus/`web-dev`-guard exit behaviour, the compose `command:` → `SERVICE_ROLE:` conversion, the dry-run + mode + `web`-boot checks and which CI job now runs them, ADR-103, `docs/ops/service-role-cutover.md` incl. its Railway service→role mapping table), the `users.0005` migration + new models (`TermsDocument`, `TermsAcceptance`, `pending_delete_at`), new endpoints + error codes, GDPR export job + storage backend + redaction, delete/anonymize job, CSP config (report-only vs enforcing — say which shipped), `pip-audit`/`pnpm audit` gates + any waivers + Dependabot PRs triaged, axe-core Playwright job + pages covered, bundle-gate threshold + measured initial size, Locust harness + load results (p50/p95/p99, queue depths, WS reconnect), chaos drill outcomes, backup-restore drill, KEK + JWT rotation measured times, burn-rate alerts added, new metrics, `en.json` key groups, ADRs/runbooks/docs (+ runbook frontmatter sweep count), CHANGELOG/PROGRESS/tracker updates, CI workflow changes.
- Local gauntlet + GitHub CI results at merge; the ASVS L2 evidence summary (Pass/Waiver counts); coverage number on new code.
- Anything decided autonomously (one line + rationale each); any hard blocker hit, what was parked, and the risk it creates.

### Section B — Manual user steps & follow-ups (the human to-do list)
Actionable, grouped, each item = what / why / where. **Lead with the role cutover.** At minimum:
- **⚠️ `SERVICE_ROLE` cutover (AC-11-15) — do this first, staging then production.** For every Railway service in **both** environments: set `SERVICE_ROLE` to its role, then **delete the Custom Start Command** (the image is now the single source of truth; those text boxes were the live fix for BUG-011 and are exactly what this replaces). After staging: confirm `up{job=~"worker|beat|streams|worker-backtest"} == 1` and `celery_queue_depth` still fresh, then do production. Roll back by re-typing the start command. **Until this is done the new entrypoint is inert** — an existing start command overrides the image `CMD`, so the merge deployed the capability, not the change. Procedure: `docs/ops/service-role-cutover.md`.
- **Production bring-up (AC-11-10, all operator):** register `strattraderpro.com`; create the `strattraderpro-prod` Railway project with the real service set (backend, frontend, Postgres, Redis, worker, worker-backtest, beat, streams, ws, grafana-agent, postgres/redis exporters — per `docs/ops/prod-bringup.md`); Cloudflare account + DNS (`api.`/`app.`) + WAF + rate-limit + bot-fight + origin-lock; then the 24h prod soak.
- **Cloudflare R2 (GDPR + backups):** create the R2 bucket + credentials; set the `STORAGES`/`AWS_*` (or R2) env on backend + worker; until set, exports stay PENDING with a clear operator note (code path proven against `moto`/MinIO).
- **Grafana Cloud — import the NEW burn-rate rules only.** The stack itself is already live (6 dashboards, 21 rules, email + Telegram contact points, notification policy — M10, verified 2026-07-11), so this is *not* a re-import. **After importing, assert every new rule has `isPaused == false`** — Grafana's converter pauses by default and a paused rule reports `health: ok` forever (BUG-009). Then run fire+receive on email + Telegram.
- **Restricted audit DB role** (`M10-cowork-followups.md` A6) — the one known M10 operator carryover; state its actual status as found, and provision it if still open.
- **Secret rotation [LIVE] part:** rotate the Railway **DB password**, measure downtime, log it (KEK + JWT rehearsals are already done + timed in the runbooks).
- **Lighthouse FCP-on-4G:** run against a deployed URL once prod/staging serves the SPA (needs a deployed env).
- **Legal:** counsel review + sign-off of `docs/legal/terms-of-service.md` + `privacy-policy.md` (minimum-viable ToS is usable at beta meanwhile).
- **Tag:** `v0.11.0-rc.1` created locally, **not pushed** (operator convention; prior `v0.1.1`…`v0.10.0-admin` tags also still unpushed).
- **If the PR couldn't be admin-merged:** the exact `gh pr merge` command left to run.
- Anything decided autonomously that the user should sanity-check (e.g. CSP directive set, bundle threshold value, export schema shape, waiver entries).

---

*End of one-shot prompt.*
