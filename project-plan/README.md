# StratTraderPro — Milestone Index

> Breakdown of the master plan (`strat-trader-pro.md`) into implementable milestones (M00–M11
> shipped, M12 scrapped, M13 merged, M14 + M15 spec). Each milestone has a stand-alone spec
> covering scope, acceptance criteria, definition-of-done, test plan, i18n, tech-stack notes,
> security, observability, and exit gate.

## How to use this folder

1. Milestones are sequential. Each milestone lists its **Depends on** and **Unlocks** so you know the critical path.
2. Each file is the authoritative spec for that week. When scope changes mid-week, amend the milestone file, not the master plan.
3. The **Exit Gate Checklist** at the bottom of each file is the go/no-go for moving to the next milestone. Do not advance with open items unless explicitly deferred and logged in the Risk register of the master plan.
4. **Current status lives in [`PROGRESS.md`](./PROGRESS.md)** (canonical, verified-against-code). `plan-progress-tracker.md` keeps the detailed per-task history tables.
5. **2026-07-05 broker pivot:** the first execution broker is **Alpaca**, not IBKR — see `docs/adr/041-alpaca-over-ibkr.md`. `04-webhook-ingest-and-ibkr.md` keeps its filename but now specs the Alpaca integration.
6. **2026-07-14 OSS pivot:** StratTraderPro stopped being a hosted service and became open-source, self-hosted software (`PIVOT-TO-OSS.md`). The hosted/beta/prod/counsel tracks are void; M12 was scrapped; the engineering is unaffected. Live specs were amended in place to strike void operator sections while keeping shipped engineering honest.
7. **Superseded material moves to [`archived/`](./archived/)** with a banner explaining its status — reference material, not work items. Two kinds live there:
   - **Scrapped** plans (`❌ SCRAPPED` banner — void premise): `04A-IBKR-Web-API.md`, `12-beta-and-signoff.md`, `analysis-cost-and-business-model.md`, `M10-cowork-followups.md`, `M11-operator-cowork-prompt.md`, `ONE-SHOT-M12.prompt.md`, `ONE-SHOT-M11-OPERATOR-TAIL.prompt.md`, and the `debug-and-verifications/` M04 IB-Gateway spike trail.
   - **Spent** one-shot prompts (`⚙️ SPENT` banner — the agent prompts that built now-shipped milestones, moved out of the active plan on 2026-07-14): the `ONE-SHOT-M04-M08*`, `ONE-SHOT-M09`, `ONE-SHOT-M10`, `ONE-SHOT-M11*`, `ONE-SHOT-REVIEW-FIXES`, `ONE-SHOT-OSS-PIVOT`, and `ONE-SHOT-ACCOUNT-CLEANUP` prompts (the last two archived 2026-07-15).

   No live one-shots remain — every one-shot prompt is now archived. The durable record of shipped work is `PROGRESS.md` + each `M*-EXECUTION-REPORT.md`.

## Milestones

| # | File | Week | Name | Primary outcome |
|---|------|------|------|-----------------|
| M00 | [00-scoping-and-setup.md](./00-scoping-and-setup.md) | 0 | Scoping & Setup | Repo, CI, Railway, `/healthz` green on staging. |
| M01 | [01-auth-foundation.md](./01-auth-foundation.md) | 1 | Auth Foundation | Register, verify, login, JWT, refresh, guards. |
| M02 | [02-mfa-and-user-profile.md](./02-mfa-and-user-profile.md) | 2 | MFA & User Profile | TOTP, backup codes, profile, password change. |
| M03 | [03-strategies-and-webhook-config.md](./03-strategies-and-webhook-config.md) | 3 | Strategies & Webhook Config | Strategy upload, seed import, webhook modal. |
| M04 | [04-webhook-ingest-and-ibkr.md](./04-webhook-ingest-and-ibkr.md) | 4 | Webhook Ingest + Alpaca Paper | End-to-end TradingView → Alpaca paper fill. *(Rescoped from IBKR 2026-07-05, ADR-041; filename kept.)* |
| M05 | [05-tradestation-and-order-lifecycle.md](./05-tradestation-and-order-lifecycle.md) | 5 | Order Lifecycle + Second Broker | Reconciliation, order types/history; TradeStation if access confirmed. |
| M06 | [06-market-data-and-regime.md](./06-market-data-and-regime.md) | 6 | Market Data + Regime | FMP client, HMM + rule classifier, regime UI. |
| M07 | [07-sentiment-pipeline.md](./07-sentiment-pipeline.md) | 7 | Sentiment Pipeline | News ingest, FinBERT, local LLM worker. |
| M08 | [08-risk-engine-and-kill-switches.md](./08-risk-engine-and-kill-switches.md) | 8 | Risk Engine + Kill Switches | Sizing + all 4 kill-switch levels ≤ 5s. |
| M09 | [09-walk-forward-backtester.md](./09-walk-forward-backtester.md) | 9 | Walk-Forward Backtester | vectorbt + backtrader, tearsheet PDF. |
| M10 | [10-admin-audit-observability.md](./10-admin-audit-observability.md) | 10 | Admin + Audit + Observability | Platform kill switch, audit chain, Grafana. |
| M10.5 | [10.5-app-shell-and-operability.md](./10.5-app-shell-and-operability.md) | 10.5 | App Shell & Operability | Unified app shell, nav, help route, first-run checklist. |
| M11 | [11-hardening-and-load-test.md](./11-hardening-and-load-test.md) | 11 | Hardening + Load Test | OWASP pass, 100-user load, runbooks. |
| ~~M12~~ | [archived/12-beta-and-signoff.md](./archived/12-beta-and-signoff.md) | — | ~~Beta + Signoff~~ | **❌ SCRAPPED 2026-07-14 (OSS pivot)** — no hosted beta; salvage folded into WP-2/4/9. |
| M13 | [13-live-trading-switch.md](./13-live-trading-switch.md) | 13 | Live-Trading Switch | **Merged (inert):** `ENABLE_LIVE_TRADING` + admin gate; ships disabled-by-default (D6). |
| M14 | [14-frontend-first-paint.md](./14-frontend-first-paint.md) | 14 | Frontend First Paint | **Spec** — prerender public routes (Option A locked), FCP ≤ 1.2 s. |
| M15 | [15-dashboard-responsiveness.md](./15-dashboard-responsiveness.md) | 15 | Dashboard Responsiveness | **Spec** — deferred authenticated-dashboard speed levers (skeletons, PWA). |


## Cross-cutting conventions

### Translation & Localization (applies to every milestone)

StratTraderPro is **English-only at MVP** but wired for localization from day 1:

- **Backend:** Django's `ugettext_lazy` everywhere user-facing strings appear (error messages, email templates, admin). `LANGUAGE_CODE = 'en-us'`, `USE_I18N = True`, `USE_L10N = True`, `USE_TZ = True`. A `locale/` directory with `en` baseline is committed.
- **Frontend:** `@ngx-translate/core` with JSON language files under `src/assets/i18n/en.json`. Every user-facing string uses the `translate` pipe or `TranslateService`. No hard-coded English in templates.
- **Timezones:** Persist everything in UTC. Render in `USER.timezone` (IANA id, default `America/New_York` for trading context). ISO-8601 on the wire.
- **Numbers / currency:** Render via `Intl.NumberFormat` with the user's locale + account currency (USD in MVP). Always transmit decimals as strings in JSON to avoid float drift.
- **Email templates:** Wrapped in `{% blocktrans %}`; `locale/<code>/LC_MESSAGES/django.po` extracted each release.
- **Accessibility + RTL readiness:** No `dir="ltr"` hard-coded; layouts use logical properties (`margin-inline-start` vs `margin-left`); all icons have `aria-label`.
- **Adding a language post-MVP:** (a) extract `.pot` via `manage.py makemessages -a`; (b) add `src/assets/i18n/<code>.json`; (c) update `ng serve --configuration=<code>` build; (d) add to user profile language dropdown.

### Definition of Done (applies to every milestone unless overridden)

> **2026-07-14 OSS pivot:** the hosted-service DoD items below (staging deploy, Sentry release
> triage, Grafana panels) are now **optional** — they apply only if *you* run those integrations on
> your instance. The engineering bar (tests, coverage, no type drift, security) is unchanged.

- All acceptance criteria met and demo-able locally (or on your own instance).
- Code merged to `main` via PR (fork-and-PR for outside contributors; self-review with a written PR narrative for the maintainer) using the GitHub PR template's checklist.
- ≥ 80% unit-test coverage on new code (enforced by CI).
- No `TODO`/`FIXME` without a linked GitHub issue.
- OpenAPI schema regenerated; frontend types regenerated; no type drift.
- Structured logs + Prometheus metrics added for new code paths.
- *(optional — if you run Sentry)* Sentry releases tagged; errors triaged.
- *(optional — if you run Grafana)* relevant dashboard panels added/updated.
- Docs updated: `/docs/adr/` for architectural decisions, `/docs/runbooks/` for ops, `/docs/api/` for API changes, user-facing help in `/frontend/src/assets/help/`.
- Translation keys extracted; `en.json` populated; no hard-coded strings in components.
- Security: no new `bandit`/`semgrep` findings of MEDIUM+; dependency scan clean.
- Accessibility: `axe-core` audit on new pages passes WCAG 2.1 AA.
- Changelog entry in `CHANGELOG.md` under `[Unreleased]`.

### Branching & release strategy

- Trunk-based with short-lived feature branches: `feat/m04-adapter`, `fix/m04-reconnect-storm`.
- Outside contributions come as **fork-and-PR**; CI must be green before merge to `main`.
- Releases are **git tags** (e.g. `v0.1.0`) on `main`. There is no hosted deploy pipeline — each
  self-hoster deploys their own instance from a tag or from `main`.

### Ownership

Open-source, self-hosted. The maintainer is Yuval; contributions are welcome via fork-and-PR (see
`CONTRIBUTING.md`). A "reviewer" pass before the exit gate is the formal second-read.
