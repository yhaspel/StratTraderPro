# M13 — Paper ⇄ Live trading switch (Alpaca)

**Status:** SPEC — implementation landed behind `ENABLE_LIVE_TRADING=false` (inert).
**Supersedes:** M11 §3's "Live-trading enablement (v0.2+; `ENABLE_LIVE_TRADING=false` stays)".
**Owner:** Yuval
**Created:** 2026-07-13

---

## 0. The one-paragraph version

`BrokerAccount.Mode` (PAPER|LIVE) already exists in the model. What does not exist is any way to
*reach* LIVE: the Alpaca adapter hard-codes `TradingClient(paper=True)`, `connect()` hard-codes
`is_paper=True`, and `looks_like_live_key()` rejects any `AK`/`BK`-prefixed key outright. M13 makes
mode a real, per-account, immutable property that the adapter honours — gated behind a global
`ENABLE_LIVE_TRADING` flag AND an MFA step-up, with the UI screaming about it. **Shipping this code
does not turn live trading on.** Flipping the flag does, and that is a human decision with
prerequisites (§6).

---

## 1. Why this is a milestone and not a config toggle

Four gates, only one of which is code:

1. **Alpaca live eligibility for Israeli residents is UNCONFIRMED.** `MEMORY.md` §2 says to check
   with Alpaca support *before any live scope*. If Alpaca will not open a live account, this entire
   milestone is dead and should not be built further than the flagged-off code. **This is the
   cheapest gate and it must be answered first.**
2. **The risk controls have almost no proven runtime.** `daily_loss_watcher` — the beat-scheduled
   circuit breaker — **never executed in production** until BUG-011 was fixed on 2026-07-11, and the
   alert that should have caught that was itself paused (BUG-009). Beat is verified running as of
   2026-07-13, but the L2 breaker has never actually stopped anything.
3. **The kill switch has never been load-tested.** M11 §7.4/§7.5 (Locust + chaos drills) are still
   un-run. `docs/slo.md` claims kill-switch flatten p99 ≤ 5s. That number is currently **unproven**,
   and it is precisely the control that matters when real money is moving.
4. **Legal.** `docs/legal/terms-of-service.md` states *"Mode in force: **PAPER TRADING ONLY** —
   `ENABLE_LIVE_TRADING=false`. No real money moves."* and is not counsel-approved.

## 2. Frozen decisions

- **F-1. Mode is per-`BrokerAccount`, chosen at connect time, and IMMUTABLE thereafter.**
  There is no "flip this account to live" button. To trade live you *connect a new account* with
  live keys. Rationale: a mutable switch means an account's historical orders/fills/positions can no
  longer be trusted to be paper — the audit trail becomes ambiguous. Immutability keeps every row
  attributable to exactly one mode for its whole life.
- **F-2. Three independent conditions must ALL hold to create a LIVE account:**
  (a) the live gate is open (F-2a), (b) MFA step-up re-auth on the connect call,
  (c) an explicit typed confirmation from the client (`confirm: "LIVE"`).
  No single env var, and no single compromised session, is sufficient.

- **F-2a. The live gate is `env AND db-override` — asymmetric by design.**
  `ENABLE_LIVE_TRADING` is registered `mutable=True, dangerous=True`, so
  `admin_portal.flags.is_enabled()` resolves a **DB override first** and falls back to env.
  There are therefore two readings of "the flag", and using either one alone is a bug:

  | Read only… | Failure |
  |---|---|
  | `settings.ENABLE_LIVE_TRADING` | The admin-portal **OFF** switch reports success and does nothing. The platform keeps trading real money. (BUG-011 shape.) |
  | `is_enabled(...)` | A **database write alone** arms real-money trading — no deploy, no review, no env change. |

  The effective gate is the **AND** of both, exposed as
  `apps.brokers.live_gate.live_trading_permitted()`. **Nothing may read the flag any other
  way.** This yields the only correct asymmetry for a dangerous flag:
  **hard to arm** (requires a deliberate, deployed, reviewed env change) and
  **instant to revoke** (DB override, no redeploy).
- **F-3. The adapter derives the endpoint from the account, never from a global.**
  `TradingClient(paper=(mode == PAPER))`. A PAPER account stays on `paper-api.alpaca.markets`
  **even when the global live flag is on**. The flag is a *permission to create* live accounts, not
  a mode.
- **F-4. Key-shape validation becomes mode-aware, and stays fail-closed.**
  Live-looking keys (`AK`/`BK`) on a PAPER account → reject (unchanged, this is the existing
  `LIVE_KEYS_FORBIDDEN` guard, and it is what stops a mistaken paste). Paper-looking keys on a LIVE
  account → reject too (`BROKER_PAPER_KEYS_ON_LIVE`): a live account that silently trades paper is
  just as much a lie as the reverse.
- **F-5. Risk controls are NOT optional on a live account.** A LIVE account with no `RiskProfile`,
  or with `daily_loss_usd = 0` (the documented "no USD limit" escape hatch), is refused at connect
  time. Paper may run unguarded; live may not.
- **F-6. `ENABLE_LIVE_TRADING` stays `false` in every committed config,** including
  `.env.example`, compose, and both Railway environments. Turning it on is an operator act,
  recorded, with §6 satisfied.

## 3. Scope

- `BrokerAccount.mode` honoured end-to-end: connect → adapter → order submit → streams.
- Mode-aware key validation (F-4).
- MFA step-up + typed confirmation on live connect (F-2).
- Risk-profile precondition on live connect (F-5).
- `broker_account_mode` label on the execution metrics + an audit event on live connect.
- UI: mode picker at connect, permanent unmissable LIVE affordance, typed confirm dialog.

## 4. Out of scope

- TradeStation live (Alpaca only).
- Options / crypto / futures (US equities + ETFs, as M04).
- Alpaca OAuth / Broker API.
- Any change to the sizing, regime or sentiment engines.

## 5. Acceptance criteria

| # | AC | Kind |
|---|---|---|
| AC-13-1 | With `ENABLE_LIVE_TRADING=false`, `POST /brokers/accounts` with `mode=LIVE` returns **503 `FEATURE_DISABLED`**; no account row is created. | CI |
| AC-13-2 | With the flag on, creating a LIVE account **without** MFA step-up returns 403; **without** `confirm:"LIVE"` returns 400. | CI |
| AC-13-3 | A PAPER account resolves to `paper-api.alpaca.markets` **even when `ENABLE_LIVE_TRADING=true`** (F-3). Asserted on the constructed client, not on a comment. | CI |
| AC-13-4 | A LIVE account resolves to the live endpoint and `ConnectionInfo.is_paper == False`. | CI |
| AC-13-5 | Live-shaped keys on a PAPER account → `BROKER_LIVE_KEYS_FORBIDDEN`. Paper-shaped keys on a LIVE account → `BROKER_PAPER_KEYS_ON_LIVE`. (F-4, both directions.) | CI |
| AC-13-6 | `mode` is rejected on update — `PATCH` of an existing account's mode is a 400 (F-1). | CI |
| AC-13-7 | Creating a LIVE account with no `RiskProfile`, or `daily_loss_usd = 0`, is refused (F-5). | CI |
| AC-13-8 | A `broker.live_account_connected` audit row is written, with the account id and the acting user. | CI |
| AC-13-9 | The dashboard and the brokers page render a persistent, non-dismissable LIVE indicator when any live account exists. | CI (a11y+visual) |
| **AC-13-11** | **The FILL STREAM follows the account's mode**: a LIVE account constructs `TradingStream(paper=False)`; a PAPER account constructs `TradingStream(paper=True)`. Asserted on the flag actually handed to `TradingStream`. | **CI — see §5a** |
| AC-13-12 | Revoking the DB override while `ENABLE_LIVE_TRADING=true` **stops** live order submission *and* refuses to open a LIVE stream (`BROKER_LIVE_TRADING_DISABLED`). | CI |
| AC-13-13 | Setting the DB override to `true` while `ENABLE_LIVE_TRADING=false` does **not** enable live trading (F-2a). | CI |
| AC-13-14 | `get_account()` on a LIVE account returns `Account.is_paper == False` (the broker-truth DTO must not lie about mode). | CI |
| AC-13-15 | Building an adapter for a **TradeStation** account with `mode=LIVE` raises `BROKER_LIVE_TRADING_DISABLED`. Out-of-scope must FAIL, not silently mislabel. | CI |
| AC-13-10 | **Kill-switch L1 flatten against LIVE-*mode* accounts (on the fake-broker seam) completes within the SLO (p99 ≤ 5s) under the M11 load, proving the flatten SLO holds and the `BrokerAccount.mode → BrokerContext.mode` plumbing does not break the kill-switch path. NB: the Alpaca *live endpoint* is never exercised — `fake_broker_patch` replaces `build_adapter` wholesale, so `AlpacaAdapter` never runs.** | ✅ **MEASURED 2026-07-14 — PASS (p99 0.169s)**, `docs/ops/load-test-results.md` |

### 5a. Why AC-13-11 is the most important row in this table

The first implementation pass made the *order* path mode-aware and left
`alpaca/streams.py` hard-coded to `paper=True`. That combination is **worse than not
shipping live trading at all**:

> A LIVE account would place **real orders** through the live REST endpoint, while its
> `trade_updates` socket stayed subscribed to the **paper** endpoint. Real fills would never
> arrive. `ingest_fill_event` would never run. Positions, realised P&L and equity would
> silently diverge from the broker's actual state — and `daily_loss_watcher`, the L2 circuit
> breaker and the kill switch would all go on making decisions about **a portfolio that does
> not exist**.

And it would conceal itself: `broker_stream_heartbeat_age_seconds` stays fresh (the paper
socket is alive and healthy), so `BrokerStreamSilent` never fires. A dead fill pipeline that
reports itself green is this project's signature failure mode — BUG-008, BUG-009, BUG-011 are
all the same animal. It must not be reintroduced on the one code path where the money is real.

**A second, related trap:** `streams.BrokerStreamSupervisor._context_for()` built its
`BrokerContext` **without `mode`**, so it silently defaulted to `PAPER`. Making
`_build_stream()` mode-aware while leaving that line alone produces a fix that is completely
inert — and a test that only checks `_build_stream()` in isolation would still pass.
**The endpoint is only ever as correct as the context that reaches it.** Any test for AC-13-11
must exercise the supervisor's real context construction, not a hand-built one.

## 5b. Coexisting with the M12 paper-only beta

M12 §3 states: *"Live trading enablement (v0.2; `ENABLE_LIVE_TRADING` stays `False`)."* M12 runs a
3–5 user **paper** beta (AC-12-1/2/3) and ships `v0.1.0`. Once M13 merges, that beta runs on a build
that **contains the live-trading code path**, and the only thing between beta users and real-money
execution is the flag.

"The flag is off" is currently a *convention*. This project has been bitten — twice — by a control
that was assumed to be in force and was not (BUG-009: rules paused; BUG-011: workers running the
wrong process, both reporting healthy). A convention is not a control. Two ACs make it one:

| # | AC | Kind |
|---|---|---|
| **AC-13-16** | **CI fails if `ENABLE_LIVE_TRADING` is committed as true** (`true`/`True`/`1`/`yes`) in any tracked config: `.env.example`, `docker-compose*.yml`, `config/settings/*.py`, `infra/`, workflows. Mirrors the existing `block-legacy-ibkr-creds` guard. Docs/plans allowlisted. | CI |
| **AC-13-17** | **When the gate is closed the LIVE option is ABSENT from the UI, not merely disabled or erroring.** No mode picker, no live affordance — the connect form is exactly what it is today. A beta user in a paper-only beta must never see a control that implies real-money trading exists. (Precedent: M10.5 *hid* the unconfigured Google button rather than shipping one that dumped users on raw JSON; the flag-off TradeStation button is disabled **with** a "not yet available" note.) | CI |

AC-13-17 also protects the legal position: the ToS in force during M12 says **PAPER TRADING ONLY**.
Showing a LIVE control under those terms is a contradiction, even if clicking it 503s.

## 6. Enablement prerequisites (ALL must be true before `ENABLE_LIVE_TRADING=true` anywhere)

1. ☑ **Alpaca live-account eligibility — CONFIRMED (2026-07-13, operator).** An Israeli national can
   open and fund an Alpaca live account. This gate is closed; `MEMORY.md` §2's "unconfirmed — check
   with Alpaca support" note is now stale and should be corrected.
   *(Keep whatever written confirmation exists with the compliance record — this is the kind of thing
   an auditor asks for later, and "we checked once" is not evidence.)*
2. ☑ M11 §7.4 load test + §7.5 chaos drills **RUN 2026-07-14** (all PASS), and AC-13-10 (kill-switch
   flatten under load) **passes against LIVE-mode accounts on the fake-broker seam** — p99 0.169s
   (≤5s). Proves the flatten SLO + mode plumbing; the live Alpaca endpoint is deliberately not
   exercised (see AC-13-10 note). **Gate 2 satisfied for the SLO/plumbing dimension** — the live
   endpoint itself is validated separately by AC-13-01..09/14/15 (CI) + prod bring-up.
3. ☐ `daily_loss_watcher` has ≥ 30 days of unbroken production execution, evidenced by
   `up{job="beat"} == 1` continuity and at least one *deliberately provoked* L2 trip in staging.
4. ☐ Counsel has approved a ToS/Privacy revision that removes "PAPER TRADING ONLY" and states the
   real-money risk; `seed_terms` bumped to a new version so **every user must re-accept**.
5. ☐ Backups + restore drill re-verified (`scripts/restore-drill.sh`) against the live-mode schema.
6. ☐ A written go/no-go, in `docs/oncall.md`, naming who can flip the flag back off.

**Until every box is ticked, the correct value is `false`.** The code shipped in M13 is inert and
safe to merge with the boxes empty — that is the point of building it behind the flag.

---

## 7. Dependencies — can M13 be built independently of the M11 tail and M12?

**Split the question. BUILDING M13 is independent. ENABLING it is not.**

### 7.1 Implementation — INDEPENDENT ✅

M13 can be implemented, reviewed and merged **now**, without waiting for anything:

| Pending work | Blocks M13 implementation? | Why not |
|---|---|---|
| M11 PART C (R2 / GDPR export) | **No** | Touches `apps/users` export storage. Zero overlap with `apps/brokers`. |
| M11 PART D (DB password rotation) | **No** | Pure ops. No code. |
| M11 PART E (Lighthouse FCP) | **No** | A measurement, not a change. |
| M11 PART F (`seed_terms` / legal) | **No** *(blocks ENABLEMENT — see 7.2)* | Different app; no shared code path. |
| M11 PART H (prod bring-up) | **No** | Infra. And `ENABLE_LIVE_TRADING = env.bool(..., default=False)` **fails safe**: a brand-new prod project that never sets the var is automatically paper. |
| M12 (beta + `v0.1.0`) | **No** | M12 is release management + beta ops. It *assumes* `ENABLE_LIVE_TRADING=False`, which M13 respects by default and AC-13-16 now enforces in CI. |

### 7.2 Enablement — HARD-BLOCKED on the M11 tail ⛔

Turning the flag on is **not** independent. §6 gates map directly onto pending M11 work:

- **§6 gate 2** needed M11 **§7.4 load test + §7.5 chaos drills** — **RUN 2026-07-14, all PASS**
  (`docs/ops/load-test-results.md`, `docs/ops/chaos-drill-logs.md`). AC-13-10 measured: kill-switch
  flatten **p99 0.169s** (≤5s) against LIVE-mode accounts under the M11 load — the SLO and the mode
  plumbing hold. The kill switch is the control that matters most once money is real. **Caveat kept
  explicit:** this proves latency + plumbing, not the Alpaca live endpoint (fake-broker seam); the
  live path is covered by AC-13-01..09/14/15 (CI) and prod bring-up, not by this load test.
- **§6 gate 4** needs a counsel-approved ToS revision + a `seed_terms` version bump — **that is M11
  PART F**. It cannot be skipped: the ToS currently in force says *"PAPER TRADING ONLY — no real money
  moves."*
- **§6 gate 5** needs the restore drill re-verified.
- **§6 gate 1** (Alpaca eligibility for the operator's jurisdiction) is independent of all milestones
  and is the cheapest — do it first, because a "no" from Alpaca makes gates 2–6 wasted effort.

And note M12 is itself blocked: its stated hard gate is *"prod Railway env live … terms-acceptance
flow shipped"* — i.e. **M11 PART H + PART F**.

### 7.3 Recommended order

```
Alpaca eligibility check ──────────────────┐  (do this NOW; it can invalidate everything below)
                                           │
M11 tail (C, D, E, F, H) + load/chaos ─────┼──► M12 paper beta ──► v0.1.0
                                           │
M13 code (merged, flag OFF, CI-guarded) ───┘            │
                                                        ▼
                                          §6 gates all green ──► ENABLE_LIVE_TRADING=true ──► v0.2
```

M13 code can land **in parallel** with the M11 tail. It simply must not be *armed* until the tail,
the drills and the legal work are done.

### 7.4 The real coupling is merge-order, not dependency

Three pieces of frontend all touch `ShellComponent`:

- M11 PART F — the blocking **terms-gate modal**
- M12 — the **"Give feedback"** button
- M13 — the persistent **LIVE indicator** (AC-13-9)

These are **merge conflicts to sequence, not dependencies**. Land whichever is ready and rebase the
others. Nothing in M13's backend touches M11 or M12 code at all.
