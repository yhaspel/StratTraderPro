# Milestone 05 — TradeStation + Order Lifecycle

> **Week:** 5
> **Duration:** 5 working days
> **Depends on:** M04 (Webhook + IBKR)
> **Unlocks:** M06 (Market Data + Regime)

## 1. Purpose

Prove out the broker-adapter abstraction by shipping a second implementation (TradeStation simulator) behind the same protocol and ensure both brokers behave symmetrically through a unified `orders` domain. Add a proper reconciliation loop, extended order types (LMT/STP/STP_LMT + TIF), and asset-class support for options, futures, and ETFs.

## 2. In Scope

- `TradeStationPaperAdapter`: OAuth2 authorization_code flow, REST order placement, WebSocket streaming fills.
- Unified `OrderRequest` supporting stocks, ETFs, options (OPRA symbol format), futures.
- Reconciliation Celery beat job every 5 min comparing our `Position` / `Order` tables to broker truth.
- Orders page in frontend with filters (date range, broker, strategy, status).
- Broker picker on `Send order` path (from webhook): route to user's default broker unless alert specifies; selection UI on webhook modal too.
- Drift-healing logic: if we think we're flat but broker holds a position, open a "drift alert" audit event and lean toward broker truth after confirming twice.
- Paper → Live mode switch in broker UI, **gated by a feature flag** (`ENABLE_LIVE_TRADING=false` until M12 gate passes).

## 3. Out of Scope

- Advanced order types (OCO, bracket) — deferred to v0.2.
- Real-time market data for dashboard marks (comes in M06).
- Sophisticated sizing or regime gating (M06–M08).
- Live trading enablement (post-MVP).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-05-1 | A user can complete TradeStation OAuth flow from the dashboard; refresh tokens stored encrypted; account list populated. |
| AC-05-2 | Sending a TV webhook routes to the user's chosen broker (default or alert-specified); order is placed on that broker only. |
| AC-05-3 | Both IBKR paper and TradeStation sim can be connected simultaneously by the same user. |
| AC-05-4 | Order types MKT / LMT / STP / STP_LMT round-trip correctly on both brokers and are reflected in `Order.status` transitions. |
| AC-05-5 | Options alerts (`asset_class=OPTION`, `symbol=AAPL_240119C00150000` OPRA) and futures alerts (`ES-NQ-YM-RTY` root, expiry) place correctly on both brokers. |
| AC-05-6 | Reconciliation task runs every 5 min; detects a deliberately-injected drift and emits a `RECON_DRIFT` audit event + heals toward broker truth. |
| AC-05-7 | Orders page lists orders with pagination, filters, and deep-linking; exports CSV on demand. |
| AC-05-8 | `BrokerAccount.mode` switch to `LIVE` is rejected (403 + `LIVE_TRADING_DISABLED`) until feature flag is on AND user has accepted a versioned disclaimer. |
| AC-05-9 | Flatten a specific broker's positions without affecting the other broker. |
| AC-05-10 | End-to-end demo: same alert → two users, two different brokers → two correct paper fills in parallel. |
| AC-05-11 | Reconnect storm (TS WebSocket drops 5 times in 60s) is handled with exponential backoff; no duplicate fill ingestion. |

## 5. Definition of Done

Baseline DoD applies, plus:

- Both adapters share ≥ 80% test cases (parameterized suite).
- OAuth refresh token rotation handled transparently; no user re-login needed within 90 days.
- Runbook `docs/runbooks/tradestation-oauth-recover.md` committed.
- OpenAPI shows both broker `connect` request schemas.

## 6. Implementation Tasks

### 6.1 TradeStation adapter (`apps/brokers/tradestation`)

- Base URL (sim): `https://sim-api.tradestation.com/v3/`; (live): `https://api.tradestation.com/v3/` — not used in M05.
- OAuth2 authorization_code:
  - `GET /api/v1/brokers/tradestation/oauth/start/` returns consent URL.
  - Callback `/api/v1/brokers/tradestation/oauth/callback/?code=...&state=...` exchanges for access+refresh; persists encrypted.
  - Refresh flow on every API call — decorator `@ts_auth_refresh`.
- REST calls: `GET /accounts/`, `POST /orderexecution/orders`, `GET /orderexecution/orders/{id}`, `DELETE /orderexecution/orders/{id}`.
- WebSocket stream: `wss://sim-api.tradestation.com/v3/marketdata/stream` + order events stream; re-connect with backoff (`tenacity`).
- Map OPRA symbol input into TS option symbol conventions (documented in code).
- Futures: TS uses `@ES` style — adapter translates from our canonical (`ES` + expiry month + year).

### 6.2 Unified OrderRequest + converter

```python
@dataclass
class OrderRequest:
    broker_account_id: UUID
    symbol: str               # canonical
    asset_class: Literal['STOCK','ETF','OPTION','FUTURE']
    option: OptionContract | None   # strike, expiry, call/put
    future: FutureContract | None   # root, expiry
    side: Literal['BUY','SELL','BUY_TO_OPEN','SELL_TO_OPEN','BUY_TO_CLOSE','SELL_TO_CLOSE']
    qty: Decimal
    order_type: Literal['MKT','LMT','STP','STP_LMT']
    limit_price: Decimal | None
    stop_price: Decimal | None
    tif: Literal['DAY','GTC','IOC']
    client_order_id: str
    strategy_id: UUID
```

Each adapter exposes `to_broker_payload(req: OrderRequest) -> dict` and `from_broker_ack(resp) -> OrderAck`.

### 6.3 Reconciliation (`apps/orders/reconcile.py`)

Celery beat every 5 min:
1. For each user with any connected broker:
   - Fetch positions from broker via `list_positions()`.
   - Compare to our `Position` rows (by `(symbol, asset_class, option_id)`).
   - If diff > tolerance (0.01 shares / 1 contract): emit `ReconEvent`.
2. After second consecutive drift, call `heal_toward_broker()` — update our `Position` to match broker; do NOT place corrective orders automatically.
3. If a detected drift persists > 30 min, page ops.

### 6.4 Orders page (`/orders`)

- Server-paginated table (25/page) with columns: time, broker, strategy, symbol, side, qty, type, status, fills, P&L.
- Filters: date range (default today), broker, strategy, status.
- Click row → detail drawer with full lifecycle events (submit → ack → partial → fill → complete), broker codes, raw payload (masked).
- Export CSV respects filters.

### 6.5 Broker picker in webhook modal

- Per-strategy default broker dropdown added to M03's modal.
- Alert payload may include `"broker": "IBKR"` to override at alert time.

### 6.6 Feature flag — live mode

- Global flag `ENABLE_LIVE_TRADING` (default false).
- Per-user flag `user.live_trading_enabled` (default false); set only after explicit opt-in flow that lands post-MVP.
- UI: if disabled, `Mode: LIVE` radio shows disabled with "Live trading coming in v0.2" tooltip.
- Server enforces regardless of UI state.

## 7. Tech Stack Notes

- **TradeStation API v3** REST + WS — no official Python SDK; we build a thin client in `brokers/tradestation/client.py` using `httpx` + `websockets`.
- **tenacity** for backoff.
- **pyOAuth-like** flow implemented explicitly; refresh token re-wrap on expiry.
- **Adapter base class** — both adapters inherit common utilities (client_order_id generation, encrypted creds handling, audit emission).

## 8. Data Model Changes

Migrations:
- `orders.0002_extended_order_types` — new columns `asset_class`, `option_expiry`, `option_strike`, `option_right`, `future_root`, `future_expiry`; indexes.
- `brokers.0002_tradestation` — TS-specific fields (expires_at, scope).

## 9. API Contract Changes

New / modified:
```
GET  /api/v1/brokers/tradestation/oauth/start/    returns consent URL
GET  /api/v1/brokers/tradestation/oauth/callback/ internal; redirects to /settings/brokers
GET  /api/v1/orders/?broker&strategy&status&from&to&page
GET  /api/v1/orders/{id}/
GET  /api/v1/orders/export.csv?...
POST /api/v1/brokers/{id}/mode/  { mode: PAPER|LIVE }
GET  /api/v1/reconciliation/events/?from&to
```

## 10. Test Plan

### 10.1 Unit tests

- Order symbol conversion: canonical ↔ IBKR ↔ TradeStation for stocks, ETFs, options, futures with tricky cases (BRK.B, root `ES` Dec 2026).
- OAuth refresh: expired token triggers refresh, succeeds transparently.
- OAuth refresh permanent failure surfaces `BROKER_REAUTH_REQUIRED`.
- Reconcile diff detection & healing logic.

### 10.2 Integration (parameterized across both adapters)

For each `adapter in [IBKR, TradeStation]`:
- `place_order_market_buy_goes_to_filled`
- `place_order_limit_stays_open_until_price`
- `cancel_order`
- `flatten_all`
- `stream_fills` emits in-order, no dupes
- `disconnect_reconnect_reestablishes_stream`

### 10.3 E2E (Playwright)

- `broker.tradestation.connect.spec.ts` — OAuth flow stubbed with test IdP.
- `orders.list.spec.ts` — filtering, pagination, CSV export.
- `broker.mode.live.spec.ts` — switching to LIVE is denied in M05.
- `multi.broker.alert.spec.ts` — alert flows into chosen broker only.

### 10.4 Load

- 20 alerts/sec mixed across 2 brokers / 3 strategies / 5 users for 5 min: p95 end-to-end < 2s; reconciliation converges within 2 cycles.

### 10.5 Security

- OAuth state+PKCE enforced; replay attacks rejected.
- Refresh tokens encrypted; test asserts.

## 11. Security Considerations

- TS access + refresh tokens encrypted with the same envelope pattern as M04.
- OAuth `state` param signed + single-use via Redis.
- PKCE code_verifier used to mitigate auth-code interception.
- CSRF unnecessary on OAuth callback — signed state.
- WebSocket JWT on dashboard side; TS WS uses TS's own auth header.
- Masked raw order payload in order detail drawer (never show secrets or full account numbers).

## 12. Observability

- Prometheus:
  - `reconcile_drifts_total{broker,kind}`
  - `reconcile_heals_total`
  - `oauth_refresh_total{result}`
  - `order_state_transitions_total{from,to,broker}`
  - `broker_ws_reconnects_total{broker}`
- Alerts:
  - Drift persists > 30 min.
  - OAuth refresh failure rate > 5% / hr.
  - WS reconnects > 10/hr.
- Grafana **Trading Ops** dashboard gets per-broker panels + reconciliation panel.

## 13. Translation & Localization

- Order status enums mapped to translated labels: `orders.status.PENDING_SUBMIT`, `orders.status.FILLED`, etc.
- OAuth error codes mapped to translated explanations; avoid exposing raw TS messages to end users.
- CSV exports use ISO-8601 timestamps + USD formatting; future multi-currency planned via profile currency (currently USD).
- Option symbol render uses locale-aware month names in detail drawer.

## 14. Documentation Deliverables

- `/docs/adr/050-broker-adapter-abstraction.md`.
- `/docs/adr/051-reconciliation-policy.md`.
- `/docs/runbooks/tradestation-oauth-recover.md`.
- `/docs/runbooks/reconcile-drift-investigation.md`.
- User help: "Connect your TradeStation account", "Reading the Orders page".

## 15. Rollback Plan

- Feature flag `BROKER_TRADESTATION_ENABLED` hides TS in UI and returns 503 on its endpoints.
- Migrations additive; rollback drops new columns after emptying.
- Reconcile job can be toggled off via Celery beat config if producing false positives.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| TS rate limit hit during burst alerts | Med | Med | Client-side token bucket; retry with jitter; surface rate-limit to user. |
| Adapter symbology mismatch (esp. options) | Med | High | Extensive unit tests; canonical format documented in ADR. |
| Reconcile triggers oscillation (heal → broker updates → drift again) | Low | Med | Two-consecutive-cycle confirmation before heal. |
| Refresh token revoked silently by TS | Low | Med | Sentry alert + UI banner "Reconnect TradeStation"; non-blocking for IBKR users. |

## 17. Exit Gate Checklist

- [ ] AC-05-1 … AC-05-11 pass.
- [ ] Parameterized adapter suite green on both brokers.
- [ ] Multi-broker E2E demo recorded.
- [ ] Reconciliation runbook validated with a deliberate drift.
- [ ] Live-trading gate verified (unreachable via UI + API).
- [ ] Changelog entry.
- [ ] Tag `v0.5.0-tradestation`.

Proceed to **M06 Market Data + Regime**.
