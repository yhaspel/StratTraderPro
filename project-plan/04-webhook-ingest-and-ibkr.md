# Milestone 04 — Webhook Ingest + Broker Adapter + IBKR Paper

> **Week:** 4
> **Duration:** 5 working days
> **Depends on:** M03 (Strategies & Webhook Config), M02 (MFA)
> **Unlocks:** M05 (TradeStation + Order Lifecycle)

## 1. Purpose

Make the pipeline live end-to-end in paper mode for the first broker: a TradingView alert hits our public webhook, passes HMAC + schema validation, enqueues to Celery, flows through a minimal risk gate, routes to the IBKR paper adapter, places an order, receives a fill, and surfaces in a real-time dashboard widget. No sentiment, no regime, no sizing sophistication yet — those compound in later milestones.

## 2. In Scope

- Public webhook endpoint `POST /hooks/v1/{user_uuid}/{strategy_uuid}/` with HMAC verify, idempotency, Celery dispatch.
- `BrokerAdapter` protocol + `FakeBrokerAdapter` (test double) + `IBKRPaperAdapter`.
- IBKR paper infra: IB Gateway running as a sidecar on Railway `worker` service; IBC for auto-login against paper credentials.
- Per-user broker account connection (store encrypted credentials; only paper in M04).
- Order placement flow: map alert → internal `OrderRequest` → adapter `place_order` → persist `Order` + `Fill` → push WebSocket event.
- Dashboard widget: live open positions + today's fills.
- Minimal kill-switch hooks (per-user + per-strategy) implemented at reject-new-orders level (full kill switch in M08 — here we only check the flag; we don't auto-flatten yet).

## 3. Out of Scope

- TradeStation (M05).
- Sophisticated sizing / regime / sentiment (M06–M08).
- Live trading mode — PAPER only in M04.
- Full reconciliation loop (lightweight one-shot check only; proper scheduler in M05).
- Options and futures (stocks + ETFs only in M04; other asset classes M05–M08).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-04-1 | A correctly-signed alert to a user's webhook URL is accepted with 200 within 300ms p95. |
| AC-04-2 | An alert with a bad `sig` field returns 401; no order placed; audit row written. |
| AC-04-3 | An alert with valid sig but a payload that fails the user's JSON schema returns 400 with error detail. |
| AC-04-4 | Duplicate `idempotency_key` within 24h returns 200 with a `duplicate=true` indicator; no second order placed. |
| AC-04-5 | If the user's global kill switch is on, the endpoint returns 200 but the order is rejected with `reason=USER_HALTED`; audit row written. |
| AC-04-6 | User can connect an IBKR paper account (account id + credentials) via dashboard; creds stored encrypted; connection test returns 200. |
| AC-04-7 | On a valid alert, an equity market order is placed on IBKR paper and the broker's order id is stored; the fill event is captured and stored as `Fill`. |
| AC-04-8 | Dashboard positions widget updates within 2s of the fill via WebSocket. |
| AC-04-9 | A `flatten_all` call (triggered manually for this milestone from a debug button) places closing orders for all open positions; all positions reach flat within 10s. |
| AC-04-10 | End-to-end test from `send_webhook()` fixture to `position_created` WebSocket event completes in ≤ 5s locally. |
| AC-04-11 | IBKR adapter auto-reconnects after a deliberate network drop and reports status via `/api/v1/brokers/{id}/status/`. |
| AC-04-12 | No broker credentials, HMAC secrets, or order PII appear in logs. |

## 5. Definition of Done

Baseline DoD applies, plus:

- IBKR adapter behind a feature flag; can be disabled globally without redeploy.
- IB Gateway sidecar documented in runbook with start/stop, re-auth steps.
- OpenAPI schema includes webhook endpoint (using custom post-processor since it's unauth from DRF's perspective but HMAC-auth'd).
- The "hello world" e2e flow is a Playwright-scripted demo that can be rerun at any time.

## 6. Implementation Tasks

### 6.1 Backend — Broker adapter protocol (`apps/brokers`)

```python
class BrokerAdapter(Protocol):
    name: str
    supported_asset_classes: list[str]

    def connect(self, creds: EncryptedCreds) -> ConnectionInfo: ...
    def disconnect(self) -> None: ...
    def get_account(self) -> Account: ...
    def list_positions(self) -> list[Position]: ...
    def list_open_orders(self) -> list[Order]: ...
    def place_order(self, req: OrderRequest, client_order_id: str) -> OrderAck: ...
    def cancel_order(self, broker_order_id: str) -> None: ...
    def flatten_all(self, reason: str) -> list[OrderAck]: ...
    async def stream_fills(self) -> AsyncIterator[Fill]: ...
    def health(self) -> BrokerHealth: ...
```

`FakeBrokerAdapter` implements the protocol for tests. It exposes a `script` for predetermining fills, slippage, rejects.

### 6.2 Backend — IBKR adapter (`apps/brokers/ibkr`)

- Library: `ib_insync`.
- Connection: `ib_insync.IB().connect(host, port, clientId, account)` against IB Gateway on `localhost:4002` (paper).
- IB Gateway sidecar: Docker image based on `ghcr.io/ibcalpha/ibc` (or maintained fork) + Java 17.
  - Container command: `./IBCLinux-3.*.sh --gateway` with paper credentials from env.
  - Healthcheck: TCP on port 4002.
  - Auto-restart on 2FA / nightly reauth via `IBC` scripted login.
- Credentials per user: encrypted in DB; decrypted into env of a per-user Gateway process; processes pooled by Celery worker (one active user session per worker at a time; serialized by Redis lock per user).
  - For 10–50 users this pool-of-one works; multi-replica handled by deterministic routing: hash(`user_id`) → worker.

Methods:
- `connect` — starts a Gateway session for user; waits up to 30s for login.
- `place_order`: build `Stock(symbol, 'SMART', 'USD')` or `ETF` contract; `MarketOrder` or `LimitOrder`; `outsideRth=False` by default.
- `stream_fills`: subscribes to `execDetailsEvent` → convert to `Fill` DTO → push to Redis Stream `fills:user:{id}`.
- `flatten_all`: walks positions, issues MKT opposite-side orders with IOC, tracks acks.
- `health`: queried every 30s.

### 6.3 Backend — Webhook endpoint (`apps/webhooks`)

Router attached **outside** `/api/v1` to avoid auth middleware:

```python
urlpatterns = [
    path('hooks/v1/<uuid:user_id>/<uuid:strategy_id>/', WebhookView.as_view()),
]
```

`WebhookView.post` pseudocode:
```
body = request.body
sig = extract_sig(body_json)
wc = WebhookConfig.objects.get(user_id=user_id, strategy_id=strategy_id)
if not hmac_verify(body_without_sig, sig, wc.secret): return 401
if not jsonschema.validate(body, wc.json_schema): return 400
if redis.setnx("idem:"+idem_key, "1", ex=86400) is False: return 200 {duplicate=true}
if kill_switch_active(user_id) or kill_switch_active(strategy_id): write_audit("REJECTED"); return 200
alert = AlertMessage.objects.create(user=..., strategy=..., body=..., received_at=now())
process_alert.delay(alert.id)
return 200
```

Response is always small (< 1 KB) and fast. TradingView timeout is 3s; we return well under 300ms.

Celery task `process_alert(alert_id)`:
1. Hydrate alert + user + strategy + broker account.
2. Build `OrderRequest` (stocks/ETFs only in M04 — reject others with `UNSUPPORTED_ASSET`).
3. Skip sizing (use alert's `qty` verbatim for this milestone; sizing pipeline wires in M08).
4. Call broker adapter `place_order`.
5. Write `Order` + audit row.
6. Push WebSocket event `order.created`.

### 6.4 Backend — Orders app minimal (`apps/orders`)

Models:
- `Order(...)` per master plan Appendix B — `status` enum starts with {`PENDING_SUBMIT`,`SUBMITTED`,`FILLED`,`PARTIAL`,`CANCELLED`,`REJECTED`}.
- `Fill(order, qty, price, ts, broker_exec_id)` — immutable.
- `Position(user, broker_account, symbol, qty, avg_cost, updated_at)` — derived but persisted for dashboard speed.

A `FillIngestor` Celery task reads Redis Stream `fills:user:{id}` and upserts `Fill` + refreshes `Position`.

### 6.5 Backend — Channels / WebSocket

- `apps/dashboard/consumers.py` — `DashboardConsumer(AsyncJsonWebsocketConsumer)`.
- URL `/ws/dashboard/` — requires JWT on query string + MFA enforcement.
- Group-per-user: `dashboard.user.{user_id}`.
- Events emitted this milestone: `order.created`, `order.updated`, `fill.created`, `position.updated`, `broker.status`.

### 6.6 Frontend — broker connection

Route: `/settings/brokers`:
- List connected brokers with status badge (Connected / Disconnected / Error).
- Add broker: picker (IBKR only in M04), account id + username + password fields.
- Test connection button → hits `/api/v1/brokers/{id}/test-connection/`.
- Remove broker (requires MFA re-prompt).

### 6.7 Frontend — dashboard v0

Route: `/dashboard`:
- Open positions grid (columns: symbol, qty, avg cost, mark, unrealized P&L).
- Today's fills feed.
- Broker status indicator.
- WebSocket live updates — reducer patterns in signal stores.
- Debug "Send test alert" (dev env only) calls a fixture endpoint that simulates a webhook.

### 6.8 Frontend — WebSocket client

`core/services/ws.service.ts`:
- Connects on auth, re-connects with exponential backoff.
- Dispatches messages into relevant signal stores.
- Heartbeat every 25s.

## 7. Tech Stack Notes

- **`ib_insync`** over raw TWS API — massively better DX.
- **IB Gateway** (not TWS) — headless, lighter.
- **IBC** for auto-login in the sidecar.
- **Django Channels 4** with Daphne (ASGI) and Redis channel layer.
- **`hmac.compare_digest`** for constant-time comparison.
- **Structured alert logging** — log message envelope includes `alert_id`, `user_id_hash`, `strategy_id`, but NEVER body JSON or secret.

## 8. Data Model Changes

Migrations:
- `webhooks.0001_initial` — `AlertMessage(id, user, strategy, body_json (with sig redacted), received_at, status)`.
- `brokers.0001_initial` — `BrokerAccount(id, user, broker, mode, creds_encrypted, nickname, is_default, last_connected_at)`.
- `orders.0001_initial` — `Order`, `Fill`, `Position`.

## 9. API Contract Changes

New paths:
```
POST /hooks/v1/{user}/{strategy}/              (public; HMAC-auth'd)
GET  /api/v1/brokers/                          list user brokers
POST /api/v1/brokers/                          add broker
GET  /api/v1/brokers/{id}/
DELETE /api/v1/brokers/{id}/
POST /api/v1/brokers/{id}/test-connection/
GET  /api/v1/brokers/{id}/status/
POST /api/v1/brokers/{id}/flatten/             (admin-enabled debug in M04, full in M08)
GET  /api/v1/orders/                           list with filters
GET  /api/v1/positions/                        live snapshot
GET  /api/v1/fills/                            list
WS   /ws/dashboard/                            JWT via query param
```

## 10. Test Plan

### 10.1 Unit tests

- HMAC verification with valid/invalid/tampered payloads.
- Idempotency: second identical key returns duplicate.
- Kill switch short-circuits order creation.
- `FakeBrokerAdapter` scripted fills produce `Fill` rows and update `Position`.
- OrderRequest validation rejects unsupported asset classes in M04.

### 10.2 Integration

- Webhook → Celery → FakeBroker → Fill → Position pipeline with Postgres + Redis + Channels.
- Broker creds encryption roundtrip.
- WebSocket emits `order.created`, `fill.created` in order.

### 10.3 E2E (Playwright + stubbed IBKR)

- Connect paper IBKR (mocked at Gateway boundary) → dashboard shows Connected.
- Trigger simulated TV alert via test helper → watch dashboard update in real time.
- Flip kill switch → next alert rejected.

### 10.4 Live against real IBKR paper (manual, one-shot)

- Boot full staging stack with IB Gateway sidecar.
- Use real paper creds.
- Send an alert from a test TradingView alert URL.
- Assert the paper account shows the position.
- Document any IBKR quirks in a runbook.

### 10.5 Load tests

- 10 alerts/sec for 2 min, FakeBroker: p95 end-to-end < 1s; no drops.
- 50 alerts from 10 concurrent users against FakeBroker: p99 < 2s.

### 10.6 Resilience tests

- Kill Redis mid-pipeline: Celery retries; no duplicate orders because idempotency key is in Postgres as secondary guard.
- Kill IB Gateway mid-place: adapter surfaces `BROKER_DISCONNECTED`; order marked `REJECTED` with reason; audit trail complete.

## 11. Security Considerations

- Webhook endpoint is **unauthenticated** at the JWT layer — HMAC is the only auth. This is expected but we add:
  - Per-user rate limit (60/min) before reading body.
  - Max body size 16 KB.
  - Optional IP allowlist (off by default).
  - Refuse non-`application/json` content types.
- No PII or secrets in logs; `sig` field stripped before persisting `AlertMessage.body_json`.
- Broker credentials encrypted with user-bound envelope (user-specific DEK wrapped by the platform KEK).
- IB Gateway sidecar container has its own restricted IAM; no host mounts except the creds tmpfs.
- CORS unchanged — the webhook endpoint is not called by the browser.

## 12. Observability

- Prometheus:
  - `webhook_received_total{result}`
  - `webhook_latency_ms` histogram
  - `order_submit_latency_ms` histogram
  - `broker_connect_total{broker,result}`
  - `broker_disconnects_total{broker}`
  - `fills_ingested_total`
- OpenTelemetry traces: `webhook.post` → `alert.process` → `broker.place_order` → `fill.ingest`.
- Alerts:
  - Webhook 5xx > 1% over 5 min.
  - Broker disconnect > 2 min.
  - `order_submit_latency_ms` p95 > 2s.
- Grafana: **Trading Ops** dashboard created.

## 13. Translation & Localization

- Error responses (i18n'd) returned under codes like `WEBHOOK_HMAC_BAD`, `WEBHOOK_SCHEMA_INVALID`, `ORDER_UNSUPPORTED_ASSET`. Frontend maps code → translated message.
- Broker connection UI copy keyed `brokers.*`.
- Dashboard widget labels keyed `dashboard.positions.*`, `dashboard.fills.*`.
- Order status enums rendered via translation map, not raw string.
- Currency formatting through `Intl.NumberFormat` with user's locale + account currency (USD).

## 14. Documentation Deliverables

- `/docs/adr/040-ibkr-gateway-sidecar.md`.
- `/docs/adr/041-webhook-hmac-in-body.md` — explains why the signature is in the body, not a header (TV limitation).
- `/docs/runbooks/ib-gateway-reauth.md`.
- `/docs/runbooks/webhook-debug.md` — how to inspect an ingested alert end-to-end.
- User help: "Connect your IBKR account" and "Set up your TradingView alert" (with screenshots).

## 15. Rollback Plan

- Feature flag `WEBHOOK_V1_ENABLED` short-circuits to 503.
- Feature flag `BROKER_IBKR_ENABLED` hides IBKR from the picker and returns 503 from connect.
- Migrations additive; rollback = drop new tables (user data loss acceptable pre-launch).

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| IBKR daily 2FA kicks the session | High | Med | Paper account avoids 2FA; plan for live (M13+) addresses with IB mobile push. |
| Duplicate orders due to retry storms | Med | High | Idempotency key at endpoint + client_order_id at broker. |
| Webhook flood DoS | Med | Med | Per-user rate limit + max body size. |
| Gateway sidecar OOM | Low | Med | Set memory limit + restart policy; alert on restart rate. |
| Race between fill event and position fetch | Med | Low | Trust fills as the source of truth; reconciler (M05) corrects drift. |

## 17. Exit Gate Checklist

- [ ] AC-04-1 … AC-04-12 pass.
- [ ] Real IBKR paper test executed and documented.
- [ ] Grafana Trading Ops dashboard live.
- [ ] Runbooks IB-gateway-reauth + webhook-debug committed.
- [ ] E2E demo script rerunnable.
- [ ] Changelog entry.
- [ ] Tag `v0.4.0-ibkr-paper`.

Proceed to **M05 TradeStation + Order Lifecycle**.
