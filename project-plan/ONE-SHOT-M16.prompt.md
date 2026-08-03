# ONE-SHOT PROMPT — Implement StratTraderPro Milestone M16 (Strategy Screener, autonomous) — v2

> Paste everything below the line into Claude Code CLI (max effort), running from the repo root
> `~/Documents/Claude/Projects/StratTraderPro`. It is self-contained and designed to run end-to-end
> **without human input**, through land-the-dependency → implement → gauntlet → commit → push → PR →
> CI → review → squash-merge to `main` → local `main` sync. Operator decisions already made:
> **admin-merge PRs autonomously**; on a hard blocker, **park it, document it, and finish everything
> else best-effort** (do not halt the run — the exceptions are Phase 0's enumerated stop rules,
> each of which still ends with the full two-section report).
>
> **v2 (2026-08-03) supersedes the v1 committed in `1baaac9`.** What changed: the spec was reviewed
> line-by-line against the codebase on 2026-08-03; nine findings are folded in below as SPEC
> AMENDMENTS A1–A9 (they are corrections, and they override the spec on exactly those points). The
> Phase-0 landing state was re-verified the same day: branch tip `8f25d3b`, `origin/main` at
> `aa16811`, merge simulation clean except `CHANGELOG.md`. The FMP screener params were also
> re-checked against the live docs page (see the web-check note).

---

## MISSION

Implement **Milestone M16 — Strategy Screener** of StratTraderPro (Django 5 + Angular 19 trading-bot
monorepo), end to end, on its own branch, through PR → review → merge → local `main` sync.

**The authoritative spec is `project-plan/16-strategy-screener.md` AS AMENDED by §SPEC AMENDMENTS
below.** The spec defines scope, AC-16-1…AC-16-12, the `[screen]` block grammar and its exact
key→FMP-param mapping table (§6.1), the one new vendor endpoint (§6.2), the `ScreenRun` model
(§6.3), the pipeline task (§6.4), the API ladder with error codes (§6.5), the frontend panel states
(§6.6), flags/throttle/audit (§6.7), metrics (§6.8), the guide (§6.9), test plan §10, security §11,
rollback §15, and the Exit Gate Checklist §17. Read every section yourself — do **not** trust this
prompt's summaries over the spec or the code. Precedence: **amended spec > spec > this prompt's
prose**. A1–A9 are the complete list of deliberate deviations; do not invent others. As part of
your docs commit you MUST also patch `project-plan/16-strategy-screener.md` itself per A1–A9 so
the shipped spec matches the shipped code (each amendment names its spec locations).

**Two decisions are frozen in the spec's provenance note — do NOT revisit them autonomously:**
(1) screening criteria come from a deterministic `[screen]` block inside the strategy description —
no LLM extraction, no separate criteria editor; (2) the screen runs on the **instance** FMP key via
`apps.marketdata.keys.resolve_key` (ADR-062) — there are no per-user vendor keys.

The spec's "Duration: 4 working days" is a planning label, not a constraint. Use subagents freely
(parser/backend/frontend implementers + a dedicated reviewer), but land everything in **one**
milestone PR (Phase 0's dependency PR is separate and comes first).

## WHAT "AUTONOMOUS" MEANS HERE (non-negotiable)

- **Never stop to ask the user anything.** If a decision isn't covered by the amended spec or this
  prompt, choose the safest reversible option, proceed, and log it in the final report (Section B,
  "decided autonomously").
- **Deferred-live set for M16** (expected, not failures): **AC-16-12's live half** — re-validating
  the FMP company-screener wire shape with a real key. If `resolve_key("FMP")` on this machine (or
  in the local DB) is empty, record the live re-validation as a Section-B manual step, per the
  spec's deferred-external convention (M06 precedent). Everything else in M16 is provable locally
  against fixtures.
- **Web check, then fixtures:** before writing `company_screener()`, attempt to verify the current
  param/field names via web fetch of the FMP stable docs
  (`https://site.financialmodelingprep.com/developer/docs/stable` → Company Search → Stock
  Screener; endpoint `…/stable/company-screener`). **On 2026-08-03 the page rendered and confirmed
  these params:** `marketCapMoreThan`, `priceMoreThan`, `volumeMoreThan`, `betaMoreThan`,
  `dividendMoreThan`, `sector`, `industry`, `exchange`, `country`, `isEtf`, `isActivelyTrading`,
  `limit`. The `*LowerThan` halves were not visible and remain documented-contract-to-verify. If
  your own fetch fails, you may rely on that recorded confirmation for the confirmed set; either
  way, pin the full §6.1 mapping in fixtures and record provenance (web-confirmed vs
  spec-contract) per param family in ADR-063. Do not invent additional params.
- **Hard blocker policy = park and continue.** If a component cannot reach green, park it —
  parking means **setting `SCREENER_ENABLED`'s default to `False` in `base.py`** (record this as
  an explicit extra deviation in the spec patch + Section B). Never merge broken default-on code:
  `main` auto-deploys.
- **Bounded waits.** Never wait indefinitely on an external system. Poll `gh pr checks` with a
  ~60-minute deadline per PR; on expiry, treat it as the CI-cannot-green path (leave that PR open
  + report — see Phase 0/5), never as a fix-forward loop.
- **CI red for causes outside your diff** (a new dependency advisory failing pip-audit/osv-scanner
  on unchanged pins, GitHub/Actions infra failure) is NOT yours to fix: do not bump pins, do not
  weaken gates, do not merge red. Leave that PR open, name the failing job + cause in Section B,
  and continue with whatever later phases remain meaningful.
- **Re-run / resume:** if a prior partial run left state (0a already committed, existing
  `feature/m16-strategy-screener` branch, open PR), do not redo completed steps — verify each
  phase's end-state and continue from the first incomplete one. Destructive steps (merges,
  `git rm`, the tag) must never run twice.
- **Keep a running report file** `project-plan/M16-EXECUTION-REPORT.md` updated as you go, so a
  partial report survives an interrupted run. Every way this run can end — including Phase-0's
  halt and every leave-the-PR-open path — still emits the FINAL REPORT's two sections, with the
  ending reason as Section A's first line.

## SPEC AMENDMENTS (2026-08-03 review — verified against code; these OVERRIDE the spec)

Each amendment states the code requirement and the spec location(s) to patch in your docs commit.

- **A1 — MFA sweep does NOT auto-cover the new paths.** AC-16-9's parenthetical ("the `strategies`
  prefix sweep … covers the new paths unchanged") is **false**: `apps/users/test_mfa.py::
  test_all_protected_prefixes_have_mfa_gate` walks a hardcoded `scaffold_paths` list, one
  representative URL per prefix — it never touches `…/screen/…`. Requirement: add the row
  `("strategies", "00000000-0000-0000-0000-000000000000/screen/criteria/")` to `scaffold_paths`
  (DRF runs permissions before object lookup, so the nil UUID cleanly yields 403 `MFA_REQUIRED`).
  Patch spec: AC-16-9 and §10.2's "sweep already covers the prefix" line.
- **A2 — GDPR export must include screener runs.** `backend/apps/users/gdpr.py` enumerates
  per-user tables by hand (see `backtests.json` from `BacktestRun.objects.filter(user=user)` — the
  direct precedent); the spec never adds `ScreenRun`, so exports would silently omit user data.
  Requirement: add `"screen_runs.json": _serialize_qs(ScreenRun.objects.filter(user=user))` (local
  import, matching the file's style), a manifest line (`screen_runs.json   Strategy screener
  runs`), and a `test_gdpr.py` assertion that the file appears and contains a seeded run. Patch
  spec: §8 Data Model Changes (note the export surface) and §10.2.
- **A3 — Flag-off error code is `FEATURE_DISABLED`, not `SCREENER_DISABLED`.** House convention —
  regime, sentiment and strategies return `fail("FEATURE_DISABLED", …, status=503)`; webhooks
  returns the same code + 503 via its own JsonResponse helper (it's a non-DRF public endpoint).
  Requirement: flag-off returns 503 `FEATURE_DISABLED` with message "Strategy screener is
  disabled."; the gate reads `apps.admin_portal.flags.is_enabled("SCREENER_ENABLED")` (mutable
  registry override honored, matching `apps/strategies/views.py::_enabled`) and applies to
  **every** screener endpoint — the criteria GET and run GETs included, not just POST (§6.6 state
  1 "panel hidden" is only observable if the GETs 503 too). The panel hides on HTTP 503 from the
  screener endpoints regardless of code. `SCREENER_DISABLED` is removed from the error-code list.
  Patch spec: AC-16-11, §6.5 (POST ladder AND a note that the flag gates all rows), §9 code list.
- **A4 — Degrade path must cover outages and per-symbol 4xx, not just rate limits.** §6.4 step 3
  names only `FMPRateLimited`/`FMPCircuitOpen`, but AC-16-7 promises "rate-limit/**outage** …
  degrades". Requirement, mid-enrichment: on `FMPRateLimited` or `FMPCircuitOpen` → stop fetching,
  count the raising symbol plus the unfetched remainder as `skipped_rate_limited`,
  `degraded=true` (spec behavior); on `FMPServerError` (outage with cold cache) → stop fetching,
  count the raising symbol plus the unfetched remainder as `skipped_unavailable`,
  `degraded=true`; on bare `FMPError` (4xx for ONE symbol — bad/delisted ticker) → skip that
  symbol only, count it in `skipped_unavailable`, continue, `degraded=true`.
  The `counts` dict gains `skipped_unavailable` everywhere counts are enumerated (model comment,
  §9 example, degraded-chip counts line, tests). The vendor *screener call* failing with no cache
  still FAILs the run (spec §6.4 step 2, unchanged). Patch spec: §6.4 step 3, §6.3 counts comment,
  AC-16-7, §9, §6.6 state 5.
- **A5 — Do not promise read-through caching.** `FMPClient.get()` is fetch-always; the cache is
  consulted **only in the failure path** (verified in `apps/marketdata/fmp.py`). A re-run within
  24h re-spends ~1+limit vendor calls on healthy days; the real quota bounds are the 10/h throttle
  and the ≤100 enrichment cap. Requirement: keep `daily_bars` + `upsert_bars` as spec'd (upserts
  feed M06A), but write the guide/§6.9 quota note, AC-16-5's parenthetical, and the §16 mitigation
  honestly ("failure-fallback cache", not "24h cache dedupe"). No store-first read in v1 (out of
  scope — say so in ADR-063 futures). Patch spec: AC-16-5 wording, §2's "cached 24h" phrase,
  §6.4 step 3's "(24h cache; …)" parenthetical, §6.9 quota note, §16 row 3.
- **A6 — Metrics only; no Grafana wiring.** ADR-109 (PR #50, on `main`) deleted the Data Pipelines
  dashboard and reduced Grafana to the 3-dashboard safety core; the spec's "System Health
  dashboard's Data Pipelines row" no longer exists (and was never a System-Health row). Requirement:
  ship §6.8's `screen_runs_total{result}` counter + `screen_run_duration_seconds` histogram and
  stop there; note in ADR-063 that dashboard panels are a future ADR-109-scope decision. Patch
  spec: §6.8 last sentence, §12.
- **A7 — Rename `criteria_sha256` → `desc_sha256`; run detail includes `criteria`.** The field
  stores the DESC `StrategyFile.sha256`, not a criteria hash — the spec's name is a misnomer.
  Requirement: model field, serializer, API payload key, tests and frontend models all use
  `desc_sha256`; `GET …/screen/runs/{id}/` also returns the stored `criteria` snapshot object
  (reproducibility visible; cheap). Patch spec: §6.3 model, §9 example (AC-16-6 already says
  "the DESC file's sha256" — nothing to rename there).
- **A8 — Poll cadence is a deliberate 2s, not a backtest precedent.** Backtest detail's `POLL_MS`
  is 5000 and is a WS-down fallback. Keep 2s for the screener (runs are seconds-to-a-minute; GETs
  are cheap), stop on terminal status and on component destroy — but the spec must stop citing the
  backtest cadence. Patch spec: §6.6 state 5.
- **A9 — `isEtf` is always sent.** Mirror `isActivelyTrading=true` (always sent): send
  `isEtf=false` unless `etf: true`. This is the deterministic-narrowing reading of §6.1's "default
  `false`" and removes the ambiguity where §9's example omits it. Patch spec: §9 `fmp_params`
  example (add `"isEtf": false`), §6.1 table note.

## GROUND TRUTH — read these first, in this order, before writing any code

1. `project-plan/PROGRESS.md` — canonical status. The 2026-08-01 "Last verified" entry records
   ADR-062 (the dependency this milestone gates on) and this spec's creation.
2. `project-plan/16-strategy-screener.md` — **the spec.** Read every section, then re-read A1–A9.
3. `docs/adr/062-data-provider-keys-in-db.md` (the key gate you consume) and
   `docs/adr/061-data-vendor-fmp.md` **§4** (the vendor-change gate: new FMP endpoint ⇒ ADR-063 +
   fixture tripwire + live re-validation when a key lands).
4. `project-plan/README.md` (cross-cutting conventions, DoD, milestone table) and
   `CONTRIBUTING.md` (branch naming, conventional commits, squash-merge, PR flow).
5. `.github/workflows/ci.yml` — the exact CI gates — and `.github/pull_request_template.md` — the
   DoD checklist the PR must fill in.
6. Reuse targets — read before implementing against them:
   - `backend/apps/marketdata/{keys.py,fmp.py,models.py,services.py,metrics.py,test_provider_keys.py}`
     — `resolve_key`, the FMP resilience stack (`get()` + token bucket + breaker + cache-FALLBACK),
     `upsert_bars(symbol, tf, rows)`, the fixture/FakeHttp test style.
   - `backend/apps/backtest/{models.py,tasks.py,urls.py,views.py}` — the async-run precedent:
     status enum + `celery_task_id`, per-task `soft_time_limit`/`time_limit` overrides, run
     list/detail URL shape.
   - `backend/apps/strategies/{models.py,views.py,permissions.py}` — `StrategyFile` (Kind.DESC,
     BinaryField `content`, `sha256`), `can_user_view(user, strategy)`, the
     `deleted_at__isnull=True` soft-delete filter every strategy lookup applies, and
     `_feature_disabled()` (the FEATURE_DISABLED 503 you mirror per A3).
   - `backend/apps/users/{responses.py,permissions.py,test_mfa.py,views.py,gdpr.py}` —
     `ok()/fail(code, message, *, status, details=None)`, `IsAuthenticatedAndMFAEnforced`, the MFA
     sweep test you extend per A1, the `ratelimit(key=…, rate=…, method="POST", block=False)(
     View.as_view())` wrap + `getattr(request, "limited", False)` → 429 pattern (RegisterView /
     LoginView — find them by name, not line number), and the GDPR export you extend per A2.
   - `backend/apps/audit/{events.py,services.py}` + `backend/apps/admin_portal/flags.py` — `emit()`
     signature, `AuditEventType` naming (`strategy.created` style; ADR-062 added the choices
     migration `audit/0007` — you will generate `0008`), `is_enabled()`.
   - `backend/config/{urls.py,settings/base.py}` — mount points (`api/v1/strategies/` include at
     the top level), `FEATURE_FLAGS_REGISTRY` + `_flag()`, `CELERY_TASK_SOFT_TIME_LIMIT=30`
     default, `INSTALLED_APPS`.
   - `frontend/src/app/features/settings/data-providers/data-providers.component.ts` (+`.spec.ts`),
     `abstraction/facades/data-providers.facade.ts`, `core/services/data-providers.api.ts` — the
     freshest full-stack precedent (facade-only pattern, `Result<T>`, error mapping, spec style
     with facade stubs) — the facade's nullable `keys` signal (type in
     `core/models/data-providers.models.ts`) gives `keys()?.fmp.configured` for the §6.6 state-4
     pre-check.
   - `frontend/src/app/features/strategies/detail/strategies-detail.component.ts` — where the
     panel embeds; how DESC is fetched.
   - `frontend/src/app/core/util/tradingview-description.ts` (+`.spec.ts`) — the escape-first
     whitelist renderer you extend with the `[screen]` swallow rule. Follow the `[pine]`
     special-case's *shape* (regex interception before the generic tokenizer) but NOT its
     unclosed-tag behavior: unclosed `[pine]` swallows to end-of-input, whereas unclosed
     `[screen]` MUST fall back to strip-keep-text and never eat the rest of the description.
   - `frontend/src/app/features/guides/guides.catalog.ts` + `scripts/check_guides_catalog.py` —
     the both-directions CI guard for the new guide.
   - `frontend/src/assets/i18n/en.json` — flat per-feature roots; add `screener.*`.

## PROJECT-SPECIFIC GUARDRAILS (hard-won; violating these wastes hours)

Carried over (all still true):

- **Local CI-parity gauntlet is the merge bar** — `pytest` + `tsc` is NOT enough; CI also runs
  `ruff`, `bandit`, both pytest lanes, karma (`pnpm test:ci`), `pnpm build`, the a11y Playwright
  job, dependency audits, and the guard scripts. Green gauntlet before every push.
- **Angular template errors need `ngc`, not `tsc`:** `pnpm exec ngc --noEmit -p tsconfig.app.json`
  from `frontend/`.
- **Frontend gate is `pnpm`** (corepack; `packageManager` pins `pnpm@10.33.4`;
  `pnpm install --frozen-lockfile` must be a lockfile no-op).
- **Settings star-import drops `_`-prefixed names** — any new settings helper must be
  non-underscore or explicitly re-imported in `dev.py`/`prod.py`; the prod-import smoke below
  catches it.
- **Working-tree junk:** the tree may contain untracked Finder duplicates (names containing
  `" 2"`) and a `_to_delete/` folder at the repo root (contains a spent review bundle — ignore it,
  never stage it, never delete it). **NEVER `git add -A` / `git add .`** — stage explicit paths
  only.
- **UTC crontabs / no glob Celery routes** (M09 rule). M16 adds NO beat entries and NO route
  entries — the screener task rides the default queue.
- **No new dependencies**, backend or frontend. `requirements/*.txt` and `pnpm-lock.yaml` must be
  byte-identical after this milestone. Parser is stdlib; SMA/52w math is plain Python (numpy is
  already pinned if you want it — do NOT reach for pandas).

M16-specific (these encode the spec's trickiest failure modes — treat as required):

- **Never read `settings.FMP_API_KEY` directly.** The gate and the client key are
  `apps.marketdata.keys.resolve_key("FMP")` (UI key → env → ""), re-checked inside the task
  (the key can be removed between enqueue and execution → run FAILED `FMP_NOT_CONFIGURED`).
- **Active-run race hardening (required addition beyond the spec's 409):**
  `UniqueConstraint(fields=["user", "strategy"], condition=Q(status__in=["QUEUED", "RUNNING"]),
  name="uniq_active_screen_run_per_user_strategy")` on `ScreenRun`, with run-creation wrapped so an
  `IntegrityError` returns the same 409 `SCREEN_RUN_ACTIVE`. (Partial unique indexes work on both
  SQLite and Postgres; test the pre-check path AND the constraint path.)
- **Celery default soft limit is 30s** (`CELERY_TASK_SOFT_TIME_LIMIT`) — the screener task MUST set
  `soft_time_limit=240, time_limit=300` on its own decorator (backtest precedent) or a
  50-candidate enrichment dies mid-run. `bind=True, ignore_result=True`, task arg is `run_id` only.
- **DESC bytes → text:** decode `bytes(file.content)` as UTF-8 with `errors="replace"`; apply the
  §6.1 size/line caps BEFORE parsing; at most one block (`duplicate_block` error). Linear scan
  only — no backtracking-prone regex over user text (§11). DESCs can be up to 256KB since #49 —
  the scan must stay O(n).
- **Soft-delete:** every strategy lookup in the screener views filters `deleted_at__isnull=True`
  (match `apps/strategies/views.py`) and applies `can_user_view` → 404 (`STRATEGY_NOT_FOUND`),
  never 403, for invisible strategies.
- **Parser fixtures must mirror REAL TradingView exports** (the #45 lesson): licence-header
  lead-in, CRLF line endings, UTF-8 BOM, block mid-prose, BBCode around the block. A
  synthetic-only fixture set is a spec violation (§10.1).
- **Renderer swallow rule:** `[screen]…[/screen]` drops the tag AND inner text (unlike the default
  strip-keep-text); an **unclosed** `[screen]` falls back to strip-keep-text and must never eat the
  rest of the description. Extend `tradingview-description.spec.ts` for both.
- **New-app scaffolding checklist** for `backend/apps/screener/`: `__init__.py`, `apps.py`
  (`name = "apps.screener"`), `migrations/__init__.py`, add `"apps.screener"` to `INSTALLED_APPS`
  in `config/settings/base.py`, THEN `python manage.py makemigrations screener`. Adding
  `AuditEventType.SCREEN_RUN_REQUESTED = "screener.run_requested"` changes `AuditLog.event_type`
  choices — `makemigrations audit` will emit `0008_alter_auditlog_event_type` (expected; commit
  it).
- **URL mount:** in `config/urls.py`, add
  `path("api/v1/strategies/<uuid:strategy_id>/screen/", include("apps.screener.urls"))`
  **above** the `api/v1/strategies/` include, so the literal `screen/` segment can never be
  shadowed. Then apply A1's sweep row and run `apps/users/test_mfa.py` to prove the gate.
- **Ratelimit house pattern:** `django_ratelimit` with `block=False` + explicit
  `getattr(request, "limited", False)` → 429 `RATE_LIMITED` (see the RegisterView wrap in
  `apps/users/views.py`); `RATELIMIT_ENABLE=False` in test settings keeps the suite hermetic — the
  throttle test itself uses `override_settings(RATELIMIT_ENABLE=True)`.
- **Key-leak surfaces:** the FMP key must never appear in `ScreenRun` rows, task args, log lines,
  audit rows, or exception strings (the client already redacts transport errors — don't undo
  that).
- **OpenAPI regen ORDER:** regenerate the schema + types BEFORE the final karma/build runs —
  `frontend/src/app/core/models/auth.models.contract.spec.ts` imports the generated
  `core/generated/schema.ts`, so a post-test regen invalidates your karma evidence. Commands
  (docker-free equivalents of `make schema`):
  `cd backend && DJANGO_SETTINGS_MODULE=config.settings.test python manage.py spectacular --file ../docs/openapi/openapi.json`
  then `cd ../frontend && pnpm run schema:types`.
- **Guide + catalog move together** (`scripts/check_guides_catalog.py` fails on drift in BOTH
  directions), and it also verifies referenced screenshots exist — write the `strategy-screening`
  guide **without `<img>` references** (text + tables + code samples) unless you also generate real
  screenshots via `frontend/tools/guide-screenshots.mjs`.
- **Deterministic ranking:** §6.4's rank order with ties broken by symbol; the §10.5
  reproducibility test asserts byte-identical `results` JSON on identical inputs.
- **i18n:** new flat `screener.*` root in `en.json` (panel states, table headers,
  `screener.error.<CODE>` for every code that can surface in the panel: `FMP_NOT_CONFIGURED`
  (copy points at Settings → Data Providers), `NO_SCREEN_CRITERIA`, `SCREEN_CRITERIA_INVALID`,
  `SCREEN_RUN_ACTIVE`, `RATE_LIMITED` (the 429 an 11th run-click per hour surfaces),
  `FMP_RATE_LIMITED`, `FMP_UNAVAILABLE`. `FEATURE_DISABLED` needs no screener copy — the panel
  hides on 503). Karma specs assert raw keys (no loader in tests).

## WORKFLOW — execute in this exact order

### 0. Land the dependency (every legitimate early stop lives here — each with the two-section report)

**State as verified 2026-08-03:** the repo sits on `feat/data-provider-keys-ui` @ `8f25d3b`
(ADR-062 code + M16 spec + ADR-109 doc fixes), NOT pushed, NOT merged; `origin/main` was
`aa16811`. A `git merge-tree` simulation of `origin/main` into the branch tip showed **exactly one
conflict: `CHANGELOG.md`** (PROGRESS.md auto-merges). Re-verify all of this — states drift.

```bash
cd ~/Documents/Claude/Projects/StratTraderPro
git fetch origin
git status --porcelain     # untracked junk + _to_delete/ fine; see 0a for THIS file
git log --oneline -1       # expect 8f25d3b on feat/data-provider-keys-ui (or later — adapt, don't halt)
```

Tracked changes other than `project-plan/ONE-SHOT-M16.prompt.md`: leave them untouched — do NOT
stash, commit, or check them out. If they block 0b's merge, END the run with the two-section
report naming the files (Section B top step: operator resolves the dirty tree, then re-runs).

**0a. Self-persist this prompt (non-destructive, resume-safe).** The house convention is that
one-shot prompts are tracked with the work they drive. While still on `feat/data-provider-keys-ui`,
inspect `project-plan/ONE-SHOT-M16.prompt.md` in the tree:

- Tree copy is **v2** (title line contains "— v2" / file contains "SPEC AMENDMENTS (2026-08-03"):
  keep the tree copy exactly as-is — the v2 file was delivered to disk on 2026-08-03 and is the
  canonical text even if it differs cosmetically from your pasted copy. Commit it if uncommitted:
  `git add project-plan/ONE-SHOT-M16.prompt.md && git commit -m "docs(plan): ONE-SHOT-M16 v2 — fold 2026-08-03 spec-review amendments A1-A9"`.
  Already committed → skip entirely.
- Tree copy is still **v1** (372-line version, no SPEC AMENDMENTS section): overwrite it with the
  full prompt you were given (restore the `# ONE-SHOT PROMPT … — v2` title line if your paste
  began below it), then commit as above.
- Tree copy is neither (operator-edited): keep the tree copy, commit it as-is, and note the
  divergence in Section B. Never discard operator edits.

After 0a the tree must have NO tracked changes.

**0b. Decide the landing path:**

1. If ADR-062 is already merged (check: `git log origin/main --oneline | head -20` contains the
   data-provider-keys squash, or `backend/apps/marketdata/keys.py` exists on `origin/main` —
   `git cat-file -e origin/main:backend/apps/marketdata/keys.py`): skip to step 0-final.
2. Else if local branch `feat/data-provider-keys-ui` exists (expected): land it now.

   ⛔ **It will NOT merge as-is** — reconcile with `main` first:

   ```bash
   git checkout feat/data-provider-keys-ui
   git merge origin/main
   # CHANGELOG.md is the ONLY expected conflict — both [Unreleased] sections diverged.
   # Resolve by KEEPING BOTH sides' section headings and bullets. Known trap: the branch removed
   # main's "### Added — Guides tab…" heading and re-homed its bullets; after resolving, read the
   # merged [Unreleased] top-to-bottom and ensure every heading appears once and every bullet
   # appears exactly once (de-duplicate the guides bullets). Do not drop the ADR-109 entries.
   git add CHANGELOG.md && git commit --no-edit
   # De-duplicate: main added project-plan/ONE-SHOT-OBSERVABILITY-OPERATOR.prompt.md; this branch
   # archived the same document (with a provenance header) at project-plan/archived/.
   # Guard: diff them first — if the loose copy gained post-aa16811 edits, fold those into the
   # archived copy before removing.
   git diff --no-index --stat project-plan/ONE-SHOT-OBSERVABILITY-OPERATOR.prompt.md project-plan/archived/ONE-SHOT-OBSERVABILITY-OPERATOR.prompt.md || true
   git rm project-plan/ONE-SHOT-OBSERVABILITY-OPERATOR.prompt.md
   git commit -m "docs(plan): drop loose observability one-shot duplicate (archived copy is canonical)"
   git merge-tree --write-tree origin/main HEAD >/dev/null && echo MERGEABLE
   ```
   Any conflict other than `CHANGELOG.md` is not the expected shape — stop and inspect before
   resolving it (inspect ≠ halt: resolve conservatively, document in Section B).

   ⚠️ **Re-run a gauntlet on the merged tip — do NOT trust the 2026-08-01 green.** The branch tip
   has moved (docs commits `21cddf3`, `1baaac9`, `8f25d3b`, your 0a commit, the merge). All are
   docs-only so expect green, but prove it. Minimum: backend `pytest`,
   `python manage.py makemigrations --check --dry-run`, `pnpm build`.

   ⚠️ **Scope note — put this in the PR body.** This PR lands ADR-062 **and** everything else on
   the branch: run `git log --oneline $(git merge-base origin/main HEAD)..HEAD` and inventory it in
   the PR description (ADR-062 backend/frontend/docs, M16 spec, ADR-109 doc fixes + operator
   report, archived prompts, this v2 prompt, the de-dup). State it rather than letting a reviewer
   discover it.

   Then: `git push -u origin feat/data-provider-keys-ui`; write the scope-note inventory to a
   temp file and
   `gh pr create --base main --title "feat(marketdata): instance FMP/FRED data-provider keys (ADR-062) + M16 spec" --body-file <that file>`;
   watch `gh pr checks` (≤60 min; a red job whose cause is IN this diff is yours to fix forward);
   `gh pr merge --squash --admin --delete-branch`; `git checkout main && git pull origin main`.

   **Phase-0 failure ladder (this dependency PR gets the same mercy as Phase 7):** if the push,
   PR creation, CI (external-cause red or deadline expiry), or the `--admin` merge cannot
   complete — do NOT bump pins, weaken gates, or merge red. Leave the dependency PR open and END
   the run with the two-section report: Section A's Phase-0 outcome = "ADR-062 PR open at <url>,
   CI <state>", Section B's top step = the exact finishing command
   (`gh pr merge <num> --squash --admin --delete-branch && git checkout main && git pull`), and
   note that M16 implementation never started. Do NOT proceed to Phase 1 on an unmerged
   dependency, and do NOT use the step-3 HALT message for this case — it is reserved for the
   branch-actually-missing state.
3. Else **HALT** and report (two-section format, this as Section A's first line): "M16 blocked —
   ADR-062 (`feat/data-provider-keys-ui`) is not on main and the branch is missing. Land the
   data-provider-keys work first." (The delivery bundle for this branch was applied and deleted
   on 2026-08-03 — if the branch is gone, something external happened; do not guess.)

**0-final:** on `main`, freshly pulled, verify
`git cat-file -e origin/main:backend/apps/marketdata/keys.py && test -f project-plan/16-strategy-screener.md && echo PRECONDITIONS-OK`.
No `PRECONDITIONS-OK` → HALT with the step-3 message.

### 1. Branch

`git checkout -b feature/m16-strategy-screener` (from the fresh `main`).

### 2. Plan

Turn spec §6.1–§6.9 + §14 + A1–A9 into a todo list before coding. Implementation order that
respects the dependencies: §6.1 parser (+ §10.1 tests) → §6.2 `company_screener` (+ contract
fixture) → §6.3 app scaffold + model + constraint + migrations (screener 0001, audit 0008) → §6.4
task (A4 semantics) → §6.5 API + A1 sweep row → §6.7 flag/throttle/audit (A3) → §6.8 metrics (A6)
→ A2 GDPR export → OpenAPI regen → §6.6 frontend (models/api/facade/panel + specs, renderer
swallow rule + specs, A7/A8) → §13 i18n → §6.9 guide + catalog → §14 docs (ADR-063, runbook
paragraph, CHANGELOG `[Unreleased]`, spec patched per A1–A9).

### 3. Implement

To the amended spec, with the GUARDRAILS above. Frontend follows the house 3-layer pattern
(component → facade → api; components never inject `*.api.ts`), standalone + OnPush + inline
template, reactive forms where forms exist, design-system components (`app-card`, `app-button`
with `(clicked)`, `app-status-chip`, `app-empty-state`, `app-help-link`), Tailwind token classes
only (no raw hex). Poll the active run every 2s until terminal; stop on destroy (A8).

### 4. Verify locally — CI-parity gauntlet (GREEN before pushing)

```bash
# ---- backend (repo venv: backend/.venv/bin/… or ../.venv/bin/… — whichever this machine uses;
#      if neither exists: python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements/dev.txt, note it in the report)
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
  python -m pytest -m pg --tb=short -q              # host port 5434 — see docker-compose.yml

# ---- OpenAPI (BEFORE the frontend gates — see guardrail)
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py spectacular --file ../docs/openapi/openapi.json

# ---- frontend
cd ../frontend
pnpm install --frozen-lockfile                      # must be a lockfile no-op
pnpm run schema:types
pnpm exec ngc --noEmit -p tsconfig.app.json
pnpm test:ci                                        # karma — all specs incl. yours
pnpm build
pnpm exec playwright test e2e/a11y                  # incl. your §10.3 panel a11y spec
#   (if Chromium is missing locally: pnpm exec playwright install chromium, then retry)

# ---- repo guards
cd ..
python3 scripts/check_guides_catalog.py
python3 scripts/check_envsubst_filter.py
```

Fix everything until green. **Do not push a red tree.** Do not weaken any existing CI gate or
test. CI additionally runs pip-audit and osv-scanner — the no-new-deps rule keeps those green
barring a brand-new advisory on unchanged pins, which is the external-cause case (see the
autonomy rules: leave the PR open + report, don't bump pins). When done:
`docker compose stop postgres` if you started it.

### 5. Commit, push, PR

- Conventional commits, logically grouped, explicit paths staged every time (never `git add -A`).
  Suggested shape: `feat(screener): [screen] parser + FMP company-screener client` →
  `feat(screener): ScreenRun model, pipeline task + API` → `feat(strategies): screening panel UI` →
  `docs(screener): ADR-063, guide, spec amendments A1-A9, changelog`.
- `git push -u origin feature/m16-strategy-screener`.
- `gh pr create --base main --title "feat(m16): strategy screener — [screen]-block driven FMP screening" --body-file <file>`
  — fill the **entire** PR-template DoD checklist; paste the AC-16-1…AC-16-12 coverage table
  (Met / Deferred-live, with proving test names) **plus a nine-row A1–A9 table** (each: applied
  where, proven how); include the gauntlet results; note that fork-PR approval is "all external
  contributors" and CI is the only enforced gate — which is why the gauntlet above is the merge
  bar.
- Watch `gh pr checks` (≤60 min); a red job caused by this diff is yours to fix and re-push (CI
  makes no live vendor calls — fixtures only). External-cause red or deadline expiry → the
  leave-PR-open path from the autonomy rules (record the finishing command; continue to Phase 8's
  PR-open branch).

### 6. Independent review (on the open PR)

Spawn a **reviewer subagent** against `git diff main...HEAD` with this focus list: parser
robustness on hostile/degenerate blocks (size caps enforced pre-parse, no quadratic scans, unknown
keys rejected, numeric clamps); active-run race (constraint + `IntegrityError` path actually
tested); A4 semantics (stop-and-count vs skip-one — both tested; counts always populated; no
silent truncation); key-leak surfaces (run rows, logs, task args, audit payloads, exception
strings); permission matrix (soft-deleted strategy 404, non-owner private strategy 404, system
strategy visible, non-MFA 403 — including the A1 sweep row actually failing before the fix and
passing after; runs strictly owner-scoped); FMP-call budget (exactly one screener call per run,
enrichment ≤ limit — assert via FakeHttp call counts); renderer regression risk (unclosed-tag
fallback; existing descriptions unchanged); A7 rename consistency (model, serializer, OpenAPI,
generated types, frontend models — no `criteria_sha256` stragglers); A9 golden mapping test;
i18n completeness for every §9 panel-surfaced code; A2 export content; OpenAPI/type drift;
migration cleanliness (`--check` green); no `" 2"` files, no `_to_delete/`, no `*.bundle` staged.
Address all MEDIUM+ findings, re-run the gauntlet, push fixes, append the review narrative to the
PR description (recorded self-review — the solo-dev DoD allows this).

### 7. Merge + sync main

- Re-confirm `gh pr checks` green after the last push (≤60 min), then
  `gh pr merge --squash --admin --delete-branch`.
- If `--admin` is blocked or CI can't green for external causes: leave the PR open, record the
  exact finishing command as the top manual step in Section B, and continue to close-out's
  **PR-open branch**.
- On merge: `git checkout main && git pull origin main` — verify `git log --oneline -1` is this
  PR's squash commit, `git status --porcelain` shows nothing tracked, and the local feature
  branch is deleted.

### 8. Close out — two branches, chosen by merge state

**If the M16 squash landed on `main`:**

- Tag locally on the merge commit: `git tag -a v0.16.0-screener -m "M16 strategy screener"`.
  **Do NOT push the tag** (operator-gated convention). Note for Section B: Railway auto-deploys
  `main` on merge — M16's migrations are additive and safe; the feature activates only once an
  FMP key is configured (Settings → Data Providers, staff + MFA;
  `make promote-owner EMAIL=…` first if no staff account exists).
- On `main`, a small `docs:` commit (pushed): flip the M16 rows in `project-plan/PROGRESS.md`
  (status table + a dated Last-verified entry with gauntlet evidence and the merge SHA; demote
  the previous entry) and `project-plan/README.md` (milestone table — Spec → shipped wording);
  update the spec's own header (`**Status:** Spec — not started` → `Implemented (PR #N,
  <date>)`) and tick §17's exit-gate checklist; stage `project-plan/M16-EXECUTION-REPORT.md` in
  this same commit so the tree ends clean.

**If the M16 PR (or the ADR-062 PR) is still open:** NO tag, NO shipped wording anywhere.
PROGRESS.md gets a dated entry "M16 PR #N open awaiting merge — finishing command: …" only if
you can push it without weirdness (on the open M16 PR's branch, put it in the PR body instead);
README stays at Spec. The execution report still gets finished and printed — as an untracked
file plus Section B instructions if there is no clean place to commit it.

- Either way: finish `project-plan/M16-EXECUTION-REPORT.md` and print the same content as your
  final message.

## FINAL REPORT — exactly two top-level sections

### Section A — What was implemented

- Phase-0 outcome: the ADR-062 PR (number, squash SHA), or "already landed", or "PR open at
  <url> + finishing command"; the merge-conflict resolution actually needed; the de-dup commit.
- M16: branch, PR URL + number, merge status (squash SHA / or "PR open" + finishing command),
  local-only tag, post-merge `git log --oneline -1` of `main`.
- AC coverage table: AC-16-1…AC-16-12, each **Met** (proving test) / **Deferred-live** (why —
  expected only for AC-16-12's live half) / **Not done** (why + impact).
- A1–A9 table: each amendment — code change, spec patch, proving evidence.
- Inventory: parser module + grammar decisions taken autonomously; `company_screener` + fixture
  provenance (web-confirmed vs spec-contract, per param family); models + both migrations +
  constraint; endpoints + full error-code list; task limits + queue + A4 semantics; flag/throttle/
  audit/metrics; GDPR export entry; frontend files + renderer change; i18n key groups; guide +
  catalog entry; ADR-063; CHANGELOG/PROGRESS/README/spec updates; gauntlet outputs (exact counts
  per gate, and whether the pg lane ran locally or was left to CI).

### Section B — Manual user steps & follow-ups (the human to-do list)

Lead with: what the merges auto-deployed and that activation requires an FMP key in
Settings → Data Providers (plus the staff-promotion one-liner if still needed). Then: the live
AC-16-12 re-validation if deferred, the unpushed tag (if created), anything parked under the
blocker policy (and that parking flipped `SCREENER_ENABLED`'s default to False), every decision
taken autonomously, and — if the folder is present — a pointer to delete `_to_delete/` at the
repo root (pre-existing review junk, never touched by this run).
