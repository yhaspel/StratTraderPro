> **❌ SCRAPPED 2026-07-14 (OSS pivot) — do not run.**
> M12 (private beta + prod sign-off) is dead under the pivot to open-source self-hosting: no hosted
> service, no beta cohort, no prod deploy. Superseded by `PIVOT-TO-OSS.md`. Salvage already
> reassigned there: the `/help` route (already shipped in M10.5), `scripts/smoke.sh`, and the
> v0.1.0 public-release tag idea (WP-9). Never ran — there is no M12 execution report.

---

# ONE-SHOT PROMPT — Implement StratTraderPro Milestone M12 (Private Beta, Bugfix & MVP Signoff — buildable scope, autonomous)

> Paste everything below the line into Claude CLI (UltraCode, Xhigh effort), running from the repo root
> `/Users/yuval3000/Documents/Claude/Projects/StratTraderPro`. It is self-contained and designed to run end-to-end
> **without human input**. Operator decisions already made: **admin-merge the PR autonomously**; on a hard blocker,
> **park it, document it, and finish everything else best-effort** (do not halt the run) — with ONE exception, the
> M11 precondition gate below, where halting is the operator-approved behavior.

---

## MISSION

Implement the **[CI]-tagged scope of Milestone M12 — Private Beta, Bugfix & MVP Signoff** of StratTraderPro (Django + Angular trading-bot monorepo), end to end, on its own branch, through PR → review → merge → local main sync.

**The authoritative spec is `project-plan/12-beta-and-signoff.md`** (header marker: `REVIEWED & FROZEN 2026-07-10`). It defines scope, acceptance criteria AC-12-1…AC-12-13 (each tagged **[CI]** or **[OPS]**), definition of done, implementation tasks §6.1–§6.10, test plan §10, security §11, observability §12, i18n §13, documentation deliverables §14, rollback §15, and the Exit Gate Checklist §17. Implement to that spec. Do **not** trust this prompt's summaries over the plan file or the code — read them yourself. Where this prompt and the plan disagree, **the plan wins**.

M12 is unusual: it is a beta/release milestone, so roughly half its items are **[OPS]** — they need live beta users, external services, credentials, or a deployed environment. **You implement every [CI] item; every [OPS] item becomes a documented manual step in the final report — a deliverable, not a failure.** The plan's §2 and §4 tags do this classification for you.

**Six decisions are frozen in the plan's header note — do NOT revisit them autonomously:** (1) final release tag = `v0.1.0`, RC chain `v0.1.0-rc.N`, tag pushes operator-gated; (2) deploy + rollback are Railway-native — do NOT build any GitHub Actions deploy/release pipeline; (3) feedback button = Telegram deep link + `mailto:` fallback — no feedback API, no Sentry widget; (4) help center = in-app `/help` route over the existing static articles + two new ones; (5) beta cohort = env-based `BETA_USER_EMAILS` → Sentry tag — **no schema change**; (6) **zero new dependencies**, backend and frontend.

The plan's "Duration: 5 working days" is a planning-calendar label covering the human beta week, not a constraint on you. Use subagents freely to parallelize (help-center / feedback+cohort / landing+smoke / docs implementers + a dedicated reviewer), but land everything in the **one** milestone PR.

## PRECONDITION GATE — check before anything else (the one permitted halt)

M12 hard-depends on M11 (hardening, load test, terms flow, prod env, axe + bundle CI gates). Verify **M11 is implemented and merged to `main`** via three signals: `project-plan/PROGRESS.md` shows the M11 row implemented/merged; `git log --oneline -30` contains the M11 merge (e.g. `feat(m11)` / its PR number); `project-plan/M11-EXECUTION-REPORT.md` exists. **All three must indicate M11 present; if any is missing or they conflict, treat M11 as absent and STOP.** Write `project-plan/M12-EXECUTION-REPORT.md` containing only the gate result and the instruction "run ONE-SHOT-M11 first", print the same as your final message, and end the run. Do not implement M12 against a pre-M11 tree — its frontend work would collide with M11's a11y/bundle/ToS changes. (This halt is operator-approved; everywhere else, park-and-continue.)

Also read M11's execution report Section B — if M11 deferred something M12 consumes (e.g. ToS public route for the landing-page links, axe gate wiring), note it and use the plan's stated fallbacks (§6.9: link the getting-started article if no public ToS route exists; AC-12-11: local axe scan if the gate is absent).

## WHAT "AUTONOMOUS" MEANS HERE (non-negotiable)

- **Never stop to ask the user anything.** If a decision isn't covered by the plan or this prompt, choose the safest reversible option, proceed, and log it in the final report (Section B, "decided autonomously").
- **Anything that genuinely requires a human, an external credential, live beta users, or a deployed environment → skip it, keep going, document it.** Expected **[OPS]-deferred** set for M12 (the plan tags these): recruiting/onboarding the 3–5 beta users (AC-12-1…3), creating the Telegram group + setting `BETA_FEEDBACK_URL`/`TRADESTATION_ENABLED`/`BETA_USER_EMAILS` on Railway services, the daily ops cadence §6.2, P0/P1 beta bugfixing §6.3 (AC-12-5), importing `beta-ops-dashboard.json` + tightened alert thresholds into Grafana Cloud, the Sentry saved search/alert on `beta:true`, the staging rollback drill + its timing record (AC-12-7), cutting/pushing `v0.1.0-rc.N` and `v0.1.0` tags, the prod deploy + 24h soak (AC-12-6/7), filling signoff evidence rows + the "MVP delivered" commit (AC-12-4), the CHANGELOG `[Unreleased]` → `[0.1.0]` flip at release time, the master-plan annotation completion, beta sign-off emails, and the announcement.
- **Build everything that CAN be built without those externals** — the plan's [CI] set: AC-12-8 (roadmap doc), AC-12-9 (help center), AC-12-10 (feedback button), AC-12-11 (landing page), AC-12-12 (smoke harness), AC-12-13 (beta cohort plumbing + dashboard JSON + cross-check test), plus the §6.8 signoff scaffold with `PENDING-OPERATOR` evidence cells, `docs/runbooks/beta-support.md`, CHANGELOG entries under `[Unreleased]`, and the PROGRESS/tracker close-out.
- **Hard blocker policy = park and continue** (except the M11 gate). If a component cannot reach green, park it in the least-coupled way (the help feature, feedback button, landing content, smoke script, and docs are all independently landable), record blocker + impact in the report, and complete the rest.
- **Keep a running report file** `project-plan/M12-EXECUTION-REPORT.md` updated as you go, so a partial report survives an interrupted run.

## GROUND TRUTH — read these first, in this order, before writing any code

1. `project-plan/PROGRESS.md` — canonical verified-against-code status. Confirm M10 AND M11 rows; note any M11 deferrals that touch M12.
2. `project-plan/12-beta-and-signoff.md` — **the spec.** Read every section. The header records the six frozen decisions and the [CI]/[OPS] tagging rules.
3. `project-plan/README.md` — cross-cutting conventions: baseline Definition of Done, i18n rules, branching, tags. `CONTRIBUTING.md` — branch naming, PR process, squash-merge, conventional commits, Angular 19 rules (standalone components, `@if/@for`, `inject()`, facades-not-core-services, all strings via `ngx-translate`).
4. `.github/workflows/ci.yml` — **as it exists at run time** (M11 will have added gates: axe, bundle budget, dependency audit). Mirror whatever is there; never weaken a gate. Note the `e2e-smoke` job you must extend for the smoke-script self-test.
5. `.github/pull_request_template.md` — the DoD checklist the PR must fill in.
6. `project-plan/M10-EXECUTION-REPORT.md` + `project-plan/M11-EXECUTION-REPORT.md` (if present) — report-format precedent (Sections A/B) + open deferrals M12 must not duplicate or silently absorb.
7. Reuse targets you must read before implementing against them:
   - `frontend/src/app/core/services/config.service.ts` (runtime-config accessor you extend) + `docker/nginx.conf.template` (the `window.STP_CONFIG` line) + **`docker/frontend.Dockerfile` — find `NGINX_ENVSUBST_FILTER`; it is an anchored allowlist and MUST be extended for every new `${VAR}`** (plan §6.4; the M12 review's top finding).
   - `frontend/src/app/features/dashboard/dashboard.component.ts` (header nav — `nav.admin` precedent for the Help + Feedback additions), `frontend/src/app/features/landing/landing.component.ts` (placeholder you flesh out), `frontend/src/app/features/backtest/` or `features/admin/` (lazy-routes + 3-layer precedent for the new `features/help/`), `frontend/src/assets/help/*.html` (the 13 existing articles — match their format for the 2 new ones), `frontend/src/assets/i18n/en.json`, `frontend/angular.json` (bundle budgets — landing/help must not break them).
   - `backend/config/settings/base.py` (env-flag conventions; where `BETA_USER_EMAILS` goes), `backend/config/settings/prod.py` (Sentry init), `backend/config/middleware.py` (`RequestIdMiddleware` + `tag_sentry_correlation` — the thing you must NOT hook for the beta tag), the JWT authentication class M10 installed in `DEFAULT_AUTHENTICATION_CLASSES` (where the beta tag DOES hook — plan §6.4 names the constraint: DRF resolves the user after middleware).
   - `backend/config/test_alert_rules.py` (cross-check-test precedent for the dashboard series test; note its `apps/*/metrics.py` glob and the plan's instruction about `metrics_m02.py`/`metrics_oauth.py`), `backend/apps/*/metrics*.py` (the real series names), `infra/grafana/*.json` (dashboard JSON shape to copy for `beta-ops-dashboard.json`).
   - `CHANGELOG.md` (Keep-a-Changelog, `[Unreleased]`), `docs/oncall.md`, `docs/slo.md`, `docs/runbooks/` (runbook format), `scripts/` (script conventions for `smoke.sh`).

## PROJECT-SPECIFIC GUARDRAILS (hard-won; violating these wastes hours)

Carried over from M04–M11 (all still true):

- **Local CI-parity gauntlet is the merge bar.** `pytest` + `tsc` is NOT enough — CI also runs `ruff`, `bandit`, the pg pytest lane, a real Angular build, and (post-M11) axe/bundle/dep gates. Green gauntlet before every push.
- **Angular template errors need `ngc`, not `tsc`:** `npx ngc --noEmit -p tsconfig.app.json` from `frontend/` before claiming the frontend compiles.
- **Frontend gate is `pnpm`** (`pnpm install --frozen-lockfile`, `pnpm build`); **locked decision 6 means `pnpm-lock.yaml` and `backend/requirements/*.txt` must be byte-identical at the end** — prove it with `git diff --stat` on those paths (empty).
- **Settings star-import drops `_`-prefixed names:** name-import any private helper into `prod.py`/`dev.py`; the prod-import smoke below catches this.
- **Prod web tier is WSGI (gunicorn, `config.wsgi`, gthread).** The Sentry beta-tag hook is request-scoped through DRF authentication, so it works under WSGI — but verify nothing you add assumes ASGI-only execution.
- **Prometheus:** don't invent series — the beta-ops dashboard uses existing series only, proven by the cross-check test; under multiproc gunicorn don't assert on `process_*`/`django_db_*`.
- **Match CI runtimes: Python 3.12, Node 20.**
- **Finder duplicates:** never `git add -A` / `git add .` — stage explicit paths only; never commit any file whose name contains `" 2"`.

New, M12-specific (these encode the plan review's findings — they are the milestone's trickiest failure modes):

- **`NGINX_ENVSUBST_FILTER` is the #1 trap:** adding `${BETA_FEEDBACK_URL}` / `${TRADESTATION_ENABLED}` to `nginx.conf.template` WITHOUT extending the Dockerfile's anchored allowlist ships the literal `${...}` string to every browser; karma specs stubbing `window.STP_CONFIG` will stay green while prod is broken. **Known pre-existing desync (sanctioned to fix here):** the live filter is `^BACKEND_URL$` (`docker/frontend.Dockerfile`) while the template already emits `${GRAFANA_URL}`/`${SENTRY_DSN}`/`${SENTRY_ENVIRONMENT}`/`${RELEASE}` — four vars currently ship unsubstituted (latent M10 defect; the template comment claims otherwise). Widen the anchored group to all seven vars (five existing + two new), fix the comment, and note the M10 fix in the report. Make every consumer treat empty/`${`-prefixed values as unset (spec the `${`-literal branch in karma); scope the no-literal-`${` verification assertion to the `/config.js` line after the widened filter.
- **Beta Sentry tag hooks the DRF authentication path, not middleware** — `request.user` is `AnonymousUser` when `RequestIdMiddleware` runs. Put the `tag_beta_scope(email)` helper where the JWT auth class resolves the user; keep it no-op without `SENTRY_DSN`; never log or expose `BETA_USER_EMAILS`.
- **Help viewer sanitization is scoped:** fixed manifest (slug → asset file), slug looked up never interpolated, `HttpClient` text fetch from `assets/help/`, `DomSanitizer.bypassSecurityTrustHtml` ONLY because content is first-party build-shipped — comment this at the call site. Strip/scope per-article `<style>` + full-page chrome so app styles win. Unknown slug → redirect to the index. `/help` is public (no `authGuard`).
- **No migrations, no API changes:** `python manage.py makemigrations --check --dry-run` must stay clean; OpenAPI schema + frontend types must show **no drift** (regenerate and prove the diff is empty). If a change you're making would touch either, you're outside M12 scope — stop and re-read the plan.
- **Landing page:** static content only, all strings via `en.json`, keep bundle budgets green (`pnpm build` output vs `angular.json` + any M11 gate), link ToS/Privacy per what M11 actually shipped (fallback: getting-started article), paper-trading-only disclaimer is mandatory.
- **`scripts/smoke.sh`:** exact contract = AC-12-12 (`<BASE_URL> [FRONTEND_URL]`, healthz 200 + non-empty SHA, readyz 200, optional frontend grep, non-zero + named check on failure). In the CI self-test, add a `/readyz` wait before invoking it — the `e2e-smoke` job's existing loop polls `/healthz` only.
- **CHANGELOG:** M12 entries go under `[Unreleased]`. The `[Unreleased]` → `[0.1.0]` rename is a release-time operator step (Section B) — do NOT perform it in this run.
- **Docs deliverables are [CI] even when their content is operator-fillable:** `docs/mvp-signoff.md` ships with criterion/amendment/evidence-type columns filled and evidence cells `PENDING-OPERATOR` (amendments per plan §1: ADR-041/042/090 — quote §1.1 criteria verbatim from `project-plan/strat-trader-pro.md`); `docs/post-mvp-roadmap.md` follows §6.7's 10 priorities with summary/success-criteria/effort/dependencies each; `docs/runbooks/beta-support.md` includes the smoke-harness usage, rollback-drill procedure (operator records timing), triage flow, and Telegram URL rotation note.

## WORKFLOW — execute in this exact order

### 1. Precondition gate
Run the M11 gate above. Halt with the gate report if it fails.

### 2. Branch (state-aware — the repo may have in-flight work)
- **Never absorb, commit, stash-drop, or discard work that isn't yours.** If the current branch has uncommitted changes beyond the two files named below, leave them exactly where they are; only switch branches if `git checkout main` succeeds without `-f`; if checkout is blocked, park-and-report per the blocker policy.
- `git checkout main && git pull origin main`.
- `git checkout -b feature/m12-beta-signoff`.
- **Freeze the spec as the first commit:** verify `project-plan/12-beta-and-signoff.md` contains the header marker `REVIEWED & FROZEN 2026-07-10`, then commit **exactly** `project-plan/12-beta-and-signoff.md` and `project-plan/ONE-SHOT-M12.prompt.md` (this file) as `docs(m12): freeze reviewed M12 plan + one-shot prompt` (precedent: M04–M10 prompts are committed). Explicit paths only — no `-A`, no `.`. If the two files are already committed and unchanged on `main`, skip the freeze commit and note it.

### 3. Plan
- Re-read the plan file in full. Extract every AC, §6 task, test, and Exit-Gate item into a work breakdown.
- Classify each item **[BUILDABLE NOW]** vs **[OPS-DEFERRED]** (the plan's tags do this — carry them into `project-plan/M12-EXECUTION-REPORT.md` immediately). You are accountable for every BUILDABLE item; OPS items become Section B manual steps.

### 4. Implement (to the plan's §6.4–§6.10, §8–§14)
- Frontend: `features/help/` (routes, manifest, index, viewer + specs), feedback button in the dashboard header (+ specs incl. the `${`-literal branch), landing content (+ spec), `en.json` keys, runtime-config fields + nginx template + **Dockerfile envsubst filter**.
- Backend: `BETA_USER_EMAILS` setting + `tag_beta_scope` helper at the DRF auth layer + stubbed-SDK unit tests.
- Observability: `infra/grafana/beta-ops-dashboard.json` + series cross-check test (sibling of `config/test_alert_rules.py`, glob per plan).
- Ops tooling: `scripts/smoke.sh` + `e2e-smoke` job self-test (with `/readyz` wait).
- Docs: signoff scaffold, roadmap, beta-support runbook, help articles, CHANGELOG `[Unreleased]` entries.
- Two new help articles: `getting-started.html`, `troubleshooting.html` — match the existing articles' format; user-facing tone; troubleshooting content derived from the runbooks (`webhook-debug.md`, `user-locked-out.md`, `user-lost-mfa.md`, `kill-switch-verify-monthly.md`, `daily-loss-false-trigger.md`).

### 5. Verify locally — CI-parity gauntlet (GREEN before pushing)

```bash
# ---- CI-MIRRORED gates (read .github/workflows/ci.yml at run time; it may have M11 additions — mirror ALL of them) ----
cd backend
export DJANGO_SETTINGS_MODULE=config.settings.test
ruff check .
bandit -r apps/ config/ -x tests -q --severity-level medium
python -m pytest --tb=short -q                     # SQLite lane
docker compose up -d postgres
DJANGO_SETTINGS_MODULE=config.settings.test_pg \
  DATABASE_URL=postgres://stp_user:stp_local_pw@localhost:5433/strattraderpro \
  python -m pytest -m pg --tb=short -q             # pg lane
cd ../frontend
pnpm install --frozen-lockfile
pnpm build                                          # + check bundle-budget output
cd ..
docker compose up -d --build
for i in $(seq 1 30); do curl -sf http://localhost:8777/healthz && break; sleep 2; done
for i in $(seq 1 30); do curl -sf http://localhost:8777/readyz  && break; sleep 2; done
bash scripts/smoke.sh http://localhost:8777 http://localhost:4444    # the new harness, self-tested
docker build -f docker/backend.Dockerfile -t stp-backend:local .
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image \
  --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed stp-backend:local

# ---- LOCAL-ONLY extra guards (run even if CI doesn't) ----
cd backend
python manage.py makemigrations --check --dry-run                    # M12 ships ZERO migrations
DJANGO_SETTINGS_MODULE=config.settings.prod python -c "import config.settings.prod"
cd ../frontend
npx ngc --noEmit -p tsconfig.app.json
pnpm run test:ci                                    # karma incl. all new specs
cd ..
git diff --stat main -- frontend/package.json frontend/pnpm-lock.yaml backend/requirements/   # MUST be empty (locked decision 6)
```

Also: verify the built nginx config substitutes the new vars (build the frontend image, run it with `BETA_FEEDBACK_URL` set and unset, curl the config endpoint, assert no literal `${` in output — or assert via the template + Dockerfile filter if image-run isn't feasible, and say which you did); regenerate the OpenAPI schema + frontend types and prove **zero drift**; run the Playwright suite locally if `npx playwright install chromium` succeeds (else a documented skip); if M11 shipped an axe gate, run it. Fix everything until green. **Do not push a red tree.**

### 6. Commit, push, PR
- Conventional commits, logically grouped; explicit paths staged every time.
- `git push -u origin feature/m12-beta-signoff`.
- `gh pr create --base main --title "feat(m12): beta readiness — help center, feedback, beta ops & MVP signoff scaffolding" --body-file <file>` — fill the **entire** PR-template DoD checklist; paste the AC coverage table (Met / OPS-deferred, with proving test names) and the local gauntlet results.
- `gh pr checks --watch` until GitHub CI is green; fix and re-push as needed.

### 7. Independent review (on the open PR)
- Spawn a **reviewer subagent** (and/or run the `/security-review` and `engineering:code-review` skills) against `git diff main...HEAD`. Review focus: help-viewer sanitization scope (manifest-only paths, no user-controlled fetch), envsubst filter actually extended + `${`-guards present, beta-tag hook placement (DRF auth layer, no email leakage to logs/frontend), dashboard series fidelity (cross-check test honest), smoke-script failure modes, zero dep/schema/API drift proofs, i18n completeness (no hard-coded strings), bundle budgets, no `" 2"` files staged.
- Address all MEDIUM+ findings, re-run the gauntlet, push fixes. Append the review narrative to the PR description (recorded self-review — the DoD allows this for the solo dev).

### 8. Merge + sync main
- `gh pr merge --squash --admin --delete-branch` (operator-approved).
- If `--admin` is blocked: leave the PR open, record the exact finishing command as a manual step, and continue.
- `git checkout main && git pull origin main`.

### 9. Close out
- Tag locally on the merge commit: `git tag -a v0.1.0-rc.1 -m "M12 beta-readiness RC1"`. **Do NOT push the tag** (operator-gated; Railway deploys `main` on merge, so the merge itself deployed staging/prod).
- Update `project-plan/PROGRESS.md` (M12 row: [CI] scope implemented, beta/[OPS] phase handed to operator) and `project-plan/plan-progress-tracker.md`, via a small `docs:` commit to main (push it).
- Finish `project-plan/M12-EXECUTION-REPORT.md` and print the same content as your final message.

## FINAL REPORT — exactly two top-level sections

### Section A — What was implemented
- Branch, PR URL, merge status (merged SHA / or "PR open" + reason), created-but-unpushed tag `v0.1.0-rc.1`.
- AC coverage table: AC-12-1…AC-12-13, each **Met** (with the proving test/artifact) / **OPS-deferred** (what the operator does) / **Not done** (why + impact).
- Inventory: frontend routes/components/manifest/specs, `en.json` key groups, runtime-config fields + nginx/Dockerfile changes, backend setting + hook + tests, dashboard JSON + cross-check test, `scripts/smoke.sh` + CI wiring, docs (signoff scaffold, roadmap, runbook, 2 articles), CHANGELOG entries, PROGRESS/tracker updates. Explicit proofs: zero migrations, zero API/schema drift, zero dependency changes.
- Local gauntlet + GitHub CI results at merge; anything decided autonomously (one line + rationale each); any parked blocker and its risk.

### Section B — Manual user steps & follow-ups (the human to-do list)
Actionable, grouped, each item = what / why / where. At minimum:
- **Beta launch:** recruit 3–5 users; create the Telegram group; set `BETA_FEEDBACK_URL` + `TRADESTATION_ENABLED` on the Railway **frontend** service (the latter is the runtime-config display flag — distinct from the backend's `BROKER_TRADESTATION_ENABLED`) and `BETA_USER_EMAILS` on the backend services; onboard users per the getting-started article (AC-12-1…3 evidence into the signoff doc).
- **Observability:** import `infra/grafana/beta-ops-dashboard.json`; create the Sentry saved search + alert on `beta:true`; apply/import tightened alert thresholds for beta week and revert after.
- **Release train:** run the beta week (§6.2 cadence, §6.3 bug bar); staging rollback drill + timing into the runbook (AC-12-7); push `v0.1.0-rc.1` (created, unpushed); cut further RCs as fixes land; at the bar: tag `v0.1.0`, Railway-native prod deploy, 24h soak (AC-12-6), flip CHANGELOG `[Unreleased]` → `[0.1.0]`, complete the master-plan "MVP delivered" annotation, fill + commit the signoff doc ("MVP delivered" commit), send beta sign-off emails, announce.
- **Inherited items:** anything M11's Section B left open that M12 touches, restated not absorbed.
- **If the PR couldn't be admin-merged:** the exact `gh pr merge` command left to run.
- Anything decided autonomously that the user should sanity-check.

---

*End of one-shot prompt.*
