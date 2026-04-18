# Milestone 08 — Risk Engine, Position Sizing & Kill Switches

> **Week:** 8
> **Duration:** 5 working days
> **Depends on:** M04 (Orders), M06 (Regime), M07 (Sentiment)
> **Unlocks:** M09 (Backtester can borrow sizing primitives)

## 1. Purpose

Wire the three decision inputs — regime, sentiment, and user risk profile — into a coherent pre-trade pipeline that (a) computes correct position size, (b) applies risk gates, and (c) exposes four kill-switch levels with sub-5-second latency. This milestone transforms the raw "alert → order" pipeline of M04 into a defensible risk-aware engine.

## 2. In Scope

- `RiskProfile` CRUD + UI with validation.
- Sizing algorithm per master plan §6.6, wired into `process_alert`.
- Four kill-switch levels:
  - L0 — Per-strategy (user toggle + auto on strategy drawdown).
  - L1 — Per-user global (user toggle + daily-loss auto).
  - L2 — Daily-loss circuit breaker (auto).
  - L3 — Platform admin (admin only; staged to UI in M10 but engine supports it now).
- Auto-flatten logic (wires to broker adapter `flatten_all`).
- Daily-loss watcher beat task every 30s during market hours.
- Soft-stop: size-reduction when intraday drawdown crosses threshold.
- Sizing decision audit trail — every decision persisted with inputs + outputs for later analysis.
- Risk page in dashboard.
- Kill-switch UI controls: per-strategy toggle, global halt button, event log.

## 3. Out of Scope

- Margin/leverage checks beyond buying-power reads from broker (full margin system post-MVP).
- Portfolio-level risk (VaR, correlation caps) — post-MVP.
- Options Greeks sizing — post-MVP.
- Admin UI for platform kill switch (M10 surfaces UI).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-08-1 | User can configure RiskProfile: risk/trade %, max position %, max concurrent, daily-loss $ + %, leverage cap, asset-class allowlist, soft-stop %, hard-stop %. |
| AC-08-2 | Invalid profile rejected (e.g. hard-stop < soft-stop, risk/trade > 5%) with localized messages. |
| AC-08-3 | `process_alert` integrates sizing: computed qty respects ATR-based stop, regime-scaled risk%, sentiment adjustment, position clamps. |
| AC-08-4 | Every order carries a `SizingDecision` row with full inputs → output; queryable via API. |
| AC-08-5 | Regime = CRISIS → sizing returns 0 and order rejects with `REGIME_CRISIS`. |
| AC-08-6 | Regime = BEAR + strategy.side = LONG + sentiment < -0.5 → qty × 0.5 AND user with "strict mode" ON → rejected with `REGIME_SIDE_MISMATCH`. |
| AC-08-7 | User toggling L0 (strategy) kill switch rejects new orders for that strategy within 1s; does not affect others. Optional flatten toggle on the UI flattens strategy-tagged positions only. |
| AC-08-8 | User clicking L1 "Halt my trading" flattens ALL positions and rejects new orders; latency from click to last flatten submit ≤ 5s p99. |
| AC-08-9 | L2 auto triggers at the configured daily-loss threshold; same action as L1; cannot be undone until next trading day UTC-05 rollover (user's effective day boundary). |
| AC-08-10 | L3 platform kill switch (admin-triggered from API) stops all webhook processing globally within 2s; UI banner shows system-wide halt. |
| AC-08-11 | Load test: 50 users simultaneously trigger L1 during a 10-orders/sec traffic pattern; all flatten submissions complete within 10s end-to-end; no orphaned positions. |
| AC-08-12 | Soft-stop kicks in at intraday drawdown ≥ user's `soft_stop_pct`; subsequent orders sized × 0.5; resets at next session. |

## 5. Definition of Done

Baseline DoD applies, plus:

- Deterministic sizing: given pinned inputs, output is byte-identical (property-tested).
- Pre-warm broker session at startup to remove cold-start latency from flatten path.
- Chaos drill: Redis killed mid-L1 — kill switch still flattens via cached broker session.
- Runbook `docs/runbooks/kill-switch-verify-monthly.md` committed and dated.

## 6. Implementation Tasks

### 6.1 RiskProfile model + CRUD

Model defined in master plan Appendix B. Serializer validators:
- `0 < risk_per_trade_pct ≤ 5.0`
- `max_position_pct ≤ 50`
- `max_concurrent ≥ 1`
- `daily_loss_pct ≤ 25`
- `soft_stop_pct < hard_stop_pct`
- `permitted_asset_classes` non-empty

Endpoints:
```
GET  /api/v1/risk/profile/
PUT  /api/v1/risk/profile/
GET  /api/v1/risk/events/?from&to&type
GET  /api/v1/risk/sizing-decisions/?order_id
GET  /api/v1/risk/killswitches/
POST /api/v1/risk/killswitches/  { scope, target_id?, active, reason, flatten?:bool }
```

### 6.2 Sizing algorithm (`apps/risk/sizing.py`)

```python
def compute_size(alert, profile, regime, sentiment, account, instrument) -> SizingResult:
    risk_pct = profile.risk_per_trade_pct * REGIME_SCALE[regime.label]   # CRISIS=0, BEAR=0.3, CHOP=0.6, BULL=1.0
    if profile.strict_mode and regime.label in ('BEAR','CRISIS') and alert.side=='LONG':
        return SizingResult.reject('REGIME_SIDE_MISMATCH')
    stop_dist = max(alert.stop_distance, ATR_FACTOR * instrument.atr14)
    dollar_risk = account.equity * (risk_pct / 100)
    raw_qty = dollar_risk / (stop_dist * instrument.contract_multiplier)

    # clamps
    max_qty_by_pos = account.equity * profile.max_position_pct/100 / instrument.price
    qty = min(raw_qty, max_qty_by_pos)

    # sentiment
    if sentiment.polarity > 0.7 and alert.side == 'LONG':
        qty *= 1.10
    if sentiment.polarity < -0.5 and alert.side == 'LONG':
        qty *= 0.70

    # soft stop
    if account.intraday_dd_pct >= profile.soft_stop_pct:
        qty *= 0.5

    # Kelly damper when history available
    history = TradeHistory.objects.filter(strategy=alert.strategy).count()
    if history >= 100:
        qty *= 0.25 * kelly_fraction(alert.strategy)

    qty = round_to_lot(qty, instrument.lot_size)
    if qty <= 0:
        return SizingResult.reject('SIZING_ZERO')
    return SizingResult.ok(qty, metadata={...})
```

All paths write a `SizingDecision` row.

### 6.3 Kill switch engine (`apps/risk/killswitch.py`)

A single `is_blocked(user_id, strategy_id)` function consults:
1. Platform state (`KillSwitchState(scope='PLATFORM', active=true)`).
2. User state.
3. Strategy state (for this user).
4. Daily-loss state (same as user state but with auto-reset boundary).

Called inside webhook endpoint pre-enqueue AND at the top of `process_alert` (belt-and-suspenders in case the webhook race was lost).

Flatten action: `broker_adapter.flatten_all(reason=<scope>)` using MKT IOC orders; awaited with a 10s budget then degraded to "submitted, not confirmed" state.

Pre-warm broker sessions: on worker startup, authenticate all brokers that have had activity in the last hour; keep sessions alive with heartbeats.

### 6.4 Daily-loss watcher (beat + task)

- Runs every 30s during market hours.
- For each user: compute realized + unrealized P&L for the day using our cached fills and broker position marks.
- If `daily_pnl <= -abs(daily_loss_usd)` OR `daily_pnl_pct <= -daily_loss_pct`: trigger L2.
- Emits `RiskEvent(type='DAILY_LOSS_BREACH', details)`.

### 6.5 Soft-stop

- Same job records intraday max equity; if current equity drops `soft_stop_pct` from that peak, sets a transient flag used by sizing.
- Flag resets at session rollover (user timezone).

### 6.6 Frontend — Risk page

Route: `/risk`:
- Profile editor: fields per §6.1 with inline validation; "Defaults" reset button.
- Active kill switches panel: cards per scope with toggle + "Flatten" secondary option.
- Events feed (paginated `RiskEvent`): type chip, timestamp, details.
- Sizing decisions feed (last 50): shows alert → computed qty → reason, tied to orders.

### 6.7 Frontend — Dashboard kill-switch controls

- Big red "Halt my trading" button (L1) with confirm dialog.
- Per-strategy toggle inline on Strategies page.
- Banner strip across top of dashboard when any kill switch active.

## 7. Tech Stack Notes

- Sizing functions in pure Python with no external I/O besides inputs — easy to unit test and reuse in backtester (M09).
- Kelly fraction computed as the empirical mean / variance of log returns; capped at 0.5; damped × 0.25.
- ATR computed from latest `Bar` rows; cache keyed by `(symbol, tf, date)`.
- Redis pub/sub for kill-switch state changes so workers pick up state without polling.

## 8. Data Model Changes

Migrations:
- `risk.0001_initial` — `RiskProfile`, `SizingDecision`, `RiskEvent`, `KillSwitchState`.

## 9. API Contract Changes

Paths per §6.1. Response error codes: `SIZING_ZERO`, `REGIME_CRISIS`, `REGIME_SIDE_MISMATCH`, `LIMIT_MAX_CONCURRENT`, `LIMIT_POSITION_PCT`, `LIMIT_ASSET_CLASS`, `DAILY_LOSS_BREACH`, `KILL_SWITCH_ACTIVE`.

## 10. Test Plan

### 10.1 Unit tests

- `compute_size` deterministic for fixed inputs.
- All clamp paths exercised.
- Regime scaling table correct.
- Sentiment adjustment bounds.
- Kelly damper only applies past history threshold.
- `is_blocked` truth table across four scopes.

### 10.2 Integration

- Webhook → sized order → broker place, against FakeBroker.
- L1 trigger flattens within budget under traffic.
- L2 auto trigger: inject fake negative P&L → kill switch engages.
- L3 platform halt: set via API → no alerts processed.
- Soft-stop reduces size after threshold reached.

### 10.3 E2E

- User configures profile → sends alert → sized qty matches expected.
- User clicks "Halt my trading" → dashboard banner, fills flatten.
- Strategy toggle rejects future alerts for that strategy only.

### 10.4 Load / Chaos

- Kill-switch latency: 100-order backlog + click L1 → all flatten submissions in ≤ 10s.
- Kill Redis during L1 → sizing + kill path survives via cached broker sessions; audit preserved via Postgres writes.
- Pre-warm test: fresh worker processes flatten within budget on first request.

## 11. Security Considerations

- Kill-switch toggle requires MFA re-prompt for L1 (global halt) to prevent cookie-theft abuse from disabling risk controls without the user.
- Platform admin kill switch requires admin role AND MFA; logged verbosely.
- Sizing inputs (regime, sentiment, account equity) are read from trusted server stores; alerts cannot override sizing parameters directly — they only carry the base `qty` request the user or Pine script wrote.

## 12. Observability

- Prometheus:
  - `sizing_decisions_total{result}`
  - `sizing_reject_reason_total{reason}`
  - `killswitch_trigger_total{scope}`
  - `killswitch_flatten_latency_seconds` histogram
  - `daily_loss_breach_total`
- Alerts:
  - Flatten latency p99 > 5s.
  - Any platform kill switch engagement pages immediately.
  - Repeated sizing rejects (> 20/min for a user) paged for dev review.
- Grafana: **Risk Ops** dashboard.

## 13. Translation & Localization

- Risk form labels keyed `risk.profile.*`.
- Enum values translated: `risk.event.DAILY_LOSS_BREACH`, `risk.switch.STRATEGY`, etc.
- Reject reason codes mapped to translated sentences on the frontend.
- Number formatting respects user's locale for displayed $ + %.
- Risk tooltips contain explanatory guidance ("What is ATR?"); all translated.

## 14. Documentation Deliverables

- `/docs/adr/080-sizing-algorithm.md`.
- `/docs/adr/081-kill-switch-levels.md`.
- `/docs/runbooks/kill-switch-verify-monthly.md` — monthly drill.
- `/docs/runbooks/daily-loss-false-trigger.md`.
- User help: "Setting your risk profile" + "Using the kill switch".

## 15. Rollback Plan

- Feature flag `SIZING_V1_ENABLED`; when off, `process_alert` uses alert-provided qty directly (regressing to M04 behavior).
- Feature flag `KILL_SWITCHES_ENABLED`; when off, only per-strategy on/off toggle is honored.
- Migrations additive.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Sizing computes surprising qty for users | High | Med | Show sizing decision detail before live trading; log all decisions. |
| Kill switch race with in-flight order | Med | High | Order placement guarded by `is_blocked` at three points; broker-side cancel called even after submit. |
| Daily-loss false positive due to stale broker marks | Med | Med | Require two consecutive polls below threshold before triggering. |
| Pre-warm session memory leak | Med | Low | Heartbeat + recycle connections hourly. |
| Admin fat-fingers platform halt | Low | High | Confirmation dialog + require typing `HALT PLATFORM`. |

## 17. Exit Gate Checklist

- [ ] AC-08-1 … AC-08-12 pass.
- [ ] Kill-switch latency p99 ≤ 5s measured on staging.
- [ ] Chaos drill completed (Redis kill + flatten).
- [ ] Risk Ops dashboard live.
- [ ] ADRs 080, 081 committed.
- [ ] Runbooks committed.
- [ ] Tag `v0.8.0-risk`.

Proceed to **M09 Walk-Forward Backtester**.
