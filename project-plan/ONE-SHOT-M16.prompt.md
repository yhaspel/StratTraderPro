# ONE-SHOT PROMPT — Implement StratTraderPro Milestone M16 (Strategy Screener, autonomous)

> Paste everything below the line into Claude CLI (max effort), running from the repo root
> `~/Documents/Claude/Projects/StratTraderPro`. It is self-contained and designed to run end-to-end
> **without human input**, through implement → gauntlet → commit → push → PR → CI → review →
> squash-merge to `main` → local `main` sync. Operator decisions already made: **admin-merge the PR
> autonomously**; on a hard blocker, **park it, document it, and finish everything else best-effort**
> (do not halt the run — the one exception is the Phase-0 precondition, which has its own rule).

---

## MISSION

Implement **Milestone M16 — Strategy Screener** of StratTraderPro (Django 5 + Angular 19 trading-bot
monorepo), end to end, on its own branch, through PR → review → merge → local `main` sync.

**The authoritative spec is `project-plan/16-strategy-screener.md`** (status header: "Spec — not
started", dated 2026-08-01). It defines scope, AC-16-1…AC-16-12, the `[screen]` block grammar and
its exact key→FMP-param mapping table (§6.1), the one new vendor endpoint (§6.2), the `ScreenRun`
model (§6.3), the pipeline task (§6.4), the API ladder with exact error codes (§6.5), the frontend
panel states (§6.6), flags/throttle/audit (§6.7), metrics (§6.8), the guide (§6.9), test plan §10,
security §11, rollback §15, and the Exit Gate Checklist §17. Implement to that spec. Do **not**
trust this prompt's summaries over the spec or the code — read them yourself. Where this prompt and
the spec disagree, **the spec wins** (one deliberate exception: the active-run race hardening in
GUARDRAILS below is required even though the spec only states the 409 behavior).

**Two decisions are frozen in the spec's provenance note — do NOT revisit them autonomously:**
(1) screening criteria come from a deterministic `[screen]` block inside the strategy description —
no LLM extraction, no separate criteria editor; (2) the screen runs on the **instance** FMP key via
`apps.marketdata.keys.resolve_key` (ADR-062) — there are no per-user vendor keys.

The spec's "Duration: 4 working days" is a planning label, not a constraint. Use subagents freely
(parser/backend/frontend implementers + a dedicated reviewer), but land everything in **one**
milestone PR.

## WHAT "AUTONOMOUS" MEANS HERE (non-negotiable)

- **Never stop to ask the user anything.** If a decision isn't covered by the spec or this prompt,
  choose the safest reversible option, proceed, and log it in the final report (Section B,
  "decided autonomously").
- **Deferred-live set for M16** (expected, not failures): **AC-16-12's live half** — re-validating
  the FMP company-screener wire shape with a real key. If `resolve_key("FMP")` on this machine (or
  a `FMP_API_KEY` in `backend/.env`) yields a key, run the §17 live re-validation once and record
  it in ADR-063; otherwise mark it **Deferred-live with the M06 deferred-external banner** in
  ADR-063 + the report. Everything else in M16 is provable locally against fixtures.
- **Web check, then fixtures:** before writing `company_screener()`, attempt to verify the current
  param/field names via web search/fetch of the FMP stable docs
  (`https://site.financialmodelingprep.com/developer/docs/stable` → Company Search → Stock
  Screener; endpoint is `…/stable/company-screener`). The param table is JS-rendered and was NOT
  statically verifiable on 2026-08-01 — if you can't confirm it either, implement exactly the spec
  §6.2/§6.1 documented contract, pin it in fixtures, and say so in ADR-063. Do not invent
  additional params.
- **Hard blocker policy = park and continue.** If a component cannot reach green, park it behind
  `SCREENER_ENABLED` and record blocker + impact in the report.
- **Keep a running report file** `project-plan/M16-EXECUTION-REPORT.md` updated as you go, so a
  partial report survives an interrupted run.

## GROUND TRUTH — read these first, in this order, before writing any code

1. `project-plan/PROGRESS.md` — canonical status. The 2026-08-01 "Last verified" entry records
   ADR-062 (the dependency this milestone gates on) and this spec's creation.
2. `project-plan/16-strategy-screener.md` — **the spec.** Read every section.
3. `docs/adr/062-data-provider-keys-in-db.md` (the key gate you consume) and
   `docs/adr/061-data-vendor-fmp.md` **§4** (the vendor-change gate: new FMP endpoint ⇒ ADR-063 +
   fixture tripwire + live re-validation when a key lands).
4. `project-plan/README.md` (cross-cutting conventions, DoD, milestone-table) and
   `CONTRIBUTING.md` (branch `feature/<short-name>`, conventional commits, squash-merge, PR flow).
5. `.github/workflows/ci.yml` — the exact CI gates, and `.github/pull_request_template.md` — the
   DoD checklist the PR must fill in.
6. Reuse targets — read before implementing against them:
   - `backend/apps/marketdata/{keys.py,fmp.py,models.py,services.py,metrics.py,test_provider_keys.py}`
     — `resolve_key`, the FMP resilience stack (`get()` + token bucket + breaker + cache-fallback),
     `upsert_bars`, the fixture/FakeHttp test style.
   - `backend/apps/backtest/{models.py,tasks.py,urls.py,views.py}` — the async-run precedent:
     status enum + `celery_task_id`, per-task `soft_time_limit`/`time_limit` overrides, run
     list/detail URL shape.
   - `backend/apps/strategies/{models.py,views.py,permissions.py}` — `StrategyFile(kind="DESC")`
     (BinaryField `content`, `sha256`), `can_user_view`, and the `deleted_at__isnull=True`
     soft-delete filter every strategy lookup applies.
   - `backend/apps/users/{responses.py,permissions.py,test_mfa.py,views.py}` — `ok()/fail()`,
     `IsAuthenticatedAndMFAEnforced` + `mfa_required`, the MFA sweep test (the `strategies` prefix
     already covers your nested paths — verify, don't assume), and the `ratelimit(...)(view)` /
     `block=False` house pattern around line 165.
   - `backend/apps/audit/{events.py,services.py}` + `backend/apps/admin_portal/flags.py` — `emit()`
     signature, `AuditEventType` (note ADR-062 added a choices-change migration `audit/0007` — you
     will generate `0008`), `is_enabled()`.
   - `backend/config/{urls.py,settings/base.py}` — mount points, `FEATURE_FLAGS_REGISTRY` +
     `_flag()`, `CELERY_TASK_ROUTES` (explicit routes only — M09 rule), `INSTALLED_APPS`.
   - `frontend/src/app/features/settings/data-providers/data-providers.component.ts` (+`.spec.ts`)
     and `abstraction/facades/data-providers.facade.ts` + `core/services/data-providers.api.ts` —
     the freshest full-stack precedent (facade-only pattern, Result<T>, KNOWN_ERRORS mapping,
     spec style with facade stubs).
   - `frontend/src/app/features/strategies/detail/strategies-detail.component.ts` — where the
     panel embeds; how DESC is fetched (`api.download(id, 'DESC')`).
   - `frontend/src/app/core/util/tradingview-description.ts` (+`.spec.ts`) — the escape-first
     whitelist renderer you extend with the `[screen]` swallow rule.
   - `frontend/src/app/features/guides/guides.catalog.ts` + `scripts/check_guides_catalog.py` —
     the both-directions CI guard for the new guide.
   - `frontend/src/assets/i18n/en.json` — flat per-feature roots; add `screener.*`.

## PROJECT-SPECIFIC GUARDRAILS (hard-won; violating these wastes hours)

Carried over (all still true):

- **Local CI-parity gauntlet is the merge bar** — `pytest` + `tsc` is NOT enough; CI also runs
  `ruff`, `bandit`, karma-equivalent, `pnpm build`, guards, image scan. Green gauntlet before
  every push.
- **Angular template errors need `ngc`, not `tsc`:** `pnpm exec ngc --noEmit -p tsconfig.app.json`
  from `frontend/`.
- **Frontend gate is `pnpm`** (corepack, pinned `pnpm@10.33.4`; `pnpm install --frozen-lockfile`).
- **Settings star-import drops `_`-prefixed names** — any new settings helper must be
  non-underscore or explicitly re-imported in `dev.py`/`prod.py`; the prod-import smoke below
  catches it.
- **Finder duplicates:** the working tree may contain untracked junk whose names contain `" 2"`,
  plus stray delivery artifacts (`*.bundle` files at the repo root). **NEVER `git add -A` /
  `git add .`** — stage explicit paths only.
- **UTC crontabs / no glob Celery routes** (M09 rule). M16 adds NO beat entries and NO route
  entries — the screener task rides the default queue.
- **No new dependencies**, backend or frontend. `requirements/*.txt` and `pnpm-lock.yaml` must be
  byte-identical after this milestone. Parser is stdlib; SMA/52w math is plain Python.

New, M16-specific (these encode the spec's trickiest failure modes — treat as required):

- **Never read `settings.FMP_API_KEY` directly.** The gate and the client key are
  `apps.marketdata.keys.resolve_key("FMP")` (UI key → env → ""), re-checked inside the task
  (AC-16-2/3; the key can be removed between enqueue and execution).
- **Active-run race hardening (required addition):** the "one active run per (user, strategy)"
  gate must be a DB constraint, not just a pre-check —
  `UniqueConstraint(fields=["user", "strategy"], condition=Q(status__in=["QUEUED", "RUNNING"]),
  name="uniq_active_screen_run_per_user_strategy")` on `ScreenRun`, with the create wrapped so an
  `IntegrityError` returns the same 409 `SCREEN_RUN_ACTIVE`. (Works on SQLite + Postgres; test
  both the pre-check and the constraint path.)
- **Celery default soft limit is 30s** (`CELERY_TASK_SOFT_TIME_LIMIT`) — the screener task MUST
  set `soft_time_limit=240, time_limit=300` on its own decorator (backtest precedent) or a
  50-candidate enrichment dies mid-run.
- **DESC bytes → text:** decode `bytes(file.content)` as UTF-8 with `errors="replace"`; apply the
  §6.1 size/line caps BEFORE parsing; at most one block (`duplicate_block` error). Linear scan
  only — no backtracking-prone regex over user text (§11).
- **Soft-delete:** every strategy lookup in the screener views filters
  `deleted_at__isnull=True` (match `apps/strategies/views.py`) and applies `can_user_view` → 404,
  never 403, for invisible strategies (strategies-app convention).
- **Parser fixtures must mirror REAL TradingView exports** (the #45 lesson): licence-header lead-in
  before any block, CRLF line endings, UTF-8 BOM, block mid-prose, BBCode around the block. A
  synthetic-only fixture set is a spec violation (§10.1).
- **Renderer swallow rule:** `[screen]…[/screen]` drops the tag AND inner text (unlike the default
  strip-keep-text); an **unclosed** `[screen]` falls back to strip-keep-text and must never eat the
  rest of the description. Extend `tradingview-description.spec.ts` for both.
- **New-app scaffolding checklist** for `backend/apps/screener/`: `__init__.py`,
  `apps.py` (`name = "apps.screener"`), `migrations/__init__.py`, add `"apps.screener"` to
  `INSTALLED_APPS` in `config/settings/base.py`, THEN `python manage.py makemigrations screener`.
  Adding `AuditEventType.SCREEN_RUN_REQUESTED` also changes `AuditLog.event_type` choices —
  `makemigrations audit` will emit `0008_alter_auditlog_event_type` (expected; commit it).
- **URL mount:** in `config/urls.py`, add
  `path("api/v1/strategies/<uuid:strategy_id>/screen/", include("apps.screener.urls"))`
  **above** the `api/v1/strategies/` include, so the literal `screen/` segment can never be
  shadowed. The new paths inherit the MFA sweep's `strategies` prefix — run
  `apps/users/test_mfa.py` and confirm; if the sweep needs an explicit entry, add
  `("strategies", "<some-uuid>/screen/runs/")`-style coverage rather than weakening anything.
- **Ratelimit house pattern:** `django_ratelimit` with `block=False` + an explicit
  `getattr(request, "limited", False)` → 429 `RATE_LIMITED` check (see `RegisterView` wrapping in
  `apps/users/views.py`); `RATELIMIT_ENABLE=False` in test settings keeps the suite hermetic —
  the throttle test itself uses `override_settings(RATELIMIT_ENABLE=True)`.
- **Key-leak surfaces:** the FMP key must never appear in `ScreenRun` rows, task args (pass
  `run_id` only), log lines, audit rows, or exception strings (the clients already redact
  transport errors — don't undo that).
- **OpenAPI regen ORDER:** regenerate the schema + types BEFORE the final karma/build runs —
  `frontend/src/app/core/models/auth.models.contract.spec.ts` imports the generated
  `core/generated/schema.ts`, so a post-test regen invalidates your karma evidence. Commands
  (docker-free equivalents of `make schema`):
  `cd backend && DJANGO_SETTINGS_MODULE=config.settings.test python manage.py spectacular --file ../docs/openapi/openapi.json`
  then `cd ../frontend && pnpm run schema:types`.
- **Guide + catalog move together** (`scripts/check_guides_catalog.py` fails on drift in BOTH
  directions), and it also verifies every referenced screenshot file exists — write the
  `strategy-screening` guide **without `<img>` references** (text + tables + code samples) unless
  you also generate real screenshots via `frontend/tools/guide-screenshots.mjs`.
- **Deterministic ranking:** §6.4's rank order with ties broken by symbol; the §10.5
  reproducibility test asserts byte-identical `results` JSON on identical inputs.
- **i18n:** new flat `screener.*` root in `en.json` (panel states, table headers,
  `screener.error.<CODE>` for every §9 error code — `FMP_NOT_CONFIGURED`'s message points at
  Settings → Data Providers). Karma specs assert raw keys (no loader in tests).

## WORKFLOW — execute in this exact order

### 0. Preconditions (the one legitimate halt)

```bash
cd ~/Documents/Claude/Projects/StratTraderPro
git status --porcelain        # untracked *.bundle / " 2" junk is fine; TRACKED changes → park-and-report, do not absorb
git checkout main && git pull origin main
test -f backend/apps/marketdata/keys.py && test -f project-plan/16-strategy-screener.md && echo PRECONDITIONS-OK
```

If `PRECONDITIONS-OK` does not print, **ADR-062 has not been landed on `main`** — M16 gates on it.
Recover in this order, then re-run the check:

1. If local branch `feat/data-provider-keys-ui` exists (`git branch --list feat/data-provider-keys-ui`),
   land it first.

   ⛔ **It is BEHIND `main` and will NOT merge as-is.** Verified 2026-08-02: the branch is 2 commits
   behind (`5fafff0` = PR #50, `aa16811` = PR #51) and **conflicts on `CHANGELOG.md`**. `gh pr merge`
   refuses a non-mergeable PR, so reconcile BEFORE opening it:

   ```bash
   git checkout feat/data-provider-keys-ui
   git merge origin/main
   # CHANGELOG.md is the ONLY expected conflict — both sides appended entries.
   # Resolve by KEEPING BOTH, in date order. Do not drop the ADR-109 entries.
   git add CHANGELOG.md && git commit --no-edit
   git merge-tree --write-tree origin/main HEAD >/dev/null && echo MERGEABLE
   ```
   Any conflict other than `CHANGELOG.md` is not the expected shape — stop and inspect before
   resolving it.

   ⚠️ **Re-run the gauntlet on the merged tip — do NOT trust the 2026-08-01 green.** The branch has
   moved since: it also carries `e786a47` (M16 spec + plan docs) and `21cddf3` (ADR-109 doc fixes +
   the operator report). Both are docs-only so expect green, but the recorded gauntlet does not
   cover this tip. Minimum: backend `pytest`, `makemigrations --check --dry-run`, `pnpm build`.

   ⚠️ **Scope note — put this in the PR body.** That PR now lands ADR-062 **and** the ADR-109
   documentation fixes (4 runbooks, `bugs/README.md`, `.gitignore`, and
   `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md`). State it in the description rather than
   letting a reviewer discover it. To keep them apart, move `21cddf3` to its own branch first —
   but do not silently drop it.

   Then: `git push -u origin feat/data-provider-keys-ui`, `gh pr create --base main --fill`,
   `gh pr checks --watch` until green (a red CI job is yours to fix forward inside that PR),
   `gh pr merge --squash --admin --delete-branch`, `git checkout main && git pull origin main`.
2. Else if `strattraderpro-data-provider-keys.bundle` exists at the repo root:
   `git bundle verify strattraderpro-data-provider-keys.bundle && git fetch strattraderpro-data-provider-keys.bundle 'refs/heads/feat/data-provider-keys-ui:refs/heads/feat/data-provider-keys-ui'`,
   then do step 1. Delete the bundle file only after the branch is pushed.
3. Else **HALT** and report: "M16 blocked — ADR-062 (feat/data-provider-keys-ui) is not on main and
   neither the branch nor its bundle is present. Land the data-provider-keys work first."

Do not touch `observability-reduced-scope.bundle` if present — it belongs to a different pending landing.

### 1. Branch

`git checkout -b feature/m16-strategy-screener` (from the fresh `main`).

### 2. Plan

Turn spec §6.1–§6.9 + §14 into a todo list before coding. Implementation order that respects the
dependencies: §6.1 parser (+ §10.1 tests) → §6.2 `company_screener` (+ contract fixture) → §6.3 app
scaffold + model + migrations (screener 0001, audit 0008) → §6.4 task → §6.5 API + MFA-sweep
confirmation → §6.7 flag/throttle/audit → §6.8 metrics → OpenAPI regen → §6.6 frontend
(models/api/facade/panel + spec, renderer swallow rule + spec) → §13 i18n → §6.9 guide + catalog →
§14 docs (ADR-063, runbook paragraph, CHANGELOG `[Unreleased]`).

### 3. Implement

To the spec, with the GUARDRAILS above. Frontend follows the house 3-layer pattern (component →
facade → api; components never inject `*.api.ts`), standalone + OnPush + inline template, reactive
forms, design-system components (`app-card`, `app-button` with `(clicked)`, `app-status-chip`,
`app-help-link`), Tailwind token classes only (no raw hex, `rounded-none`). Poll the active run at
the 2s cadence until terminal; stop polling on component destroy.

### 4. Verify locally — CI-parity gauntlet (GREEN before pushing)

```bash
# ---- backend (use the repo venv: backend/.venv/bin/... or ../.venv/bin/... — whichever this machine uses; HANDOFF precedent)
cd backend
ruff check .
bandit -r apps/ config/ -x tests -q --severity-level medium
python -m pytest --tb=short -q                      # SQLite lane — the whole suite, not just new tests
python manage.py makemigrations --check --dry-run
SECRET_KEY=smoke \
  FERNET_KEK=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
  DATABASE_URL=postgres://u:p@localhost:5432/x REDIS_URL=redis://localhost:6379/0 \
  DJANGO_SETTINGS_MODULE=config.settings.prod python -c "import django; django.setup()"   # star-import trap
# pg lane (CI enforces it regardless; run locally if Docker is available — note which in the report):
docker compose up -d postgres && sleep 3 && \
  DJANGO_SETTINGS_MODULE=config.settings.test_pg \
  DATABASE_URL=postgres://stp_user:stp_local_pw@localhost:5434/strattraderpro \
  python -m pytest -m pg --tb=short -q              # host port 5434 — see docker-compose.yml comment

# ---- OpenAPI (BEFORE the frontend gates — see guardrail)
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py spectacular --file ../docs/openapi/openapi.json

# ---- frontend
cd ../frontend
pnpm install --frozen-lockfile                      # must be a no-op change to pnpm-lock.yaml
pnpm run schema:types
pnpm exec ngc --noEmit -p tsconfig.app.json
pnpm test:ci                                        # karma — CI runs this; all specs incl. yours
pnpm build
pnpm exec playwright test e2e/a11y                  # incl. your §10.3 panel a11y spec

# ---- repo guards
cd ..
python3 scripts/check_guides_catalog.py
python3 scripts/check_envsubst_filter.py
```

Fix everything until green. **Do not push a red tree.** Do not weaken any existing CI gate or test.

### 5. Commit, push, PR

- Conventional commits, logically grouped, explicit paths staged every time (never `git add -A`).
  Suggested shape: `feat(screener): [screen] parser + FMP company-screener client` →
  `feat(screener): ScreenRun pipeline + API` → `feat(strategies): screening panel UI` →
  `docs(screener): ADR-063, guide, changelog` — include
  `project-plan/ONE-SHOT-M16.prompt.md` (this file) in the docs commit, matching the repo's
  one-shot convention.
- `git push -u origin feature/m16-strategy-screener`.
- `gh pr create --base main --title "feat(m16): strategy screener — [screen]-block driven FMP screening" --body-file <file>`
  — fill the **entire** PR-template DoD checklist; paste the AC-16-1…AC-16-12 coverage table
  (Met / Deferred-live, with proving test names) and the gauntlet results; note that fork-PR
  approval is "all external contributors" and branch protection is saved-not-enforced, so **CI is
  the only gate that actually runs** — which is why the gauntlet above is the merge bar.
- `gh pr checks --watch` until green; a red job is yours to fix and re-push (CI makes no live
  vendor calls — fixtures only).

### 6. Independent review (on the open PR)

Spawn a **reviewer subagent** (and/or the `engineering:code-review` skill) against
`git diff main...HEAD`. Review focus: parser robustness on hostile/degenerate blocks (size caps
enforced pre-parse, no quadratic scans, unknown keys rejected, numeric clamps); active-run race
(constraint + IntegrityError path actually tested); key-leak surfaces (run rows, logs, task args,
audit `data_after`, exception strings); permission matrix (soft-deleted strategy 404, non-owner
private strategy 404, system strategy visible, non-MFA 403, runs strictly owner-scoped); degraded
honesty (counts always populated, no silent truncation); FMP-call budget (exactly one screener call
per run, enrichment ≤ limit — assert via FakeHttp call counts); renderer regression risk on
existing descriptions (unclosed-tag fallback); i18n completeness for every §9 error code; OpenAPI
snapshot/type drift; migration cleanliness (`--check` green); no `" 2"` files or `*.bundle` staged.
Address all MEDIUM+ findings, re-run the gauntlet, push fixes, append the review narrative to the
PR description (recorded self-review — the solo-dev DoD allows this).

### 7. Merge + sync main

- Re-confirm `gh pr checks` green after the last push, then
  `gh pr merge --squash --admin --delete-branch`.
- If `--admin` is blocked: leave the PR open, record the exact finishing command as the top manual
  step in Section B, and continue to close-out.
- `git checkout main && git pull origin main` — then verify: `git log --oneline -1` is the squash
  commit of this PR, `git status --porcelain` shows nothing tracked, and
  `git branch --list feature/m16-strategy-screener` is gone (delete it if `--delete-branch` left a
  local copy).

### 8. Close out

- Tag locally on the merge commit: `git tag -a v0.16.0-screener -m "M16 strategy screener"`.
  **Do NOT push the tag** (operator-gated convention). Note for Section B: Railway auto-deploys
  `main` on merge — M16's migrations are additive and safe; the feature activates only once an FMP
  key is configured (Settings → Data Providers, staff + MFA — `make promote-owner EMAIL=…` first
  if no staff account exists yet).
- On `main`, a small `docs:` commit (pushed): flip the M16 rows in `project-plan/PROGRESS.md`
  (Where-the-project-stands table + a dated Last-verified entry with the gauntlet evidence and the
  merge SHA; demote the previous entry to Prior) and `project-plan/README.md` (milestone table —
  Spec → shipped wording), referencing PR number + `project-plan/M16-EXECUTION-REPORT.md`.
- Finish `project-plan/M16-EXECUTION-REPORT.md` and print the same content as your final message.

## FINAL REPORT — exactly two top-level sections

### Section A — What was implemented

- Branch, PR URL + number, merge status (squash SHA on `main` / or "PR open" + the finishing
  command), local-only tag, post-merge `git log --oneline -1` of `main`.
- AC coverage table: AC-16-1…AC-16-12, each **Met** (proving test) / **Deferred-live** (why —
  expected only for AC-16-12's live half) / **Not done** (why + impact).
- Inventory: parser module + grammar decisions taken autonomously; `company_screener` + fixture
  provenance (web-verified or spec-contract); models + both migrations; endpoints + full error-code
  list; task limits + queue; flag/throttle/audit/metrics; frontend files (component/facade/api/
  models/specs) + renderer change; i18n key groups; guide + catalog entry; ADR-063; CHANGELOG/
  PROGRESS/README updates; gauntlet outputs (exact counts per gate, and whether the pg lane ran
  locally or was left to CI).

### Section B — Manual user steps & follow-ups (the human to-do list)

Lead with: what the merge auto-deployed and that activation requires an FMP key in
Settings → Data Providers (plus the staff-promotion one-liner if still needed). Then: the live
AC-16-12 re-validation if it was deferred, the unpushed tag, anything parked under the blocker
policy, and every decision taken autonomously.
