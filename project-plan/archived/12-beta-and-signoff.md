# Milestone 12 — Private Beta, Bugfix & MVP Signoff

> **Status: ❌ SCRAPPED 2026-07-14 — OSS pivot; do not implement.**
> Superseded by `project-plan/PIVOT-TO-OSS.md`. M12's premise — a private beta cohort and a
> hosted MVP sign-off — dies with the pivot to open-source self-hosting: there is no hosted
> service, no beta users, and no prod deploy to sign off.
>
> **What carried over:** the `/help` route (already shipped in M10.5 — remaining articles folded
> into README/WP-2); the `scripts/smoke.sh` idea → WP-4 self-hosting bootstrap; the `v0.1.0` tag
> idea → WP-9, re-scoped as a **public-release tag**, not a prod deploy. Never ran — there is no
> M12 execution report.

> **Week:** 12
> **Duration:** 5 working days (planning label, not an execution constraint)
> **Depends on:** M11 (hard gate — do not start until the M11 exit gate is closed: prod Railway env live, `v0.11.0-rc.1` soaked 24h, terms-acceptance flow shipped, SLO docs current)
> **Unlocks:** `v0.1.0` production release → post-MVP roadmap (live trading, marketplace, etc.)
>
> **REVIEWED & FROZEN 2026-07-10.** This spec was re-validated against the code at `main` (M10 merged, PR #29). Six decisions are locked — do not revisit autonomously:
> 1. **Final release tag = `v0.1.0`** (master-plan canonical). RC chain = `v0.1.0-rc.1`, `-rc.2`, … (semver prereleases of 0.1.0). M11's `v0.11.0-rc.1` belongs to the per-milestone `v0.M.0` marker scheme and is NOT part of this chain. Tags are created locally on merge commits; **pushing tags is operator-gated**.
> 2. **Deploy + rollback are Railway-native.** Deploy = merge to `main` (Railway auto-deploys with the git SHA intact; there is no tag-triggered workflow and `deploy-staging.yml` is dispatch-only). Rollback = Railway "redeploy previous deployment" + `git revert` on `main`. Do NOT build a GitHub Actions deploy pipeline in this milestone.
> 3. **Feedback button = Telegram deep link + `mailto:` fallback** (runtime-configured). No feedback API, no Sentry feedback widget.
> 4. **Help center ships as an in-app `/help` route** (index + viewer) over the existing static articles in `frontend/src/assets/help/` plus two new articles (getting-started, troubleshooting).
> 5. **Beta cohort identification is env-based** (`BETA_USER_EMAILS`), surfaced as a Sentry tag. No schema change (§8 stands).
> 6. **No new backend or frontend dependencies.** The help viewer and feedback button use Angular built-ins.
>
> Every acceptance criterion and §6 task is tagged **[CI]** (buildable + provable in the repo/CI, no external services) or **[OPS]** (requires humans, live users, credentials, or a deployed environment). An autonomous implementation run is accountable for every [CI] item; [OPS] items become documented operator steps.

## 1. Purpose

Run a private beta with 3–5 trusted users in paper mode, collect feedback, fix the top-priority issues, and formally sign off the MVP against the §1.1 success criteria in the master plan (`strat-trader-pro.md`). No new scope beyond what this spec lists. The deliverable is a production release (`v0.1.0`) that can onboard new users safely.

**§1.1 is verified as amended.** Three criteria contain wording that pre-dates shipped pivots and must be checked against current reality, with the amendment recorded in the signoff doc — not silently rewritten and not silently passed:
- Criterion 2 says "per-strategy HMAC" — actual: TradingView embeds a static per-strategy secret in the body (ADR-042); HMAC applies to non-TV callers.
- Criterion 6 says "vectorbt + backtrader" — actual: vectorbt sweep + custom in-repo replay engine (ADR-090).
- The §1 preamble says "IBKR paper and TradeStation" — actual: Alpaca paper is the first broker (ADR-041); TradeStation shipped behind `BROKER_TRADESTATION_ENABLED=False`.

## 2. In Scope

- Inviting 3–5 beta users (friends / early prospects). [OPS]
- Dedicated beta communications channel (Telegram group + mailto). [OPS]
- Daily triage of beta feedback; GitHub issue creation + prioritization. [OPS]
- Fix critical (P0/P1) bugs; park P2/P3 in backlog. [OPS-driven, fixes are CI]
- Polish obvious UX papercuts found during beta. [OPS-driven]
- In-app Help Center (`/help` route + viewer + two new articles). [CI]
- "Give feedback" button on the dashboard (Telegram + mailto). [CI]
- Marketing-shell landing page (static content in the existing `LandingComponent`). [CI]
- Beta cohort Sentry tagging + Beta Ops Grafana dashboard. [CI build, OPS import]
- `scripts/smoke.sh` — one-command smoke harness for staging/prod checks. [CI]
- Final demo-script rerun verifying all §1.1 success criteria. [OPS, scaffolded by CI]
- Release notes, `CHANGELOG.md` v0.1.0 section. [CI]
- MVP signoff doc + post-MVP roadmap doc. [CI scaffold, OPS evidence + signature]
- Final production deploy of `v0.1.0` + 24h soak. [OPS]

## 3. Out of Scope

- Major new features (any new scope idea → post-MVP backlog).
- Live trading enablement (v0.2; `ENABLE_LIVE_TRADING` stays `False`).
- Mobile app (v0.2).
- Any GitHub Actions deploy/release pipeline (locked decision 2).
- Non-English locales (es is a post-MVP task; see §13).

## 4. Acceptance Criteria

| # | Tag | Criterion |
|---|-----|-----------|
| AC-12-1 | [OPS] | 3–5 beta users onboarded; each completes registration + email verify + MFA + Alpaca paper connection. |
| AC-12-2 | [OPS] | Each beta user fires at least one TradingView webhook and sees a paper fill on the dashboard. |
| AC-12-3 | [OPS] | Each beta user configures their risk profile and fires a kill switch at least once (drill). |
| AC-12-4 | [OPS] | All §1.1 MVP success criteria independently verified **as amended per §1**; each has a dated evidence row in `docs/mvp-signoff.md`. The [CI] portion is the committed signoff doc with the criterion/amendment/evidence-type columns pre-filled and evidence cells marked `PENDING-OPERATOR`. |
| AC-12-5 | [OPS] | All P0 bugs from beta feedback fixed and verified; every P1 fixed or explicitly deferred with rationale in its GitHub issue. |
| AC-12-6 | [OPS] | 24-hour post-deploy soak shows no unresolved alerts (per `infra/grafana/alerts/alert-rules.yaml`); SLO error budgets per `docs/slo.md` intact. |
| AC-12-7 | [OPS] | `v0.1.0` tagged on the release merge commit and live on prod (Railway-native deploy); rollback drill executed once on staging per §6.5 and timed ≤ 10 min. |
| AC-12-8 | [CI] | Post-MVP roadmap committed at `docs/post-mvp-roadmap.md` with prioritized items reflecting the Alpaca pivot; each entry has a 1-line summary, success criteria, rough effort, and dependencies. |
| AC-12-9 | [CI] | In-app Help Center: lazy `/help` route lists ≥ 10 articles (index + viewer over `frontend/src/assets/help/`), reachable from the dashboard nav, covering at minimum: getting started (register/verify/MFA), connect Alpaca paper, upload strategy, TradingView alert setup, risk profile, kill switch, backtest, troubleshooting. TradeStation article present but annotated/hidden while `BROKER_TRADESTATION_ENABLED` is off. Karma specs cover index + viewer. |
| AC-12-10 | [CI] | "Give feedback" button on the dashboard opens the beta Telegram group (URL from runtime config) with a `mailto:` fallback when unset; covered by a karma spec. |
| AC-12-11 | [CI] | Landing page (`/`) shows static marketing-shell content: product name, tagline, 3–4 feature blurbs, paper-trading-only disclaimer, Sign-in / Register CTAs; all strings via i18n keys; axe-clean via the gate M11 delivers (M11 is a hard precondition — if that gate is somehow absent at implementation time, run an equivalent local axe scan and record the result; the CI gate remains the enforcement point). |
| AC-12-12 | [CI] | `scripts/smoke.sh <BASE_URL> [FRONTEND_URL]` exits 0 against a healthy env: `/healthz` 200 + version SHA present, `/readyz` 200, and — when `FRONTEND_URL` is given — frontend root 200 containing "StratTraderPro"; exits non-zero with a message naming the failed check. Works unauthenticated (metrics auth not probed by default). |
| AC-12-13 | [CI] | Beta cohort plumbing: `BETA_USER_EMAILS` env (comma-separated) → Sentry `beta:true` tag on backend events for those users; unit-tested with a fake Sentry hub. Grafana `beta-ops-dashboard.json` committed reusing existing Prometheus series (auth failures, webhook error rate, order rejects, kill-switch triggers, WS disconnects). |

## 5. Definition of Done

Baseline DoD applies (project-plan/README.md), plus:

- Beta sign-off email sent to each user confirming move from beta to general paper-trading. [OPS]
- Solo on-call active from prod-launch date per `docs/oncall.md`; backup human contact recorded there. [OPS]
- `v0.1.0` release notes published in `CHANGELOG.md` (the `[Unreleased]` section becomes `[0.1.0] - <date>` per Keep-a-Changelog). [CI]
- Yuval's own account is MFA-enabled and actively running the platform for dogfood. [OPS]

## 6. Implementation Tasks

### 6.1 Beta kickoff [OPS]

- Identify 3–5 users; send invitations with the getting-started help article link.
- Registration is open (no invite-code mechanism exists and none is added): send each the app URL + onboarding doc; point them at the seeded sample strategy (M03 seed import) to reduce friction.
- Schedule a 30-minute onboarding call with each (if geography allows); otherwise async help.
- Create the beta-only Telegram group; put its invite URL into the runtime config (§6.4) and `docs/runbooks/beta-support.md`.

### 6.2 Daily ops cadence (Mon–Fri) [OPS]

- **09:00:** Check Grafana dashboards, alert state, overnight Sentry errors (filter `beta:true`).
- **10:00:** Beta group messages triaged → GitHub issues tagged `beta`.
- **12:00–15:00:** Fix critical issues; ship small changes (each through the normal PR gauntlet).
- **17:00:** Daily summary post in beta group; tomorrow's plan.
- **18:00:** `scripts/smoke.sh` against staging AND prod (§6.10); log results in the daily summary.

### 6.3 Bug bar [OPS policy]

- **P0:** security, data integrity, kill switch ineffective, money-movement bug (n/a in paper but still guard), auth broken — **fix same-day**.
- **P1:** broken primary flow (can't place order, can't see position) — **fix within 24h**.
- **P2:** degraded secondary flow, UI glitch — fix if time; otherwise triaged to v0.2 backlog.
- **P3:** polish / nice-to-have — backlog.

### 6.4 Feedback instrumentation [CI build, OPS wiring]

- **Feedback button (locked decision 3):** a "Give feedback" button in the dashboard header. Reads `betaFeedbackUrl` from runtime config (`window.STP_CONFIG` via `ConfigService`; add `betaFeedbackUrl: '${BETA_FEEDBACK_URL}'` to `docker/nginx.conf.template`). **Envsubst allowlist (critical):** `docker/frontend.Dockerfile` sets `NGINX_ENVSUBST_FILTER` as an anchored allowlist — vars not listed are NOT substituted and the literal `${...}` string ships to the browser. The live filter is currently `^BACKEND_URL$` while the template already emits four more vars unsubstituted (latent M10 defect) — widen the group to all seven vars (five existing + `BETA_FEEDBACK_URL` + `TRADESTATION_ENABLED`) and fix the template comment. **Defense-in-depth:** every new runtime-config consumer treats an empty or `${`-prefixed value as unset. When set → opens the Telegram URL in a new tab (`rel="noopener"`); when unset → `mailto:you@example.com?subject=...` fallback. All strings via `en.json`. Karma specs for the URL-set, unset, and `${`-literal branches. [CI] Setting `BETA_FEEDBACK_URL` on the Railway frontend service is [OPS].
- **Beta cohort tag (locked decision 5):** `BETA_USER_EMAILS` env (comma-separated, default empty) in `config/settings/base.py`. On authenticated requests where the user's email is in the set, tag the Sentry scope `beta:true`. **Injection point:** DRF resolves JWT auth AFTER Django middleware, so `RequestIdMiddleware`/`tag_sentry_correlation` sees `AnonymousUser` on API requests — do NOT extend the middleware; hook the DRF authentication path instead (e.g., after user resolution in the JWT authentication class, call a small `tag_beta_scope(email)` helper; no-op when `SENTRY_DSN` unset). Unit-test the helper with a stubbed Sentry SDK. No schema change. [CI]
- **Sentry side [OPS]:** saved search + alert rule on `beta:true` events in the Sentry UI (Sentry data cannot be panelled in Grafana — no Sentry datasource is configured; do not pretend otherwise).
- **Grafana side [CI build, OPS import]:** `infra/grafana/beta-ops-dashboard.json` — panels over existing Prometheus series only: auth failure rate, webhook error rate, order rejects, kill-switch triggers, WS disconnects. Candidate series (verify names at build time): `auth_login_total`, `webhook_received_total`, `sizing_reject_reason_total` / `order_state_transitions_total`, `killswitch_trigger_total`, `broker_stream_disconnects_total`. No `/readyz` panel — no backing series exists and §8 forbids inventing one. Prometheus metrics carry no per-user labels (by design — cardinality), so this dashboard is platform-wide health during beta, not per-user filtering. Cross-check every panel's series name against `backend/apps/*/metrics*.py` via a sibling of M10's `config/test_alert_rules.py` — note that test globs only `apps/*/metrics.py`, while the MFA/OAuth auth series live in `metrics_m02.py`/`metrics_oauth.py`; broaden the glob in the new test if you use them.

### 6.5 Release process [OPS, CI-scaffolded]

- RC chain: cut `v0.1.0-rc.1` (first M12 RC — note M11's `v0.11.0-rc.1` is a different, per-milestone scheme), then `-rc.2`, … as fixes land. Tags created locally on `main` merge commits; pushing any tag is operator-gated.
- When the bar is met: tag `v0.1.0` on the final merge commit → prod deploy is the Railway auto-deploy of that merge (locked decision 2) → 24h soak (AC-12-6) → close.
- **Rollback drill (AC-12-7), on staging, before cutting v0.1.0:** Railway "redeploy previous deployment" on the staging backend + frontend services; verify `/healthz` reports the previous SHA; re-deploy current; record timing in `docs/runbooks/beta-support.md`. Prod rollback = same mechanism + `git revert` of the offending commit on `main`.
- Update `CHANGELOG.md`: rename `[Unreleased]` → `[0.1.0] - <release date>` with a fresh empty `[Unreleased]` above it; add the M12 entries. [CI]
- Annotate the master plan (`strat-trader-pro.md` §1.1 area) with a one-line "MVP delivered <date>, see docs/mvp-signoff.md" note. [CI at release time — the scaffold commit adds the annotation as `PENDING-OPERATOR` if signoff evidence isn't complete]

### 6.6 Help center [CI] (locked decision 4)

Current state: 13 orphaned static HTML articles exist in `frontend/src/assets/help/` (M04–M09 deliverables) with no route or viewer referencing them.

- **New lazy feature `/help`:** `HELP_ROUTES` in `frontend/src/app/features/help/` — `/help` (index grouped by topic) and `/help/:slug` (viewer). Public (no `authGuard`) — help must be readable before signup. Follow the 3-layer + standalone-component + `@if/@for` + `inject()` conventions in CONTRIBUTING.md.
- **Viewer mechanics:** a hardcoded article manifest (slug → asset filename, title key, topic group, `requiresFlag?`) — the slug is looked up in the manifest, never interpolated into a fetch path. Fetch the asset via `HttpClient` (`responseType: 'text'`), render via `DomSanitizer.bypassSecurityTrustHtml` — acceptable ONLY because content is first-party build-shipped assets; document this in a code comment. Strip the per-article `<style>`/full-page chrome at render time or render in a scoped container so app styles win.
- **New articles (match the existing article format):** `getting-started.html` (register → verify email → MFA → first login) and `troubleshooting.html` (webhook not arriving, order rejected by risk gate, kill-switch recovery, MFA lockout → runbook-derived, user-facing tone).
- **Flag-aware entries:** the TradeStation article's manifest entry carries `requiresFlag: 'tradestation'`; the index hides or badges it based on a config-service lookup (frontend has no flag API for this — drive it from a `tradestationEnabled` field in runtime config, added alongside `betaFeedbackUrl`: same nginx template line, same `NGINX_ENVSUBST_FILTER` extension, same `${`-literal guard — see §6.4).
- **Nav:** "Help" link in the dashboard header (next to the M10 `nav.admin` link) + a link from the landing page.
- **i18n:** viewer/index chrome strings via `en.json`; the articles themselves are static English HTML — an accepted, documented exception (existing pattern), noted in §13.
- **Tests:** karma specs — index renders all non-flag-hidden manifest entries; viewer loads + sanitizes a fixture article; unknown slug → index redirect.

### 6.7 Post-MVP roadmap [CI]

`docs/post-mvp-roadmap.md` — supersedes the master plan's stale post-MVP list (write it against the post-pivot reality):

- Priority 1: Live trading rollout (separate ADR + legal; 4–6 weeks; `ENABLE_LIVE_TRADING` + `LIVE_TRADING_DISCLAIMER_VERSION` scaffolding exists).
- Priority 2: TradeStation completion — live OAuth verification + flag ON (M05 shipped it dark; `BROKER_TRADESTATION_ENABLED=False`).
- Priority 3: Additional brokers — IBKR (Web API approval still pending for Interactive Israel; gateway artifacts parked per ADR-040/041) and Schwab. *(The master plan's "Alpaca, Schwab" wording pre-dates the pivot — Alpaca shipped in M04.)*
- Priority 4: Options Greeks-aware sizing (3 weeks).
- Priority 5: Strategy marketplace / community-tested promotion.
- Priority 6: Mobile-friendly responsive polish → native wrapper (TBD).
- Priority 7: GPU LLM worker migration when Tier-2 sentiment volume > 500/day.
- Priority 8: Per-symbol regime classifier — full spec already exists at `project-plan/06A-per-symbol-regime.md`.
- Priority 9: Portfolio-level risk (VaR, correlation caps).
- Priority 10: `es` locale (first non-English language; see §13).
- Priority 11 (**do this BEFORE the beta cohort lands — see §6.1**): move transactional email off the interim sending domain. Prod currently sends as `no-reply@example.com` because that is the only domain verified in Resend; it is unrelated to the product and reads as a phishing signal to a new user clicking a verification link. Success criteria: a StratTraderPro-branded domain verified in Resend (DKIM + SPF + DMARC green), `DEFAULT_FROM_EMAIL` updated on `backend` / `celery-worker` / `celery-beat` in both Railway environments, and a live register → deliver → verify round-trip re-run. Effort: ~1h once the domain exists. Dependency: owning the domain. Background + the sandbox-sender bug it replaced: PROGRESS.md "Open items & known debt".

Each entry: 1-line summary, success criteria, rough effort, dependencies. Cross-link parked items from PROGRESS.md "Open items & known debt" so nothing is orphaned.

### 6.8 MVP signoff doc [CI scaffold, OPS evidence]

`docs/mvp-signoff.md` with one row per §1.1 criterion:

| # | Criterion (verbatim) | Amendment (if any) | Evidence | Verified by | Date |
|---|---|---|---|---|---|
| 1 | … | — | PR link / test run id / screen-capture ref | Yuval | `PENDING-OPERATOR` |
| 2 | … | ADR-042: static TV secret, not per-strategy HMAC | … | … | … |

- The scaffold commit fills #, Criterion, Amendment, and the evidence *type* expected; operator fills Evidence/Verified/Date rows during the final walkthrough.
- Amendments column cites ADR-041 (criterion-adjacent preamble), ADR-042 (criterion 2), ADR-090 (criterion 6).
- Doc is completed and committed with a final "MVP delivered" commit. [OPS]

### 6.9 Marketing-shell landing page [CI]

Flesh out the placeholder `frontend/src/app/features/landing/landing.component.ts` (currently title/tagline/status only):

- Hero (name, tagline), 3–4 feature blurbs (webhook→paper-fill automation, regime + sentiment context, risk engine + kill switches, walk-forward backtesting), a prominent **paper-trading-only** disclaimer, Sign-in / Register CTAs, links to `/help` and the ToS/Privacy docs (M11 delivers those routes/flows — link to wherever M11 exposed them; if M11 exposed no public route, link the help center's getting-started article instead).
- Static content only; all strings via `en.json`; keep it in the initial or landing lazy chunk without breaking the M11 bundle budget (AC-11-12: initial ≤ 400 KB gzipped — check `pnpm build` output).
- Keyboard/axe-clean (M11 added axe-core CI; the new page must pass it).

### 6.10 Smoke harness [CI]

`scripts/smoke.sh <BASE_URL> [FRONTEND_URL]`:

- `GET /healthz` → 200 AND response contains a non-empty version SHA; `GET /readyz` → 200; frontend root → 200 containing "StratTraderPro" (only when `FRONTEND_URL` given).
- Plain bash + curl, no auth, exits non-zero with a clear message naming the failed check. Add a trivial CI-side self-test: run it (both args) against the compose stack inside the existing `e2e-smoke` job — do not weaken that job, and add a `/readyz` wait first (the job's existing loop polls `/healthz` only, so a readiness race is possible).
- Documented in `docs/runbooks/beta-support.md` with staging + prod URLs (URLs themselves [OPS]).

## 7. Tech Stack Notes

No new tech and **no new dependencies** (locked decision 6). All M12 code is Angular built-ins + existing backend libs + bash. Everything else in this milestone is operational.

## 8. Data Model Changes

None. `BETA_USER_EMAILS` is env-only by design (locked decision 5). Any schema change this week is an indication the bug bar is being violated — escalate, don't migrate.

## 9. API Contract Changes

None. The feedback button is client-side (locked decision 3); the help center serves static assets. Breaking API changes this late are a red flag. (Bug fixes that must touch a serializer contract require OpenAPI + frontend-types regeneration per the baseline DoD.)

## 10. Test Plan

### 10.1 Regression [CI]

- Full local CI-parity gauntlet green on every M12 PR: `ruff`, `bandit` (medium+), full pytest (SQLite lane + `-m pg` lane), `pnpm install --frozen-lockfile`, `pnpm build`, `npx ngc --noEmit -p tsconfig.app.json`, `pnpm run test:ci` (karma), `makemigrations --check`, prod-import smoke, compose `/healthz` smoke, Trivy.
- The Playwright suite is 4 auth specs against a mock API and is NOT in CI — run it locally where the environment allows (`pnpm e2e` after `npx playwright install chromium`); treat failures as blockers, treat an un-runnable environment as a documented skip.

### 10.2 Acceptance re-verification [OPS, CI-scaffolded]

- Every §1.1 criterion: exercised by an existing scripted test (map each criterion → concrete test file/name in the signoff doc scaffold) AND a manual walkthrough recorded as a short screen capture [OPS].

### 10.3 Beta usage test [OPS]

- Each beta user's first-hour experience observed (call, or review with consent).

### 10.4 Post-launch soak [OPS]

- 24h soak post-prod deploy: no new P0/P1 Sentry issues; no firing alerts; SLO error budgets (docs/slo.md) intact.

### 10.5 New-code tests [CI]

- Karma: help index/viewer (incl. sanitization fixture + unknown-slug redirect), feedback button (URL-set and mailto branches), landing content smoke.
- Pytest: `BETA_USER_EMAILS` parsing + Sentry beta-tag unit test (stubbed SDK, no network).
- Dashboard JSON: series-name cross-check test for `beta-ops-dashboard.json` (§6.4).
- `scripts/smoke.sh` self-test wired into the compose smoke job.

## 11. Security Considerations

- Beta users go through the same registration + MFA + terms-acceptance flow as any user; no shortcuts, no shared accounts.
- Access to prod admin stays limited to Yuval (`is_staff`); backup human contact noted in `docs/oncall.md` — but no second admin account is created for M12.
- Broker-connection steps are delivered via the in-app help center, never over chat; beta users are reminded not to paste API keys into Telegram.
- Help viewer renders only first-party build-shipped assets via a fixed manifest (no user-controlled paths); `bypassSecurityTrustHtml` is scoped to that and commented as such.
- The Telegram invite URL is not a secret but is rotated if leaked (regenerate invite link).
- `BETA_USER_EMAILS` contains PII (emails) — env-var only, never logged, never sent to the frontend.

## 12. Observability

- `infra/grafana/beta-ops-dashboard.json` committed [CI]; imported into Grafana Cloud [OPS].
- Sentry: `beta:true` tag live (§6.4); saved search + Sentry-side alert on any beta-tagged error [OPS]. Tightened thresholds during beta week — e.g. any `auth.*` error burst or webhook 5xx pages immediately — are edits to `infra/grafana/alerts/alert-rules.yaml` thresholds [CI] + re-import [OPS]; revert thresholds post-beta.
- Daily smoke results (§6.2) logged in the beta group; failures create GitHub issues.

## 13. Translation & Localization

- MVP ships `en` only; ngx-translate scaffolding is live (`assets/i18n/en.json`) — all NEW UI chrome (help index/viewer, feedback button, landing) uses translation keys. No hard-coded strings in components.
- **Documented exception:** help articles are static English HTML assets (existing M04–M09 pattern). Translating them is part of the post-MVP `es` task (roadmap Priority 10), which also covers extracting backend `.po` files per README conventions.
- Articles stay translation-friendly: short paragraphs, no idioms, no culture-specific examples.

## 14. Documentation Deliverables

- `docs/mvp-signoff.md` (§6.8). [CI scaffold]
- `docs/post-mvp-roadmap.md` (§6.7). [CI]
- `CHANGELOG.md` — v0.1.0 release section (§6.5). [CI]
- `frontend/src/assets/help/getting-started.html` + `troubleshooting.html`; manifest covers all articles (§6.6). [CI]
- `docs/runbooks/beta-support.md` — beta channel, triage flow, smoke-harness usage, rollback-drill record, Telegram URL rotation. [CI, operator fills live URLs]
- PROGRESS.md + plan-progress-tracker.md updated at close-out. [CI]

## 15. Rollback Plan

- **Mechanism (locked decision 2):** Railway "redeploy previous deployment" per service (backend, frontend, workers) + `git revert` on `main` for the offending change. `/healthz` version SHA confirms which build is live.
- Drilled once on staging before `v0.1.0` (§6.5, AC-12-7); measured target ≤ 10 min end-to-end.
- If a post-launch P0 surfaces: roll back first, announce in the beta group within 30 min, then diagnose.
- Database: M12 ships no migrations (§8), so rollbacks are code-only. If a beta bugfix ever requires a migration, its PR must state the reverse path explicitly before merge.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Beta users uncover a major design flaw late | Med | High | Keep a 10% buffer in Week 12 for rework; escalate to post-MVP roadmap if unfixable in-week. |
| Beta recruiting slips (fewer than 3 users) | Med | Med | Personal network first; AC-12-1 floor is 3; dogfood account supplements but doesn't count. |
| Solo dev burnout after 12-week sprint | High | Med | Explicit break window (2 weeks) before starting v0.2. |
| Beta users want live trading immediately | High | Med | Clear messaging: paper is the MVP; live = v0.2 on a quality bar (roadmap Priority 1). |
| Legal review of ToS slips | Med | Med | M11's minimum-viable ToS is live; upgrade when counsel responds; tracked in roadmap. |
| Railway rollback slower than assumed | Low | High | The staging drill (AC-12-7) measures it before launch; if > 10 min, document the real number and pre-stage a `git revert` playbook. |

## 17. Exit Gate Checklist

- [ ] AC-12-1 … AC-12-13 pass (each [CI] item proven by a named test/artifact; each [OPS] item evidenced in the signoff doc or runbook).
- [ ] `v0.1.0` tagged on the release merge commit and live on prod; tag pushed [OPS]; 24h soak clean.
- [ ] MVP signoff doc completed and committed ("MVP delivered" commit).
- [ ] Post-MVP roadmap committed.
- [ ] CHANGELOG v0.1.0 section published.
- [ ] Help center live at `/help`; articles reachable from dashboard + landing.
- [ ] Beta users migrated onto normal paper-trading (sign-off email sent).
- [ ] Solo on-call active per `docs/oncall.md`.
- [ ] Announcement (internal or soft-public) sent [OPS].

**MVP delivered.** 🎯
