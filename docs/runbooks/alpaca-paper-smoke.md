# Runbook — Alpaca paper end-to-end smoke test (M04 §10.4)

**Owner:** Yuval
**Status:** Executable checklist — run once against staging with real Alpaca
paper keys to close M04 §10.4 / AC-04-7 / AC-04-8. Log the run in the M04 PR
description and the exit-gate checklist.
**Companion docs:** `project-plan/04-webhook-ingest-and-ibkr.md` §10.4 (the
procedure this runbook operationalises), `docs/adr/041-alpaca-over-ibkr.md`
(why Alpaca), `docs/adr/042-webhook-secret-in-body.md` (webhook auth),
`docs/runbooks/webhook-debug.md` (if any step below fails),
`frontend/src/assets/help/alpaca-paper-connect.html` (the user-facing version
of the key-generation steps).

## What this proves

A **real** TradingView alert, fired at the **staging** webhook URL, places a
real order on **Alpaca paper**, and the fill lands in our dashboard within 5 s
with positions matching. This is the one manual, non-CI test in M04 — the rest
of the pipeline is covered by `FakeBrokerAdapter` (AC-04-10) and `respx`
fixtures (§10.2). It uses the operator's **own** Alpaca paper account, connected
**through the app UI**, never through env vars.

> **RUN DURING US REGULAR TRADING HOURS (RTH).** Market orders placed outside
> RTH **queue** at Alpaca and do **not** fill until the next session open — so
> the "fill lands in ≤5 s" assertion will fail through no fault of the
> pipeline. RTH is **09:30–16:00 America/New_York**, i.e. roughly
> **16:30–23:00 Asia/Jerusalem**, Mon–Fri (minus US market holidays). This is
> the same discipline the IBKR spike followed — its fill capture only succeeded
> on the 2026-05-15 RTH rerun (AAPL @ $299.15). If you must smoke outside RTH,
> use a **limit** order priced to fill immediately, or expect `status=SUBMITTED`
> (queued) and re-check at the open.

## Prerequisites

- [ ] **Staging is up** with `WEBHOOK_V1_ENABLED=true` and
  `BROKER_ALPACA_ENABLED=true`. `ENABLE_LIVE_TRADING` stays `false` (M04
  default — Alpaca live keys are rejected server-side regardless).
- [ ] The `streams` service (`run_broker_streams`) is running on staging (its
  own Railway service, mirrors `worker`/`beat`).
- [ ] You can reach the staging dashboard and are enrolled in 2FA (all
  `/api/v1/*` and `/settings/*` routes are MFA-enforced).
- [ ] A strategy is uploaded/enabled on your staging account with a
  **webhook configured** — you have its URL
  `https://<staging-host>/hooks/v1/<user-uuid>/<strategy-uuid>/` and its
  one-time `sig` secret copied (M03 flow; rotate to re-reveal if lost).
- [ ] A **TradingView Pro+** account (webhooks require Pro or above) with the
  strategy's Pine script on a chart for a **US equity or ETF** symbol
  (e.g. `AAPL`, `SPY`). Options/crypto/futures are rejected in M04 with
  `ORDER_UNSUPPORTED_ASSET`.
- [ ] It is currently **US RTH** (see the box above).

## Step 1 — Create a free Alpaca account

1. Go to <https://alpaca.markets/> and sign up (free). No approval gate, no
   funding required for paper trading.
2. Verify your email and log into the Alpaca dashboard.

## Step 2 — Generate PAPER API keys

1. In the Alpaca dashboard, switch to **Paper Trading** (the account toggle —
   make sure you are NOT in a Live view). Paper trading is free and needs no
   approval or funding.
2. Open the **Paper** section's API-keys panel (labelled "API Keys" /
   "Generate New Key" under the paper account).
3. Click **Generate** (or **Regenerate**). Alpaca shows the **API Key ID** and
   the **Secret Key**.

> **The Secret Key is shown exactly once.** Copy both values immediately.
> **Regenerating keys invalidates the previous pair** — if you regenerate
> later, any keys already pasted into StratTraderPro stop working and must be
> re-pasted (`broker.status` will flip to Error on the next call).

The paper trading endpoint these keys authenticate against is
`https://paper-api.alpaca.markets`. We hard-code `paper=True` server-side in
M04 — the live URL is unreachable by construction.

## Step 3 — Connect the keys via the app UI (NOT env vars)

1. On staging, go to **`/settings/brokers`**.
2. Click **Connect Alpaca Paper**. Paste the **API Key ID** and **Secret Key**
   from Step 2 into the two fields. (The secret field is write-only — it is
   never echoed back by any serializer.)
3. Save. The keys are Fernet-encrypted at rest with the platform KEK (same
   pattern as MFA + webhook secrets).
4. Click **Test connection**. This calls Alpaca `GET /v2/account` and should
   show your paper **account number** and **buying power**. A `401/403` surfaces
   as `BROKER_AUTH_FAILED`; a non-paper account/endpoint surfaces as
   `BROKER_LIVE_KEYS_FORBIDDEN` (AC-04-6).

> Do **not** put these keys in `.env` / Railway env vars. Production users
> always bring their own keys through this UI; the optional `ALPACA_*` env vars
> are a local-dev smoke convenience only and are not the path under test here.

## Step 4 — Fire a real TradingView alert at the staging webhook

1. In TradingView, open the chart with your strategy and click **Alerts →
   Create alert**.
2. **Condition:** pick your strategy + the signal to fire.
3. **Notifications → Webhook URL:** paste your staging webhook URL from the
   prerequisites.
4. **Message:** paste the JSON template from the app's "Configure your
   TradingView alert" help — placeholders pre-filled and `sig` set to your
   secret. Confirm `order_type` is `MKT` (or a marketable `LMT`) and the symbol
   is a US equity/ETF.
5. **Save**, then trigger the alert (either wait for the condition or use
   TradingView's "fire now" on a manual condition).

## Expected results

Assert all of the following (this is AC-04-7 + AC-04-8 + §10.4):

- [ ] **Webhook accepted:** the POST returns `200` within TradingView's 3 s
  timeout (target 300 ms p95). A `401` means the `sig` doesn't match the
  current secret; a `400` means the payload failed your saved JSON Schema.
- [ ] **Order visible in Alpaca:** open the Alpaca **paper** dashboard →
  Orders. You see an equity **market DAY** order with our `client_order_id`
  `stp-<alert-uuid>`, moving `new → filled`.
- [ ] **Fill lands in our dashboard ≤ 5 s:** the StratTraderPro dashboard
  positions widget and today's-fills feed update within ~2 s of the fill (WS
  push), well inside the 5 s §10.4 bound. The fill arrived via Alpaca's
  `trade_updates` stream → Redis Stream `fills:user:{id}` → `FillIngestor`.
- [ ] **Positions match:** the symbol, quantity, and average cost shown in our
  positions widget match the Alpaca paper Positions view.
- [ ] **Broker status healthy:** `/settings/brokers` shows the account
  **Connected**; `GET /api/v1/brokers/{id}/status/` reads `CONNECTED` (the
  streams service refreshes the heartbeat every 15 s).

Record the order id, `client_order_id`, fill price, and end-to-end latency in
the PR description.

## Troubleshooting / known quirks

| Symptom | Likely cause | Action |
|---|---|---|
| Order sits at `SUBMITTED`/`new`, never fills | **Fired outside RTH** — market orders queue until the open | Re-run during RTH (16:30–23:00 Israel time), or use a marketable limit order. This is the single most common false failure. |
| Webhook returns `401` | `sig` in the alert message ≠ current secret (rotated, or copied wrong) | Re-copy the secret from the webhook modal; rotate + re-paste if lost. See ADR-042 for why this is a bearer-secret compare. |
| Webhook returns `400` | Payload failed the strategy's saved JSON Schema | The `400` body includes the schema error detail; fix the alert Message JSON. |
| Test connection fails `BROKER_AUTH_FAILED` | Wrong/expired keys, or keys **regenerated** in the Alpaca dashboard after pasting | Regenerate in Alpaca, re-paste both values (regenerating invalidates the old pair). |
| Test connection fails `BROKER_LIVE_KEYS_FORBIDDEN` | Live keys pasted instead of paper | Generate keys from the **Paper** section; M04 is paper-only and rejects live keys server-side. |
| `duplicate=true`, no new order | Same `idempotency_key` replayed within 24 h (Redis `SETNX` guard) | Expected idempotency behaviour. Fire a fresh alert (new `{{time}}`/order id) to place a new order. |
| Order rejected `USER_HALTED` / `STRATEGY_HALTED` | A `TradingHalt` row is active for the user or strategy | Release the halt, then re-fire. The endpoint still returns `200` with `rejected: <reason>`. |
| Order rejected `ORDER_UNSUPPORTED_ASSET` | Symbol is not a US stock/ETF (option/crypto/future) | M04 supports US equities + ETFs only; pick e.g. `AAPL`/`SPY`. |
| Fill never reaches our dashboard though Alpaca shows filled | `run_broker_streams` down or `broker.status` DEGRADED | Check the streams service and `GET /api/v1/brokers/{id}/status/`; on restart, REST catch-up (`get_orders`) recovers missed fills, deduped on `broker_exec_id`. See `docs/runbooks/webhook-debug.md`. |
| `429` / `BROKER_RATE_LIMITED` | Alpaca ~200 req/min/account ceiling under a burst | Client token-bucket + jittered retry; wait and re-fire. Not expected for a single smoke. |
| Rate limit `429` from **our** endpoint | >60 alerts/min for one user (per-user webhook rate limit, applied before body read) | Slow the alert cadence. |

### Notes carried from the pivot

- The `paper=True` construction hard-codes `https://paper-api.alpaca.markets`;
  there is no code path in M04 that reaches the live endpoint.
- Unlike the parked IBKR gateway, Alpaca has **no** paper-account dormancy
  re-auth and **no** one-session-per-boot limit (ADR-041) — a smoke that
  worked yesterday works today with the same keys, as long as the keys weren't
  regenerated.
