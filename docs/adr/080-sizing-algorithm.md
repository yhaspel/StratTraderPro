# ADR-080 — A pure, deterministic position-sizing function

**Date:** 2026-07-08
**Status:** Accepted
**Milestone:** M08 — Risk Engine, Position Sizing & Kill Switches
**Reference:** `project-plan/08-risk-engine-and-kill-switches.md` §6.2 (the sizing
algorithm), §11 (security — trusted inputs), §12 (observability); master plan
§6.6; AC-08-3, AC-08-4, AC-08-5, AC-08-6, AC-08-12

## Context

M08 has to turn three independent server-side signals — the market **regime**
(M06), the symbol/market **sentiment** (M07), and the user's **risk profile** —
plus the account's live equity into a single number: *how many shares/contracts
should this alert actually trade?* M04 shipped a straight pass-through — the qty
the Pine script or user wrote on the alert became the order qty. That is fine as
a floor but it ignores every risk input we now compute.

The sizing step is on the **hot path** of `process_alert` and it is the one
number a user is most likely to question ("why did it buy 40 and not 100?"). Two
properties matter more than cleverness here:

- **It must be explainable and reproducible.** Every decision has to be
  reconstructable from its inputs, both for the user-facing sizing-decision feed
  (AC-08-4) and so the M09 walk-forward backtester can replay the *exact* sizing
  a live alert would have gotten.
- **It must not be steerable by the alert.** The alert is attacker-adjacent
  input (it arrives over a webhook). If an alert could set the risk percentage,
  the position cap, or the regime, the whole risk engine would be theatre.

## Decision

Ship sizing as a **single pure function**,
`compute_size(inputs, profile) -> SizingResult`, in
`backend/apps/risk/sizing.py`. It performs **no I/O** — every value it needs
arrives in a frozen `SizingInputs` dataclass, and it returns a frozen
`SizingResult` (`ok`, `qty`, `reason`, `meta`). All gathering of inputs, all
database reads, and the `SizingDecision` audit write live *outside* the function,
in `backend/apps/risk/integration.py::apply_sizing`. The function itself is a
deterministic transform: same inputs ⇒ byte-identical output (AC-08-4, DoD
"deterministic sizing").

### 1. The pipeline, step by step

`compute_size` runs a fixed sequence. The order is load-bearing — the two reject
gates run **first**, then the arithmetic, then the multiplicative adjustments,
then the lot rounding and the zero check:

1. **Normalize the regime.** `label = regime_label.upper()`;
   `scale = REGIME_SCALE[label]`, defaulting to **0.6** for any unrecognized
   label (fail-safe: an unknown regime sizes like CHOP, never like BULL).
2. **Classify the side.** `is_long` iff the side is one of
   `{LONG, BUY, BUY_TO_OPEN, BUY_TO_CLOSE}`.
3. **Strict-mode gate (AC-08-6).** If `profile.strict_mode` and
   `label ∈ {BEAR, CRISIS}` and `is_long` → **reject `REGIME_SIDE_MISMATCH`**.
   This is checked *before* the CRISIS gate, so a strict-mode long in CRISIS
   reports the mismatch, not the crisis.
4. **CRISIS gate (AC-08-5).** If `label == CRISIS` or `scale <= 0` → **reject
   `REGIME_CRISIS`**. Sizing is halted entirely; no order.
5. **Regime-scaled risk budget.** `risk_pct = profile.risk_per_trade_pct × scale`.
6. **Stop distance.** `atr_stop = profile.atr_factor × atr14`;
   `stop_dist = max(alert stop_distance, atr_stop)`. If that is still ≤ 0 (no ATR
   and no alert stop), fall back to **2% of price** (`_DEFAULT_STOP_FRAC`). Price
   is floored at `0.01` to avoid divide-by-zero.
7. **Dollar risk → raw qty.** `dollar_risk = equity × risk_pct/100`;
   `raw_qty = dollar_risk / (stop_dist × contract_multiplier)`.
8. **Position-size clamp.**
   `max_qty_by_pos = equity × profile.max_position_pct/100 / price`;
   `qty = min(raw_qty, max_qty_by_pos)`. No single position exceeds the user's
   equity cap regardless of how tight the stop is.
9. **Sentiment adjustment (long only).** If `sentiment_polarity > 0.7` → `× 1.10`
   (lean in on strong positive sentiment); if `sentiment_polarity < -0.5` →
   `× 0.70` (trim on negative). Shorts get no sentiment tilt.
10. **Soft-stop reduction (AC-08-12).** If `intraday_dd_pct ≥ profile.soft_stop_pct`
    → `× 0.5`.
11. **Round to lot.** `qty = floor(qty / lot_size) × lot_size` — always rounds
    *down*, never up into a bigger position than the math allows.
12. **Zero check.** If `qty ≤ 0` → **reject `SIZING_ZERO`**; otherwise **accept**
    with the computed qty.

Every accept/reject carries a `meta` dict recording the intermediate values
(`regime_scale`, `risk_pct`, `stop_dist`, `raw_qty`, `max_qty_by_pos`,
`sentiment`, `soft_stop_applied`) — this is what gets persisted on the
`SizingDecision.inputs` field and rendered in the user's sizing-decision feed, so
every number above is auditable after the fact.

### 2. The regime scale table

`REGIME_SCALE` maps the M06 ensemble label (ADR-060 §3) onto a multiplier on the
user's per-trade risk:

| Regime label | Scale | Reads as |
|---|---:|---|
| `BULL` | **1.0** | full risk budget |
| `NEUTRAL` | **0.6** | reduced |
| `CHOP` | **0.6** | reduced (same as NEUTRAL — churn, not trend) |
| `BEAR` | **0.3** | heavily reduced |
| `CRISIS` | **0.0** | sizing halted → `REGIME_CRISIS` |
| *(unknown)* | **0.6** | fail-safe default = CHOP |

The scale is the *only* place the regime enters sizing, and CRISIS is expressed
as a hard 0.0 that the CRISIS gate turns into an explicit reject rather than a
silent zero — so the reason code is `REGIME_CRISIS`, not `SIZING_ZERO`.

### 3. Reject codes are first-class outputs

Three of the plan's error codes (§9) originate here, each a distinct, testable
branch:

| Code | Cause | Gate |
|---|---|---|
| `REGIME_SIDE_MISMATCH` | strict mode + BEAR/CRISIS + long | step 3 |
| `REGIME_CRISIS` | CRISIS regime (scale 0) | step 4 |
| `SIZING_ZERO` | qty rounded/clamped to ≤ 0 | step 12 |

A reject is not an error — it is a *decision*. `apply_sizing` persists a
`SizingDecision(result=REJECT, reject_reason=…)` and increments
`sizing_reject_reason_total{reason}`; the caller turns it into a rejected order
with that reason code, exactly like any other pre-trade gate.

### 4. "No RiskProfile → raw qty" preserves M04 behavior

Sizing is **opt-in per user**. `apply_sizing` returns `None` — and the caller
falls back to the alert-provided qty — in two cases:

- The `SIZING_V1_ENABLED` flag is off (§15 rollback → regress to M04
  pass-through).
- The user has **no `RiskProfile`** row.

A user who has never configured risk keeps the M04 pipeline unchanged: their
alert's qty is placed as written. Sizing only ever engages once a user has
deliberately created a profile. This makes the milestone strictly additive and
the rollback a one-flag flip.

### 5. Alerts cannot override sizing parameters (§11)

The security property the plan calls out (§11) is structural, not a check:
`compute_size` reads its risk parameters **only** from `profile` (a trusted
server-side `RiskProfile` row) and its market inputs **only** from trusted
stores, assembled by `apply_sizing`:

- **regime** ← latest `RegimeObservation(scope="MARKET")`,
- **sentiment** ← latest `SentimentScore` for the symbol, then market,
- **equity** ← a fresh `adapter.get_account().buying_power` read, with a
  conservative configured fallback (`RISK_DEFAULT_EQUITY`) on a broker hiccup,
- **price / ATR** ← our own `Bar` rows (ATR14 computed from the last 15 daily
  bars).

The alert contributes only the *base request* — `symbol`, `side`, and the
requested `qty` (which sizing recomputes anyway). There is no field on the alert
that reaches `risk_per_trade_pct`, `max_position_pct`, the regime, or the
sentiment. A hostile webhook payload cannot dial its own position up.

### 6. Why pure and deterministic

The function is a pure transform for three concrete payoffs:

- **Property-testable.** Determinism is asserted directly
  (`test_deterministic`), and each branch — regime scaling, the position clamp,
  the sentiment boost/cut, the soft-stop halving, the CRISIS/mismatch rejects —
  is exercised in isolation because none of them need a database.
- **Reusable by the M09 backtester.** The plan (§6, "Unlocks") specifies M09
  borrows the sizing primitives. Because `compute_size` has no I/O, the
  backtester can feed it historical `SizingInputs` and get the *exact* qty a live
  alert would have received on that date — no live-vs-backtest sizing skew.
- **Auditable.** The `meta` dict makes every intermediate value inspectable, so a
  surprising qty (Risk §16) can be explained from the stored decision without
  re-running anything.

## Consequences

**Positive:**

- **One number, fully reconstructable.** Given the stored `SizingDecision.inputs`
  and the profile, the output qty is reproducible byte-for-byte — the basis for
  both the user-facing feed and the M09 replay guarantee.
- **Additive and reversible.** No profile (or flag off) ⇒ unchanged M04
  behavior; the whole milestone rolls back on one env flag.
- **Not steerable.** Risk parameters and market inputs come from trusted server
  stores only; the alert cannot move its own size (§11).

**Negative / honest limits:**

- **The Kelly damper is deferred.** The master-plan algorithm (§6.2) ends with a
  `× 0.25 · kelly_fraction` step gated on ≥ 100 historical trades for the
  strategy. That needs the M09 `TradeHistory` table, which does not exist yet, so
  it is **intentionally omitted** — the function ships without it and picks it up
  in M09. Nothing downstream assumes it.
- **The live intraday-drawdown feed into soft-stop is not yet wired.** The
  soft-stop reduction (step 10) is implemented and unit-tested via the pure
  function (`test_soft_stop_halves`), but `apply_sizing` currently passes
  `intraday_dd_pct = 0.0`. The plan's §6.5 peak-equity watcher that would compute
  a live intraday drawdown per user and feed it in is not connected on the sizing
  path, so soft-stop does not fire on live orders yet. The gate is proven; its
  live input is pending.
- **ATR quality depends on bar coverage.** ATR14 is computed from our own daily
  `Bar` rows; a thinly-covered symbol falls back to the 2%-of-price stop, which
  is deliberately conservative but coarse.

## Alternatives considered

1. **Keep M04 pass-through and gate only on regime/kill switches.** Rejected: the
   whole point of M08 is that the qty itself becomes risk-aware; a gate-only
   design leaves the position-size decision with the alert author.
2. **Compute size inline in `process_alert`.** Rejected: it would bury the
   arithmetic behind I/O, make it un-property-testable, and make it impossible for
   M09 to reuse without dragging in the webhook stack. The pure-function seam is
   exactly what lets both call sites (live + backtest) share one implementation.
3. **Ship the Kelly damper now with a stubbed history.** Rejected: a stub would
   make the sizing non-reproducible against real M09 history and encode a
   fraction with no data behind it. Deferring it keeps the shipped function honest.

## See also

- ADR-081 — the kill-switch levels that gate this pipeline before it runs
- ADR-060 — the regime ensemble that produces the `REGIME_SCALE` label input
- `backend/apps/risk/sizing.py` — the pure function + `REGIME_SCALE`
- `backend/apps/risk/integration.py` — input gathering, the `SizingDecision`
  write, and the no-profile / flag-off fallback
- `backend/apps/risk/models.py` — `RiskProfile`, `SizingDecision`
- `project-plan/08-risk-engine-and-kill-switches.md` §6.2, §11, §12
