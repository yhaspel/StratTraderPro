# StratTraderPro — PROGRESS

> **Canonical project status.** Verified against the actual code, not the plans.
> Update this file with **every development milestone** (phase start/close, AC pass, tag push, scope change).
> Detailed per-task history: `plan-progress-tracker.md`. Milestone specs: this folder. Master plan: `strat-trader-pro.md`.

**Last verified:** 2026-08-04 (**M16 Strategy Screener SHIPPED** — PR #55, squashed as `7bd3af0`;
the ADR-062 key gate it depends on landed the same day as PR #53. A strategy description can now
carry a machine-readable `[screen]` block: `/strategies/:id` grows a Screening panel that shows the
parsed criteria as chips and runs them — ONE FMP `/company-screener` call for the vendor-side
filters, then local enrichment over daily bars for the derived ones (SMA 50/200, SMA-200 slope,
52-week-high proximity), returning a deterministically ranked candidate list. Degrades rather than
lies: a rate limit or outage mid-enrichment finishes `DONE` with `degraded=true` and per-cause
counts. Bounded by a 10/h/user throttle, one active run per (user, strategy) enforced by a partial
unique index, `limit <= 100`, and a 240s task soft limit; rollback is the mutable `SCREENER_ENABLED`
flag. **Activation still requires an FMP key** (Settings -> Data Providers, or `FMP_API_KEY`) — until
one is set the panel says so honestly. Gauntlet at merge: backend `pytest` **885 passed, 9 skipped,
74 subtests** + `-m pg` **9 passed**, `ruff`/`bandit` clean, `makemigrations --check` clean,
prod-import smoke OK; frontend `ngc` clean, karma **264 SUCCESS**, `pnpm build` OK, Playwright a11y
**9 passed**, both repo guards green; OpenAPI snapshot + generated types regenerated. An independent
adversarial review of the diff found 2 HIGH + 4 MEDIUM + 1 LOW + 1 NIT — all fixed before merge (see
`M16-EXECUTION-REPORT.md` and the PR #54 review comment). **Deferred:** AC-16-12's live
re-validation of the FMP screener wire shape needs a real key — steps are in ADR-063 §4. Note also
that the frontend osv-scanner HIGH+ gate went red repo-wide this day on an unchanged lockfile; six
new advisory IDs were waived with per-package evidence in `docs/security/dependency-waivers.md`.)

**Previously verified:** 2026-08-01 (**ADR-062 shipped** on branch `feat/data-provider-keys-ui`: instance FMP/FRED keys are now settable in the UI — Settings → Data Providers, encrypted `DataProviderKey` rows, staff-set, validated-before-persist; `resolve_key` = UI key → env var → unconfigured, consumed by `FMPClient`/`FREDClient`/regime gate/`backfill_bars`. **The regime plane's missing-keys blocker is now a two-paste fix with no Railway edits and no redeploy** — the plane stays INERT until an operator actually pastes keys (ledger item 1 updated). Local gauntlet at `6b7059c`+2: backend `pytest` full green (SQLite; container), 29 new key tests, `ruff` clean, `bandit` clean (medium+); frontend `ngc` clean, karma **219 passed** (7 new), `pnpm build` OK, guides+envsubst guards green; OpenAPI snapshot + generated types regenerated. **M16 Strategy Screener spec written** (`16-strategy-screener.md`, status Spec): description-driven `[screen]` block → one FMP company-screener call + local SMA/52w-high enrichment, gated on the ADR-062 key. Note: PRs #45–#49 landed after the 2026-07-12 verification below — their record is `CHANGELOG.md [Unreleased]`.)
**Prior:** 2026-07-12 (**M10.5 CLOSED** — merged to `main` via **PR #31** (squash `e29cb12`), CI green, tagged **`v0.10.5-app-shell`**). Post-merge follow-ups also in: register validation feedback + hide-unconfigured-Google-button; C2 prod-settings test made hermetic (CI had no `backend/.env`); stale branch-protection required-check `Frontend — Lint & Test` reconciled to `Frontend — Build & Test`. Backend: `pytest` green (SQLite, `config.settings.test`) + `-m pg` **8**, `ruff`/`bandit` clean, `makemigrations --check` clean, prod-import smoke clean. Frontend: `ngc` clean, `ng build` OK, karma **111 passed**. Live E2E (Chrome): landing→login, shell + nav + logout, getting-started checklist, authed 404, help viewer, register validation, Google-button honesty — all pass. AC-by-AC + gauntlet output: `M10.5-EXECUTION-REPORT.md`. (Earlier prior: 2026-07-11, M10 closed — see the M10 close-out below.)
**Verification at HEAD (`d574057`):** backend `pytest` **587 passed** (SQLite) + **8 `-m pg`** (Postgres lane), `ruff` clean, `bandit` clean (medium+), `makemigrations --check` clean, prod-import smoke clean; frontend `ngc --noEmit` clean, `pnpm build` (449.56 kB), `pnpm run test:ci` **61 karma**; Docker image builds + Trivy HIGH/CRITICAL clean. GitHub CI: all 5 checks green.

> **2026-07-08 — M04–M08 review remediation** (`fix/m04-m08-review-remediation`): an
> adversarial review found 35 correctness/safety defects CI missed (L2 daily-loss
> semantics, sizing off `buying_power`/fabricated price, options position math,
> non-ASCII webhook 500, stream-supervisor masking, regime stub, FMP/FRED resilience,
> etc.). All fixed with regression tests; gauntlet green (**361 pytest** passed).
> Full ledger + evidence: `M04-M08-EXECUTION-REPORT.md` → "Remediation". Migration
> `orders.0004`. Follow-ups: per-strategy flatten tagging (M09), C1 worker/beat
> metrics scrape, M14 UI MFA-on-release prompt.

## Where the project stands

| Phase | Scope | Status | Shipped as |
|---|---|---|---|
| M00 | Scaffold, CI, Railway, observability | ✅ Done (2026-05-08) | `v0.0.0-scaffold` |
| M01 | Auth: register/verify/login, JWT family rotation + reuse detection, lockout, reset | ✅ Done (2026-05-01) | `v0.1.0-auth` (+`v0.1.1-auth-metrics` — **tag push still pending**) |
| M02 | MFA (TOTP + backup codes), profile, sessions, password change | ✅ Done (2026-05-03) | `v0.2.0-mfa` |
| M2.5 | Google OAuth sign-in (allauth bridge + exchange codes) | ✅ Done (2026-05-03) | `v0.2.5-oauth-google` |
| M03 | Strategy upload (3-file bundle), webhook config, HMAC secret reveal-once/rotation, seeding | ✅ Done (2026-05-03) | `v0.3.0-strategies` |
| **M04** | **Webhook ingest + broker adapter + Alpaca paper execution** | ✅ **Phase B–F implemented (2026-07-07)** — CI-green; live-paper smoke deferred | `v0.4.0-alpaca-paper` (tag pending) |
| M04A | IBKR Web API OAuth migration | ❌ Scrapped 2026-07-05 → superseded by the Alpaca pivot (ADR-041) |  |
| **M05** | **Order lifecycle + TradeStation (descoped)** | ✅ **Implemented (2026-07-07)** — order-lifecycle half full; TS behind flag OFF; live TS OAuth deferred | `v0.5.0-tradestation` (tag pending) |
| **M06** | **Market data + regime classifier** | ✅ **Code merged (2026-07-07)** — FMP/FRED + Bar store + rule/HMM/ensemble. ⚠️ **INERT — produces no output** (no API keys, no intraday task; AC-06-2 never written). See INERT ledger. | `v0.6.0-regime` (tag pending) |
| **M07** | **Sentiment pipeline** | ✅ **Code merged (2026-07-07)** — fetchers/tagger/tiered scorers (fakes)/EWMA/API. ⚠️ **INERT — polarity 0.00** (fake scorers default; registry seeding shipped in M10.5). See INERT ledger. | `v0.7.0-sentiment` (tag pending) |
| **M08** | **Risk engine, sizing & kill switches** | ✅ **Implemented (2026-07-08)** — sizing + 4-level kill switches on `TradingHalt`; staging p99 + Risk Ops "live" deferred | `v0.8.0-risk` (tag pending) |
| **M09** | **Walk-forward backtester** | ✅ **Implemented (2026-07-08)** — vectorbt sweep + custom replay engine, PBO/CSCV, tearsheet PDF/HTML/JSON, dedicated `backtest` queue, `/backtest` UI; PR #28 merged `afe6c24`; staging SLAs + Railway worker + real-symbol PDF deferred | `v0.9.0-backtest` (tag pending) |
| **M10** | **Admin portal, chained audit log & observability polish** | ✅ **DONE (2026-07-11)** — code merged `d574057` (PR #29); **operator track completed and verified live 2026-07-11**: Grafana Cloud (6 dashboards, 21 alert rules, contact points, notification policy, Tempo+OTel, Sentry↔Tempo), Railway exporters/services, Sentry+GitHub wiring. **11 defects found and fixed during the live bring-up (`bugs/`), 3 of them S1** — see the note below; the observability stack was *entirely inert* before this pass. | `v0.10.0-admin` (tag created locally, **not pushed**) |
| **M10.5** | **App shell, navigation, operability & review remediation** | ✅ **DONE (2026-07-12)** — merged to `main` via **PR #31** (squash `e29cb12`), CI green, tagged `v0.10.5-app-shell`. One `ShellComponent` wraps every authed route (nav + user menu + logout + impersonation slot + skip link + toast host); honest landing with Sign-in/Create-account CTAs; real 404; getting-started checklist + `GET /onboarding/status/`; help viewer `/help/:slug` + index; shared UI kit + global toasts. **Security C1/C2/C3/SEC-4/H8/M1 fixed** (per-email auth rate-limit key, prod fail-closed SECRET_KEY/FERNET_KEK, MFA step-up throttle, session-revoke-own-session bug, Django `/admin` unmounted in prod, `/metrics` fail-closed). **Risk truthfulness RISK-1..5** (soft-stop wired to real intraday DD; `max_concurrent`/`leverage_cap`/`permitted_asset_classes` enforced; `requested_qty` clamp; ×0.5 bear+sentiment factor per OQ-1; `seed_tickers`). Frontend C-FE-1..4 + swallowed-error sweep; a11y on touched screens. Post-merge: register validation feedback + hide-unconfigured-Google-button. **See INERT ledger below.** | `v0.10.5-app-shell` |
| **M11** | **Hardening, security, load test & docs** | ✅ **Implemented (2026-07-12)** — merged to `main` via **PR #32** (squash `72ed231`), **all 8 CI jobs green**, tagged **`v0.11.0-rc.1`** (local, not pushed). **§7.0 SERVICE_ROLE dispatch discharges BUG-011 IN CODE** (unset/bogus role exits non-zero, never falls back to `web`; entrypoint-dispatch CI job) — the Railway cutover stays pending as **AC-11-15 [LIVE]**. GDPR export/delete + Terms (`users.0005`), CSP report-only + log scrubber, `pip-audit`/`pnpm audit`/axe-core/bundle CI gates, SLO burn-rate alerts, KEK/JWT rotation rehearsals. Load harness + chaos scripts **EXECUTED 2026-07-14 on a dedicated `stp-load` stack — AC-11-3/4/5/6 all PASS** (`docs/ops/load-test-results.md`, `docs/ops/chaos-drill-logs.md`): AC-11-3 100-WS + 19-rps/10-min zero-5xx, p95 ingest→submit 47.5ms, queue→0 (measured on a **prod-shaped** gunicorn backend — the default dev runserver caps at ~5 rps); AC-11-4 50-user L1 flatten **p99 0.20s** (paper) / **0.17s** (LIVE = **M13 §6 gate 2**); AC-11-5 redis-kill + AC-11-6 streams-kill green; §7.5 worker-kill/alpaca-5xx/db-restart/role-removal green. **The 50-user L1 flatten closes deferred AC-08-11.** Running the harness required fixing several never-run defects (WS user had no `@task`; chaos scripts' `UID` readonly-var + query-separator bugs; unimplemented 5xx flag; streams seam hitting real Alpaca) — all detailed in the evidence docs. **[LIVE] reconciled by the 2026-07-14 OSS pivot:** SERVICE_ROLE cutover ✅ done, burn-rate import+unpause ✅ done; prod bring-up + Cloudflare R2 **void** (no hosted service; R2 → filesystem export, WP-7); DB-pw rotation + Lighthouse are now each self-hoster's own concern (Lighthouse → M14). Adversarial review: no CRITICAL/HIGH/MEDIUM; 1 LOW fixed. See `M11-EXECUTION-REPORT.md`. | `v0.11.0-rc.1` (tag pending) |
| ~~M12~~ | Beta & sign-off | ❌ **SCRAPPED 2026-07-14** → `archived/12-beta-and-signoff.md` (OSS pivot: no hosted beta / prod sign-off) | — |
| M13 | Live-trading switch (`ENABLE_LIVE_TRADING` + admin gate) | ✅ **Merged, inert** (`87240a3`) — ships disabled-by-default (D6); enabling it is each self-hoster's deliberate act. Hosted-service enablement gates void (OSS pivot). | on `main` |
| M14 | Frontend first paint (prerender public routes) | 📋 **Spec** — Option A locked 2026-07-14; FCP ≤ 1.2 s target held (first-run polish). Ships on its own. | — |
| M15 | Dashboard responsiveness (authed-dashboard speed levers) | 📋 **Spec** — deferred from the M14 review (in-app skeletons, service-worker/PWA); post-OSS-release polish. | — |
| M16 | Strategy Screener (FMP, description-driven `[screen]` block) | ✅ **Shipped** (2026-08-04, PR #55 `7bd3af0`) — one company-screener call + local SMA/52w-high enrichment; gated on the ADR-062 instance FMP key; deterministic parser, no LLM. Degrade-not-lie on vendor failure; 10/h/user throttle; `SCREENER_ENABLED` rollback flag. Live wire-shape re-validation deferred until an FMP key exists (ADR-063 §4). | ADR-063 |

### INERT features (M10.5 audit, 2026-07-12)

Code that is merged + CI-green but **structurally incapable of producing output in any deployed config**. Recorded honestly so "implemented" is never confused with "produces output". Each names the owning fix.

1. **Regime plane** — no FMP/FRED keys ⇒ no feature vectors ⇒ no HMM ⇒ `regime.no_data` forever (live-verified). No `marketdata/tasks.py` intraday task (AC-06-2 never written). **Owner:** operator keys + 10-yr backfill (M11/ops). **2026-08-01 (ADR-062): the keys are now a UI act** — Settings → Data Providers (staff + MFA; run `make promote-owner EMAIL=…` first if no staff account exists), takes effect on web/worker/beat with no env edits and no redeploy; env vars remain a fallback. Still inert until someone actually pastes keys; the intraday-task gap is unchanged.
2. **Sentiment** — `SENTIMENT_FAKE_SCORERS=True` default + (until M10.5) an unseeded `TickerRegistry` ⇒ market polarity `0.00` (live-verified). **Owner:** RISK-5 `seed_tickers` (shipped here — run it) + real FinBERT/LLM scorers (operator/M07-followup).
3. **TradeStation** — flag OFF ⇒ no TS `BrokerAccount` can be created; no `tradestation/streams.py`. M10.5 disables the `/settings/brokers` "Connect TradeStation" button + notes it is unavailable. **Owner:** M05 follow-up.
4. **Backtest worker** — no Railway `worker-backtest` consumer ⇒ prod backtests sit `QUEUED` forever. **Owner:** M11 §7.0 (`SERVICE_ROLE` dispatch).
5. **Soft-stop (AC-08-12)** — **RESOLVED here (RISK-1):** `apply_sizing` now passes a real broker-equity intraday drawdown, so the soft-stop can fire (test `test_soft_stop_fires_on_real_intraday_drawdown`).
6. **Alpaca missed-fill recovery (AC-04-11)** — `catch_up_account` replays only if `adapter.recent_fills` exists; `AlpacaAdapter` has none (only the fake). **Owner:** M11 (needs the real Alpaca activities endpoint). Do NOT claim AC-04-11 met for the real broker.

**Overstated-claim corrections:** M02's "revoke other sessions" logged you out of your *own* session (SEC-4 — **fixed here**). M06/M07 "implemented" overstates — key ACs were never written (regime intraday task; real scorers), not merely "keys deferred": they are **code-merged, no live output**. M08 soft-stop was dead code (**fixed here**). M04 AC-04-11 is not met for the real broker. **`vectorbt==1.0.0` pin:** confirmed installed + importable in the backend image on 2026-07-12 (operator re-check: `pip index versions vectorbt`).

### M10 close-out — the observability stack was inert until 2026-07-11

M10 merged CI-green on 2026-07-09 and **every component reported healthy while doing
nothing.** The live bring-up on 2026-07-11 found 11 defects (`bugs/README.md`), all now
fixed and verified in production. The three that mattered:

- **BUG-009 (S1) — all 17 imported alert rules were `isPaused: true`.** Grafana's
  Prometheus-rule converter imports paused by default. `KillSwitchTriggered`,
  `AuditIntegrityFailure`, `BrokerStreamSilent` could never have fired. The rules API
  reported `health: ok` for every one of them — *because a rule that never evaluates
  never reports a problem.* **AC-10-9 passed anyway**, because its wording only required
  that "a sample alert fires": the drill created a *temporary* rule, which is not paused.
  AC-10-9 and `docs/runbooks/alerting-setup.md` have both been rewritten to assert
  against the **real** rules (`isPaused == false`).
- **BUG-011 (S1) — `celery-worker` and `celery-beat` were running gunicorn, not Celery**
  (empty Railway start command → image default `CMD`). The default queue had no consumer
  and beat had **never fired a scheduled task**, in both envs, including
  `daily_loss_watcher`. Fixed live; the structural fix (fail loudly instead of silently
  substituting a web server) is **M11 §7.0** — the first task of M11.
- **BUG-008 (S1) — no dead-man's switch.** 14 of 17 rules are self-filtering (`… > 0`), so
  *empty = healthy*; nothing fired on **absence**, making a dead metrics pipeline
  indistinguishable from a green one. Added `MetricsPipelineDown` + `TargetDown`, which
  found BUG-011 within 60 seconds of going live.

Also fixed: OTel never traced the web tier (001/002), frontend Sentry never worked (004),
the frontend CI job ran neither lint nor tests — 67 specs had never executed (007), and the
"free tier" banner was a 30s scrape interval double-billing us, not a series-count problem
(005). A daily scheduled audit now re-asserts all of this (zero paused rules, all targets up,
beat→queue→worker loop fresh, budget, frontend config) and reports only on failure.

**The lesson, recorded in `bugs/README.md`: a clean bill of health can be produced by the
defect itself.** Prefer end-to-end assertions over any component's self-report.

**M04 truth (updated 2026-07-07):** Phase A (IB Gateway spike) done 2026-05-15 (ADR-040). **Phase B–F now implemented** on `feature/m04-webhook-alpaca-paper`: public webhook endpoint + `AlertMessage` + `process_alert`; `BrokerAdapter` protocol + `FakeBrokerAdapter` + `AlpacaAdapter` (paper) with `BrokerAccount`/`TradingHalt`/`BrokerCallAudit`; `Order`/`Fill`/`Position` + `ingest_fill_event` (dedup on `broker_exec_id`); Redis-Stream fill transport + `run_broker_streams` supervisor; Channels `/ws/dashboard/` consumer; `/settings/brokers` + `/dashboard` frontend; `alpaca-py` + `channels`/`daphne` in requirements. Backend gauntlet green (ruff/bandit/191 pytest/migrations/prod-import); CI grep gate + pivot hygiene done. **Deferred (needs externals):** the §10.4 live-Alpaca-paper smoke (runbook committed; operator runs with real keys), the Grafana Trading Ops "live on staging" panel (dashboard JSON committed), and the IBKR password rotation + Railway/GitHub secret deletion (operator step).

## The 2026-07-05 broker pivot

IBKR is out; **Alpaca is the first execution broker**. Why: IBKR Web API consumer approval never cleared for the Interactive Israel account (M04A's hard blocker), and the working-but-interim gateway path demands weekly manual re-auth and one session per process boot. Alpaca has no approval gate: paper keys are self-service and free, transport is REST + `trade_updates` WebSocket via `alpaca-py` (0.43.x, verified current).

- Decision record: `docs/adr/041-alpaca-over-ibkr.md`
- Implementation-ready spec: `04-webhook-ingest-and-ibkr.md` (rewritten; filename kept for link stability)
- Scrapped: M04A — full spec archived at `archived/04A-IBKR-Web-API.md` (scrapped plans move to `project-plan/archived/`)
- IBKR artifacts parked, not deleted (ADR-040, `docker/ib-gateway/`, re-auth runbook, spike script)

## The 2026-07-14 OSS pivot

StratTraderPro stopped being a hosted service Yuval operates for others and became **open-source,
self-hosted software** each user clones and runs against their own broker account. Yuval keeps a
private instance. **Why:** operating automated execution for third parties is plausibly a regulated
activity; distributing software is not. **Costs the SaaS; keeps the software, live trading, and
users.**

- Decision record: `PIVOT-TO-OSS.md` (revision 2, VALIDATED). Locked decisions D1–D8.
- **Licence:** Apache-2.0 (`LICENSE` + `NOTICE`); `NOTICE` discloses vectorbt's Commons Clause (D3).
- **Scrapped:** M12 (beta & sign-off) → `archived/`; the Stripe/business-model + hosted-operator
  plans → `archived/` with `❌ SCRAPPED` banners (D7). The record of what was deliberately *not*
  built is kept as a credibility asset (D8).
- **Void, not deleted-in-code:** the terms-acceptance + GDPR features stay (D4, inert by default);
  only the legal *documents* (`docs/legal/`) were deleted. `infra/grafana*` stays (D5).
- **Live trading:** ships enabled-capable, **disabled-by-default** (D6, M13 merged). Each
  self-hoster flips `ENABLE_LIVE_TRADING` on their own box, trading their own money.
- **Self-hosting bootstrap:** `make setup` generates `SECRET_KEY` + `FERNET_KEK`; `make up` no longer
  pulls the ngrok tunnel; export storage falls back to filesystem when no R2.

## The 2026-08-01 observability rightsizing (ADR-109)

- Decision record: `docs/adr/109-observability-reduced-scope.md`; full plan + adversarial-review
  log: `development-plans/2026-08-01-grafana-reduced-form.md`.
- **Code (this repo): DONE** — `alert-rules.yaml` 18 → 9 rules (backtest-ops + slo-burn-rate groups
  removed; `OrderSubmitLatencyHigh`/`SentimentLag`/`HMMModelStale`/`DBConnectionSaturation`
  retired), agent scrape jobs 7 → 5 (exporter jobs gone), compose exporters deleted, dashboards
  6 → 3 (SLO wording → targets), `docs/slo.md` deleted, runbooks/guides swept, `_EXTERNAL` pruned.
  The dead-man's pair + both budget rules are untouched; zero executable backend lines changed.
- **Operator track: ⏳ PENDING `[LIVE]`** — until executed, Grafana Cloud still shows the old
  surface (≈23 rules incl. the 3 hand-made auth rules, 6+ dashboards) and the exporter Railway
  services still run. Steps O-1…O-5 in the plan: backup → re-import + un-pause (⛔ BUG-009 gate) →
  delete retired rules/dashboards/Auth folder → agent redeploy **before** exporter-service
  deletion (else `TargetDown` pages) → drill one real rule → budget-rate check.
- **Daily audit: ⏳ PENDING** — its assertion spec must move to the reduced shape (11 rules,
  5 `up` targets, env=production only) per plan WP-8, or it will false-alarm after O-4.
- D5 narrowed, not violated: the CI-required `infra/grafana/alerts/*.yaml` + `agent.yaml` stay.

## Next steps (ordered)

1. **M04 Phase B — webhook ingest core** (broker-agnostic): `POST /hooks/v1/{user}/{strategy}/` with secret verify + schema + idempotency + halt gate, `AlertMessage`, `process_alert`, `Order`/`Fill`/`Position` models, `FakeBrokerAdapter`. Spec §6.1, §6.3–§6.4.
2. **M04 Phase C — AlpacaAdapter + streams service**: per-user encrypted paper keys, `place_order` via `alpaca-py`, `run_broker_streams` + `FillIngestor`. Spec §6.2, §6.5. *(User action: create an Alpaca account + generate paper keys — self-service, no approval wait.)*
3. **M04 Phase D — dashboard v0 + broker-connect UI + WS client.** Spec §6.6–§6.8.
4. **M04 Phase E/F — pivot hygiene + exit gate**: compose profile for ib-gateway, `TWS_*` scrub + IBKR password rotation, CI grep gate, real-paper smoke (§10.4), Trading Ops dashboard, tag `v0.4.0-alpaca-paper`.
5. **Before M05 starts:** confirm TradeStation sim-API access is actually obtainable, else descope M05 to Order-Lifecycle-only (see M05 review note).
6. ~~**Before M09 starts:** resolve vectorbt AGPL licensing~~ ✅ **RESOLVED 2026-07-08** — premise was wrong: vectorbt OSS is fair-code (Apache-2.0 + Commons Clause), not AGPL. Adopted `vectorbt==1.0.0` behind a `SweepEngine` seam; backtrader dropped for a custom in-repo replay engine (ADR-090). M09 implemented + merged (PR #28).
7. **Alpaca live eligibility:** live trading is each self-hoster's choice (D6, M13 shipped disabled-by-default); confirm your own jurisdiction's eligibility with Alpaca before you enable it (paper is unaffected).
8. **Bring the regime plane live (now a UI act, ADR-062):** promote the owner account to staff (`make promote-owner EMAIL=…`), paste FMP + FRED keys in **Settings → Data Providers**, confirm *Admin → Health → Regime data source: Configured*, then trigger one run (`python manage.py shell -c "from apps.regime.tasks import run_daily_feature_pipeline; print(run_daily_feature_pipeline())"`). Closes INERT item 1's key half; the intraday task (AC-06-2) and 10-yr backfill remain.
9. **M16 — Strategy Screener:** ✅ shipped (PR #55). Dormant until an FMP key is set (step 8) — the panel states that honestly rather than failing on click.

## Open items & known debt (carried from review, 2026-07-05)

- `v0.1.1-auth-metrics` tag never pushed (tracker 01.11.15).
- Tracked junk files to `git rm`: `_tmp_14_afb3bf…` (repo root), `frontend/_tmp_14_c77e270e…` (+ untracked " 2"–" 13" Finder duplicates); `gateway-*.png` screenshots in repo root; add `_tmp_*` to `.gitignore`. (Folded into M04 §6.9.)
- ADR-031 wording ("TradingView signs the alert body") is imprecise — TV embeds a static secret; ADR-042 (M04 deliverable) documents the honest semantics.
- Known UI follow-ups from M2.5: env badge hardcoded to "staging" copy; login 401 shows `UNKNOWN` error after refresh-interceptor retry.
- `DJANGO_SETTINGS_MODULE=config.settings.prod` on both staging and prod (only `RAILWAY_ENVIRONMENT_NAME` differs) — consider `staging.py` when they need to diverge.
- ~~M10 §6.5 observability carryover: move `/metrics` out of Django middleware, wire postgres/redis/celery exporters, remaining dashboards.~~ ✅ **RESOLVED (M10, PR #29)** — `/metrics` moved to `config/metrics_endpoint.py` at the WSGI entry (+ ASGI mirror), Sentry `before_send` mitigation deleted; postgres/redis exporters + agent scrape jobs added; **FIX-C1** worker/beat/streams scrape wired via `TASK_METRICS_PORT`; all six dashboards updated + alert rules committed as code. The M09 backtest-alert "live wiring is M10" note is also closed (backtest rules in `infra/grafana/alerts/alert-rules.yaml`). Remaining = operator import to Grafana Cloud + Railway env.
- **Transactional email (only if you run a multi-user instance).** Local dev uses the console email backend — the signup verification link is printed to `docker compose logs backend`, no email provider needed. If you run a multi-user instance and want real email, configure your own [Resend](https://resend.com) (or SMTP) sender: register/verify your own domain (DNS: DKIM + SPF + DMARC) and set `DEFAULT_FROM_EMAIL` for the `backend`, `celery-worker`, and `celery-beat` processes. Note that a bare sandbox sender (e.g. `onboarding@resend.dev`) only delivers to the account owner, so every other user's verification email is silently rejected while `/register` still returns 201 — the `auth_email_send_total{result="error"}` counter surfaces this.

## How to re-verify this file's claims

```bash
cd backend && python -m pytest -q && ruff check . && bandit -r apps/ config/ -x tests -q --severity-level medium
cd frontend && npx ngc --noEmit -p tsconfig.app.json
git log --oneline -5 && git tag -l
grep -rn "class.*Adapter" backend/apps/brokers/   # empty until M04 Phase C lands
```
