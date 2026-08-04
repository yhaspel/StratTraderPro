# ADR-091 — The walk-forward protocol: windows, OOS concatenation, replay semantics, determinism

**Date:** 2026-07-08
**Status:** Accepted
**Milestone:** M09 — Walk-Forward Backtester
**Reference:** `project-plan/09-walk-forward-backtester.md` §6.0, §6.3, §6.4, §10.1,
§10.5; DoD (deterministic `metrics_hash`); AC-09-4, AC-09-5, AC-09-9, AC-09-12;
ADR-090 (the engines), ADR-092 (the adapter), ADR-080 (`compute_size`)

## Context

A walk-forward backtest is only as trustworthy as the rules it runs by. Two
segments that overlap by one day silently double-count returns; a fill placed on
the signal bar instead of the next bar bakes in look-ahead; a same-bar
stop-and-target that resolves optimistically inflates every result; a sizing path
that diverges from production makes the whole "earn the right to trade live"
premise a lie. None of these are caught by "it runs" — they need the semantics
**written down and pinned by tests before the code**.

This ADR is that written-down protocol. It is the specification the custom replay
engine (`replay_engine.py`), the orchestrator (`wf.py`), and the loader
(`data.py`) implement, and the reference the §10.1 golden-file tests assert
against.

## Decision

### 1. All intervals are half-open `[start, end)` — one convention, everywhere

Every date range in M09 — the loader, the windows, the train/test segments, every
slice — is **half-open**: the start bar is included, the end bar is excluded. This
single rule is what makes train/test and consecutive OOS segments **non-overlap by
construction**: window `w_i`'s test period ends exactly where `w_{i+1}`'s begins,
and because both are half-open the shared boundary date belongs to exactly one of
them.

pandas label slicing is inclusive on the right (`df.loc[a:b]` includes `b`), so
implementations must **not** use naked label slices — they use boolean masks
(`(index >= start) & (index < end)`) or `.loc[start : end - 1 bar]`. The loader,
the sweep engine, and the replay all mask; the `BacktestSegment` train/test date
fields store the half-open boundaries verbatim.

### 2. Window math + the golden worked example

Windows are **calendar days** over daily bars. The orchestrator walks a cursor `t`
from `cfg.start`, stepping by `step_days`, emitting a window whenever a full
train+test span still fits before `cfg.end`:

```python
while t + timedelta(days=train_days + test_days) <= end:
    train_start = start if anchored else t     # anchored grows from start; rolling slides
    train_end   = t + timedelta(days=train_days)
    test_start  = train_end                    # test begins where train ends
    test_end    = train_end + timedelta(days=test_days)
    emit Window(train_start, train_end, test_start, test_end)
    t += timedelta(days=step_days)
```

Trailing days that don't fill a complete train+test window are **dropped** (an
explicit consequence of the loop bound). Runs that yield **< 2 complete windows**
are rejected up front (`VALIDATION_ERROR`); > 60 windows exceed the §11 cap.

**The golden example** (pins the §10.1 fixtures) — `start=2020-01-01`,
`end=2021-01-01`, `train=180`, `test=60`, `step=60`, `rolling` ⇒ **exactly 3
windows**:

| Window | Train `[start, end)` | Test `[start, end)` |
|---|---|---|
| w0 | `[2020-01-01, 2020-06-29)` | `[2020-06-29, 2020-08-28)` |
| w1 | `[2020-03-01, 2020-08-28)` | `[2020-08-28, 2020-10-27)` |
| w2 | `[2020-04-30, 2020-10-27)` | `[2020-10-27, 2020-12-26)` |

The trailing `[2020-12-26, 2021-01-01)` is dropped (a fourth window's train+test
would end 2021-02-24 > `end`). Note **w_i's test start == w_{i-1}'s test end** —
contiguous, zero overlap under half-open intervals. **Anchored** mode produces the
*same* boundaries with every `train_start` pinned to `2020-01-01` (the train window
grows instead of slides).

### 3. The MVP `step_days == test_days` rule

The config carries a `step_days` field, but the MVP **validates
`step_days == test_window_days`** (else 400 `VALIDATION_ERROR`). With half-open
intervals, equal step and test lengths make the test segments **exactly tile** the
OOS timeline — contiguous, gapless, non-overlapping — so the concatenated OOS
curve double-counts nothing. The field is retained for a future
overlapping-window analysis mode; until then it is pinned to `test_days` so the
concatenation guarantee holds by construction rather than by hope.

### 4. OOS concatenation compounds returns — equity does *not* carry across windows

**Each test segment replays from `initial_cash`.** The equity at the end of one
window does **not** become the starting equity of the next. Instead, the
orchestrator stitches the OOS curve in **return space**: it takes each segment's
within-segment daily returns and compounds them into one continuous curve:

```
oos_curve = initial_cash × cumprod(1 + concat(per-segment daily returns))
```

Why return-space and not equity-carry: production sizing (below) is a function of
*current equity*, so if equity compounded across windows, a lucky early window
would inflate position sizes in every later window and the walk-forward would stop
being a fair per-window test. Replaying each segment from the same `initial_cash`
keeps every window's sizing on equal footing; compounding the returns afterward
gives an honest end-to-end OOS equity curve. (This is also why PBO is built from a
*separate* full-range sweep, not from the per-window segments — see ADR-090 §2 and
§6.5.)

### 5. Replay fill semantics (the exactly-specified event loop)

The replay is a **pure** function (no I/O, no RNG — the `RiskProfile` for
production sizing is passed in by the caller). Its rules, in the order the loop
applies them per bar:

- **Entry timing.** A signal evaluated on bar close `t` fills at bar **`t+1`
  open**, adjusted by slippage: buy `open × (1 + bps/1e4)`, sell mirrored. Default
  slippage 5 bp, floor 1 bp.
- **Stops / targets.** From the adapter's `stop_pct` / `target_pct`, evaluated
  **intra-bar** on `t+1…`: a long stop hits if `low ≤ stop`; a target hits if
  `high ≥ target`. Fill at the level — **except on a gap-through**, where the bar
  opened past the level, in which case the fill is at the **open**.
- **Same-bar both-hit → STOP FIRST.** If a bar's range spans both the stop and the
  target, the replay resolves the **stop** (conservative — we assume the adverse
  level was reached first because intra-bar order is unknowable from daily bars).
- **Partial fills.** Fill qty per bar is capped at `volume_participation_pct`
  (default 10%) of that bar's volume. The remainder is re-attempted on subsequent
  bars for at most **5 bars**, after which the unfilled remainder is **cancelled**
  and recorded on the trade (`partial=True`, `cancelled_qty`).
- **Commissions.** `per_order_usd` (default 0) + `per_share_usd × qty` (default 0)
  — Alpaca-style zero-commission default, applied on both entry and exit.
- **Long-only in the MVP.** Adapters emit boolean entries/exits; short signals are
  out of scope.
- **Same-bar entry+exit → no-op.** If a bar has both `entries` and `exits` true,
  nothing happens (there is no meaningful zero-duration trade on daily bars).
- **Force-close at segment end.** Any position still open at the test segment's
  **final bar is force-closed at that bar's close** (with slippage + commission,
  no exemption), so no window leaks an open position into the return series.

Outputs per segment: equity series, drawdown, per-trade records with MFE/MAE from
the in-trade bar extremes, exposure, and turnover — all a deterministic function
of the bars + params.

### 6. Production-sizing hook — same `compute_size`, ATR-14 replicated exactly

With `sizing_mode="production"`, the replay sizes each entry through the **same**
`apps.risk.sizing.compute_size` that `process_alert` uses live (ADR-080), so a
backtest reflects the qty a real alert would have received (AC-09-12). The
`SizingInputs` the replay builds neutralize the live-only feeds the backtest has
no history for:

- `regime_label="NEUTRAL"`, `sentiment_polarity=0.0`, `intraday_dd_pct=0.0` —
  neutralized (the backtest has no regime/sentiment/live-drawdown feed).
- `requested_qty=Decimal("0")` — required by the dataclass but **unread** by
  `compute_size`; a §10.1 test asserts it stays unread, so a future sizing change
  that starts reading it breaks loudly.
- `contract_multiplier=1`, `lot_size=1`, `side="BUY"`.

**ATR-14 must replicate `apps.risk.integration._atr14` EXACTLY** — a **simple mean
of the last ≤ 14 true ranges over the last 15 bars**, **not** Wilder smoothing. If
the replay used Wilder ATR while production uses the simple mean, backtest qty
would silently diverge from live qty and the whole parity guarantee would be
theatre. The replay's `atr14_from_bars` computes the simple mean over `Decimal`
values, and because `_atr14` always reads the latest 15 stored bars (no as-of
parameter), the §10.1 parity test pins the compared trade to the fixture's final
bar so both sides see the same 15 bars.

**Two documented divergences** from live `apply_sizing`, stated here and surfaced
in the UI help text so nobody is surprised:

1. **Profile-less users.** Live `apply_sizing` *skips sizing entirely* for a user
   with no `RiskProfile` (the M04 raw-qty pass-through, ADR-080 §4). The backtest
   instead sizes with **default-profile values** via
   `RiskProfile.objects.get_or_create(user=run.user)` (model defaults, same as the
   risk view's `_get_or_create_profile`). A backtest is analysis, not order flow;
   producing a sized curve for a not-yet-configured user is more useful than
   producing a raw-qty=1 curve, and it is explicit.
2. **`stop_distance`.** Production `apply_sizing` passes `stop_distance=None` (the
   live alert path derives the stop elsewhere). The replay **populates it** from
   the adapter's `stop_pct` (`price × stop_pct`), because in a backtest the
   adapter's stop *is* the known stop. The AC-09-12 parity test excepts this field
   (and the three neutralized fields) and asserts everything else — including the
   identical `_atr14` value — matches, then asserts equal qty through
   `compute_size`.

`fixed_qty_1` mode ignores all of the above and sizes every entry at **1 share**.

### 7. Determinism and the `metrics_hash`

Running the same config twice must yield an **identical** `metrics_hash`
(reproducibility DoD). The hash is **SHA-256 over the canonical report JSON** —
sorted keys, floats rounded to **1e-9** — covering config, per-symbol metrics, the
per-window table, the OOS equity + drawdown series, and the full trade list. The
replay is pure and the sweep's ties break deterministically (param-tuple order),
so identical inputs give byte-identical JSON and therefore an identical hash.

Crucially, the hash must also be **identical across numba JIT-enabled and
JIT-disabled** runs — the CI smoke runs the config both ways (via
`NUMBA_DISABLE_JIT=1`, ADR-090 §6) and compares. On the demo fixture the hash was
**reproducible and identical** across both paths, which is the practical proof
that the JIT compile introduces no numerical drift into the ranked params or the
replayed curve.

## Consequences

**Positive:**

- **No double-counting, no look-ahead, by construction.** Half-open intervals +
  `step == test` tile the OOS timeline exactly; next-bar-open fills + the past-only
  adapter contract (ADR-092) keep signals honest.
- **Conservative where the data is ambiguous.** Same-bar stop-first and
  volume-capped partial fills bias results *pessimistic*, which is the right
  direction for a "earn the right to trade" gate.
- **Backtest sizing == production sizing.** One `compute_size`, an
  exactly-replicated ATR-14, and a non-tautological parity test mean the sized
  curve reflects live behavior — with the two divergences named, not hidden.
- **Reproducible to the bit.** A stable `metrics_hash`, verified JIT-invariant, is
  the foundation for trusting a saved tearsheet.

**Negative / honest limits:**

- **Daily-bar intra-bar resolution is a guess.** Stop-first and gap-through are
  conservative *conventions*, not ground truth — real intra-bar order is unknown
  from daily OHLCV. Documented on the tearsheet cover.
- **Return-space concatenation loses cross-window compounding.** The OOS curve is
  an honest per-window test, not a "what if I'd let it ride" account curve; the two
  are different questions and we answer the former deliberately (§4).
- **The profile-less divergence is a real behavior difference.** A backtest can
  produce sized results for a user whose live alerts would pass through raw — by
  design, and stated in the help copy, but it is a divergence.
- **`step != test` is unimplemented.** Overlapping windows are out of MVP scope;
  the field exists but is pinned equal.

## Alternatives considered

1. **Inclusive `[start, end]` intervals.** Rejected: the shared boundary bar would
   belong to two segments, double-counting one day's return at every window seam.
   Half-open removes the ambiguity entirely.
2. **Carry equity across windows.** Rejected: it couples each window's sizing to
   prior windows' luck and defeats the fair per-window test (§4). Return-space
   concatenation keeps windows independent.
3. **Fill on the signal bar's close.** Rejected: that is look-ahead — you cannot
   act on a close you only know at the close. Next-bar-open is the honest fill.
4. **Resolve same-bar stop+target optimistically (target first).** Rejected:
   unknowable intra-bar order should bias pessimistic, not flatter the strategy.
5. **Wilder-smoothed ATR in the backtest.** Rejected: production uses the simple
   15-bar mean; any different ATR silently breaks sizing parity (§6). The replay
   copies `_atr14` exactly.
6. **Skip sizing for profile-less users (mirror live exactly).** Rejected for the
   backtest: a raw-qty=1 curve is far less useful for analysis than a
   default-profile sized curve, and the difference is explicit. The parity test
   still guards the *sizing math* for users who do have a profile.

## See also

- ADR-090 — vectorbt sweep + custom replay engine choices (the engines this
  protocol runs on)
- ADR-092 — the strategy adapter contract (source of the signals + stops)
- ADR-080 — the pure `compute_size` and its `SizingInputs`/`REGIME_SCALE`
- `backend/apps/backtest/wf.py` — `compute_windows`, `concat_oos`, `walk_forward`
- `backend/apps/backtest/replay_engine.py` — the event loop + `atr14_from_bars` + `build_sizing_inputs`
- `backend/apps/backtest/data.py` — the half-open loader + weekday-coverage rule
- `backend/apps/risk/integration.py` — `_atr14` and `apply_sizing` (the parity target)
- `project-plan/09-walk-forward-backtester.md` §6.3, §6.4, §10.1, §10.5
