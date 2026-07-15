> **⚙️ SPENT ONE-SHOT — milestone shipped; not a work item.**
> This is the agent prompt that built a now-merged milestone. Moved out of the active plan on
> 2026-07-14 (OSS pivot) and kept for historical record only — **do not re-run.** The durable record
> of what shipped lives in `project-plan/PROGRESS.md` and the matching `M*-EXECUTION-REPORT.md`.

---

# ONE-SHOT PROMPT — Implement StratTraderPro Milestone M09 (Walk-Forward Backtester, autonomous)

> Paste everything below the line into Claude CLI (UltraCode, Xhigh effort), running from the repo root
> `/Users/yuval3000/Documents/Claude/Projects/StratTraderPro`. It is self-contained and designed to run end-to-end
> without human input. Operator decisions already made: **admin-merge the PR autonomously**; on a hard blocker,
> **park it, document it, and finish everything else best-effort** (do not halt the run).

---

## MISSION

Implement **Milestone M09 — Walk-Forward Backtester** of StratTraderPro (Django + Angular trading-bot monorepo), end to end, on its own branch, through PR → review → merge → local main sync.

**The authoritative spec is `project-plan/09-walk-forward-backtester.md`** (reviewed and frozen 2026-07-08). It defines scope, acceptance criteria AC-09-1…AC-09-12, definition of done, implementation tasks §6.0–§6.9, data model, API contract, test plan, security, observability, i18n, documentation deliverables, rollback, risks, and the Exit Gate Checklist. Implement to that spec. Do **not** trust this prompt's summaries over the plan file or the code — read them yourself. Where this prompt and the plan disagree, **the plan wins**.

Four engineering decisions are already made and recorded in the plan's header note — do **not** revisit them autonomously:

1. Sweep engine = **vectorbt OSS `1.0.0`** (fair-code license; behind the `SweepEngine` seam).
2. Replay engine = **custom in-repo** (`apps/backtest/replay_engine.py`) — backtrader is rejected; never add it as a dependency.
3. Artifacts = **DB-stored** (`BacktestReport` JSON/BYTEA) — no object storage, no django-storages, no signed URLs.
4. Frontend charts = **chart.js@4 + chartjs-chart-matrix**, lazy-loaded inside the backtest bundle only.

The plan's "Duration: 5 working days" is a planning-calendar label, not a constraint on you. This is a large milestone — use maximum effort. Use subagents freely to parallelize (backend / frontend / docs implementers + a dedicated reviewer), but land everything in the **one** milestone PR.

## WHAT "AUTONOMOUS" MEANS HERE (non-negotiable)

- **Never stop to ask the user anything.** If a decision isn't covered by the plan or this prompt, choose the safest reversible option, proceed, and log it in the final report (Section B, "decided autonomously").
- **Anything that genuinely requires a human, an external credential, or a deployed environment → skip it, keep going, document it.** Known examples for M09: creating the Railway `worker-backtest` service on staging/prod, the AC-09-10 staging performance SLAs (3y ≤ 10 min / 10y ≤ 30 min / RSS ≤ 2 GB), Grafana "Backtest Ops live on staging", a real-symbol 3-year sample PDF (needs the M06 FMP backfill — the plan explicitly allows synthetic fixture bars for the exit gate instead), and pushing the release tag (triggers prod deploy).
- **Build everything that CAN be built without those externals.** M09 was specced for exactly this: fixture bars via `upsert_bars`, a seeded demo strategy + adapter, SQLite-compatible models, eager-Celery integration tests, a local CI smoke (1y fixture, grid ≤ 24, ≤ 60 s). Every AC is CI-testable except the staging half of AC-09-10.
- **Hard blocker policy = park and continue.** If some component cannot reach green (e.g., an unfixable dependency conflict), park that component behind its flag/seam, record the blocker + impact in the report, and complete the rest. Special case: if `vectorbt==1.0.0` will not install on Python 3.12 with the repo pins (verified compatible on 2026-07-08: it requires `numpy>=1.23`, `pandas>=2.0,<3.0`, `numba>=0.60`), first retry with minor pin adjustments within the repo's ranges; if genuinely impossible, **do not swap engines autonomously** — the engine choice is an operator decision. Park the sweep behind the `SweepEngine` seam with a clear `NotImplementedError` + failing-marked tests, finish the rest of the milestone, and flag it as the top item in the report.
- **Keep a running report file** `project-plan/M09-EXECUTION-REPORT.md` updated as you go, so a partial report survives an interrupted run.

## GROUND TRUTH — read these first, in this order, before writing any code

1. `project-plan/PROGRESS.md` — canonical verified-against-code status (M00–M08 implemented; M09 not started; `apps/backtest` is an empty stub already in `INSTALLED_APPS`). Note its "Next steps" list predates the M04–M08 run — trust code and git over any stale tracker lines. Merge/PR/tag facts come from `project-plan/M04-M08-EXECUTION-REPORT.md` + `git log`/`git tag` (M08 merged as PR #26, local tag `v0.8.0-risk`); read that execution report too — it is also the format precedent for your Section A/B report.
2. `project-plan/09-walk-forward-backtester.md` — **the spec.** Read every section. The header review note records the four frozen decisions and the DB-artifact rationale.
3. `project-plan/README.md` — cross-cutting conventions: Definition of Done, i18n rules, branching, ownership.
4. `CONTRIBUTING.md` — branch naming, PR process, squash-merge, conventional commits, ruff/bandit/pytest, Angular 19 rules (standalone components, `@if/@for`, `inject()`, facades-not-core-services, all strings via `ngx-translate`).
5. `.github/workflows/ci.yml` — the exact CI gates (see CI PARITY below).
6. `.github/pull_request_template.md` — the DoD checklist the PR must fill in.
7. Reuse targets you must read before implementing against them: `backend/apps/risk/sizing.py` + `backend/apps/risk/integration.py` (`compute_size`, `SizingInputs`, `_atr14` — AC-09-12 parity), `backend/apps/marketdata/{models,services}.py` (`Bar`, `upsert_bars`, `missing_bars`), `backend/apps/dashboard/{consumers,events}.py` (`push_to_user`, event wire shape), `backend/apps/strategies/{models,services}.py` (`Strategy.slug`, `upsert_system_strategy`), `frontend/src/app/abstraction/facades/orders.facade.ts` (blob download), `frontend/src/app/core/services/ws.service.ts` (events$), `frontend/src/app/features/strategies/webhook-config/webhook-config-modal.component.ts` (textarea-JSON precedent + Monaco warning).

## PROJECT-SPECIFIC GUARDRAILS (hard-won; violating these wastes hours)

Carried over from M04–M08 (all still true):

- **Local CI-parity gauntlet is the merge bar.** `pytest` + `tsc` is NOT enough — CI also runs `ruff`, `bandit`, and a real Angular build. Green gauntlet before every push.
- **Angular template errors need `ngc`, not `tsc`:** `npx ngc --noEmit -p tsconfig.app.json` from `frontend/` before claiming the frontend compiles.
- **Frontend gate is `pnpm`** (`pnpm install --frozen-lockfile`, `pnpm build`); keep `pnpm-lock.yaml` in sync when adding chart.js.
- **Settings star-import drops `_`-prefixed names:** if you add a private helper to `config/settings/base.py`, name-import it in `prod.py` or prod crashes at boot; the prod-import smoke below catches this.
- **Prometheus:** module-level metrics in a per-app `metrics.py`; under multiproc gunicorn don't assert on `process_*`/`django_db_*`.
- **No npm `monaco-editor`** — the plan mandates a plain `<textarea>` JSON editor anyway (webhook-config precedent).
- **Match CI runtimes: Python 3.12, Node 20.** Don't assume the existing (gitignored) `.venv` matches — the Day-1 spike uses a fresh 3.12 venv regardless, matching CI's `setup-python@v5` pin.

New, M09-specific (from the reviewed plan — these encode its trickiest failure modes):

- **Half-open intervals `[start, end)` everywhere** (loader, windows, segments). Pandas label-slicing is inclusive-right — use masks or `end - 1 bar`. The §6.4 worked example (3 windows, 2020 dates) is the golden fixture; your window math must reproduce it exactly.
- **The sweep receives the FULL bars frame + boundaries** (never a pre-sliced train window) so `warmup_bars` context exists; signals masked to `[start, end)`.
- **Coverage rule:** ≥ 95% of *weekdays* present, not 98% (US holidays ≈ 3.5% of weekdays); test fixtures must include holiday gaps.
- **PBO input matrix comes from ONE dedicated full-range sweep per symbol** — never from per-window train sweeps (overlap breaks CSCV). S=16 fixed; vectorized per-block statistics (a naive 12 870-partition loop blows the 60 s CI smoke); `pbo: null` when N < 10 or T < 2S.
- **`apps/backtest/stats.py` for financial metrics; `apps/backtest/metrics.py` is Prometheus-only** (repo convention).
- **Celery route is an explicit per-task entry** for `run_backtest` only — **no `apps.backtest.tasks.*` glob** (it would drag the eviction task off the default queue and silently break retention when the backtest worker is absent; eager tests can't catch it). Add the settings unit test the plan demands.
- **Eviction task runs on the default `celery` queue.**
- **WeasyPrint system deps go in BOTH places:** `docker/backend.Dockerfile` **and** the CI backend job in `ci.yml` (CI runs pytest on the runner, not in Docker). Debian slim: `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core`. No Cairo.
- **matplotlib SVGs with `svg.fonttype="none"`** (selectable text in the PDF).
- **vectorbt sweep fills must be aligned with the replay:** shift entries/exits one bar + `price=open`.
- **chart.js only inside the lazy backtest bundle** — keep `angular.json` budgets green.
- **Day-1 dependency spike (do this before any feature code):** fresh 3.12 venv → add `vectorbt==1.0.0`, `weasyprint>=68,<69`, matplotlib, plotly pins to `backend/requirements/base.txt` → resolver + import + 100-combo sweep smoke → build the backend image → run the Trivy scan CI runs (fat transitive tree: scipy/sklearn/plotly/matplotlib arrive with vectorbt). If tests are flaky under numba JIT, `NUMBA_DISABLE_JIT=1` for tests only.

## WORKFLOW — execute in this exact order

### 1. Branch (state-aware — the repo may have in-flight work)
- As of 2026-07-08 an unrelated remediation effort may exist (`fix/m04-m08-review-remediation`, possibly with uncommitted backend changes). **Never absorb, commit, stash-drop, or discard work that isn't yours.** If the current branch has uncommitted changes, leave them exactly where they are (they belong to that branch's session) and only switch branches if `git checkout main` succeeds without `-f` and without carrying those changes into your commits; if checkout is blocked, park-and-report per the blocker policy.
- `git checkout main && git pull origin main`.
- **Verify you have the frozen spec:** `project-plan/09-walk-forward-backtester.md` on your working branch must contain the header marker `RESOLVED 2026-07-08`. If main's copy lacks it, recover the reviewed version with `git show fix/m04-m08-review-remediation:project-plan/09-walk-forward-backtester.md > project-plan/09-walk-forward-backtester.md` (falling back to `origin/fix/m04-m08-review-remediation`) and commit it as the first commit of your feature branch (`docs(m09): freeze reviewed M09 plan`). Do the same for this prompt file if it's untracked — committing `project-plan/ONE-SHOT-M09.prompt.md` on the feature branch is expected (precedent: the M04–M08 prompt is committed).
- `git checkout -b feature/m09-walk-forward-backtester`.
- If `fix/m04-m08-review-remediation` is still unmerged when you finish, flag it in Section B: it touches `apps/risk`/`apps/brokers` files M09 builds on, so whichever merges second may need a small conflict pass.

### 2. Plan
- Re-read the plan file in full. Extract every AC, §6 task, migration, endpoint, test, and Exit-Gate item into a work breakdown.
- Classify each AC/exit-gate item **[BUILDABLE NOW]** vs **[LIVE-DEFERRED]** (staging/externals). Write the classification into `project-plan/M09-EXECUTION-REPORT.md` immediately. You are accountable for every BUILDABLE item; LIVE-DEFERRED items become documented manual steps, not failures. Expected LIVE-DEFERRED set: Railway `worker-backtest` service; staging SLAs of AC-09-10; Grafana live-on-staging; real-symbol 3y PDF (synthetic OK); tag push.
- Run the Day-1 dependency spike (guardrails above) and record its outcome before proceeding.

### 3. Implement (to the plan's §6.0–§6.9, §8, §9, §11, §12, §13, §14, §15)
- Backend: `apps/backtest` buildout — `data.py` loader, `strategies/` registry + `sma_cross` adapter + `seed_demo_strategy` command, `vbt_engine.py` behind `SweepEngine`, `replay_engine.py` (ADR-091 semantics, pure), `wf.py`, `pbo.py`, `stats.py`, `report.py` (JSON + inline-Plotly HTML + WeasyPrint PDF with disclaimer), `tasks.py` (routed `run_backtest`, default-queue eviction beat entry), `metrics.py` (Prometheus), serializers/views/urls, `backtest.0001_initial`, `BACKTEST_ENABLED` flag, `worker-backtest` compose service, WS events via `dashboard.events.push_to_user`.
- Frontend: lazy `backtest.routes.ts` (`/backtest`, `/backtest/:id`, `canMatch: [authGuard]`), `backtest.api.ts` → `backtest.store.ts` (signals) → `backtest.facade.ts` → standalone components (launcher, runs table, run detail with chart.js tabs, downloads via the blob pattern), `backtest.*` keys in `en.json`, chart.js + chartjs-chart-matrix in `package.json` + lockfile.
- Tests: the plan's §10 in full for BUILDABLE items — unittest-style per-app `test_*.py` (repo convention), golden replay fixtures, PBO synthetic known-answers, window-math goldens pinned to the §6.4 worked example, sizing-parity test (§10.1 exact form), eager-Celery integration run, eviction test, karma specs for store+facade. Target ≥ 90% on new code (the stricter of the repo's two documented bars).
- Docs: ADR-090/091/092, `docs/runbooks/backtest-stuck.md`, three user-help articles, `CHANGELOG.md` under `[Unreleased]`, PROGRESS.md pre-M09-blocker line marked resolved.
- Regenerate OpenAPI schema + frontend types (`make schema`, or `cd backend && python manage.py spectacular --file ../docs/openapi/openapi.json` then `cd frontend && pnpm run schema:types` — note the `../`: the repo-root file is canonical; writing `backend/docs/...` silently leaves types stale).

### 4. Verify locally — CI-parity gauntlet (GREEN before pushing)

```bash
# ---- CI-MIRRORED gates (.github/workflows/ci.yml) ----
cd backend
export DJANGO_SETTINGS_MODULE=config.settings.test
ruff check .
bandit -r apps/ config/ -x tests -q --severity-level medium
python -m pytest --tb=short -q                     # SQLite; M09 models are SQLite-compatible by design
cd ../frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
# docker gates: if the daemon is down, `open -a Docker` and poll `docker info` until ready
docker compose up -d --build
for i in $(seq 1 30); do curl -sf http://localhost:8777/healthz && break; sleep 2; done   # backend migrates first — mirror CI's retry loop
curl -sf http://localhost:8777/healthz
docker build -f docker/backend.Dockerfile -t stp-backend:local .   # must include the WeasyPrint apt deps
# Trivy (CI runs this on the PR; local fallback if trivy isn't installed):
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

Also: run the reproducibility check twice (identical `metrics_hash`), once with `NUMBA_DISABLE_JIT=1` and once without; confirm the 1y CI smoke ≤ 60 s; run the plan §16 zero-cost/no-stops cross-check once (replay vs vectorbt with aligned fills — must match within tolerance); record `pytest --cov=apps/backtest` for the report (target ≥ 90% on new code); verify the PDF renders in the built image (the runner alone passing is not proof the Dockerfile deps are right). Fix everything until green. Do not push a red tree. Keep the `TWS_*` CI grep gate green (don't touch the allowlist).

### 5. Commit, push, PR
- Conventional commits, logically grouped (`feat:`, `test:`, `docs:`, `chore:`).
- `git push -u origin feature/m09-walk-forward-backtester`.
- `gh pr create --base main --title "feat(m09): walk-forward backtester" --body-file <file>` — fill the **entire** PR-template DoD checklist; paste the AC coverage table (Met / Deferred-live, with proving test names) and the local gauntlet results.
- `gh pr checks --watch` until GitHub CI is green; fix and re-push as needed (CI uses no live calls — a red job is yours to fix).

### 6. Independent review (on the open PR)
- Spawn a **reviewer subagent** (and/or run the `/security-review` and `engineering:code-review` skills) against `git diff main...HEAD`. Review focus: every BUILDABLE AC actually met and tested; look-ahead bias (§16); half-open interval consistency; the celery-route no-glob rule; owner-scoping on runs/artifacts (§11); no secrets/PII in logs; migration safety; i18n completeness; param-grid input validation.
- Address all MEDIUM+ findings, re-run the gauntlet, push fixes. Append the review narrative to the PR description (recorded self-review — the DoD explicitly allows this for the solo dev).

### 7. Merge + sync main
- `gh pr merge --squash --admin --delete-branch` (operator-approved).
- If `--admin` is blocked: leave the PR open, record the exact finishing command as a manual step, and continue.
- `git checkout main && git pull origin main`.

### 8. Close out
- Tag locally on the merge commit: `git tag -a v0.9.0-backtest -m "M09 walk-forward backtester"`. **Do NOT push the tag** — tag pushes are operator-gated by project convention (`project-plan/README.md`). Note for Section B: as of 2026-07-08 no tag-triggered workflow actually exists in `.github/workflows/` (Railway auto-deploys `main` on merge instead — your PR merge itself deploys staging, which is established M04–M08 precedent), so tell the user to verify the prod-release trigger before relying on a tag push doing anything.
- Update `project-plan/PROGRESS.md` (M09 row + deferred items; the "before M09" blocker is resolved per the plan header) and `project-plan/plan-progress-tracker.md`, via a small `docs:` commit to main (push it).
- Finish `project-plan/M09-EXECUTION-REPORT.md` and print the same content as your final message.

## FINAL REPORT — exactly two top-level sections

### Section A — What was implemented
- Branch, PR URL, merge status (merged SHA / or "PR open" + reason), created-but-unpushed tag.
- AC coverage table: AC-09-1…AC-09-12, each **Met** (with the proving test) / **Deferred-live** (why) / **Not done** (why + impact).
- Inventory: models + migration, endpoints + error codes, Celery task/route/beat entries + compose service, WS events, feature flag + default, Angular routes/components/store/facade, new deps (backend pins + frontend packages), ADRs/runbook/help docs, CHANGELOG/PROGRESS/tracker updates.
- Local gauntlet + GitHub CI results at merge; Day-1 spike outcome (resolver/Trivy/image size); reproducibility-hash and CI-smoke timings.
- Any hard blocker hit, what was parked, and the risk it creates.

### Section B — Manual user steps & follow-ups (the human to-do list)
Actionable, grouped, each item = what / why / where. At minimum:
- **Railway:** create the `worker-backtest` service on staging/prod (`celery -A config.celery worker -Q backtest -l info --concurrency=1 --max-memory-per-child=2000000`) — until it exists, prod runs sit QUEUED forever (the queue-wait alert will fire) though retention/eviction still works (default queue by design).
- **Staging verifications deferred:** AC-09-10 SLAs (3y ≤ 10 min, 10y ≤ 30 min, RSS ≤ 2 GB — procedure in `docs/runbooks/backtest-stuck.md`), Grafana "Backtest Ops" live panel.
- **Data:** run the M06 FMP backfill (needs FMP key) if a real-symbol sample tearsheet is wanted; regenerate + archive the exit-gate sample PDF from real data when available.
- **Release:** the created-but-unpushed `v0.9.0-backtest` tag; note that no tag-triggered deploy workflow exists today (Railway deploys `main` on merge), so pushing it is bookkeeping until the operator wires a release pipeline.
- **In-flight work:** status of `fix/m04-m08-review-remediation` (if still unmerged) and any expected conflict surface with M09.
- **If the PR couldn't be admin-merged:** the exact `gh pr merge` command left to run.
- Anything decided autonomously that the user should sanity-check (list each with one-line rationale).

---

*End of one-shot prompt.*
