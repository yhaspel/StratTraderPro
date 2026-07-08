# StratTraderPro — PROGRESS

> **Canonical project status.** Verified against the actual code, not the plans.
> Update this file with **every development milestone** (phase start/close, AC pass, tag push, scope change) — the rule lives in the project-root `MEMORY.md`.
> Detailed per-task history: `plan-progress-tracker.md`. Milestone specs: this folder. Master plan: `strat-trader-pro.md`.

**Last verified:** 2026-07-05 (full review — every claim below re-checked against code, migrations, tests, and git)
**Verification at HEAD (`264e637`):** backend `pytest` **128 passed** (+4 subtests), `ruff` clean, `bandit` clean (medium+), `ngc --noEmit` clean.

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
| **M06** | **Market data + regime classifier** | ✅ **Implemented (2026-07-07)** — FMP/FRED + Bar store + rule/HMM/ensemble; live keys/backfill/retrain deferred | `v0.6.0-regime` (tag pending) |
| **M07** | **Sentiment pipeline** | ✅ **Implemented (2026-07-07)** — fetchers/tagger/tiered scorers (fakes)/EWMA/API; model weights + benchmark deferred | `v0.7.0-sentiment` (tag pending) |
| **M08** | **Risk engine, sizing & kill switches** | ✅ **Implemented (2026-07-08)** — sizing + 4-level kill switches on `TradingHalt`; staging p99 + Risk Ops "live" deferred | `v0.8.0-risk` (tag pending) |
| M09–M12 | Backtester, admin/audit, hardening, beta | ⏳ Not started | — |

**M04 truth (updated 2026-07-07):** Phase A (IB Gateway spike) done 2026-05-15 (ADR-040). **Phase B–F now implemented** on `feature/m04-webhook-alpaca-paper`: public webhook endpoint + `AlertMessage` + `process_alert`; `BrokerAdapter` protocol + `FakeBrokerAdapter` + `AlpacaAdapter` (paper) with `BrokerAccount`/`TradingHalt`/`BrokerCallAudit`; `Order`/`Fill`/`Position` + `ingest_fill_event` (dedup on `broker_exec_id`); Redis-Stream fill transport + `run_broker_streams` supervisor; Channels `/ws/dashboard/` consumer; `/settings/brokers` + `/dashboard` frontend; `alpaca-py` + `channels`/`daphne` in requirements. Backend gauntlet green (ruff/bandit/191 pytest/migrations/prod-import); CI grep gate + pivot hygiene done. **Deferred (needs externals):** the §10.4 live-Alpaca-paper smoke (runbook committed; operator runs with real keys), the Grafana Trading Ops "live on staging" panel (dashboard JSON committed), and the IBKR password rotation + Railway/GitHub secret deletion (operator step).

## The 2026-07-05 broker pivot

IBKR is out; **Alpaca is the first execution broker**. Why: IBKR Web API consumer approval never cleared for the Interactive Israel account (M04A's hard blocker), and the working-but-interim gateway path demands weekly manual re-auth and one session per process boot. Alpaca has no approval gate: paper keys are self-service and free, transport is REST + `trade_updates` WebSocket via `alpaca-py` (0.43.x, verified current).

- Decision record: `docs/adr/041-alpaca-over-ibkr.md`
- Implementation-ready spec: `04-webhook-ingest-and-ibkr.md` (rewritten; filename kept for link stability)
- Scrapped: M04A — full spec archived at `archived/04A-IBKR-Web-API.md` (scrapped plans move to `project-plan/archived/`)
- IBKR artifacts parked, not deleted (ADR-040, `docker/ib-gateway/`, re-auth runbook, spike script)

## Next steps (ordered)

1. **M04 Phase B — webhook ingest core** (broker-agnostic): `POST /hooks/v1/{user}/{strategy}/` with secret verify + schema + idempotency + halt gate, `AlertMessage`, `process_alert`, `Order`/`Fill`/`Position` models, `FakeBrokerAdapter`. Spec §6.1, §6.3–§6.4.
2. **M04 Phase C — AlpacaAdapter + streams service**: per-user encrypted paper keys, `place_order` via `alpaca-py`, `run_broker_streams` + `FillIngestor`. Spec §6.2, §6.5. *(User action: create an Alpaca account + generate paper keys — self-service, no approval wait.)*
3. **M04 Phase D — dashboard v0 + broker-connect UI + WS client.** Spec §6.6–§6.8.
4. **M04 Phase E/F — pivot hygiene + exit gate**: compose profile for ib-gateway, `TWS_*` scrub + IBKR password rotation, CI grep gate, real-paper smoke (§10.4), Trading Ops dashboard, tag `v0.4.0-alpaca-paper`.
5. **Before M05 starts:** confirm TradeStation sim-API access is actually obtainable, else descope M05 to Order-Lifecycle-only (see M05 review note).
6. **Before M09 starts:** resolve vectorbt AGPL licensing (see M09 review note).
7. **Before M12 live scope:** confirm Alpaca live eligibility for Israeli residents with Alpaca support (paper is unaffected).

## Open items & known debt (carried from review, 2026-07-05)

- `v0.1.1-auth-metrics` tag never pushed (tracker 01.11.15).
- Tracked junk files to `git rm`: `_tmp_14_afb3bf…` (repo root), `frontend/_tmp_14_c77e270e…` (+ untracked " 2"–" 13" Finder duplicates); `gateway-*.png` screenshots in repo root; add `_tmp_*` to `.gitignore`. (Folded into M04 §6.9.)
- ADR-031 wording ("TradingView signs the alert body") is imprecise — TV embeds a static secret; ADR-042 (M04 deliverable) documents the honest semantics.
- Known UI follow-ups from M2.5: env badge hardcoded to "staging" copy; login 401 shows `UNKNOWN` error after refresh-interceptor retry.
- `DJANGO_SETTINGS_MODULE=config.settings.prod` on both staging and prod (only `RAILWAY_ENVIRONMENT_NAME` differs) — consider `staging.py` when they need to diverge.
- M10 §6.5 observability carryover: move `/metrics` out of Django middleware (removes the Sentry `before_send` mitigation), wire postgres/redis/celery exporters, remaining dashboards.
- Master-plan-level gaps flagged in `analysis-cost-and-business-model.md` and now cross-referenced in the plan review notes: billing milestone missing (insert before beta if commercialization is still the goal), vectorbt AGPL, model-artifact storage (no DB pickles), news-source ToS.

## How to re-verify this file's claims

```bash
cd backend && python -m pytest -q && ruff check . && bandit -r apps/ config/ -x tests -q --severity-level medium
cd frontend && npx ngc --noEmit -p tsconfig.app.json
git log --oneline -5 && git tag -l
grep -rn "class.*Adapter" backend/apps/brokers/   # empty until M04 Phase C lands
```
