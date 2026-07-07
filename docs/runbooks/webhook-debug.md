# Runbook — Debugging an ingested webhook alert end-to-end

**Owner:** Yuval
**Status:** Production reference (M04). Use when an operator or user reports "I
fired an alert but nothing happened" or "the order/fill/position looks wrong".
**Companion docs:** `project-plan/04-webhook-ingest-and-ibkr.md` §6.3–§6.5
(pipeline), §12 (metrics), §13 (error codes),
`docs/adr/042-webhook-secret-in-body.md` (webhook auth semantics),
`docs/runbooks/alpaca-paper-smoke.md` (the happy-path smoke).

## The pipeline (what you are tracing)

```
TradingView POST  ─▶ WebhookView.post ─▶ AlertMessage row ─▶ process_alert.delay()
                       (sig compare,        (sig redacted)     │
                        schema, idem,                          ▼
                        halt gate)                     AlpacaAdapter.place_order
                                                              │  client_order_id = stp-{alert.id}
                                                              ▼
                                                          Order row (orders_order)
                                                              │
        Alpaca trade_updates stream ─▶ XADD fills:user:{id} ─▶ FillIngestor
                                                              │
                                              Fill (orders_fill, dedup broker_exec_id)
                                              Position (orders_position)
                                                              │
                                              WS: order.created / fill.created / position.updated
```

Work the stages left-to-right; the first stage that has no record is where the
alert stopped.

## Step 1 — Find the `AlertMessage` row

Every accepted POST (and every rejected-but-authenticated one) writes an
`AlertMessage`. Fields: `id, user, strategy, body_json (sig redacted),
idempotency_key, received_at, status, reject_reason?`.

```python
# manage.py shell (staging)
from apps.webhooks.models import AlertMessage
a = (AlertMessage.objects
     .filter(user__email="operator@example.com")
     .order_by("-received_at").first())
a.id, a.status, a.reject_reason, a.idempotency_key, a.received_at
```

> **`body_json` has the `sig` field redacted at write time** — you will see
> `"sig": "***redacted***"` (or the key absent), never the plaintext secret.
> This is intentional (AC-04-12); do not "fix" it.

- **No `AlertMessage` at all** → the POST never passed auth/schema. It was
  rejected before row creation (bad `sig`, unknown user/strategy, oversized
  body, non-JSON, or rate-limited). Jump to Step 6 (metrics) and the error
  table — check `webhook_received_total{result="rejected"|"unauthorized"}`.
- **`status = REJECTED`** → read `reject_reason` (`USER_HALTED`,
  `STRATEGY_HALTED`, etc.) and cross-reference the error table below.
- **`status = ACCEPTED`/queued** → the alert reached Celery; continue to Step 2.

## Step 2 — Check the `process_alert` Celery task

`process_alert(alert_id)` hydrates the alert + default `BrokerAccount`, builds
the `OrderRequest`, and calls the adapter. Look at the worker logs:

```bash
# Railway
railway logs --service worker | grep -E "process_alert|alert_id=<uuid>"
# local
docker compose logs -f worker | grep process_alert
```

Common outcomes:

- `NO_BROKER_CONNECTED` — the user has no default `BrokerAccount`; nothing to
  route to. Connect one at `/settings/brokers`.
- `ORDER_UNSUPPORTED_ASSET` — symbol isn't a US stock/ETF; rejected before the
  SDK call.
- `BROKER_AUTH_FAILED` / `BROKER_LIVE_KEYS_FORBIDDEN` — stored Alpaca keys are
  bad, regenerated, or live. Re-paste paper keys.
- `BROKER_RATE_LIMITED` — Alpaca 429 after retries; the order is surfaced as
  rejected, never silently dropped.

## Step 3 — Trace to the `Order`, `Fill`, and `Position`

```python
from apps.orders.models import Order, Fill, Position
o = Order.objects.get(client_order_id=f"stp-{a.id}")   # deterministic id
o.status, o.broker_order_id, o.symbol, o.side, o.qty, o.reason
list(Fill.objects.filter(order=o).values("qty", "price", "ts", "broker_exec_id"))
list(Position.objects.filter(user=a.user, symbol=o.symbol)
     .values("qty", "avg_cost", "updated_at"))
```

- **`Order` exists, `status=REJECTED`** → `o.reason` holds the mapped
  `BROKER_*` code; go back to Step 2 logs for the adapter exception.
- **`Order` `SUBMITTED`/`PENDING_SUBMIT` but no `Fill`** → the submit worked;
  the fill hasn't streamed back. Two causes: (a) order genuinely unfilled —
  **fired outside RTH**, market orders queue (see alpaca-paper-smoke); (b) the
  stream is down — Step 5.
- **`Fill` rows exist but `Position` looks wrong** → `FillIngestor` upserts
  `Fill` then refreshes `Position`; check the ingestor task logs (below) for an
  exception between the two. `broker_exec_id` is `unique` — a re-emitted fill
  after a stream reconnect is deduped here, so duplicate fills are a bug, not a
  reconnect artifact.

## Step 4 — Check the Redis idempotency key

Step 7 of the webhook flow does `SETNX idem:{user}:{sha256(idempotency_key)}
EX 86400`. A duplicate alert within 24 h returns `200 {duplicate: true}` and
places no second order.

```bash
# key is idem:{user_id}:{sha256 hex of the alert's idempotency_key}
redis-cli --scan --pattern "idem:<user-uuid>:*"
redis-cli TTL "idem:<user-uuid>:<sha256hex>"     # remaining seconds (<= 86400)
```

- Key present + user reports "my second alert didn't place an order" → **working
  as designed** (idempotent replay). The client re-used the same
  `idempotency_key` (often `{{strategy.order.id}}-{{time}}` collided, or a
  literal replay). Confirm the alert template varies the key per fire.
- Key absent but you expected a duplicate block → the two alerts had different
  `idempotency_key`s; both are legitimately distinct orders.

## Step 5 — Check the fill stream + broker status

Fills flow over one Alpaca `TradingStream` per account (run by
`run_broker_streams`), normalized and pushed onto the Redis Stream
`fills:user:{id}`; `FillIngestor` consumes it via a consumer group.

```bash
# is anything on the stream?
redis-cli XINFO STREAM "fills:user:<user-id>"
redis-cli XRANGE  "fills:user:<user-id>" - + COUNT 10   # recent normalized fill events
# consumer group lag (is FillIngestor keeping up / acking?)
redis-cli XINFO GROUPS "fills:user:<user-id>"
```

```bash
# ingestor task logs
railway logs --service worker | grep FillIngestor
# streams service logs
railway logs --service streams | grep -E "trade_updates|reconnect|heartbeat"
```

Then check the per-account stream health endpoint — it reads a heartbeat key the
streams service refreshes every 15 s:

```bash
curl -s https://<staging-host>/api/v1/brokers/<broker-id>/status/   # CONNECTED | DEGRADED | DOWN
```

- **DEGRADED/DOWN** → the stream dropped. The supervisor restarts it with
  backoff and does a REST catch-up (`get_orders(after=last_event_ts)`),
  re-emitting missed fills; `broker_exec_id` dedup makes that safe (AC-04-11).
  If it stays DOWN, the streams service itself is down — restart it.
- **CONNECTED but no events on the stream after a known fill** → suspect the
  `trade_updates` subscription; bounce the account's stream (disconnect +
  reconnect the broker, or restart `run_broker_streams`).

## Step 6 — Prometheus metrics (§12)

Scrape `/metrics` on the backend (and the streams service for the gauge). The
signals for this pipeline:

| Metric | Type | What it tells you |
|---|---|---|
| `webhook_received_total{result}` | counter | Split by `result` (`accepted`, `duplicate`, `rejected`, `unauthorized`, `schema_invalid`). If your alert produced no `AlertMessage`, the `unauthorized`/`rejected` count moving confirms it was dropped pre-row. |
| `webhook_latency_seconds` | histogram | End-to-end handler latency. AC-04-1 wants p95 < 300 ms; a spike here explains TradingView 3 s timeouts. |
| `order_submit_latency_seconds{broker}` | histogram | Adapter `place_order` latency to Alpaca. Alert fires: `submit p95 > 2s`. |
| `broker_stream_heartbeat_age_seconds` | gauge | Age of the last stream heartbeat. Alert fires: `> 120s` → stream is stale/down; correlates with `/status/` = DEGRADED. |
| `broker_connect_total{broker,result}` | counter | Connect attempts + outcomes (auth failures show here). |
| `broker_stream_disconnects_total{broker}` | counter | Stream drop count; rising = flapping. |
| `fills_ingested_total{broker}` | counter | Fills persisted; flat while orders fill = ingest is stuck (Step 5). |

Quick PromQL:

```promql
sum by (result) (rate(webhook_received_total[5m]))
histogram_quantile(0.95, sum by (le) (rate(webhook_latency_seconds_bucket[5m])))
max(broker_stream_heartbeat_age_seconds)
```

The OTel trace `webhook.post → alert.process → broker.place_order → fill.ingest`
ties a single alert across all four stages if distributed tracing is enabled —
search by `alert_id`.

## Example structured log lines (redacted)

The alert log envelope carries `alert_id`, `user_id_hash`, `strategy_id` — and
**never** body JSON, secrets, or API keys (the `SENSITIVE_KEYS` scrubber drops
`sig`, `secret`, `token`, `password`, `api_key`; AC-04-12). Representative,
correctly-redacted lines:

```json
{"ts":"2026-07-07T20:14:03.101Z","level":"INFO","event":"webhook.received","alert_id":"7f3c…a9","user_id_hash":"u_8b21…","strategy_id":"c14e…","result":"accepted","sig":"***redacted***","bytes":412,"latency_ms":38}
{"ts":"2026-07-07T20:14:03.140Z","level":"INFO","event":"alert.process","alert_id":"7f3c…a9","user_id_hash":"u_8b21…","broker":"alpaca","symbol":"AAPL","side":"buy","qty":1,"client_order_id":"stp-7f3c…a9"}
{"ts":"2026-07-07T20:14:03.402Z","level":"INFO","event":"broker.place_order","alert_id":"7f3c…a9","broker":"alpaca","client_order_id":"stp-7f3c…a9","broker_order_id":"a1b2…","status":"submitted","submit_latency_ms":262}
{"ts":"2026-07-07T20:14:03.980Z","level":"INFO","event":"fill.ingest","user_id_hash":"u_8b21…","broker":"alpaca","symbol":"AAPL","qty":1,"price":211.44,"broker_exec_id":"e0d5…01","order_status":"filled"}
```

Rejection example (bearer-secret mismatch — note there is no `AlertMessage`):

```json
{"ts":"2026-07-07T20:19:55.006Z","level":"WARNING","event":"webhook.rejected","user_id":"path-uuid","strategy_id":"path-uuid","result":"unauthorized","code":"WEBHOOK_SIG_BAD","sig":"***redacted***","reason":"generic 401 (no existence oracle)"}
```

If you ever see a plaintext secret or a full order-body JSON in a log line,
that is a **security regression** — the log-scan test (AC-04-12) should have
caught it. Treat it as an incident and scrub.

## Error-code table (§13)

| Code | Stage | Meaning / typical fix |
|---|---|---|
| `WEBHOOK_SIG_BAD` | webhook auth | `sig` didn't match (or missing / unknown user-strategy). Generic `401`, no oracle. Re-copy or rotate the secret and re-paste in TradingView. |
| `WEBHOOK_SCHEMA_INVALID` | webhook validation | Payload (minus `sig`) failed the strategy's saved JSON Schema. `400` includes the schema error detail; fix the alert Message JSON. |
| `ORDER_UNSUPPORTED_ASSET` | order build | Symbol isn't a US stock/ETF (option/crypto/future). Rejected before the SDK call. |
| `BROKER_AUTH_FAILED` | broker connect | Alpaca `401/403` — wrong/expired/regenerated keys. Re-paste paper keys. |
| `BROKER_LIVE_KEYS_FORBIDDEN` | broker connect | Live keys (or a live endpoint/account) detected. M04 is paper-only; generate keys from Alpaca's Paper section. |
| `BROKER_RATE_LIMITED` | broker call | Alpaca `429` after retries (~200 req/min/account). Surfaced, never dropped; client token-bucket + jittered retry. |
| `NO_BROKER_CONNECTED` | alert process | User has no default `BrokerAccount`. Connect one at `/settings/brokers`. |
| `USER_HALTED` | halt gate | A user-level `TradingHalt` is active. Endpoint returns `200 {rejected: USER_HALTED}`; release the halt. |
| `STRATEGY_HALTED` | halt gate | A strategy-level `TradingHalt` is active. Same shape as above with `STRATEGY_HALTED`. |

## Quick decision tree

1. No `AlertMessage`? → auth/schema/rate-limit reject (Step 1 + metrics + error
   table). Most common: `WEBHOOK_SIG_BAD`.
2. `AlertMessage` `REJECTED`? → read `reject_reason` (halt or unsupported asset).
3. `Order` `REJECTED`? → `o.reason` + Step 2 worker logs.
4. `Order` submitted, no `Fill`? → **RTH?** then Step 5 stream/status.
5. `Fill` present, dashboard stale? → WS delivery (`fill.created` /
   `position.updated`) — check the dashboard WS consumer and heartbeat.
