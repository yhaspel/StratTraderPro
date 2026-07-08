# M09 Execution Report — Walk-Forward Backtester

> Autonomous implementation run (2026-07-08). Two top-level sections:
> **A — What was implemented**, **B — Manual user steps & follow-ups**.

---

# Section A — What was implemented

## Branch / PR / merge / tag

- **Branch:** `feature/m09-walk-forward-backtester` (off `main` @ `b6f54db`) — merged + deleted.
- **PR:** [#28](https://github.com/yhaspel/StratTraderPro/pull/28) — ✅ **Merged** (squash, `--admin`) — merge commit **`afe6c24`**. All **5 CI checks green** (Backend, Frontend, E2E smoke, Guard-no-legacy-IBKR, Trivy). Recorded adversarial self-review on the PR; the 1 MEDIUM + cheap LOW findings fixed in `34f61c2` before merge.
- **Release tag (created locally, NOT pushed):** `v0.9.0-backtest` → `afe6c24`.

## AC coverage

| # | Status | Proving evidence |
|---|--------|------------------|
| AC-09-1 submit + §11 caps | **Met** | `test_api.ValidationTests` (no-adapter/step≠test/tf≠1d/<2 windows/>10 symbols/non-subset grid), `MakeCombosCapTests` (grid ≤ 500) |
| AC-09-2 dedicated queue + route + limits | **Met** / Railway service **Deferred-live** | `test_settings.CeleryRouteSettingsTests` (explicit route, no glob, eviction on default queue); `run_backtest` soft/hard 1500/1800; `worker-backtest` compose service |
| AC-09-3 vectorbt sweep, unit sizing, cost-aware rank | **Met** | `test_engine_extra.SweepMetricTests`; replay↔vectorbt zero-cost cross-check (exact, rel=0.00000) |
| AC-09-4 replay trades/slippage/commission/partials/same-bar | **Met** | `test_replay.ReplayGoldenTests` (entry/exit, stop, gap-through, target, stop-first, partial-cancel, force-close, commissions, force-close-while-filling) + `ReplayPropertyTests` |
| AC-09-5 OOS concat + segments | **Met** | `test_integration` (3 segments persisted), `test_windows` (contiguous, non-overlapping) |
| AC-09-6 metrics + PBO + stability | **Met** | `test_stats.StatsTests`, `test_pbo.PboTests`, integration `run.summary` |
| AC-09-7 PDF vector charts + disclaimer + PBO badge | **Met** | `test_report.ReportPdfTests` (%PDF), `ReportSvgTests` (selectable `<text>`), `ReportHtmlTests` (disclaimer + HIGH-overfitting badge); **PDF verified rendering inside the built Docker image** |
| AC-09-8 progress WS events | **Met** | `test_integration` (`backtest.progress` + `backtest.completed` emitted over `/ws/dashboard/`) |
| AC-09-9 cancellation ≤ 30 s | **Met** | `test_api.CancelTests`, `test_integration.test_cooperative_cancellation…`, `test_engine_extra.WalkForwardCancelTests` |
| AC-09-10 perf | CI smoke **Met** (1y/grid-12 ≈ 4 s ≤ 60 s) / staging 3y/10y/RSS **Deferred-live** | integration run time; grid chunking (≤ 100 combos); §B |
| AC-09-11 retention + eviction | **Met** | `test_eviction.EvictionTests` (expired nulled + metrics kept; fresh kept; custom retention) |
| AC-09-12 production-sizing parity | **Met** | `test_sizing_parity.SizingParityTests` (non-tautological: identical `_atr14`, field-by-field `SizingInputs` vs `apply_sizing`, qty via `compute_size`, `requested_qty` unread) |

**Exit-gate items:** ADRs 090–092 committed ✓ · runbook `backtest-stuck.md` ✓ · 3 help articles ✓ · Backtest Ops Grafana JSON ✓ (live-on-staging deferred) · CHANGELOG + PROGRESS + tracker ✓ · reproducibility hash (JIT + non-JIT) ✓ · sample WF PDF on the demo strategy generated (synthetic fixture — real-symbol needs the M06 FMP backfill) · tag created (push deferred).

## Inventory

- **Models + migration:** `BacktestRun`, `BacktestSegment`, `BacktestReport` (`backtest.0001_initial`, SQLite-compatible; indexes `(user,-created_at)` + `status` db_index + segment `unique_together`).
- **Engines/modules** (`apps/backtest/`): `data.py`, `strategies/` (`base` Protocol, `registry` `@register`, `sma_cross`, `seed_demo_strategy` command), `vbt_engine.py` (`SweepEngine` seam), `replay_engine.py`, `wf.py`, `pbo.py`, `stats.py`, `report.py` + `templates/backtest/tearsheet.html` + `templatetags`, `i18n.py` (report label dict), `exceptions.py`, `events.py`, `metrics.py`.
- **Endpoints** (`/api/v1/backtest/`): `GET strategies/`; `GET/POST runs/`; `GET runs/{id}/`; `POST runs/{id}/cancel/` (202); `GET runs/{id}/report.{json,html,pdf}`. **Error codes:** `BACKTEST_NO_ADAPTER`, `BACKTEST_INSUFFICIENT_DATA`, `BACKTEST_LIMIT_CONCURRENT` (409), `BACKTEST_GRID_TOO_LARGE`, `BACKTEST_REPORT_TOO_LARGE`, `BACKTEST_TIME_CAP`, `BACKTEST_DISABLED` (503), `VALIDATION_ERROR`.
- **Celery:** task `run_backtest` (routed to `backtest` queue, soft/hard 1500/1800); `evict_expired_artifacts` (default `celery` queue, own 600/900 limits); beat `backtest-evict-artifacts` @ 03:30 UTC; `CELERY_TASK_ROUTES` (explicit per-task, first in repo); compose service `worker-backtest`.
- **WS events:** `backtest.progress`/`completed`/`failed`/`cancelled` via `dashboard.events.push_to_user` (throttled ≥ 1 s).
- **Feature flag:** `BACKTEST_ENABLED` (env.bool, default **True**).
- **Frontend:** lazy `/backtest` + `/backtest/:id` (`canMatch: [authGuard]`); `backtest.api` → `backtest.store` (signals) → `backtest.facade` → standalone launcher + detail; **chart.js 4.5.1 + chartjs-chart-matrix 3.0.5** dynamically imported (own lazy chunk); `backtest.*` i18n; regenerated `schema.ts`.
- **New deps (backend pins):** `vectorbt==1.0.0`, `weasyprint>=68,<69`, `matplotlib>=3.8,<4.0`, `plotly>=5.18,<6.0` (resolved: numpy 2.1.3, pandas 2.2.3, numba 0.66.0, scipy 1.18.0, sklearn 1.9.0, matplotlib 3.11.0, plotly 5.24.1, weasyprint 68.1). **Frontend:** chart.js@4 + chartjs-chart-matrix.
- **Docs:** ADR-090/091/092, `docs/runbooks/backtest-stuck.md`, 3 help articles, `infra/grafana/backtest-ops-dashboard.json`, CHANGELOG `[Unreleased]`, PROGRESS + tracker.
- **Infra:** WeasyPrint apt deps in `docker/backend.Dockerfile` **and** `ci.yml`; `.dockerignore` (excludes `.venv`/caches/node_modules); regenerated `docs/openapi/openapi.json`.

## Local gauntlet + CI at merge

- `ruff check .` ✓ · `bandit … --severity-level medium` ✓ · **pytest 455 passed** (+4 subtests, SQLite) ✓ · `makemigrations --check` ✓ · prod-import star-import smoke ✓
- Frontend: `pnpm install --frozen-lockfile` ✓ · `ngc --noEmit` ✓ · `pnpm build` ✓ (initial 442.96 kB — under budget; backtest + chart.js lazy) · `pnpm run test:ci` **44 karma** ✓
- Docker: image builds ✓ (**2.35 GB** after `.dockerignore`) · PDF renders **inside the image** ✓ · **Trivy HIGH/CRITICAL clean** ✓ · `docker compose up` → `/healthz` 200 + `backtest.0001` applied on Postgres ✓
- **GitHub CI at merge: all 5 checks green.**

## Day-1 spike + key measurements

- `vectorbt==1.0.0` present on PyPI, resolves cleanly on Python 3.12 within the repo pins (numpy 2.1.3 < 2.2, pandas 2.2.3 < 2.3, numba 0.66). Import + sweep smoke OK; the fat transitive tree (scipy/sklearn/matplotlib/plotly/numba) arrives as expected.
- **Reproducibility:** identical `metrics_hash` across two runs **and** across `NUMBA_DISABLE_JIT=1` vs JIT-enabled (`f6595766…`). Tests run with `NUMBA_DISABLE_JIT=1`.
- **CI smoke timing:** the full 1-year, 12-combo, 1-symbol walk-forward (incl. 3 artifacts + PDF) completes in ~4 s (whole 85-test backtest suite ~11 s) — well under the 60 s budget.
- **Trivy incident (resolved):** the initial image was 3.84 GB and Trivy flagged one HIGH *secret* (an autobahn example key) — both caused by my spike `.venv` being copied in via `COPY backend/ .`. Adding `.dockerignore` removed the venv → 2.35 GB, zero Trivy findings (confirmed green in CI too).

## Blockers / parked

- None. `vectorbt==1.0.0` installed and ran cleanly, so no engine swap or `SweepEngine` parking was needed. Kelly damper (carried from M08) was intentionally **not** built — it needs a `TradeHistory` model that §3 explicitly puts out of scope.

---

# Section B — Manual user steps & follow-ups

### Railway (blocks prod runs until done)
- **Create the `worker-backtest` service** on staging + prod:
  `celery -A config.celery worker -Q backtest -l info --concurrency=1 --max-memory-per-child=2000000`.
  **Until it exists, every prod backtest sits `QUEUED` forever** (the queue-wait alert will fire). Retention/eviction still works — the eviction task runs on the default `celery` queue by design. Procedure in `docs/runbooks/backtest-stuck.md`.

### Staging verifications deferred (need a deployed env)
- **AC-09-10 SLAs:** 3-year single-symbol ≤ 10 min, 10-year ≤ 30 min, worker RSS ≤ 2 GB — procedure in `docs/runbooks/backtest-stuck.md`.
- **Grafana "Backtest Ops"** — JSON committed at `infra/grafana/backtest-ops-dashboard.json`; import to Grafana Cloud + verify panels populate on staging.

### Data
- To produce a **real-symbol** sample tearsheet, run the M06 FMP backfill (`python manage.py backfill_bars …`, needs an FMP key), then rerun a backtest and archive the PDF. The exit gate accepts the synthetic-fixture PDF; the real-symbol one is a nicety.

### Release
- Tag **`v0.9.0-backtest`** created locally on `afe6c24` but **NOT pushed** (operator-gated per `project-plan/README.md`). **Note:** as of 2026-07-08 there is **no tag-triggered deploy workflow** in `.github/workflows/` — Railway auto-deploys `main` on merge (so PR #28 already deployed staging, per M04–M08 precedent). Pushing the tag is bookkeeping until a release pipeline is wired; verify the prod-release trigger before relying on it. Prior unpushed tags (`v0.1.1-auth-metrics`, `v0.4.0`…`v0.8.0`) are still pending too.

### In-flight work
- `fix/m04-m08-review-remediation` is **already merged** (PR #27, `b6f54db`) — no conflict surface with M09.

### Decided autonomously (please sanity-check)
- **MFA-enforced backtest endpoints** — used `IsAuthenticatedAndMFAEnforced` + `mfa_required=True` for consistency with the rest of `/api/v1/*` (regime/risk precedent); §11 says "no additional re-prompt", which is honored (no per-action MFA code like kill-switches).
- **Added `GET /api/v1/backtest/strategies/`** (not in §6.7) so the launcher can enable/disable strategies by adapter availability — read-only, owner-scoped.
- **UI default `sizing_mode = production`** (frontend agent) vs the serializer default `fixed_qty_1` — the toggle is an explicit user choice; the API default is unchanged.
- **matplotlib/plotly pinned** at `>=3.8,<4.0` / `>=5.18,<6.0` (resolved to 3.11.0 / 5.24.1) — deliberate per §7 even though vectorbt pulls them transitively.
- **Report table *column headers* + chart tick labels (month abbreviations, matplotlib axis labels)** remain English literals — only `en` ships today; the §13 label set (sections/metric-names/disclaimer/PBO) IS server-side-dict-driven. Flagged LOW in self-review, accepted.
- **Concurrency-cap check-then-create is not atomic** (TOCTOU) — accepted LOW: bounded by the 30-min run cap + `concurrency=1` worker; single-user MVP. Revisit with `select_for_update` if multi-tenant contention appears.
- **`MAR`/Sortino return `0.0` for the no-downside case** — deliberate (avoids non-JSON `inf`).

### Homebrew note (local dev only)
- Installed `pango` via Homebrew locally so WeasyPrint renders PDFs on macOS; local pytest/gauntlet runs need `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`. Not relevant to CI/Docker (apt deps).
