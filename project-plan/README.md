# StratTraderPro — Milestone Index

> Breakdown of the master plan (`strat-trader-pro.md`) into 13 implementable milestones, one per week.
> Each milestone has a stand-alone spec covering scope, acceptance criteria, definition-of-done, test plan, i18n, tech-stack notes, security, observability, and exit gate.

## How to use this folder

1. Milestones are sequential. Each milestone lists its **Depends on** and **Unlocks** so you know the critical path.
2. Each file is the authoritative spec for that week. When scope changes mid-week, amend the milestone file, not the master plan.
3. The **Exit Gate Checklist** at the bottom of each file is the go/no-go for moving to the next milestone. Do not advance with open items unless explicitly deferred and logged in the Risk register of the master plan.
4. **Current status lives in [`PROGRESS.md`](./PROGRESS.md)** (canonical, verified-against-code). `plan-progress-tracker.md` keeps the detailed per-task history tables.
5. **2026-07-05 broker pivot:** the first execution broker is **Alpaca**, not IBKR — see `docs/adr/041-alpaca-over-ibkr.md`. `04-webhook-ingest-and-ibkr.md` keeps its filename but now specs the Alpaca integration.
6. **Scrapped plans move to [`archived/`](./archived/)** with a SCRAPPED banner explaining why and what carried over — they are reference material, not work items. Currently there: `04A-IBKR-Web-API.md`.

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
| M11 | [11-hardening-and-load-test.md](./11-hardening-and-load-test.md) | 11 | Hardening + Load Test | OWASP pass, 100-user load, runbooks. |
| M12 | [12-beta-and-signoff.md](./12-beta-and-signoff.md) | 12 | Beta + Signoff | Private beta, bugfix, tag v0.1.0. |


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

- All acceptance criteria met and demo-able on staging.
- Code merged to `main` via PR with at least one review (self-review w/ a written PR narrative acceptable for solo dev — but use the GitHub PR template's checklist).
- ≥ 80% unit-test coverage on new code (enforced by CI).
- No `TODO`/`FIXME` without a linked GitHub issue.
- OpenAPI schema regenerated; frontend types regenerated; no type drift.
- Structured logs + Prometheus metrics added for new code paths.
- Sentry releases tagged; first error triaged within 24h of deploy.
- Relevant Grafana dashboard panels added/updated.
- Docs updated: `/docs/adr/` for architectural decisions, `/docs/runbooks/` for ops, `/docs/api/` for API changes, user-facing help in `/frontend/src/assets/help/`.
- Translation keys extracted; `en.json` populated; no hard-coded strings in components.
- Security: no new `bandit`/`semgrep` findings of MEDIUM+; dependency scan clean.
- Accessibility: `axe-core` audit on new pages passes WCAG 2.1 AA.
- Changelog entry in `CHANGELOG.md` under `[Unreleased]`.

### Branching & release strategy

- Trunk-based with short-lived feature branches: `feat/m04-ibkr-adapter`, `fix/m04-reconnect-storm`.
- One milestone = one release candidate tag on staging (`v0.M.0-rc.1`) with a 24-hour soak before promotion.
- Version tags on `main` cut prod deploys via protected GitHub env.

### Ownership

Solo-dev MVP. For each milestone the "owner" is Yuval. A "reviewer" role exists even for solo — it's the formal second-pass read before the exit gate.
