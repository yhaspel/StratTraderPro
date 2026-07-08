# ONE-SHOT PROMPT — Implement StratTraderPro Milestones M04 → M08 (autonomous)

> Paste everything below the line into Claude CLI (UltraCode, Xhigh effort), running from the repo root
> `/Users/yuval3000/Documents/Claude/Projects/StratTraderPro`. It is self-contained and designed to run end-to-end
> without human input. Operator decisions already made: **admin-merge each PR autonomously**; on a hard blocker,
> **continue best-effort to the next milestone** (do not halt the whole run).

---

## MISSION

You are implementing five sequential milestones of StratTraderPro — a Django + Angular trading-bot monorepo — in strict order:

1. **M04** — Webhook Ingest + Broker Adapter + Alpaca Paper execution → plan: `project-plan/04-webhook-ingest-and-ibkr.md`
2. **M05** — Order Lifecycle + Second Broker (TradeStation) → plan: `project-plan/05-tradestation-and-order-lifecycle.md`
3. **M06** — Market Data + Regime Classifier → plan: `project-plan/06-market-data-and-regime.md`
4. **M07** — Sentiment Pipeline → plan: `project-plan/07-sentiment-pipeline.md`
5. **M08** — Risk Engine, Position Sizing & Kill Switches → plan: `project-plan/08-risk-engine-and-kill-switches.md`

Each milestone's plan file is **the authoritative spec** for that milestone: scope, acceptance criteria (AC-xx-n), definition-of-done, implementation tasks, data model, API contract, test plan, security, observability, i18n, and an **Exit Gate Checklist** at the bottom. Implement to that spec. Do **not** trust this prompt's summaries over the plan files or the code — read them yourself.

This is a large body of work (five weeks of planned scope). Give it maximum effort. Use subagents freely to parallelize *within* a milestone (e.g. backend + frontend + docs implementers, plus a dedicated reviewer), but keep the **milestone sequence strictly serial** — M05 builds on merged M04, M06 on M05, and so on.

## WHAT "AUTONOMOUS" MEANS HERE (non-negotiable)

- **Never stop to ask the user anything.** If a decision isn't covered by the plans or this prompt, choose the safest reversible option, proceed, and log it in the final report.
- **Anything that genuinely requires a human or an external credential you don't have → skip it, keep going, and document it.** Do not block the run on it. Examples: creating third-party accounts (Alpaca, TradeStation, FMP, FRED, Finnhub, Hugging Face), obtaining approval-gated API access, downloading gated model weights, rotating live passwords, editing Railway/GitHub secrets, running staging-only smokes, pushing release tags that trigger prod deploys.
- **Build everything that CAN be built without those externals.** The plans are written for exactly this: every broker/data/LLM integration has a Fake/mock/recorded-fixture path, feature flags default OFF, and "no live calls in CI." Implement to the CI-testable bar with fakes and flags-off; defer only the live verification.
- **Hard blocker policy = continue best-effort.** If a milestone cannot reach green local checks or cannot merge, park it (leave its branch pushed + PR open), record the blocker and the dependency risk it creates for later milestones, and move to the next milestone anyway.
- **Keep a running report file** (`project-plan/M04-M08-EXECUTION-REPORT.md`) and update it after every milestone, so a partial report survives even if the run is interrupted.

## GROUND TRUTH — read these first, before writing any code

1. `project-plan/PROGRESS.md` — **canonical, verified-against-code status.** Start here. It records that M00–M03 + M2.5 shipped and M04 is at "Phase A only" (IB Gateway spike done; Phase B–F production code does **not** exist — `apps/webhooks`, `apps/brokers`, `apps/orders` are stubs). Trust code over the tracker.
2. `docs/adr/041-alpaca-over-ibkr.md` — the 2026-07-05 pivot: **IBKR is scrapped; Alpaca is the first execution broker.** `04-webhook-ingest-and-ibkr.md` keeps its filename but specs Alpaca.
3. `project-plan/README.md` — cross-cutting conventions: **Definition of Done**, i18n rules, branching, ownership.
4. `CONTRIBUTING.md` — branch naming, PR process, squash-merge, conventional commits, ruff/bandit/pytest, Angular 19 rules (standalone components, `@if/@for`, `inject()`, facades-not-core-services, all strings via `ngx-translate`).
5. `.github/workflows/ci.yml` — the exact CI gates you must pass (see "CI PARITY" below).
6. `.github/pull_request_template.md` — the DoD checklist every PR must fill in.
7. Each of the five milestone plan files listed in MISSION.

## PROJECT-SPECIFIC GUARDRAILS (hard-won; violating these wastes hours)

- **Local CI-parity gauntlet is the merge bar.** `pytest` + `tsc` alone is NOT enough — CI also runs `ruff`, `bandit`, and a real Angular build. Run the full gauntlet locally and make it green before every push (commands below).
- **Angular template errors need `ngc`, not `tsc`.** `tsc --noEmit` does not catch NG5002/NG9 template errors. Always run `npx ngc --noEmit -p tsconfig.app.json` from `frontend/` before claiming a frontend change compiles.
- **Frontend build gate is `pnpm` (not npm).** `frontend/pnpm-lock.yaml` is the lockfile; CI runs `pnpm install --frozen-lockfile` then `pnpm build`. Keep the lockfile in sync if you add deps.
- **Settings star-import drops private names.** `dev.py`/`prod.py` do `from .base import *`, which **skips any name starting with `_`** (the existing private helper is `_wrap_db_engines_for_prometheus` — see the Prometheus note below). If you add a `_`-prefixed helper to `base.py`, you MUST name-import it in `prod.py`, or prod crashes at boot with `NameError`. Tests will NOT catch it (`config.settings.test` doesn't load `prod.py`). The prod-import smoke in the gauntlet below catches this.
- **Prometheus metrics gotchas.** Under multi-process gunicorn, `process_*` metrics are disabled (multiproc mode); don't rely on them. `django_db_*` metrics emit nothing unless the DB engine is the `django_prometheus` wrapper. When a milestone adds metrics (all of them do — §12 in each plan), follow the existing multiprocess pattern and don't assert on `process_*`/`django_db_*` unless they're actually wired.
- **If any UI needs a code editor, use the Monaco CDN AMD loader, not the npm `monaco-editor` import** — the npm path breaks `ng build` because esbuild has no `.ttf` loader for Monaco's codicon CSS. (Likely irrelevant for M04–M08, but noted.)
- **The webhook `sig` is a static bearer secret, not a computed HMAC** — TradingView cannot compute HMACs. M04 §6.3 and ADR-042 are the honest semantics; don't "fix" it into an HMAC verify. Amend ADR-031's imprecise wording as the plan says.
- **Match CI's runtimes: Python 3.12, Node 20.** The committed `.venv` is Python **3.11** — do not assume it matches CI. Recreate it on 3.12 (or install `backend/requirements/dev.txt` into a fresh 3.12 venv) so local runs match the `setup-python@v5` 3.12 pin in CI.

## THE PER-MILESTONE LOOP — execute this for M04, then M05, then M06, then M07, then M08

For milestone **Mxx** in order:

### 1. Branch
- Ensure a clean tree on `main` synced with origin: `git checkout main && git pull origin main`.
- Create the feature branch off fresh `main`: `git checkout -b feature/mNN-<short-name>`
  - `feature/m04-webhook-alpaca-paper`
  - `feature/m05-order-lifecycle`
  - `feature/m06-market-data-regime`
  - `feature/m07-sentiment`
  - `feature/m08-risk-killswitch`

### 2. Plan the milestone
- Re-read the milestone plan file in full. Extract every AC, the data-model migrations, the API contract, the test plan, and the Exit Gate Checklist.
- Classify each AC / exit-gate item as **[BUILDABLE NOW]** (test doubles, fixtures, flags-off, local) or **[LIVE-DEFERRED]** (needs an external account/key/model/staging you don't have). Write the classification into the running report. You are accountable for every BUILDABLE item; LIVE-DEFERRED items become documented manual steps, not failures.
- Optionally spawn a Plan subagent to produce a task breakdown, then implementer subagents (backend / frontend / docs) in parallel.

### 3. Implement
- Follow the plan's Implementation Tasks (§6), Data Model (§8), API Contract (§9), Security (§11), Observability (§12), i18n (§13), and Documentation Deliverables (§14).
- Backend: create/replace the stub apps, models, migrations, Celery tasks, adapters, services, DRF views/serializers, Channels consumers. Wire feature flags with safe defaults (paper-only, live disabled, new subsystems flag-gated per each plan's Rollback §15).
- Frontend: Angular 19 standalone components, signals, facades, `ngx-translate` keys in `src/assets/i18n/en.json`, no hard-coded strings.
- Tests: satisfy the plan's §10 test plan for all BUILDABLE ACs — unit + integration with `FakeBrokerAdapter` / `respx` / recorded fixtures / golden files / canned model responses. Coverage is **self-policed** — CI runs `pytest` with no `--cov-fail-under`, and the repo docs disagree (`README.md` says ≥80%, `CONTRIBUTING.md` says 90%+); target **≥90% on new code** to satisfy the stricter bar.
- Docs: write the ADRs and runbooks the plan lists (§14) as far as content allows without live data; stub live-smoke runbooks with the exact procedure the user will run later.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Regenerate the OpenAPI schema + frontend types (`make schema`, or if the docker stack isn't up: `cd backend && python manage.py spectacular --file ../docs/openapi/openapi.json` then `cd frontend && pnpm run schema:types`). **Note the `../`** — `schema:types` reads the repo-root `docs/openapi/openapi.json` (canonical, per the Makefile), so writing to `backend/docs/...` would silently leave types stale. No type drift.

### 4. Verify locally — the CI-parity gauntlet (must be GREEN before pushing)
Two groups: gates that **mirror `ci.yml` exactly** (a green PR proves these) and **local-only extra guards** that CI does NOT run (a green PR does NOT prove these — you must run them yourself).

**Note on the test DB:** `config.settings.test` uses **in-memory SQLite + eager Celery + locmem cache**, so the base `pytest` run needs **no external services** and ignores `DATABASE_URL`/`REDIS_URL`. But some milestone integration tests need real Postgres/Redis/Channels (M04 §10.2; M06 monthly-partitioned `Bar`; **M08 `SELECT FOR UPDATE`/serializable isolation** — SQLite cannot exercise row locking). For those, stand up a throwaway Postgres+Redis on the **CI DSN** and run the Postgres-dependent suites against it; if `config.settings.test` can't be pointed at Postgres via `DATABASE_URL`, adding a Postgres-backed test settings module (or a `@pytest.mark.postgres` path) is part of that milestone's work.

```bash
# ---- CI-MIRRORED gates (.github/workflows/ci.yml) — a green PR proves these ----
cd backend
export DJANGO_SETTINGS_MODULE=config.settings.test
ruff check .                                                    # ci: backend-lint-test
bandit -r apps/ config/ -x tests -q --severity-level medium     # ci: backend-lint-test
python -m pytest --tb=short -q                                  # ci: backend-lint-test (SQLite)
cd ../frontend
pnpm install --frozen-lockfile                                  # ci: frontend-lint-test
pnpm build                                                      # ci: frontend-lint-test
cd ..
docker compose up -d --build && curl -sf http://localhost:8777/healthz   # ci: e2e-smoke
docker build -f docker/backend.Dockerfile -t stp-backend:local .         # ci: image-scan target builds

# ---- LOCAL-ONLY extra guards (CI does NOT enforce — run them anyway) ----
cd backend
python manage.py makemigrations --check --dry-run              # no missing migrations
DJANGO_SETTINGS_MODULE=config.settings.prod python -c "import config.settings.prod"  # star-import NameError trap
cd ../frontend
npx ngc --noEmit -p tsconfig.app.json                         # NG5002/NG9 template errors tsc misses

# ---- Postgres-semantics suites (M06 partitioning, M08 row-locking) ----
docker run --rm -d --name stp-testpg -e POSTGRES_DB=test_db -e POSTGRES_USER=test_user \
  -e POSTGRES_PASSWORD=test_pass -p 5432:5432 postgres:16-alpine
docker run --rm -d --name stp-testredis -p 6379:6379 redis:7-alpine
# then run the Postgres-backed suites with:
#   DATABASE_URL=postgres://test_user:test_pass@localhost:5432/test_db REDIS_URL=redis://localhost:6379/0 <settings that read them>
```
Fix everything until all gates pass. Do not push a red tree. From M04 onward, also keep the `TWS_*` CI grep gate green (M04 §6.9): no `TWS_`/`DEBUG_VNC` in tracked code outside the allowlist (`docker/ib-gateway/`, ADR-040, `docs/runbooks/ib-gateway-reauth.md`, the M04 plan, `project-plan/archived/04A-IBKR-Web-API.md`).

### 5. Commit, push, PR
- Conventional-commit, logically grouped commits (`feat:`, `test:`, `docs:`, `chore:` …).
- `git push -u origin feature/mNN-<short-name>`.
- Open the PR with `gh pr create --base main --title "feat(mNN): <milestone name>" --body <file>`, filling the **entire** PR template DoD checklist and pasting the AC coverage table (met / deferred) and the local gauntlet results.
- Wait for GitHub CI to go green: `gh pr checks --watch`. If a CI job fails for a reason you can fix, fix it and re-push. If it fails only because of a LIVE-DEFERRED external (should not happen — CI uses no live calls), document it.

### 6. Independent review (the "Review" step) — on the open PR
- Spawn a **reviewer subagent** (or run the `/security-review` and `engineering:code-review` skills) against the PR diff (`git diff main...HEAD`). Check: every BUILDABLE AC is actually met and tested, auth/MFA gates present, no secrets/keys/PII in logs or code, input validation, migration safety, i18n completeness, and the milestone's §11 security items.
- Address all MEDIUM+ findings; push fixes and re-run the gauntlet until green. Append the review narrative to the PR description as the recorded self-review (the DoD explicitly allows written self-review for the solo dev).

### 7. Merge (admin, autonomous) + sync main
- Squash-merge with admin override (operator-approved; solo-dev self-review satisfies DoD):
  `gh pr merge --squash --admin --delete-branch`
- If branch protection blocks even `--admin` (e.g. gh lacks admin scope or required-review can't be bypassed): leave the PR open, record it as a manual "review & merge" step, and **continue** (best-effort) — but note that later milestones depend on this one being merged, so flag the dependency risk prominently.
- Sync local main: `git checkout main && git pull origin main`.

### 8. Close out the milestone
- **Create** the release tag locally on the merge commit (annotated), e.g. `git tag -a v0.4.0-alpaca-paper -m "M04 …"`. **Do NOT push tags** — pushing a `vX` tag on `main` triggers the prod-deploy pipeline (protected GitHub env). List created-but-unpushed tags in the report as a user step.
- Update `project-plan/PROGRESS.md` (canonical status — mark the milestone, note deferrals) and `project-plan/plan-progress-tracker.md` (per-task history). These updates can ride in the milestone PR or a tiny follow-up `docs:` commit to main.
- Append this milestone's section to `project-plan/M04-M08-EXECUTION-REPORT.md`.
- Proceed to the next milestone (back to step 1 off the freshly pulled `main`).

## MILESTONE-SPECIFIC NOTES & EXPECTED DEFERRALS

Read each plan for the full picture; these are the known human/external touchpoints to skip-and-document.

- **M04** (`04-webhook-ingest-and-ibkr.md`, tag `v0.4.0-alpaca-paper`): Build the broker-agnostic webhook ingest core, `BrokerAdapter` protocol + `FakeBrokerAdapter` + `AlpacaAdapter` (paper, `alpaca-py>=0.43,<0.44`), `run_broker_streams`, `Order/Fill/Position`, `brokers.0002_tradinghalt` (M08 reuses it), dashboard v0, `/settings/brokers`, ADR-042, pivot hygiene (`ib-gateway` behind `profiles:["ibkr"]`, `TWS_*` scrub from `.env.example`, CI grep gate, remove stray `gateway-*.png` + `_tmp_14_*` files, add `_tmp_*` to `.gitignore`). **Deferred (manual):** real Alpaca account + paper keys; the §10.4 live-paper smoke; IBKR paper+live password rotation and deleting `TWS_*` from Railway/GitHub secrets; "Grafana Trading Ops live on staging." Commit the dashboard JSON; defer the staging verification.
- **M05** (`05-tradestation-and-order-lifecycle.md`, tag `v0.5.0-tradestation`): TradeStation is approval-gated and you cannot obtain API/sim credentials. **Build the broker-agnostic order-lifecycle half in full** (reconciliation beat job, extended order types MKT/LMT/STP/STP_LMT + TIF, unified `OrderRequest`, Orders page with filters/CSV, broker picker, live-mode feature flag rejection). **Build the `TradeStationPaperAdapter` + OAuth2/PKCE code path behind `BROKER_TRADESTATION_ENABLED=false` with stubbed/recorded tests**, but mark live OAuth + real sim fills as **deferred**. This is exactly the plan's descope path (2026-07-05 review note). Document TS access as a manual step.
- **M06** (`06-market-data-and-regime.md`, tag `v0.6.0-regime`): Build the `marketdata` FMP client + FRED client + `Bar` store + feature pipeline + rule classifier + `hmmlearn` HMM + ensemble + regime UI + beat schedule, all against **recorded fixtures + golden files**; commit the `backfill_bars` script. Implement `AlpacaDataProvider` alongside `FMPProvider` **only if** the dev-cost math favors it (the plan's §6.13 abstraction makes it optional, not mandatory — judgment call at kickoff). **Deferred (manual):** FMP premium API key, FRED API key, running the 10y backfill, and the real overnight HMM retrain on staging. Tests must train HMM on seeded/fixture data with a fixed seed.
- **M07** (`07-sentiment-pipeline.md`, tag `v0.7.0-sentiment`): Build news fetchers (FMP news, SEC EDGAR 8-K, Nasdaq halts, Finnhub, + Alpaca News), dedup, spaCy+regex tagger, FinBERT worker, Llama worker (`llama-cpp-python`), tiered routing, EWMA aggregation, sentiment API + widgets — with **test doubles for both models** (canned FinBERT/Llama responses). **Deferred (manual):** downloading `ProsusAI/finbert` and the gated `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` weights (HF license acceptance), the Day-1 Llama tokens/sec benchmark on the real Railway worker, and per-source ToS review (Benzinga/Finnhub/Yahoo). Keep the LLM tier behind `LLM_WORKER_ENABLED`; if the benchmark later fails, FinBERT-only is the fallback the plan already specifies.
- **M08** (`08-risk-engine-and-kill-switches.md`, tag `v0.8.0-risk`): Build `RiskProfile` CRUD, the sizing algorithm (§6.2) wired into `process_alert`, the four kill-switch levels **on the `brokers.TradingHalt` table M04 created** (don't invent a parallel model), daily-loss watcher, soft-stop, `SizingDecision` audit, Risk page + kill-switch UI, MFA re-prompt on L1. Use `SELECT FOR UPDATE`/serializable isolation on halt-toggle + daily-loss paths; pull fresh broker marks with a short timeout and fall back to conservative cached values. Measure kill-switch flatten latency **locally against `FakeBrokerAdapter`** and run the Redis-kill chaos drill locally. **Deferred (manual):** the "p99 ≤ 5s measured on staging" and "Risk Ops dashboard live on staging" exit-gate items (need a deployed env) — verify locally, commit the dashboard, and defer the staging measurement.

## FINAL REPORT — produce this at the very end (file + printed summary)

Write `project-plan/M04-M08-EXECUTION-REPORT.md` and print the same content as your final message. Exactly two top-level sections:

### Section A — What was implemented
For each milestone M04…M08:
- Branch name, PR URL, merge status (merged commit SHA / or "PR open — awaiting merge" with reason), and the created-but-unpushed release tag.
- AC coverage table: each AC-xx-n marked **Met** (with the test that proves it) / **Deferred-live** (with why) / **Not done** (with why + impact).
- New apps, models, migrations, Celery tasks/beat entries, adapters/services, endpoints, WS events, feature flags (and default state), Angular routes/components.
- ADRs + runbooks added; CHANGELOG + PROGRESS.md + tracker updates.
- Local gauntlet result and GitHub CI result at merge.
- Any hard blocker hit and the dependency risk it pushes onto later milestones.

### Section B — Manual user steps & follow-ups (the human to-do list)
Actionable, grouped, each item = what / why / where. At minimum, capture:
- **External accounts & API keys to create/provide:** Alpaca (paper keys), TradeStation (API access + sim creds — approval-gated), FMP (premium key), FRED (key), Finnhub (free key), Hugging Face (accept Llama-3.1 license + download GGUF; download FinBERT). Where each env var goes (local `.env`, Railway).
- **Live verifications deferred to staging:** M04 real-Alpaca-paper smoke (`docs/runbooks/alpaca-paper-smoke.md`), M06 10y backfill + overnight HMM retrain, M07 Llama tokens/sec benchmark, M08 kill-switch p99 latency on staging + Risk Ops dashboard, and each milestone's Grafana "live" panels.
- **Security/ops actions:** IBKR paper+live password rotation and deleting `TWS_*` from Railway + GitHub secrets (M04 carryover); confirm Alpaca live-trading eligibility for Israeli residents before any live scope (paper unaffected).
- **Release tags to push when ready** (each triggers a prod deploy): list every `vX` tag you created locally but did not push.
- **Any PRs left open** (if `--admin` merge was blocked) with the exact `gh pr merge` command to finish them.
- **Per-source ToS checks** for M07 news feeds; **vectorbt AGPL** note is out of scope here (M09) but mention if you touched shared sizing primitives.
- Anything you decided autonomously that the user should sanity-check.

---

*End of one-shot prompt.*
