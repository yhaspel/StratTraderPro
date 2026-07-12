# Runbook — TradeStation OAuth (connect, refresh, recover)

**Last reviewed:** 2026-07-12

**Owner:** Yuval
**Status:** **NOT YET LIVE-VERIFIED — approval-gated.** The TradeStation adapter
and its entire OAuth2/PKCE flow ship behind `BROKER_TRADESTATION_ENABLED`
(default **false**), exercised only by unit tests against the documented API
shapes and recorded fixtures. TradeStation API access was not granted in the M05
window (ADR-050 descope). **This runbook is the procedure the operator will
follow once access is granted and the flag is flipped on** — treat every step as
"expected behavior per the code + TS docs", to be confirmed on first live run.
**Companion docs:** `docs/adr/050-broker-adapter-abstraction.md` (the credential
model: OAuth tokens vs Alpaca's key pair), `docs/adr/042-webhook-secret-in-body.md`
+ ADR-031 (the shared Fernet KEK these tokens reuse),
`docs/runbooks/mfa-kek-rotation.md` (KEK rotation re-wraps TS tokens too),
`project-plan/05-tradestation-and-order-lifecycle.md` §6.1, §9, §11.

## When to use this runbook

- A user reports **"Reconnect TradeStation"** on `/settings/brokers`, or the
  broker badge for a TradeStation account is **Error / Down**.
- A TradeStation adapter call fails with **`BROKER_REAUTH_REQUIRED`** in logs or
  audit rows (`BrokerCallAudit.error_code`).
- `oauth_refresh_total{broker="tradestation",result="fail"}` is climbing (the
  §12 "OAuth refresh failure rate > 5% / hr" alert has fired).
- You are enabling TradeStation for the first time and validating the flow end
  to end (the deferred live-verification task).

## Preconditions before any of this works

- `BROKER_TRADESTATION_ENABLED=true` on the environment. While it is false, the
  start endpoint returns `503 BROKER_DISABLED` and the callback redirects to
  `/settings/brokers?ts=disabled` — by design.
- App config present: `TRADESTATION_CLIENT_ID`, `TRADESTATION_CLIENT_SECRET`,
  `TRADESTATION_REDIRECT_URI`, `TRADESTATION_OAUTH_BASE` (the authorize/token
  host), `TRADESTATION_API_BASE` (the sim host,
  `https://sim-api.tradestation.com/v3` in M05 — the **live** host is never
  configured in this milestone).
- Redis reachable (the single-use `state` and PKCE `code_verifier` live in the
  Django cache, i.e. Redis).

## How the flow works (authorization_code + PKCE)

The consent flow is standard OAuth2 authorization_code hardened with PKCE and a
single-use signed `state`. Code lives in `backend/apps/brokers/tradestation/`
(`oauth.py`, `views.py`, `client.py`).

1. **Start** — `GET /api/v1/brokers/tradestation/oauth/start/` (JWT + MFA
   enforced). The server:
   - generates a PKCE pair — `code_verifier` (48 random bytes, b64url) and its
     S256 `code_challenge` (`oauth.generate_pkce`);
   - mints a **single-use `state`** bound to the user, stored in Redis with a TTL
     (`TRADESTATION_OAUTH_STATE_TTL`, default 600 s) via `oauth.issue_state`;
   - stashes the `code_verifier` in Redis keyed by that state
     (`oauth.store_verifier`);
   - returns the TradeStation **consent URL**
     (`authorize?response_type=code&client_id=…&code_challenge=…&code_challenge_method=S256&state=…&scope=openid offline_access MarketData ReadAccount Trade`).
   The frontend redirects the user's browser to that URL.

2. **User consents at TradeStation**, which redirects the browser back to
   `GET /api/v1/brokers/tradestation/oauth/callback/?code=…&state=…`. This
   callback is **public** (`AllowAny`, no JWT) — the browser arrives from
   TradeStation with no session. **The single-use signed `state` is the auth**:
   `oauth.consume_state(state)` returns the bound `user_id` **and deletes the
   key** (replay of the same `state` finds nothing → redirect
   `?ts=error&reason=state`). This is why no CSRF token is needed on the callback
   (plan §11) — the state *is* the anti-forgery token.

3. **Code exchange** — `client.exchange_code_for_tokens(code, code_verifier)`
   POSTs `grant_type=authorization_code` + the consumed `code_verifier` to the
   token endpoint. On success we get `access_token`, `refresh_token`,
   `expires_in`, `scope`.

4. **Persist** — for each brokerage account TradeStation returns, we
   `update_or_create` a `BrokerAccount` (`broker=TRADESTATION`, `mode=PAPER`)
   with the tokens **Fernet-encrypted** onto `ts_access_token_enc` /
   `ts_refresh_token_enc`, plus `ts_expires_at` and `ts_scope`. Same platform KEK
   as MFA/webhook/Alpaca secrets (ADR-050 §5). The browser is redirected to
   `/settings/brokers?ts=connected&accounts=N`. Any failure in steps 3–4 is
   caught and redirected as `?ts=error&reason=exchange` (or `…=user`) — the
   callback **never 500s** into the user's browser.

## Where tokens live, and transparent refresh on 401

- **At rest:** `BrokerAccount.ts_refresh_token_enc` (the durable one) and
  `ts_access_token_enc` (short-lived), both Fernet-wrapped. Bytes never leave
  `apps.brokers.services` decrypted; adapter `__repr__` is a redaction guard.
- **In use:** `TradeStationPaperAdapter` builds a `TSClient` lazily, decrypting
  both tokens (`services.decrypt_key`) and passing an `on_refresh` callback.
- **Transparent refresh** — the plan calls for a `@ts_auth_refresh`
  "refresh-on-every-call" decorator (§6.1); this is realized as **refresh-on-401
  inside `TSClient._request`**: any API call that comes back `401` triggers
  `TSClient.refresh()` (a `grant_type=refresh_token` POST) **once**, then the
  original request is retried a single time. On success the client swaps in the
  new access token (and rotated refresh token, if TS returned one) and fires
  `on_refresh`, which **re-encrypts and persists** the rotated tokens back onto
  the `BrokerAccount` (`ts_access_token_enc`, `ts_refresh_token_enc`,
  `ts_expires_at`). Every refresh increments
  `oauth_refresh_total{broker="tradestation",result=ok|fail}`. Because refresh
  tokens rotate and are persisted on each refresh, an active user never needs to
  re-consent within the token's validity (DoD: no re-login within 90 days).

## When a refresh token is revoked / expired

If `refresh()` itself gets a `4xx` (refresh token revoked by TradeStation,
expired from disuse, scope/consent withdrawn, or client secret rotated), the
client raises **`TSAuthError` → error code `BROKER_REAUTH_REQUIRED`**
(non-retryable) and increments `oauth_refresh_total{result="fail"}`. This is a
**terminal** auth state — no amount of retrying fixes it; the user must
re-consent.

**Operator actions:**

1. **Confirm it's a revoke, not a blip.** Check
   `oauth_refresh_total{result="fail"}` and the account's recent
   `BrokerCallAudit` rows (`error_code=BROKER_REAUTH_REQUIRED`). A single failure
   that then succeeds is a transient TS hiccup; a *persistent* fail is a revoke.
2. **Confirm the blast radius is one broker.** A revoked TradeStation token does
   **not** affect the user's Alpaca account — routing to Alpaca keeps working
   (plan §16). Reassure accordingly; this is non-blocking for Alpaca users.
3. **The user re-runs OAuth.** There is no server-side fix for a revoked refresh
   token — by design we hold no recoverable copy. The user goes to
   **`/settings/brokers`**, clicks **Reconnect TradeStation** (the UI banner
   raised off `BROKER_REAUTH_REQUIRED`), and walks the consent flow again from
   step 1 above. `update_or_create` on `(user, TRADESTATION, account_number)`
   means re-consent **overwrites** the dead tokens in place — no duplicate
   account rows.
4. **If re-consent also fails**, work down the triage table below (client
   secret rotated? redirect URI mismatch? clock skew? flag off?).

## Failure-mode triage

| Symptom | Likely cause | Action |
|---|---|---|
| Start endpoint returns `503 BROKER_DISABLED` | `BROKER_TRADESTATION_ENABLED=false` | Expected while descoped. Flip the flag on the env once access is granted. |
| Callback lands `?ts=error&reason=state` | `state` expired (> TTL), already used (replay), or Redis lost it | Restart the flow from `/settings/brokers`; the state is single-use and short-lived by design. Check Redis health if it recurs for everyone. |
| Callback lands `?ts=error&reason=exchange` | Code exchange failed — bad `client_secret`, redirect-URI mismatch, expired `code`, or clock skew on PKCE | Verify `TRADESTATION_CLIENT_SECRET` and that `TRADESTATION_REDIRECT_URI` **exactly** matches the app registered at TradeStation. Retry the flow (a fresh `code`). |
| Calls fail `BROKER_REAUTH_REQUIRED`; refresh 401s | Refresh token revoked/expired, or client secret rotated after issuance | User re-runs OAuth (above). If a secret rotation caused a fleet-wide wave, expect **all** TS users to re-consent. |
| `oauth_refresh_total{result="fail"}` > 5%/hr alert | Systemic: TS token endpoint down, clock skew, or a bad `client_secret`/`client_id` deploy | Check TS status + the last config deploy. This is infra, not per-user — don't tell users to reconnect until it's ruled out. |
| Account connected but `list_positions`/`place_order` 401 then **recovers** | Normal transparent refresh on an expired access token | No action — this is the happy path; the rotated tokens were persisted. Confirm via a `result="ok"` refresh datapoint. |
| Broker badge Error right after KEK rotation | Tokens re-wrapped incorrectly, or rotation missed the TS columns | Re-run `docs/runbooks/mfa-kek-rotation.md` for this surface; KEK rotation must re-wrap `ts_*_enc` alongside `api_*_enc`. |
| Duplicate TradeStation accounts after reconnect | Shouldn't happen — `update_or_create` keys on `(user, broker, account_number)` | If seen, the returned `AccountID` changed between consents; investigate the TS account list mapping (`from_ts_account`). |

## Security notes (plan §11)

- **PKCE (S256)** on every authorization request mitigates auth-code
  interception — a stolen `code` is useless without the `code_verifier`, which
  never leaves our Redis.
- **`state` is single-use and user-bound**, stored in Redis and deleted on
  consume — this both prevents replay and stands in for CSRF on the public
  callback.
- **No secrets in logs.** The callback logs `ts.oauth.callback_failed` with no
  token material; tokens are only ever handled encrypted outside a live request.
- **Refresh tokens are the crown jewels** — Fernet-wrapped at rest, rotated and
  re-persisted on each refresh, and never returned to any client/serializer.

## First live-verification checklist (the deferred task)

When TradeStation access is granted, before trusting this in prod:

- [ ] Set `BROKER_TRADESTATION_ENABLED=true` + the four `TRADESTATION_*` config
  values on staging; confirm `TRADESTATION_API_BASE` is the **sim** host.
- [ ] Run the consent flow from `/settings/brokers`; confirm redirect
  `?ts=connected&accounts=N` and encrypted `ts_*_enc` populated on the row.
- [ ] Force an access-token expiry (or wait it out); make an API call; confirm
  the 401→refresh→retry path succeeds and `oauth_refresh_total{result="ok"}`
  increments and the rotated tokens are re-persisted.
- [ ] Revoke the app's consent at TradeStation; confirm the next call surfaces
  `BROKER_REAUTH_REQUIRED` and the UI shows **Reconnect TradeStation**, with
  Alpaca routing unaffected.
- [ ] Re-verify the option/futures symbology conversions (ADR-050 §4) against
  real TS order acks — the highest-risk assumption in the descoped adapter.
- [ ] Log the run in the M05 PR / exit-gate checklist and lift the
  NOT-YET-LIVE-VERIFIED banner from this runbook.
