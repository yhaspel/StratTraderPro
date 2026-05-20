# Milestone 04A — IBKR Client Portal Web API (OAuth) Migration

> **Slot:** Between M04 and M05 (sub-milestone, refactor)
> **Duration:** 5–7 working days (after IBKR consumer approval clears — see §5)
> **Depends on:** M04 (Webhook + IBKR Gateway adapter), M02 (MFA & Profile)
> **Unlocks:** M05 (TradeStation + Order Lifecycle), and the multi-tenant story end-to-end
> **Status:** Planning — blocked on IBKR developer-portal enrollment

## 1. Purpose

Replace the M04 IB-Gateway-per-process credential model with IBKR's Client Portal Web API using OAuth 2.0 (PKCE) per user. After this milestone:

- StratTraderPro never sees a user's IBKR username or password.
- Each user authenticates with IBKR directly via a browser redirect from our dashboard.
- We hold per-user OAuth tokens in encrypted DB rows, not env vars on a sidecar.
- We can support N concurrent users without spawning N gateway containers.
- The `BrokerAdapter` protocol from M04 is unchanged; only the IBKR implementation is swapped.

This is the prerequisite for any multi-user beta.

## 2. Background & Rationale

M04 shipped `IBKRPaperAdapter` against IB Gateway with `TWS_USERID` / `TWS_PASSWORD` injected as env vars into a sidecar container, plus IBC for autologin. That works for one developer (you), but it has three structural problems for a SaaS:

1. **One gateway = one IBKR user.** TWS API does not multiplex sessions, so user count = container count, with all the orchestration cost that implies.
2. **We hold cleartext-equivalent broker passwords.** Even encrypted at rest, decryption-into-env exposes a plaintext window during gateway startup, and rotating a user's password requires re-injecting into a running container.
3. **Daily re-auth (Secure Login System) is invasive on the live side.** Each user would have to acknowledge SLS prompts in their IBKR Mobile every day for our gateway to come back up.

The Client Portal Web API solves all three: each user OAuths directly with IBKR, we receive bearer tokens scoped to that user's account, sessions are pure HTTPS + WS, and there is no gateway process. The trade-offs (feature gaps and a tickle-keepalive model) are acceptable for the order types and streaming we actually use.

This milestone is intentionally placed **after** M04 so we ship a working IBKR path quickly (gateway), prove the broker abstraction, then refactor to the production-quality transport before adding TradeStation in M05.

## 3. In Scope

- IBKR developer-portal enrollment (one-time, see §5).
- New Django app `apps/brokers/ibkr_webapi` containing:
  - OAuth 2.0 authorization-code-with-PKCE flow (`/connect/start`, `/connect/callback`).
  - Encrypted token store (`IBKRSession` model) with refresh-token rotation.
  - Session manager: tickle keepalive, brokerage-session reauth, per-user session lifecycle.
  - `IBKRWebAPIAdapter` implementing the M04 `BrokerAdapter` protocol.
  - WebSocket client to `/v1/api/ws` for streaming order events and (where used) live market data.
- Frontend: replace the M04 username/password broker-connect form with a "Connect with IBKR" button that performs the OAuth handshake.
- Feature flag `BROKER_IBKR_TRANSPORT={gateway|webapi}` so we can A/B in dev and roll out behind a flag.
- Migration tooling: a one-shot management command that walks existing M04 `BrokerAccount(broker=IBKR)` rows, marks them `LEGACY_GATEWAY`, and prompts those users to re-link via Web API on next dashboard load.
- Decommission plan for IB-Gateway sidecar + IBC config + `TWS_USERID` / `TWS_PASSWORD` envs.
- Paper environment first; live environment supported but disabled by `ENABLE_LIVE_TRADING` flag inherited from M04/M05.
- Updated runbooks, ADR, observability.

## 4. Out of Scope

- TradeStation adapter (M05).
- Advanced order types not yet used in M04 (OCO, bracket) — covered in M05.
- Streaming historical bars beyond what M04 already needs (M06 territory).
- Migrating the test/CI path off `FakeBrokerAdapter` — unit + integration tests still use the fake.
- Full institutional OAuth 1.0a flow (consumer-key + RSA-signed) — documented in §16 as a fallback if our OAuth 2.0 application isn't approved in time, but **not** built unless that fallback is triggered.

## 5. Prerequisites — User Action Items (BLOCKING)

These must be completed by Yuval **before** any code in §8 can be merged. They involve IBKR account/portal actions that only the account holder can perform, and several have multi-day turnaround.

### 5.1 IBKR Developer Portal Enrollment

> **Owner:** Yuval. **Lead time:** 5–10 business days for approval. **Cost:** none.

1. Sign in at <https://www.interactivebrokers.com/sso/Authenticator> with the StratTraderPro developer credentials (the same Israel unified login).
2. Navigate to **User Settings → API → Web API → Manage Applications** → **Create Application**.
3. Fill the application form:
   - **Application name:** `StratTraderPro`.
   - **Description:** "Per-user algorithmic trading platform integrating TradingView alerts → broker execution."
   - **Application type:** "OAuth 2.0 — Individual Customer Access" (NOT "Institutional / Third-Party"; that's the OAuth 1.0a flow).
   - **Grant types:** `authorization_code` + `refresh_token`.
   - **Redirect URIs (exact, https-only, no trailing slash):**
     - `https://app.strattraderpro.com/api/v1/brokers/ibkr/oauth/callback/` (prod)
     - `https://staging.strattraderpro.com/api/v1/brokers/ibkr/oauth/callback/` (staging)
     - `http://localhost:8000/api/v1/brokers/ibkr/oauth/callback/` (dev — only if IBKR allows http on localhost; if not, terminate TLS locally with mkcert)
   - **Scopes requested:** `trading`, `account-info`, `market-data` (request the minimum we actually use; we can add more later).
   - **Environment:** create **two** applications — one for **paper** and one for **live**. They have different consumer IDs. You'll wire both into our config.
4. Sign and accept IBKR's **Web API Developer Agreement**.
5. Submit. Watch for an approval email from IBKR. Approval can be 1–10 business days.
6. On approval, copy and save securely (1Password vault `strattraderpro-ibkr-webapi`):
   - `IBKR_WEBAPI_CLIENT_ID_PAPER`
   - `IBKR_WEBAPI_CLIENT_SECRET_PAPER`
   - `IBKR_WEBAPI_CLIENT_ID_LIVE`
   - `IBKR_WEBAPI_CLIENT_SECRET_LIVE`
   - The exact authorization endpoint and token endpoint URLs IBKR returns (they sometimes vary by region).

### 5.2 Approve Web API in the IBKR Account Settings

> **Owner:** Yuval (and every future user, in their own onboarding flow). **Lead time:** immediate.

1. **User Settings → API → Settings** → enable **"Allow Web API access for this account"**.
2. Acknowledge the data subscription and order routing disclaimers.
3. Confirm IBKR Mobile is installed and registered for the Secure Login System on the account that will be used for live (paper accounts skip SLS, as noted in our existing IBKR-paper-login memory).

### 5.3 Confirm Market Data Subscriptions

> **Owner:** Yuval per account. **Lead time:** immediate to monthly billing cycle. **Cost:** varies.

The Web API does not bypass per-account market-data subscriptions. For each account we'll trade, confirm subscriptions via **User Settings → Market Data Subscriptions**:

- **US Securities Snapshot and Futures Value Bundle** (snapshot is enough for paper testing).
- **OPRA** if options will be used in M05+.
- For real-time streams in M06+, upgrade to **NYSE Network B / Nasdaq Network C** (paper accounts get free 15-min-delayed by default — sufficient for M04A).

### 5.4 RSA Keypair (only if OAuth 1.0a fallback triggered)

> **Owner:** Yuval. **Lead time:** 30 minutes. **Trigger:** only if §5.1 OAuth 2.0 application is rejected.

If we have to use OAuth 1.0a instead:

```bash
openssl genrsa -out ibkr_oauth1_private.pem 2048
openssl rsa -in ibkr_oauth1_private.pem -pubout -out ibkr_oauth1_public.pem
```

Upload `ibkr_oauth1_public.pem` to the IBKR Developer Portal under the application. Store the private key in Railway as a sealed secret named `IBKR_OAUTH1_PRIVATE_KEY_PEM`. **Never commit this file.**

### 5.5 Domain & Cert Prerequisites

> **Owner:** Yuval. **Lead time:** dependent on DNS propagation.

- Confirm `app.strattraderpro.com` and `staging.strattraderpro.com` resolve and have valid TLS (Railway provides this).
- Whitelist these domains in any browser-side CORS/CSRF middleware — we'll be doing redirect flows.

### 5.6 Decision Sign-offs Before Coding

Yuval to confirm in writing in the project tracker:

- [ ] **Single consumer model** (one StratTraderPro app, all users OAuth into it) vs. user-supplied apps. Default: single consumer. Confirm.
- [ ] **Paper-only acceptance.** M04A ships and is exit-gated against paper. Live trading is left disabled until M12 hardening.
- [ ] **Migration tolerance.** It's acceptable to require any M04-era IBKR-connected user to re-link via OAuth (we do not silently migrate them).

Until §5.1 approval lands and §5.6 is signed off, M04A is **blocked**. Code prep work in §8.1 (DB models, scaffolding) can begin in parallel against IBKR's published documentation; anything that requires hitting their auth endpoints waits.

## 6. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-04A-1 | Clicking "Connect IBKR (Paper)" on `/settings/brokers` redirects to IBKR's authorization page; on consent, redirects back; an `IBKRSession` row is created with encrypted access + refresh tokens. |
| AC-04A-2 | The OAuth callback validates `state` (CSRF) and `code_verifier` (PKCE); replay or tampering returns 400 with `OAUTH_STATE_MISMATCH` and writes an audit row. |
| AC-04A-3 | After a successful link, GET `/api/v1/brokers/{id}/status/` returns `{authenticated: true, brokerage_session: true, account_id: "DUxxxxxx"}` within 5s. |
| AC-04A-4 | A scheduled tickle task pings `/v1/api/tickle` every 50s for every active session; sessions remain alive across a 30-minute idle window in CI. |
| AC-04A-5 | A simulated tickle 401 triggers `/sso/init` reauth flow; if reauth fails, the session is marked `NEEDS_REAUTH` and the dashboard shows a "Reconnect IBKR" banner. |
| AC-04A-6 | Refresh-token rotation: when an access token is within 5 minutes of expiry, the next API call transparently exchanges the refresh token; new tokens persist; old refresh token is invalidated. |
| AC-04A-7 | Placing an equity market order via the webhook pipeline against `IBKRWebAPIAdapter` results in a paper fill; the fill arrives via WebSocket within 5s; positions update on the dashboard. |
| AC-04A-8 | The same E2E webhook test from M04 passes against `BROKER_IBKR_TRANSPORT=webapi` with no test changes other than adapter selection. |
| AC-04A-9 | Two distinct test users, each linked to their own IBKR paper account, can place orders concurrently; orders are correctly attributed and there is no token cross-contamination. |
| AC-04A-10 | Removing a broker connection (`DELETE /api/v1/brokers/{id}/`) revokes the IBKR refresh token via IBKR's `/revoke` endpoint, deletes the `IBKRSession` row, and the user is logged out at IBKR. |
| AC-04A-11 | No IBKR access or refresh tokens ever appear in logs, error messages, or APM traces (verified by automated log scan in CI). |
| AC-04A-12 | The IB-Gateway sidecar service is removed from `docker-compose.yml`, `compose.staging.yml`, `compose.prod.yml`, and `railway.toml`; the dedicated `ibkr-gateway` Railway service is deleted from both production and staging environments. |
| AC-04A-12a | Every legacy credential env var (`TWS_USERID`, `TWS_PASSWORD`, `TWS_PAPER_USERID`, `TWS_PAPER_PASSWORD`, `TRADING_MODE`, `IBC_PATH`, `TWS_VERSION`, `IBC_TRUSTED_IPS`) is removed from: Railway (every service, every environment), `.env.example`, all `compose*.yml` files, `railway.toml`, GitHub Actions secrets, and all `os.environ.get(...)` reads in `apps/strattrader/settings/*.py` and `apps/brokers/ibkr/`. |
| AC-04A-12b | A CI grep gate (`.github/workflows/ci.yml` job `block-legacy-ibkr-creds`) fails the build if any of those variable names re-appear in tracked code outside the documented allowlist (this plan + superseded ADRs). |
| AC-04A-12c | Both IBKR live and paper account passwords were rotated **before** the env-var deletion; the old values were verified invalid; rotation is logged in the M04A PR description with timestamps. |
| AC-04A-13 | A user whose IBKR password changes mid-session sees the next request return `NEEDS_REAUTH`; re-OAuthing restores trading; no orders are placed during the broken window. |
| AC-04A-14 | Rate-limit handling: when IBKR returns 429, requests are retried with jitter up to 3 times, then surfaced as `BROKER_RATE_LIMITED`; no order is silently dropped. |
| AC-04A-15 | The OpenAPI spec lists the new connect/callback endpoints; the legacy `/api/v1/brokers/` POST with username/password returns 410 Gone with a deprecation message pointing at the OAuth flow. |

## 7. Definition of Done

Baseline DoD applies, plus:

- The `BrokerAdapter` protocol is unchanged. Diff against M04's `apps/brokers/ibkr/adapter.py` consists only of the new transport class and the registration; no change to public method signatures.
- ADR `docs/adr/04A-ibkr-webapi-oauth.md` committed, summarizing the decision and trade-offs.
- Runbooks `docs/runbooks/ibkr-oauth-recover.md`, `docs/runbooks/ibkr-session-debug.md` committed.
- Localized error code map updated: `BROKER_IBKR_OAUTH_FAILED`, `BROKER_IBKR_NEEDS_REAUTH`, `BROKER_IBKR_RATE_LIMITED`, `BROKER_IBKR_REVOKED`.
- `BROKER_IBKR_TRANSPORT` defaults to `webapi` in `staging.py` and `prod.py`. `local.py` retains `gateway` only until §8.9 rip-out lands.
- All M04 IBKR tests pass against the new adapter (parameterized run).
- The new `IBKRSession` table has a Postgres `CHECK` constraint enforcing exactly one of `{access_token_enc, oauth1_token_enc}` is non-null (forward-compat with §5.4 fallback).

## 8. Implementation Tasks

### 8.1 Scaffolding & data model (Day 1)

New Django app `apps/brokers/ibkr_webapi` with the following structure:

```
apps/brokers/ibkr_webapi/
├── __init__.py
├── adapter.py                  # IBKRWebAPIAdapter
├── client.py                   # Low-level HTTP/WS client
├── oauth.py                    # OAuth 2.0 flow helpers (PKCE, token exchange, revoke)
├── session_manager.py          # Tickle, reauth, lifecycle
├── tasks.py                    # Celery: tickle_active_sessions, refresh_expiring_tokens
├── models.py                   # IBKRSession, IBKRSessionAudit
├── views.py                    # OAuth start/callback DRF views
├── serializers.py
├── urls.py
├── exceptions.py               # IBKRWebAPIError hierarchy
├── constants.py                # Endpoint URLs, retryable error codes
└── tests/
    ├── test_oauth.py
    ├── test_session_manager.py
    ├── test_adapter.py
    └── conftest.py             # vcr.py cassettes against recorded IBKR responses
```

Migrations:

```python
class IBKRSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    broker_account = models.OneToOneField(BrokerAccount, on_delete=models.CASCADE)
    ibkr_account_id = models.CharField(max_length=32)         # e.g., "DU1234567"
    environment = models.CharField(choices=[('paper','paper'),('live','live')])
    access_token_enc = models.BinaryField(null=True)          # Fernet-encrypted
    refresh_token_enc = models.BinaryField(null=True)
    oauth1_token_enc = models.BinaryField(null=True)          # reserved for fallback
    access_token_expires_at = models.DateTimeField()
    refresh_token_expires_at = models.DateTimeField(null=True)
    last_tickle_at = models.DateTimeField(null=True)
    last_reauth_at = models.DateTimeField(null=True)
    brokerage_session_authenticated = models.BooleanField(default=False)
    state = models.CharField(choices=['ACTIVE','NEEDS_REAUTH','REVOKED'])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(Q(access_token_enc__isnull=False) | Q(oauth1_token_enc__isnull=False)),
                name='ibkrsession_one_token_set',
            ),
        ]
```

### 8.2 OAuth 2.0 flow (Day 1–2)

`apps/brokers/ibkr_webapi/oauth.py`:

- `build_authorize_url(user, environment) -> (url, state, code_verifier)` — generates PKCE pair, stores `state` + `code_verifier` in Redis with 10-min TTL keyed by `oauth:ibkr:{user_id}:{state}`, returns the IBKR consent URL with `client_id`, `redirect_uri`, `scope`, `code_challenge`, `code_challenge_method=S256`, `response_type=code`, `state`.
- `exchange_code(code, state, user) -> IBKRSession` — verifies `state` matches Redis entry, fetches `code_verifier`, POSTs to IBKR `/oauth2/api/v1/token` with `grant_type=authorization_code`, persists encrypted tokens, fires `broker.connected` audit event.
- `refresh_access_token(session) -> None` — POSTs `grant_type=refresh_token`, rotates both access and refresh tokens, persists.
- `revoke_session(session) -> None` — POSTs to `/oauth2/api/v1/revoke`, deletes `IBKRSession` row.

DRF views in `views.py`:

- `POST /api/v1/brokers/ibkr/oauth/start/` — body `{environment: 'paper'|'live'}`, returns `{authorize_url}`. The frontend redirects the user there.
- `GET /api/v1/brokers/ibkr/oauth/callback/?code=...&state=...` — server-side handler, exchanges code, redirects to `${FRONTEND_URL}/settings/brokers?ibkr_link=success` (or `=failure&reason=...`).

`state` and `code_verifier` are HMAC-bound to the user session to prevent cross-user CSRF.

### 8.3 Encrypted token storage (Day 2)

- Reuse the M02 envelope-encryption helper (`apps/security/crypto.py: encrypt_for_user / decrypt_for_user`).
- Token DEK derived per `BrokerAccount`; KEK in Railway-managed env (`PLATFORM_KEK_BASE64`) — same model as TradeStation refresh tokens in M05.
- Tokens are written via `encrypt_for_user(user, token_bytes)` and read via `decrypt_for_user(user, blob)`. They are **never** stored as strings or returned in any serializer.
- `IBKRSession.__repr__` redacts all `*_enc` fields. Add a `tests/test_no_token_in_repr.py` test.

### 8.4 Session manager: tickle + reauth (Day 2–3)

`session_manager.py` exposes:

```python
class IBKRSessionManager:
    def get_active_session(self, broker_account_id) -> IBKRSession | None
    def ensure_brokerage_session(self, session) -> None      # /iserver/auth/status + reauth if needed
    def tickle(self, session) -> None                        # POST /v1/api/tickle
    def refresh_if_expiring(self, session) -> None
    def mark_needs_reauth(self, session, reason) -> None
    def call_with_session(self, session, fn) -> Any         # context manager: ensure + execute + tickle
```

Celery beat tasks (`tasks.py`):

- `tickle_active_sessions` — every 50s. Queries `IBKRSession.objects.filter(state='ACTIVE')`, dispatches a tickle in parallel (group of `tickle_one(session_id)` subtasks). Idempotent. Logs metrics.
- `refresh_expiring_tokens` — every 5 min. Refreshes any session whose access token expires in < 10 min.
- `daily_brokerage_reauth_check` — every 1 hour. Calls `/iserver/auth/status`; if `authenticated=false`, attempts `/iserver/reauthenticate`; if that fails, marks `NEEDS_REAUTH`.

Concurrency: per-session Redis lock (`lock:ibkr:session:{id}`, TTL 5s) prevents two workers from refreshing the same token simultaneously.

### 8.5 IBKRWebAPIAdapter (Day 3–4)

`adapter.py`:

```python
class IBKRWebAPIAdapter(BrokerAdapter):
    name = 'ibkr_webapi'
    supported_asset_classes = ['STOCK', 'ETF']   # M04A scope; options/futures M05

    def __init__(self, broker_account: BrokerAccount):
        self.account = broker_account
        self.session_mgr = IBKRSessionManager()
        self.client = IBKRWebAPIClient(self.session_mgr)

    def connect(self, _creds_unused=None) -> ConnectionInfo:
        # No-op in OAuth world: connection is implicit in having a valid IBKRSession.
        # We just verify session liveness.
        ...

    def place_order(self, req: OrderRequest, client_order_id: str) -> OrderAck:
        contract = self._resolve_contract(req)
        body = self._build_order_body(req, contract, client_order_id)
        res = self.client.post(
            f'/iserver/account/{self.session.ibkr_account_id}/orders',
            json={'orders': [body]},
        )
        return self._parse_order_ack(res)

    async def stream_fills(self) -> AsyncIterator[Fill]:
        # See §8.6 — delegates to WebSocket client.
        ...

    def health(self) -> BrokerHealth:
        ...
```

The low-level `IBKRWebAPIClient` (in `client.py`):

- Wraps `httpx.Client` with `Authorization: Bearer {access_token}`.
- Auto-retries on 429 with exponential jitter (3 attempts, 250ms base).
- Auto-refreshes on 401 (`{error: "session_expired"}`) by calling `session_mgr.refresh_if_expiring` and replaying once.
- Records every request to `BrokerCallAudit` (see M04 audit infra) without bodies.

Contract resolution: `POST /iserver/secdef/search` with `symbol` + `secType=STK`, takes the first result's `conid`. Cache `(symbol, exchange, currency) -> conid` in Redis with 24h TTL.

Order body for an equity market order:

```json
{
  "acctId": "DU1234567",
  "conid": 265598,
  "orderType": "MKT",
  "side": "BUY",
  "tif": "DAY",
  "quantity": 100,
  "cOID": "client-order-id-uuid"
}
```

IBKR returns either an order acknowledgment or a precaution prompt (e.g., "this order exceeds X% of ADV"). The adapter auto-replies with the response endpoint using the `id` IBKR returned, **only for precautions whitelisted in `constants.PRECAUTION_AUTOREPLY`**. Anything else is surfaced as `BROKER_PRECAUTION_REQUIRED` and the order is rejected with a clear audit row. (This is a known IBKR Web API quirk — silent auto-reply to all precautions is dangerous.)

### 8.6 WebSocket streaming (Day 4)

`client.py` exposes an async `WebSocketStream`:

- Connects to `wss://api.ibkr.com/v1/api/ws` with the cookie-based auth cookie returned from a prior `/v1/api/sso/validate` call.
- Subscribes to `sor` (system order router) topic for order/fill events.
- Emits decoded `Fill` DTOs into the existing Redis Stream `fills:user:{id}` (M04 contract — no change).
- Reconnect with `tenacity` exponential backoff; on reconnect, replays missed fills via REST `GET /iserver/account/orders` + `GET /iserver/account/{id}/trades`.

Heartbeat: WS server pings every 60s; we respond. If the connection drops during the tickle window, `tickle_active_sessions` resurrects via REST + we re-open the WS.

### 8.7 Frontend OAuth flow (Day 4–5)

Files (Angular, signal-based — per project convention):

- `frontend/src/app/features/brokers/ibkr-connect.component.ts` — replaces the M04 username/password form for IBKR.
- `frontend/src/app/core/services/brokers.service.ts` — gains `startIbkrOAuth(env): Observable<{authorize_url}>` and `resolveIbkrCallback(query): void`.
- `frontend/src/app/features/brokers/oauth-result.component.ts` — landing page for the `?ibkr_link=success|failure` redirect.

UX:

1. `/settings/brokers` → "Connect IBKR" button → modal with **Paper** / **Live** toggle (Live disabled with tooltip until `ENABLE_LIVE_TRADING`).
2. Click → `POST /api/v1/brokers/ibkr/oauth/start/` → redirect `window.location.href = authorize_url`.
3. User signs into IBKR, consents.
4. IBKR redirects back to `/api/v1/brokers/ibkr/oauth/callback/`.
5. Backend exchanges code, persists session, redirects to `/settings/brokers?ibkr_link=success&account=DU...`.
6. Frontend shows success toast + new account row with status `Connected`.

Failure redirect goes to `?ibkr_link=failure&reason=<code>` with translated copy. `reason` codes: `oauth_state_mismatch`, `oauth_user_denied`, `oauth_token_exchange_failed`, `oauth_no_account`.

### 8.8 Migration: feature flag + dual-adapter coexistence (Day 5)

Add to `apps/brokers/registry.py`:

```python
def get_ibkr_adapter(broker_account):
    if settings.BROKER_IBKR_TRANSPORT == 'webapi':
        return IBKRWebAPIAdapter(broker_account)
    return IBKRPaperAdapter(broker_account)   # M04 gateway
```

`BROKER_IBKR_TRANSPORT` is read from env, default `webapi` in staging/prod, `gateway` in local until §8.9.

Existing M04 `BrokerAccount` rows are not auto-migrated. A management command `mark_legacy_ibkr_accounts`:

- Sets `BrokerAccount.status='LEGACY_GATEWAY'` on every IBKR row created before this milestone.
- These accounts are read-only in the adapter (`place_order` returns `BROKER_LEGACY_REAUTH_REQUIRED`).
- The dashboard surfaces a banner: "Reconnect your IBKR account using the new secure flow."
- Once reconnected via OAuth, a fresh `BrokerAccount` row is written and the legacy one is soft-deleted.

For the dev environment (you), this means a one-time relink. Document in `docs/runbooks/ibkr-oauth-recover.md`.

### 8.9 Decommission of Gateway sidecar + credential env vars (Day 6)

Last step, gated on AC-04A-1 through AC-04A-14 all passing in staging and 48h of clean prod traffic on the new transport. This is a security-relevant cleanup; treat the credential env vars as having been *exposed* (they lived in Railway, in operator terminals, in container snapshots, in any error-trace tooling that captured env at crash time) and act accordingly.

The list of credential-bearing environment variables to remove:

| Variable | Purpose under M04 | Locations to scrub |
|---|---|---|
| `TWS_USERID` | IBKR live username injected to gateway sidecar | Railway, `.env`, `.env.example`, `docker-compose*.yml`, `railway.toml`, settings code, IBC `config.ini`, GitHub Actions secrets |
| `TWS_PASSWORD` | IBKR live password injected to gateway sidecar | same |
| `TWS_PAPER_USERID` | IBKR paper username | same |
| `TWS_PAPER_PASSWORD` | IBKR paper password | same |
| `TRADING_MODE` | `paper` / `live` toggle for IBC | same — fully removed; user-mode now lives on `BrokerAccount.environment` |
| `IBC_PATH`, `TWS_VERSION`, `IBC_TRUSTED_IPS` | IBC-only knobs | settings code, `.env.example`, IBC dir |

#### 8.9.1 Pre-cutover credential rotation (Day 6 morning)

Even though the values are about to be deleted, **rotate them first** so any historical exposure is invalidated:

1. Yuval logs into IBKR and changes the password on the live account (User Settings → Password & Security).
2. Same for the paper account (separate password under IBKR Israel unified login — both must be rotated independently per `reference_ibkr_paper_login.md`).
3. **Do not** update Railway with the new passwords. The whole point is that the new transport doesn't need them. Rotation is purely to invalidate the old leaked values.
4. Confirm the gateway sidecar in staging still boots (it will fail authentication — that's expected and confirms rotation worked).

#### 8.9.2 Code cleanup

In a single PR labeled `chore: rip out IBKR gateway transport`:

- Delete `infra/docker/ibkr-gateway/` directory (Dockerfile + IBC config + entrypoint script).
- Delete `apps/brokers/ibkr/gateway_launcher.py`.
- Rename `apps/brokers/ibkr/adapter.py` → `apps/brokers/ibkr/legacy_adapter.py`. Keep behind `BROKER_IBKR_TRANSPORT=gateway` flag for one release cycle, then drop in M05.
- Remove all `os.environ.get('TWS_*')` and `os.environ.get('TRADING_MODE')` reads from:
  - `apps/strattrader/settings/base.py`
  - `apps/strattrader/settings/dev.py`
  - `apps/strattrader/settings/prod.py`
  - `apps/strattrader/settings/test.py`
  - `apps/brokers/ibkr/legacy_adapter.py` (these become hardcoded `None` for the legacy path; the legacy path is now disabled)
- Remove from `requirements.txt`: nothing — `ib_insync` stays for one release cycle in case we need to flip back; drop in M05.
- Remove `IBC*` files anywhere they sit on disk.

#### 8.9.3 Infra & compose cleanup

- Remove the `ibkr-gateway` service block from:
  - `docker-compose.yml`
  - `compose.staging.yml`
  - `compose.prod.yml`
- Remove the `ibkr-gateway` service entry from `railway.toml`.
- Remove any `TWS_*` / `TRADING_MODE` references from those same files (they're typically declared at service level).
- Remove the dedicated Railway service "ibkr-gateway" via the Railway UI **after** the deploy of the cleanup PR succeeds without it.

#### 8.9.4 Secret-store cleanup

Each item is a manual step — there is no central API that does all of these:

- **Railway dashboard:** for **every** service (`web`, `worker`, `beat`, any prior `ibkr-gateway`), open Variables → delete `TWS_USERID`, `TWS_PASSWORD`, `TWS_PAPER_USERID`, `TWS_PAPER_PASSWORD`, `TRADING_MODE`, `IBC_PATH`, `TWS_VERSION`, `IBC_TRUSTED_IPS`. Verify they no longer appear in any service.
- **Railway environments:** repeat the deletion for each environment (production, staging, preview). Railway scopes vars per environment.
- **`.env.example` (committed):** delete the lines and replace with a comment block: `# IBKR credentials are no longer needed — use OAuth flow at /settings/brokers (M04A)`.
- **Local `.env` (gitignored):** Yuval and any teammate run `scripts/dev/strip_legacy_ibkr_env.sh` — a small script that reads the local `.env`, removes the listed keys, writes back. The script is committed.
- **GitHub Actions secrets:** repo Settings → Secrets and variables → Actions. Delete `TWS_USERID`, `TWS_PASSWORD`, `TWS_PAPER_USERID`, `TWS_PAPER_PASSWORD` if they exist there. Same for organization-level secrets.
- **1Password vault `strattraderpro-railway-secrets`:** archive (don't delete — keep for audit) the items containing the rotated old passwords; tag them `ROTATED-2026-MM-DD-LEGACY`.
- **Sentry / logging back-ends:** kick off a one-off Sentry "Issue Search" for the literal var names; if any breadcrumb captured a value, request data deletion via Sentry's UI. Document the run in the PR description.

#### 8.9.5 Verification gate (CI)

A grep gate is added to `.github/workflows/ci.yml` (and run locally via the existing `make lint-secrets` target):

```yaml
- name: Block legacy IBKR credential references
  run: |
    BANNED='TWS_USERID|TWS_PASSWORD|TWS_PAPER_USERID|TWS_PAPER_PASSWORD|TRADING_MODE|IBC_PATH|TWS_VERSION|IBC_TRUSTED_IPS'
    if grep -RInE "$BANNED" \
        --exclude-dir={node_modules,.venv,.git,project-plan,docs/adr} \
        --exclude="04A-IBKR-Web-API.md" .; then
      echo "::error::Legacy IBKR credential references found. M04A §8.9 requires removal."
      exit 1
    fi
```

The gate excludes this plan and superseded ADRs (those are allowed to *describe* the removed vars in past tense). Anything else surfacing those names fails CI.

#### 8.9.6 Documentation

- Update `docs/adr/040-ibkr-gateway-sidecar.md`: add a "**Superseded by ADR-04A on 2026-MM-DD**" header. Do **not** rewrite history — leave the original decision intact for audit.
- Update `README.md`: remove the "IBKR Gateway Setup" section; replace with a one-liner pointing at the OAuth flow.
- Update `docs/runbooks/ib-gateway-reauth.md`: prepend "Archived as of M04A — kept for historical reference. The Web API supersedes this flow."
- Add a CHANGELOG line under `v0.4.1-ibkr-webapi`: "Removed `TWS_*` credential env vars; IBKR auth now uses per-user OAuth 2.0."

#### 8.9.7 Final manual verification

Yuval runs through and signs off:

- [ ] `rg 'TWS_USERID|TWS_PASSWORD|TWS_PAPER_USERID|TWS_PAPER_PASSWORD' /Users/yuval3000/Documents/Claude/Projects/StratTraderPro` returns nothing (modulo allowlist in §8.9.5).
- [ ] Railway CLI: for each service, `railway variables --service <name>` shows no `TWS_*` or `TRADING_MODE` keys, in **both** production and staging environments.
- [ ] GitHub Actions secrets list does not contain any `TWS_*` keys.
- [ ] The rotated old IBKR passwords are confirmed invalid (attempting to log into IBKR with the old paper password fails).
- [ ] The deployed prod app starts cleanly and processes a paper webhook end-to-end without a gateway sidecar present.

## 9. Tech Stack Notes

- **Library:** No mature Python wrapper for the Web API exists at the quality of `ib_insync`. Build a thin wrapper on `httpx` (sync) + `websockets` (async) ourselves. Reference IBKR's official OpenAPI: <https://www.interactivebrokers.com/api/doc.html>.
- **PKCE:** Use stdlib `secrets.token_urlsafe(64)` for verifier; `hashlib.sha256` + `base64.urlsafe_b64encode` for challenge.
- **Token revocation on disconnect:** IBKR exposes `/oauth2/api/v1/revoke`. Always call it; do not just delete the row.
- **Time sync:** OAuth + tickle are sensitive to clock skew. Add a startup check that asserts host clock is within ±2s of `time.cloudflare.com`. Railway hosts have NTP but document this.
- **Sandbox:** IBKR's developer portal hosts a sandbox at `api.ibkr.com/sb/` for some endpoints — we'll use it for the OAuth flow tests where possible, otherwise hit paper.
- **Avoid `requests-oauthlib` / `authlib`** for the user flow — they assume server-side session storage we don't want. The OAuth code is small enough to write directly and easier to audit.

## 10. Data Model Changes

Migrations:

- `ibkr_webapi.0001_initial` — `IBKRSession` (see §8.1) + `IBKRSessionAudit(session, action, ts, detail_redacted)`.
- `brokers.0002_legacy_status` — adds `LEGACY_GATEWAY` to `BrokerAccount.status` enum + nullable `legacy_replaced_by` self-FK.
- No data migrations beyond the management command in §8.8.

## 11. API Contract Changes

New paths:

```
POST   /api/v1/brokers/ibkr/oauth/start/
GET    /api/v1/brokers/ibkr/oauth/callback/      (browser landing)
POST   /api/v1/brokers/ibkr/{id}/reauth/         (force /sso/init)
DELETE /api/v1/brokers/{id}/                     (now also revokes refresh token)
```

Deprecated:

```
POST /api/v1/brokers/  with body {broker:'IBKR', username, password}
   → 410 Gone, body {error:'BROKER_IBKR_LEGACY_DEPRECATED', oauth_url:'/api/v1/brokers/ibkr/oauth/start/'}
```

OpenAPI: regenerate and check schema diff in PR review. New schemas `IBKRConnectRequest`, `IBKRConnectResponse`, `IBKRSessionStatus`.

## 12. Test Plan

### 12.1 Unit tests

- PKCE generator produces correct `code_challenge` for known verifier vectors (RFC 7636 examples).
- `state` validation rejects mismatched/expired entries.
- Token exchange happy path against a `respx` mock of IBKR token endpoint.
- Refresh-on-401: assert single retry, assert refresh request includes correct `refresh_token`.
- Revocation called on disconnect.
- `_repr_` redacts tokens.
- Precaution auto-reply only fires for whitelisted codes.

### 12.2 Integration tests

- `vcr.py` cassettes recorded once against real IBKR sandbox + paper (kept in `tests/fixtures/ibkr_cassettes/`, scrubbed of tokens).
- Full OAuth flow: simulated browser hits `/start/`, follows redirect, IBKR responds with code, our `/callback/` exchanges, session stored.
- `tickle_active_sessions` keeps a session alive over a 30-min idle in CI (cassette-driven).
- Refresh-token rotation across two consecutive expiries.
- Concurrent users: spin up 10 fake users, each with their own cassette, place 1 order each, assert no token cross-contamination.

### 12.3 Adapter parity tests (M04 reuse)

- The M04 webhook→adapter integration test runs once with `BROKER_IBKR_TRANSPORT=gateway` (legacy, retained until §8.9) and once with `=webapi`. Both must pass.
- `FakeBrokerAdapter` test cases share the same parameterized matrix.

### 12.4 E2E (Playwright)

- `e2e/brokers/ibkr-oauth-link.spec.ts` — drives the full UI flow against a hermetic IBKR mock that imitates `/oauth2/authorize` and `/oauth2/token` (recorded responses with state-aware fixtures). Asserts the success banner + status row.
- `e2e/brokers/ibkr-reauth.spec.ts` — simulates token expiry mid-session, asserts the "Reconnect" banner appears.
- `e2e/orders/webhook-to-paper-fill-webapi.spec.ts` — same as M04 e2e, using webapi transport.

### 12.5 Live against real IBKR paper (manual, one-shot per release)

Run script `scripts/manual_qa/ibkr_webapi_smoke.sh`:

1. Wipe local DB.
2. Seed one user.
3. Trigger OAuth start; you (Yuval) consent in the browser.
4. Send a paper webhook for `AAPL` qty=1.
5. Assert paper account in IBKR Client Portal shows the position.
6. Disconnect; assert IBKR Mobile shows the consent revoked.
7. Document any deviation in the runbook.

### 12.6 Resilience tests

- IBKR returns 500 for 30s mid-trade: adapter retries per backoff policy, eventually surfaces `BROKER_UNAVAILABLE`; no duplicate orders thanks to `cOID`.
- Tickle worker dies: next worker picks up; `last_tickle_at` proves no >2-tick gap.
- Refresh token revoked out-of-band (user clicks "Revoke" in IBKR portal): next API call gets 401, refresh attempt fails, session goes `NEEDS_REAUTH`, dashboard banner shows.

### 12.7 Security tests

- Log scanner: grep recorded test logs for any base64-looking sequence ≥40 chars in known token positions; fail CI if any match.
- Database row inspector: confirm the access_token_enc column never matches the cleartext token used in the test (basic encryption sanity check).

## 13. Security Considerations

- **No password ever transits StratTraderPro.** This is the headline change. Confirmed by a code-review checklist item.
- **Token encryption:** Fernet with per-user DEK, KEK in Railway secrets, key rotation runbook in M11.
- **CSRF on OAuth callback:** `state` is HMAC of `(user_session_id, random_nonce, timestamp)` with platform secret; verified server-side.
- **Open-redirect prevention:** the `redirect_uri` we send to IBKR is hardcoded server-side, never sourced from request input. The post-callback frontend redirect uses an allowlist.
- **Replay attack on `code`:** `code` is single-use by IBKR. We additionally store its hash in Redis with 10-min TTL and reject duplicates.
- **PKCE:** `code_challenge_method=S256` always; `plain` is rejected even if IBKR allows it.
- **Token-in-URL guard:** any redirect or log line containing `access_token=` or `refresh_token=` triggers a startup assertion failure.
- **CORS:** OAuth endpoints are first-party only; no cross-origin POST allowed.
- **Session hygiene:** `IBKRSession.delete()` also revokes at IBKR. Garbage-collect orphaned sessions weekly.
- **Audit trail:** every session lifecycle event (`OAUTH_LINKED`, `OAUTH_REFRESHED`, `OAUTH_REAUTHED`, `OAUTH_REVOKED`, `OAUTH_FAILED`) is appended to `IBKRSessionAudit` with a redacted detail field.

## 14. Observability

Prometheus counters and histograms:

- `ibkr_oauth_total{step,result}` — start, exchange, refresh, revoke; result in {success,fail}.
- `ibkr_session_active_gauge` — number of `state=ACTIVE` sessions.
- `ibkr_tickle_total{result}`.
- `ibkr_api_call_latency_ms{endpoint}` histogram.
- `ibkr_api_errors_total{endpoint,code}`.
- `ibkr_reauth_total{result}`.

OpenTelemetry traces: `oauth.start` → `oauth.callback` → `oauth.exchange` → first `iserver.auth.status`.

Alerts:

- `ibkr_oauth_total{result="fail"}` rate > 5% over 10 min → warn.
- `ibkr_session_active_gauge` drops > 30% in 5 min → page (mass re-auth event).
- `ibkr_tickle_total{result="fail"}` > 10/min → warn.
- Any session > 2 minutes without a tickle → page.

Grafana dashboard: **IBKR Web API** — sessions, OAuth funnel, error rates, tickle health.

## 15. Rollback Plan

Two-stage rollback supported because the gateway adapter is kept until §8.9:

- **Soft rollback (no deploy needed):** flip `BROKER_IBKR_TRANSPORT=gateway`. New orders route through the legacy adapter. Existing webapi sessions are quiesced. Users on legacy `BrokerAccount` rows are unaffected.
- **Hard rollback (after §8.9):** the gateway sidecar is gone, so we'd have to re-deploy the previous tag. This is why §8.9 is a separate, last step gated on staging health.

Migrations are additive. If we have to drop `IBKRSession`, no foreign keys break in the orders or audit tables.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| IBKR rejects our OAuth 2.0 application | Med | High | Apply on Day 0 (today). Fallback path documented (§5.4) using OAuth 1.0a institutional flow; we'd ship that instead with ~3 extra days of work. |
| OAuth approval lands late, blocks M05 | Med | High | Code work in §8.1–§8.6 not blocked on approval; only the live test (§12.5) requires it. We can ship M05 with TradeStation first if needed and defer M04A merge. |
| Web API feature gaps surface (e.g., cannot place a needed order type) | Med | Med | M04A scope is stocks + ETFs only. Options/futures land in M05; we'll discover gaps then with the gateway path still as a fallback. |
| Daily brokerage-session reauth UX friction for live users | Med | Med | Paper accounts skip SLS. For live (M12+), surface a calm, actionable "Reconnect IBKR" banner. We do **not** auto-trade on stale sessions. |
| WebSocket disconnects cause missed fills | Med | High | REST replay on reconnect (`/iserver/account/{id}/trades`) before resuming; idempotency on `Fill.broker_exec_id`. |
| Token leak via misconfigured logging | Low | Critical | Log scanner gate in CI; `__repr__` redaction; structured logger field allowlist. |
| Rate limits stricter than gateway path | Med | Med | Local cache for `conid` lookups; bulk endpoints where IBKR offers them; circuit breaker. |
| Concurrent token-refresh race | Med | Med | Per-session Redis lock around refresh. |
| IBKR changes Web API contract mid-cycle | Low | Med | Pin to specific endpoint versions; nightly synthetic test against paper. |

## 17. Migration Plan (deeper than rollback)

1. Day -10 to Day 0: §5 enrollment in flight; code in §8.1–§8.6 written against documented contracts and recorded cassettes.
2. Day 0 (approval lands): wire client_id/secret into staging Railway secrets.
3. Day 1: deploy to staging behind `BROKER_IBKR_TRANSPORT=webapi`. Yuval relinks his paper account via OAuth.
4. Day 2: run §12.5 smoke; iterate.
5. Day 3: invite 1–2 trusted beta users; monitor.
6. Day 4: flip prod default; legacy gateway still warm.
7. Day 5–6: confirm zero traffic on legacy path for 48h; execute §8.9 rip-out.
8. Day 7: tag release.

## 18. Documentation Deliverables

- `docs/adr/04A-ibkr-webapi-oauth.md` — the decision, alternatives weighed, trade-offs.
- `docs/runbooks/ibkr-oauth-recover.md` — how a user recovers when their session is `NEEDS_REAUTH`.
- `docs/runbooks/ibkr-session-debug.md` — operator guide: how to inspect a user's session, force-refresh, force-revoke.
- `docs/onboarding/ibkr-developer-portal-howto.md` — reproduction of §5.1 with screenshots, for the next developer.
- User help: "Connect your IBKR account (new flow)" with the one-click OAuth screenshot walkthrough.
- Updated `README.md`: remove gateway sidecar startup instructions; add Web API consumer setup.

## 19. Exit Gate Checklist

- [ ] §5 prerequisites all complete (consumer approved, market data confirmed, sign-offs filed).
- [ ] AC-04A-1 … AC-04A-15 pass.
- [ ] §12.5 manual paper smoke executed against real IBKR by Yuval, with screenshots in the runbook.
- [ ] Log scanner CI gate green.
- [ ] Grafana **IBKR Web API** dashboard live.
- [ ] Runbooks committed.
- [ ] ADR-040 marked superseded; ADR-04A merged.
- [ ] Gateway sidecar removed (§8.9) and confirmed absent in `docker-compose.yml`, `compose.staging.yml`, `compose.prod.yml`, `railway.toml`.
- [ ] Pre-cutover IBKR password rotation (§8.9.1) executed for both live and paper; old passwords verified invalid; timestamps in PR description.
- [ ] §8.9.4 secret-store cleanup completed end-to-end (Railway every service+env, `.env.example`, local `.env`, GitHub Actions, 1Password archive).
- [ ] §8.9.5 grep gate is green and is enforcing on `main`.
- [ ] §8.9.7 final manual verification checklist signed off by Yuval.
- [ ] Changelog entry.
- [ ] Tag `v0.4.1-ibkr-webapi`.

Proceed to **M05 TradeStation + Order Lifecycle**.
