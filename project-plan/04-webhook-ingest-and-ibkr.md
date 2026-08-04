# Milestone 04 — Webhook Ingest + Broker Adapter + Alpaca Paper

> **Week:** 4
> **Duration:** 5 working days (Phase B–F; Phase A already done)
> **Depends on:** M03 (Strategies & Webhook Config), M02 (MFA)
> **Unlocks:** M05 (Order Lifecycle + second broker), M08 (kill-switch engine)
> **Rescoped 2026-07-05:** execution broker changed from IBKR to **Alpaca** — see `docs/adr/041-alpaca-over-ibkr.md`. The filename keeps its historical `ibkr` name so existing links (ADR-040, debug logs, tracker) stay valid.
>
> **Phase A history (done, 2026-05-09 → 2026-05-15):** the IB Gateway sidecar spike connected, placed and filled a paper order (AAPL @ $299.15 on `DUN167649`), and surfaced the two constraints (paper-account dormancy, one-session-per-Gateway-boot) that — combined with the blocked IBKR Web API approval for the Interactive Israel account — triggered the Alpaca pivot. Artifacts are parked in-tree: ADR-040, `docker/ib-gateway/`, `docs/runbooks/ib-gateway-reauth.md`, `scripts/spike_ibkr_smoke.py`.

## 1. Purpose

Make the pipeline live end-to-end in paper mode for the first broker: a TradingView alert hits our public webhook, passes secret + schema validation, enqueues to Celery, flows through a minimal halt gate, routes to the Alpaca paper adapter, places an order, receives the fill via Alpaca's `trade_updates` stream, and surfaces in a real-time dashboard widget. No sentiment, no regime, no sizing sophistication yet — those compound in later milestones.

## 2. In Scope

- Public webhook endpoint `POST /hooks/v1/{user_uuid}/{strategy_uuid}/` with secret verification, idempotency, Celery dispatch.
- `BrokerAdapter` protocol + `FakeBrokerAdapter` (test double) + `AlpacaAdapter` (paper).
- Per-user broker connection: user pastes their Alpaca **paper** API key pair; stored Fernet-encrypted (same KEK pattern as MFA/webhook secrets); connection test.
- Order placement flow: map alert → internal `OrderRequest` → adapter `place_order` → persist `Order` + `Fill` → push WebSocket event.
- Fill streaming: one `TradingStream` per connected broker account, run by a dedicated `run_broker_streams` service; fills land on Redis Stream `fills:user:{id}`; `FillIngestor` Celery task persists them.
- Dashboard widget: live open positions + today's fills.
- Minimal kill-switch hooks (per-user + per-strategy `TradingHalt` rows) enforced at reject-new-orders level (full engine in M08; here we only check the flag — no auto-flatten).
- Repo hygiene tied to the pivot: `ib-gateway` compose service moved behind an opt-in profile; `TWS_*` vars out of `.env.example`; CI grep gate against their reintroduction; IBKR credential rotation (operator step).

## 3. Out of Scope

- TradeStation / second broker (M05).
- Sophisticated sizing / regime / sentiment (M06–M08).
- Live trading mode — PAPER only in M04 (`ENABLE_LIVE_TRADING=false` hard default; Alpaca live keys rejected by validation).
- Full reconciliation loop (lightweight one-shot sweep only; proper scheduler in M05).
- Options, crypto, futures (US stocks + ETFs only in M04; Alpaca supports options/crypto — deliberately deferred).
- Alpaca OAuth ("Connect with Alpaca") and Broker API — approval-gated; revisit at multi-user beta (M12+).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-04-1 | A correctly-authenticated alert to a user's webhook URL is accepted with 200 within 300ms p95 (TradingView's timeout is 3s). |
| AC-04-2 | An alert with a missing/wrong `sig` returns 401; no order placed; audit row written; per-user rate limit applies before body parse. |
| AC-04-3 | An alert with valid `sig` but a payload failing the user's saved JSON Schema returns 400 with the schema error detail. |
| AC-04-4 | Duplicate `idempotency_key` within 24h returns 200 with `duplicate=true`; no second order placed (Redis `SETNX` + unique `client_order_id` at Alpaca as second guard). |
| AC-04-5 | If a user-level or strategy-level `TradingHalt` is active, the endpoint returns 200, the order is rejected with `reason=USER_HALTED` / `STRATEGY_HALTED`, and an audit row is written. |
| AC-04-6 | User can connect an Alpaca paper account by pasting key ID + secret at `/settings/brokers`; keys are Fernet-encrypted at rest; "Test connection" calls `GET /v2/account` and shows account number + buying power; live keys are rejected with `BROKER_LIVE_KEYS_FORBIDDEN`. |
| AC-04-7 | On a valid alert, an equity market DAY order is placed on Alpaca paper with our `client_order_id`; the broker order id is stored; the fill arrives via `trade_updates` and is persisted as `Fill`. |
| AC-04-8 | Dashboard positions widget updates within 2s of the fill via WebSocket. |
| AC-04-9 | A `flatten_all` call (debug button, admin-gated in M04) invokes Alpaca `close_all_positions(cancel_orders=True)`; all positions reach flat and the UI reflects it. |
| AC-04-10 | End-to-end test from `send_webhook()` fixture to `position.updated` WebSocket event completes in ≤ 5s locally against `FakeBrokerAdapter`. |
| AC-04-11 | Killing the `run_broker_streams` process mid-session triggers supervised restart with backoff; on reconnect, missed fills are recovered via REST (`get_orders` since last cursor) and no fill is lost or duplicated (dedup on `broker_exec_id`). `GET /api/v1/brokers/{id}/status/` reflects DEGRADED during the gap. |
| AC-04-12 | No broker API keys, webhook secrets, or order PII appear in logs, Sentry events, or `/metrics` (verified by an automated log-scan test). |
| AC-04-13 | `make up` boots the stack **without** the ib-gateway container; `docker compose --profile ibkr up` still can. `TWS_USERID`/`TWS_PASSWORD`/`DEBUG_VNC` are gone from `.env.example`; CI fails if `TWS_` reappears in tracked code outside the allowlist (ADR-040, parked runbook, `docker/ib-gateway/`, this plan). |
| AC-04-14 | The OpenAPI schema documents the webhook endpoint (custom post-processor — unauthenticated at the JWT layer, secret-authenticated in body) and all new `/api/v1/{brokers,orders,positions,fills}` paths; regenerated frontend types compile. |

## 5. Definition of Done

Baseline DoD applies, plus:

- Alpaca adapter behind `BROKER_ALPACA_ENABLED` feature flag; disable without redeploy.
- The one-shot real-Alpaca-paper test (§10.4) executed and documented in a runbook.
- The e2e "hello world" flow is a rerunnable Playwright-scripted demo.
- ADR-042 (webhook secret-in-body semantics — see §11) committed; ADR-031's "TradingView signs the alert body" wording corrected by amendment note.
- IBKR paper + live passwords rotated after `TWS_*` env scrub (04A carryover; operator step, logged in PR description).

## 6. Implementation Tasks

### 6.1 Backend — Broker adapter protocol (`apps/brokers`)

Unchanged from the original M04 design (this protocol is the layer that made the IBKR→Alpaca pivot cheap; keep it broker-neutral):

```python
class BrokerAdapter(Protocol):
    name: str
    supported_asset_classes: list[str]

    def connect(self) -> ConnectionInfo: ...          # verify creds / liveness
    def disconnect(self) -> None: ...
    def get_account(self) -> Account: ...
    def list_positions(self) -> list[Position]: ...
    def list_open_orders(self) -> list[Order]: ...
    def place_order(self, req: OrderRequest, client_order_id: str) -> OrderAck: ...
    def cancel_order(self, broker_order_id: str) -> None: ...
    def flatten_all(self, reason: str) -> list[OrderAck]: ...
    def health(self) -> BrokerHealth: ...
```

Notes vs. the original sketch: `connect()` takes no creds argument (the adapter is constructed per `BrokerAccount` and decrypts internally — creds never travel through call sites), and `stream_fills()` is **not** on the protocol — streaming is owned by the streams service (§6.5), which writes to Redis; adapters stay synchronous and simple.

`FakeBrokerAdapter` implements the protocol for tests with a `script` for predetermined fills, partial fills, slippage, and rejects, and writes scripted fills to the same Redis Stream so the ingest path is exercised identically.

### 6.2 Backend — Alpaca adapter (`apps/brokers/alpaca/`)

- Library: `alpaca-py>=0.43,<0.44` (0.43.4 current, Apache-2.0). Add to `requirements/base.txt`.
- Client: `TradingClient(api_key, secret_key, paper=True)` → `https://paper-api.alpaca.markets`. `paper=True` is **hard-coded** in M04; the live URL is unreachable by construction.

```
apps/brokers/alpaca/
├── __init__.py
├── adapter.py        # AlpacaAdapter(BrokerAdapter)
├── mapping.py        # OrderRequest → alpaca-py request models; Alpaca order/position → our DTOs
├── errors.py         # APIError code → our BROKER_* error codes; retryable set
└── streams.py        # TradingStream wrapper used by run_broker_streams (§6.5)
```

- `place_order`: `MarketOrderRequest(symbol=..., qty=..., side=OrderSide.BUY|SELL, time_in_force=TimeInForce.DAY, client_order_id=...)` via `submit_order`. Limit orders: `LimitOrderRequest`. Reject anything not `STOCK|ETF` with `ORDER_UNSUPPORTED_ASSET` before the SDK call. Day 1 task: confirm `client_order_id` length limit against the live paper endpoint and clamp our UUID format accordingly.
- `get_account` / `list_positions` / `list_open_orders` / `cancel_order`: direct SDK calls mapped in `mapping.py`.
- `flatten_all`: `close_all_positions(cancel_orders=True)` — native one-call flatten; map the per-position HTTP statuses into `OrderAck` list.
- `connect`: `get_account()`; a 401/403 → `BROKER_AUTH_FAILED`; an account whose number does not match paper format or whose endpoint is live → `BROKER_LIVE_KEYS_FORBIDDEN`.
- Retry policy: 429 → exponential jitter, 3 attempts, then `BROKER_RATE_LIMITED` (Alpaca allows ~200 req/min per account); 5xx → 2 retries; never retry a `submit_order` timeout without first checking `get_order_by_client_id` (idempotent lookup) to avoid duplicates.
- Every call recorded to `BrokerCallAudit` (endpoint, status, latency — never bodies or keys).

### 6.3 Backend — Webhook endpoint (`apps/webhooks`)

Router attached **outside** `/api/v1` to avoid auth middleware:

```python
urlpatterns = [
    path('hooks/v1/<uuid:user_id>/<uuid:strategy_id>/', WebhookView.as_view()),
]
```

`WebhookView.post` flow (order matters):

```
1. rate-limit per user_id (60/min) — before body read
2. reject > 16 KB or non-application/json
3. parse JSON; extract top-level "sig"
4. wc = WebhookConfig for (user_id, strategy_id) — 404 → generic 401 (no existence oracle)
5. constant-time compare: hmac.compare_digest(sig, decrypt_secret(wc.secret_encrypted)) → else 401
6. jsonschema.validate(body minus sig, wc.json_schema) → else 400
7. idempotency: redis SETNX idem:{user}:{sha256(idempotency_key)} EX 86400 → dup? 200 {duplicate: true}
8. TradingHalt active for user or strategy? → audit REJECTED, 200 {rejected: reason}
9. AlertMessage row (sig field redacted), process_alert.delay(alert.id), 200
```

**Auth semantics (honest version — supersedes the old plan's "HMAC verify" wording):** TradingView alert messages are static templates with placeholder substitution only — TV **cannot compute** a per-payload HMAC. The M03 webhook modal already embeds the per-user-per-strategy secret in the template's `sig` field, so v1 verification is a constant-time match of that bearer secret. Mitigations for the replay window this implies: idempotency key (step 7), per-user rate limit (step 1), TLS-only, secret rotation (M03, destructive), and an optional TradingView source-IP allowlist (config flag, off by default; TV publishes its webhook egress IPs — pin them at deploy time). A computed-HMAC mode (`sig_mode=hmac256`, HMAC-SHA256 over raw body bytes with the `sig` pair stripped) is specified for API-capable senders post-MVP. Document all of this in **ADR-042**, and amend ADR-031's imprecise "TradingView signs the alert body" sentence.

Celery task `process_alert(alert_id)`:

1. Hydrate alert + user + strategy + default `BrokerAccount` (error `NO_BROKER_CONNECTED` if none).
2. Build `OrderRequest` — stocks/ETFs only; reject others with `ORDER_UNSUPPORTED_ASSET`.
3. Sizing: use the alert's `qty` verbatim (sizing pipeline wires in M08).
4. `client_order_id = f"stp-{alert.id}"` → adapter `place_order`.
5. Persist `Order` + audit row; push `order.created` WebSocket event.
6. On adapter exception: mark order `REJECTED` with mapped reason; audit; never re-raise into Celery retry without the §6.2 idempotent-lookup guard.

### 6.4 Backend — Orders app minimal (`apps/orders`)

Models (Django default table names `orders_order`, `orders_fill`, `orders_position` — note: the master-plan review flagged a SQL reserved-word risk for a bare `order` table; Django's app-prefixed naming already avoids it, so no custom `db_table`):

- `Order(id, user, strategy, broker_account, client_order_id unique, broker_order_id, symbol, side, qty, order_type, limit_price?, status, reason?, raw_alert FK, created_at, updated_at)` — `status` enum `{PENDING_SUBMIT, SUBMITTED, PARTIAL, FILLED, CANCELLED, REJECTED}`.
- `Fill(order FK, qty, price, ts, broker_exec_id unique)` — immutable; unique `broker_exec_id` is the stream-dedup anchor.
- `Position(user, broker_account, symbol, qty, avg_cost, updated_at)` — derived but persisted for dashboard speed; `unique_together (broker_account, symbol)`.

`FillIngestor` Celery task consumes Redis Stream `fills:user:{id}` (consumer group), upserts `Fill`, refreshes `Position`, emits `fill.created` + `position.updated` WS events.

### 6.5 Backend — Fill streaming service (`run_broker_streams`)

New management command, deployed as its own lightweight Railway service (mirrors `worker`/`beat` pattern; locally a compose service):

- On boot: load all active `BrokerAccount(broker=ALPACA, mode=PAPER)` rows; for each, start a `TradingStream(api_key, secret, paper=True)` subscribed to `trade_updates`, one thread per account (SDK's `run()` is a blocking asyncio loop; thread-per-account is fine at MVP scale, revisit ≥50 accounts).
- Each `trade_update` event (`fill`, `partial_fill`, `canceled`, `rejected`, `new`) → normalized DTO → `XADD fills:user:{id}`; order-state events also update `Order.status` via a small Celery task (keep the stream process DB-free).
- Supervisor loop: restart dead streams with exponential backoff; after reconnect, REST catch-up via `get_orders(after=last_event_ts)` and re-emit missed fills (dedup on `broker_exec_id` makes this safe).
- Listens on Redis pub/sub `brokers.accounts.changed` to hot-add/remove streams when users connect/disconnect accounts.
- `/api/v1/brokers/{id}/status/` reads a per-account heartbeat key the service refreshes every 15s (`CONNECTED` / `DEGRADED` / `DOWN`).

### 6.6 Backend — Channels / WebSocket (unchanged design)

- `apps/dashboard/consumers.py` — `DashboardConsumer(AsyncJsonWebsocketConsumer)`.
- URL `/ws/dashboard/` — JWT on query string + MFA enforcement; group-per-user `dashboard.user.{user_id}`.
- Events this milestone: `order.created`, `order.updated`, `fill.created`, `position.updated`, `broker.status`.

### 6.7 Frontend — broker connection

Route `/settings/brokers`:

- List connected brokers with status badge (Connected / Degraded / Error).
- "Connect Alpaca Paper": two fields (API Key ID, Secret Key) + inline help linking a new user-help page ("Generate paper keys on the Alpaca dashboard — Paper trading is free; keys shown once, regenerating invalidates old ones").
- Test connection button → `/api/v1/brokers/{id}/test-connection/` → shows account number + buying power.
- Remove broker (MFA re-prompt) → deletes row + stops stream.
- Secret field is write-only; never echoed back by any serializer.

### 6.8 Frontend — dashboard v0 + WS client (unchanged design)

- `/dashboard`: open-positions grid (symbol, qty, avg cost, mark, unrealized P&L — mark from latest fill price in M04; real quotes in M06), today's fills feed, broker status indicator, dev-only "Send test alert" button.
- `core/services/ws.service.ts`: connect on auth, exponential-backoff reconnect, 25s heartbeat, dispatch into signal stores.

### 6.9 Pivot hygiene (repo + infra)

- `docker-compose.yml`: move `ib-gateway` under `profiles: ["ibkr"]`; add `streams` service; drop `TWS_*`/`DEBUG_VNC` from `.env.example`, add `ALPACA_*` dev-convenience vars (optional platform-level paper keys for local smoke only — production users always bring their own).
- CI (`.github/workflows/ci.yml`): add `block-legacy-ibkr-creds` grep job (allowlist: `docker/ib-gateway/`, ADR-040, `docs/runbooks/ib-gateway-reauth.md`, this plan, `project-plan/archived/04A-IBKR-Web-API.md`).
- Operator: rotate IBKR paper + live passwords after env scrub; delete `TWS_*` from Railway and GitHub secrets.
- Remove the three stray `gateway-*.png` screenshots and the tracked `_tmp_14_*` zero-byte files from the repo root / `frontend/` (`git rm`), and add `_tmp_*` to `.gitignore`.

## 7. Tech Stack Notes

- **`alpaca-py` 0.43.x** — official SDK, pydantic request models (`MarketOrderRequest`, `LimitOrderRequest`), `TradingClient(paper=True)`, `TradingStream` for `trade_updates`. Pin `<0.44`.
- **Paper endpoint:** `https://paper-api.alpaca.markets`; keys come from the user's Alpaca dashboard Paper section; regenerating keys invalidates the old pair (surface this in help copy — users must re-paste after regenerating).
- **Rate limit:** ~200 req/min/account on trading endpoints → token-bucket client-side guard + jittered retry.
- **Django Channels 4** with Redis channel layer (already configured since M00).
- **`hmac.compare_digest`** for constant-time secret comparison.
- **Structured alert logging** — envelope includes `alert_id`, `user_id_hash`, `strategy_id`; NEVER body JSON, secrets, or API keys.

## 8. Data Model Changes

Migrations:

- `webhooks.0001_initial` — `AlertMessage(id, user, strategy, body_json (sig redacted), idempotency_key, received_at, status, reject_reason?)`.
- `brokers.0001_initial` — `BrokerAccount(id, user, broker enum {ALPACA}, mode enum {PAPER}, api_key_id_enc, api_secret_enc, account_number, nickname, is_default, status, last_connected_at, created_at)`; unique `(user, broker, account_number)`. Fernet via the shared KEK helper (`apps/users/mfa._fernet` — same reuse pattern ADR-031 documents for webhook secrets).
- `brokers.0002_tradinghalt` — `TradingHalt(id, user, strategy nullable, reason, created_by, created_at, released_at nullable)`; active = `released_at IS NULL`. (M08 builds the full engine on this table.)
- `orders.0001_initial` — `Order`, `Fill`, `Position` (§6.4).

## 9. API Contract Changes

```
POST /hooks/v1/{user}/{strategy}/              public; secret-auth'd in body
GET  /api/v1/brokers/                          list user brokers
POST /api/v1/brokers/                          connect (broker=alpaca, mode=paper, key_id, secret)
GET  /api/v1/brokers/{id}/
DELETE /api/v1/brokers/{id}/                   MFA re-prompt; stops stream
POST /api/v1/brokers/{id}/test-connection/
GET  /api/v1/brokers/{id}/status/
POST /api/v1/brokers/{id}/flatten/             admin-gated debug in M04; full in M08
GET  /api/v1/orders/                           list w/ filters (status, strategy, date)
GET  /api/v1/positions/                        live snapshot
GET  /api/v1/fills/                            list
WS   /ws/dashboard/                            JWT via query param
```

All `/api/v1/*` paths MFA-enforced (`IsAuthenticatedAndMFAEnforced`, as M02 established).

## 10. Test Plan

### 10.1 Unit

- Secret verification: valid / missing / wrong / non-constant-time regression (mock timing not required — assert `compare_digest` call).
- Idempotency: duplicate key → `duplicate=true`, single order.
- Halt gate short-circuits order creation (user-level and strategy-level).
- `mapping.py`: OrderRequest→alpaca-py model round-trips; Alpaca error→`BROKER_*` code table.
- `FakeBrokerAdapter` scripted fills produce `Fill` rows and update `Position` (incl. partial fills and rejects).
- Live-key rejection (`BROKER_LIVE_KEYS_FORBIDDEN`).

### 10.2 Integration

- Webhook → Celery → FakeBroker → Redis Stream → FillIngestor → Position, on Postgres + Redis + Channels.
- Broker creds encryption round-trip; serializer never exposes secrets.
- Stream catch-up: kill fake stream, emit REST-recovered fills, assert dedup on `broker_exec_id`.
- WebSocket ordering: `order.created` before `fill.created`.
- Alpaca HTTP layer with `respx`/recorded fixtures — no live calls in CI.

### 10.3 E2E (Playwright, stubbed broker)

- Connect Alpaca paper (backend stubbed) → dashboard shows Connected.
- Simulated TV alert via test helper → dashboard updates in real time.
- Flip halt → next alert rejected with visible reason.

### 10.4 Live against real Alpaca paper (manual, one-shot)

- Boot staging with real paper keys (operator's own account via the UI — not env vars).
- Fire a real TradingView alert at the staging webhook URL.
- Assert: order visible in Alpaca dashboard, fill lands in ours ≤5s, positions match.
- Document quirks in `docs/runbooks/alpaca-paper-smoke.md` (market-hours note: market orders queue outside RTH — run during RTH like the IBKR spike did).

### 10.5 Load

- 10 alerts/sec for 2 min against FakeBroker: p95 end-to-end < 1s; no drops.
- 50 alerts from 10 concurrent users: p99 < 2s; Alpaca token-bucket never breached in mock accounting.

### 10.6 Resilience

- Kill Redis mid-pipeline: Celery retries; Postgres unique `client_order_id` prevents duplicate orders.
- Kill `run_broker_streams` mid-fill: AC-04-11 recovery path; zero lost/duplicated fills.

## 11. Security Considerations

- Webhook endpoint is unauthenticated at the JWT layer — the body secret is the only auth. Hardening: per-user rate limit before body read, 16 KB body cap, `application/json` only, optional TV source-IP allowlist, generic 401 for unknown user/strategy (no enumeration oracle).
- The `sig` value is a **static bearer secret** (TradingView cannot compute HMACs) — replay-window mitigations and the future computed-HMAC mode are specified in §6.3 and ADR-042.
- Alpaca keys encrypted at rest (Fernet, shared KEK — rotation covered by the existing `mfa-kek-rotation.md` runbook); write-only serializers; `__repr__` redaction; log-scan test (AC-04-12).
- Paper-only enforcement is server-side (endpoint hard-coded), not a UI nicety.
- CORS unchanged — the webhook is not browser-called.

## 12. Observability

- Prometheus: `webhook_received_total{result}`, `webhook_latency_seconds` histogram, `order_submit_latency_seconds{broker}`, `broker_connect_total{broker,result}`, `broker_stream_disconnects_total{broker}`, `fills_ingested_total{broker}`, `broker_stream_heartbeat_age_seconds` gauge.
- OTel trace: `webhook.post` → `alert.process` → `broker.place_order` → `fill.ingest`.
- Alerts: webhook 5xx >1%/5min; stream heartbeat age >120s; submit p95 >2s.
- Grafana: **Trading Ops** dashboard (first of the M10 §6.5 carryover set — build it now, panels for the metrics above).

## 13. Translation & Localization

Unchanged conventions: error codes (`WEBHOOK_SIG_BAD`, `WEBHOOK_SCHEMA_INVALID`, `ORDER_UNSUPPORTED_ASSET`, `BROKER_AUTH_FAILED`, `BROKER_LIVE_KEYS_FORBIDDEN`, `BROKER_RATE_LIMITED`, `NO_BROKER_CONNECTED`, `USER_HALTED`, `STRATEGY_HALTED`) mapped to i18n keys; UI copy under `brokers.*`, `dashboard.positions.*`, `dashboard.fills.*`; currency via `Intl.NumberFormat`.

## 14. Documentation Deliverables

- `docs/adr/041-alpaca-over-ibkr.md` (done, 2026-07-05).
- `docs/adr/042-webhook-secret-in-body.md` — sig semantics, replay analysis, future HMAC mode; amendment note added to ADR-031.
- `docs/runbooks/alpaca-paper-smoke.md` — the §10.4 procedure.
- `docs/runbooks/webhook-debug.md` — inspect an ingested alert end-to-end.
- User help: "Connect your Alpaca paper account" + refresh "Set up your TradingView alert" for the live webhook.

## 15. Rollback Plan

- `WEBHOOK_V1_ENABLED=false` → webhook returns 503.
- `BROKER_ALPACA_ENABLED=false` → hides Alpaca from the picker, `connect`/`place_order` return 503; streams service exits cleanly.
- Migrations additive; rollback = drop new tables (acceptable pre-launch).

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Static `sig` secret replayed by an interceptor | Med | Med | TLS-only, idempotency, rate limit, rotation, optional TV IP allowlist; computed-HMAC mode for API senders post-MVP (ADR-042). |
| Duplicate orders from retry storms | Med | High | Redis idempotency + unique `client_order_id` + idempotent `get_order_by_client_id` check before any submit retry. |
| `trade_updates` stream drops silently | Med | Med | Heartbeat gauge + alert; supervised restart; REST catch-up with `broker_exec_id` dedup (AC-04-11). |
| Alpaca 200 req/min ceiling under alert bursts | Low | Med | Client token bucket; burst-queue in Celery; jittered retry → `BROKER_RATE_LIMITED` surfaced, never dropped. |
| Israel live-account eligibility unknown | Low now | High later | Paper-only MVP unaffected; confirm with Alpaca support before M12 live scope (ADR-041 open item). |
| Webhook flood DoS | Med | Med | Per-user rate limit + 16 KB cap + optional IP allowlist. |
| User regenerates Alpaca keys, breaking stored pair | Med | Low | `broker.status` flips to Error on 401; dashboard banner prompts re-paste; help copy warns. |

## 17. Exit Gate Checklist

- [ ] AC-04-1 … AC-04-14 pass.
- [ ] Real Alpaca paper test executed and documented (§10.4).
- [ ] Grafana Trading Ops dashboard live.
- [ ] Runbooks alpaca-paper-smoke + webhook-debug committed; ADR-042 committed.
- [ ] `TWS_*` scrub + IBKR password rotation done; CI grep gate green.
- [ ] E2E demo script rerunnable.
- [ ] CHANGELOG entry.
- [ ] Tag `v0.4.0-alpaca-paper`.

Proceed to **M05 — Order Lifecycle (+ second broker decision)**.
