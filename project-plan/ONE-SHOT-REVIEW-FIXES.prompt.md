# ONE-SHOT PROMPT — M04–M08 Post-Implementation Review Fixes (autonomous)

> Paste everything below the line into Claude CLI (max effort), running from the repo root
> `/Users/yuval3000/Documents/Claude/Projects/StratTraderPro`. Self-contained, designed to run end-to-end without
> human input. Operator decisions already made: **admin-merge each PR autonomously**; on a hard blocker,
> **continue best-effort to the next PR** (do not halt the run).

---

## MISSION

An independent adversarial review of the merged M04–M08 implementation (PRs #22–#26, HEAD ≈ `1dc33ef`) found
**2 BLOCKER, 10 HIGH, and ~20 MEDIUM/LOW defects**. You are fixing all of them in **four sequential PRs**:

1. **FIX-1 — Risk engine & kill-switch safety** (branch `fix/m08-risk-safety`) — the money-losing bugs.
2. **FIX-2 — Order/fill pipeline & webhook correctness** (branch `fix/m04-m05-execution-pipeline`).
3. **FIX-3 — Market-data/regime/sentiment data plane** (branch `fix/m06-m07-data-plane`).
4. **FIX-4 — Observability, deps & docs truth-up** (branch `fix/observability-and-docs`).

Every finding below was verified against the code at line level. Line numbers are hints — code may have shifted;
**locate by symbol name and read the surrounding code before editing**. Where a finding includes a *Required fix*,
that design decision is already made — implement it as written. Each fix that changes behavior MUST land with a
regression test that fails on the old code.

## AUTONOMY RULES (same as the M04–M08 run)

- Never stop to ask the user anything. Choose the safest reversible option and log it in the report.
- Anything needing external credentials/staging → skip, document as a manual step, keep going.
- Hard blocker → park that PR (branch pushed, PR open), record it, continue to the next PR.
- Keep updating `project-plan/M04-M08-EXECUTION-REPORT.md` (add a "Review fixes" section) after each PR.

## GROUND TRUTH — read before writing code

1. `project-plan/PROGRESS.md` — canonical status. M00–M08 all shipped; you are fixing, not re-implementing.
2. `project-plan/M04-M08-EXECUTION-REPORT.md` — what was built and what was deferred.
3. Milestone specs `project-plan/04…08*.md` — the AC-xx-n numbers cited below live there.
4. `CONTRIBUTING.md` + `project-plan/README.md` — DoD, conventional commits, squash-merge, Angular 19 rules.
5. `.github/workflows/ci.yml` — CI gates (see CI PARITY below).

## PROJECT GUARDRAILS (hard-won — violating these wastes hours)

- **Local CI-parity gauntlet before every push** (commands in §VERIFY below): ruff + bandit + pytest +
  `makemigrations --check` + prod-import smoke + `ngc --noEmit` + `pnpm build`. pytest+tsc alone is NOT enough.
- **`ngc`, not `tsc`, for Angular templates** (`npx ngc --noEmit -p tsconfig.app.json` from `frontend/`).
- **Settings star-import drops `_`-prefixed names** — if you add a `_helper` to `config/settings/base.py`, name-import
  it in `prod.py` (and `dev.py`), or prod crashes at boot. The prod-import smoke catches this.
- **Frontend package manager is pnpm** (`pnpm install --frozen-lockfile`, `pnpm build`); keep `pnpm-lock.yaml` in sync.
- **Webhook `sig` is a static bearer secret (ADR-042)** — do not "fix" it into an HMAC.
- **CI runtimes: Python 3.12, Node 20.**
- All user-facing frontend strings via `ngx-translate` (`frontend/src/assets/i18n/en.json`).
- New/changed API surface → regenerate OpenAPI (`cd backend && python manage.py spectacular --file ../docs/openapi/openapi.json`)
  then `cd frontend && pnpm run schema:types`. Note the `../` — the repo-root `docs/openapi/openapi.json` is canonical.

## OPERATOR DECISIONS ALREADY MADE (do not re-litigate)

- **D1 — Daily P&L definition (L2):** equity-snapshot based. Persist a day-start equity snapshot per user; daily
  P&L = current broker equity − day-start equity. Never compute "equity" from position notional.
- **D2 — Sizing fail-closed:** if equity or price cannot be determined from a real source, REJECT the order
  (`SIZING_NO_EQUITY` / `SIZING_NO_PRICE`). No hardcoded `100000` / `Decimal("100")` fallbacks — ever.
- **D3 — Trading-day boundary:** `America/New_York` calendar date via `zoneinfo` (DST-correct), replacing the fixed
  UTC-5 offset. Amend ADR-081 to note the deviation from AC-08-9's literal "UTC-05" wording (faithful-to-intent).
- **D4 — L0 flatten:** until per-strategy position tagging exists, `flatten=true` with `scope=STRATEGY` is rejected
  with 400 `FLATTEN_UNSUPPORTED_SCOPE`. L0 halt (block new orders) still works. Never flatten the whole account on L0.
- **D5 — Broker routing:** an alert that names a broker the user hasn't connected is REJECTED
  (`BROKER_NOT_CONNECTED`), never silently routed to another broker.
- **D6 — Price source for sizing:** `price_hint` (limit price) → broker latest-trade quote (new optional adapter
  method) → fresh `Bar` (same-day) → reject `SIZING_NO_PRICE`.
- **D7 — Tags:** create local tag `v0.8.1-review-fixes` at the end (NOT pushed). Add a report warning that the five
  unpushed milestone tags (`v0.4.0`…`v0.8.0`) point at pre-fix commits — deploy from `v0.8.1-review-fixes` instead.

---

# PR FIX-1 — `fix/m08-risk-safety` — Risk engine & kill-switch safety

## 1.1 [BLOCKER] Daily-loss L2 measures lifetime unrealized P&L, not daily P&L — false-trips AND misses real losses
`backend/apps/risk/killswitch.py` — `user_daily_pnl()` (~line 151) sums `(market_price − avg_cost) × qty` over all
open `Position` rows (lifetime unrealized, no day anchor, no realized fills) and calls gross open notional
`Σ|market_price·qty|` "equity". Consequences: a swing position at −$1,200 unrealized trips L2 **every day**, and after
`release_expired_l2_halts()` releases at rollover the watcher re-trips ~60s later → permanent lockout while holding
any loser beyond threshold; a day-trader with −$5k realized but flat positions never trips; the `daily_loss_pct` gate
divides by position notional, not account equity. `DailyLossTests.test_two_poll_breach_trips_l2` encodes the wrong
semantics as expected behavior — rewrite it.

**Required fix (D1 + D3):**
- New model `risk.DailyEquitySnapshot(user FK, trading_day DateField, equity Decimal, created_at)` with
  `unique_together (user, trading_day)`. Migration `risk.0002`.
- `trading_day()` uses `datetime.astimezone(ZoneInfo("America/New_York")).date()` (delete `_DAY_OFFSET`).
- In the `daily_loss_watcher` sweep, per user: read live broker equity (sum of `adapter.get_account().equity`
  across CONNECTED accounts — equity field added in 1.2). First successful read of a trading day →
  `get_or_create` the snapshot. Then `daily_pnl = current_equity − snapshot.equity`;
  `daily_loss_pct = daily_pnl / snapshot.equity × 100`.
- Broker equity read fails → **skip the check for that user this poll** (log + `daily_loss_check_skipped_total`
  counter). Never fall back to notional or a constant.
- Keep the two-poll confirmation and the active-L2 short-circuit. The re-trip loop disappears because a new day gets
  a fresh snapshot baseline.
- Tests (use `freezegun`): trip on real intra-day equity drop; NO trip for stale unrealized loss carried into a new
  day (snapshot resets baseline); DST boundary — a halt tripped 2026-11-01 (EDT) releases on the correct NY calendar
  day after the 2026-11-01→11-02 EST transition; skip-on-broker-failure.

## 1.2 [HIGH] Sizing "equity" is margin buying power (2–4× oversizing)
`backend/apps/risk/integration.py` (~78): `equity = adapter.get_account().buying_power`. Alpaca `buying_power` is
2× equity (4× PDT). **Fix:** add `equity: Decimal` to the `Account` DTO (`backend/apps/brokers/base.py`); map it in
`backend/apps/brokers/alpaca/mapping.py:map_account` from `TradeAccount.equity` (present in alpaca-py 0.43.5);
`FakeBrokerAdapter` sets `equity` explicitly (keep tests meaningful: make fake `buying_power = 2 × equity` so any
regression to buying_power is caught); TradeStation mapping uses its equity field or documented closest equivalent.
Use `.equity` in `apply_sizing` and in 1.1's watcher.

## 1.3 [HIGH] Sizing falls back to fictional $100,000 equity and $100 price
`backend/apps/risk/integration.py` (~79–82): `except Exception: equity = RISK_DEFAULT_EQUITY (100000)` and
`price = price_hint or _latest_price(symbol) or Decimal("100")`. Every prod MKT order today is sized against a
$100 fantasy price. **Fix (D2 + D6):** delete both fallbacks and the `RISK_DEFAULT_EQUITY` setting. Equity read
failure → sizing result `REJECT` reason `SIZING_NO_EQUITY`. Price resolution: `price_hint` → new optional adapter
method `get_latest_price(symbol) -> Decimal | None` (Alpaca: `StockHistoricalDataClient` +
`StockLatestTradeRequest`, constructed from the account's existing keys, wrapped in `_call` audit like other calls;
Fake: returns its configured mark; TradeStation: return `None` for now) → same-day `Bar` close → reject
`SIZING_NO_PRICE`. Record `equity` and `price` in `SizingDecision.inputs` (AC-08-4 "full inputs"). Emit
`RiskEvent.Type.SIZING_REJECT` on every sizing reject (the enum exists but is never emitted). Tests for both reject
paths + the price-resolution ladder.

## 1.4 [HIGH] L0 "flatten this strategy" liquidates the user's ENTIRE account
`backend/apps/risk/views.py` (~129–137) passes `flatten=d.get("flatten")` for `scope=STRATEGY` into
`trigger_halt` → `flatten_user()` (`killswitch.py` ~122) which **ignores `strategy_id`** and calls
`adapter.flatten_all()` on every account. **Fix (D4):** in the view, `scope=STRATEGY` + `flatten=true` → 400
`FLATTEN_UNSUPPORTED_SCOPE` (i18n'd message in the risk UI); remove the unused `strategy_id` parameter from
`flatten_user` or make it raise if passed; add a `docs/runbooks/kill-switch-verify-monthly.md` note + ADR-081
amendment ("strategy-scoped flatten deferred until positions are strategy-tagged"). Also fix the adjacent
`flatten=d.get("flatten", False) or scope == "USER"` line: keep USER auto-flatten (spec'd L1 semantics) but make it
explicit and commented. Test: STRATEGY+flatten → 400, no broker call (assert FakeBroker received no `flatten_all`).

## 1.5 [MEDIUM] Releasing L1/L3 requires no MFA (only engaging does)
`backend/apps/risk/views.py` (~122–127): `if active and not verify_mfa_code(...)`. A hijacked session can silently
release a halt and resume trading. **Fix:** require MFA for USER/PLATFORM both directions (drop the `active and`).
Frontend: the release action on `/risk` must prompt for the TOTP code the same way engage does (extend the existing
M