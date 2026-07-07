# ADR-042 — Webhook authentication: static bearer secret in the request body

**Date:** 2026-07-07
**Status:** Accepted
**Milestone:** M04 — Webhook Ingest + Broker Adapter + Alpaca Paper
**Amends:** ADR-031 (webhook secret imprecise "TradingView signs the alert body" wording)
**Reference:** `project-plan/04-webhook-ingest-and-ibkr.md` §6.3, §11, §16

## Context

M03 (ADR-031) shipped a per-user-per-strategy webhook secret, generated
server-side, Fernet-encrypted at rest, revealed once, rotatable. M04 makes
the ingest endpoint live and has to actually verify inbound alerts. ADR-031
described the verification step as "TradingView signs the alert body and we
verify the signature" — i.e. an HMAC over the payload. **That is not how
TradingView works, and it is not what M04 implements.**

TradingView alert messages are **static templates with placeholder
substitution only**. When an alert fires, TradingView takes the message body
you configured, swaps its `{{...}}` placeholders (`{{ticker}}`,
`{{strategy.order.action}}`, `{{time}}`, etc.) for literal values, and POSTs
the result to the webhook URL. There is no scripting hook, no request-signing
step, no shared-secret HMAC computation available to the sender. TradingView
**cannot compute a per-payload HMAC-SHA256** — the feature does not exist on
their side. Any design that assumes the sender signs the body is describing a
system TradingView does not offer.

So the secret ADR-031 embeds in the alert template's `sig` field is not a
signature. It is a **static bearer token**: the same fixed string on every
alert for that (user, strategy) pair, sitting in the JSON body. Verification
can only be "does the presented bearer secret equal the stored secret" — not
"does this signature match this body". This ADR documents that honest model,
the replay window it opens, and the mitigations, and it specifies the
computed-HMAC mode we will offer later for senders that *can* sign.

## Decision

### 1. The `sig` field is a static bearer secret, compared in constant time

The webhook body carries a top-level `sig` string. `WebhookView.post`:

1. Looks up `WebhookConfig` for the `(user_id, strategy_id)` in the URL path.
2. Fernet-decrypts the stored secret (`decrypt_secret(wc.secret_encrypted)`).
3. Verifies with `hmac.compare_digest(sig, stored_secret)` — a **constant-time
   equality check**, not an HMAC of the body. (The `hmac` module is used here
   only for its timing-safe comparator; no MAC is computed.)

A mismatch, a missing `sig`, or an unknown `(user, strategy)` all return a
generic `401` (`WEBHOOK_SIG_BAD`) with no existence oracle — an attacker
cannot distinguish "wrong secret" from "no such strategy". Constant-time
comparison denies a byte-by-byte timing side channel against the secret.

### 2. The endpoint is mounted OUTSIDE `/api/v1` — no JWT layer

```python
urlpatterns = [
    path('hooks/v1/<uuid:user_id>/<uuid:strategy_id>/', WebhookView.as_view()),
]
```

TradingView is an unauthenticated third party; it has no StratTraderPro
session, no JWT, no MFA. Mounting the route under `/api/v1` would subject it
to `IsAuthenticatedAndMFAEnforced` (M02) and reject every alert. The webhook
therefore lives at the project root, deliberately bypassing the JWT/MFA
middleware. **The body secret is the only authentication.** The OpenAPI
post-processor documents this endpoint as "unauthenticated at the JWT layer,
secret-authenticated in the body" (AC-04-14).

### 3. Verification order is fixed so cheap checks gate expensive ones

`WebhookView.post` runs (order matters):

```
1. rate-limit per user_id (60/min)         — BEFORE body read
2. reject > 16 KB or non-application/json
3. parse JSON; extract top-level "sig"
4. load WebhookConfig(user_id, strategy_id) — 404 → generic 401 (no oracle)
5. hmac.compare_digest(sig, decrypt_secret(...)) → else 401
6. jsonschema.validate(body minus sig, wc.json_schema) → else 400
7. idempotency: redis SETNX idem:{user}:{sha256(key)} EX 86400 → dup? 200
8. TradingHalt active? → audit REJECTED, 200 {rejected: reason}
9. AlertMessage row (sig redacted), process_alert.delay(id), 200
```

The rate limit is enforced **before the body is read** so a flood cannot force
16 KB reads or JSON parses per request.

## The replay window this implies, and its mitigations

A static bearer secret is replayable by definition: anyone who captures one
valid request body can POST the identical bytes again and it will authenticate.
TLS makes on-wire capture hard, but the secret also lives in the user's
TradingView alert config (screenshottable, shoulder-surfable, leakable via
browser extensions — the exact ADR-031 threat model). We do **not** pretend
this is a signed request. We bound the blast radius instead:

| Mitigation | Mechanism | Effect on replay |
|---|---|---|
| **Idempotency key** | `redis SETNX idem:{user}:{sha256(idempotency_key)} EX 86400` (step 7); unique `client_order_id` at Alpaca as a second guard | A replayed body with the same `idempotency_key` returns `200 {duplicate: true}` and places **no** second order. This is the primary replay defense within the 24 h window. |
| **Per-user rate limit** | 60/min per `user_id`, enforced **before body read** (step 1) | Caps replay/flood volume; a captured secret can't be hammered. |
| **16 KB body cap + `application/json` only** | step 2 | Denies oversized/malformed replay payloads and shrinks the DoS surface. |
| **TLS-only** | HTTPS at the edge; no plaintext listener | Denies passive on-wire capture of the secret and bodies. |
| **Secret rotation** | ADR-031 `POST /webhook-config/rotate/` — **destructive**, no history table | A leaked secret is killed immediately; the old value stops authenticating the instant a new one is minted (user must re-paste into TradingView). |
| **Optional TradingView source-IP allowlist** | Config flag, **off by default**; TradingView publishes its webhook egress IPs — pin them at deploy time | When enabled, drops any POST not originating from TradingView's ranges before the body is read. Off by default because the IP list drifts and self-hosted/API senders would be blocked. |

The residual risk (M04 §16, row 1) — "static `sig` secret replayed by an
interceptor" — is rated **Med/Med** and accepted for a PAPER-only milestone.
Live trading (M12+) will require the computed-HMAC mode below before it ships.

## Deferred: a computed-HMAC mode (`sig_mode=hmac256`) for API-capable senders

TradingView can't sign, but future senders can — a user's own bot, a serverless
relay, or a first-party mobile app hitting the same endpoint. For those we
**specify but defer** a real signature mode:

- The sender sets `sig_mode: "hmac256"` in the body and computes
  `HMAC-SHA256(secret, raw_body_bytes_with_the_sig_pair_stripped)`, placing the
  hex digest in `sig`.
- Verification recomputes the same HMAC over the raw request bytes (with the
  `sig`/`sig_mode` pair removed exactly as the sender removed it) and
  `compare_digest`s the digests.
- This binds the secret to the *specific payload*, so a replay of a **different**
  body fails. Combined with a sender-supplied nonce/timestamp it closes the
  replay window that the bearer mode leaves open.

This is **not built in M04.** The default and only implemented mode is the
static bearer compare above. `sig_mode=hmac256` is documented here so the
field is reserved and the upgrade path is clear; it lands post-MVP for
API-capable senders (and is a prerequisite for any live-trading scope).

## Consequences

**Positive:**

- The docs now match reality. No future engineer will build a body-signature
  verifier against an assumption TradingView can't satisfy, or chase a
  "signature mismatch" bug that is really a bearer-secret mismatch.
- The verification path is trivial and fast (a decrypt + `compare_digest`),
  helping AC-04-1's 300 ms p95 budget.
- The `BrokerAdapter`/webhook split is unchanged; only the *description* of
  the auth step is corrected relative to ADR-031.

**Negative:**

- We carry a real replay window for the life of the bearer-only mode. It is
  mitigated (idempotency is the load-bearing control) but not eliminated. This
  is why M04 is PAPER-only and why live trading gates on `sig_mode=hmac256`.
- The optional IP allowlist is operationally brittle (TradingView's egress
  ranges drift), so it stays off by default and is not a primary control.
- Users who leak their secret must rotate and re-paste into TradingView —
  the same destructive-rotation UX ADR-031 already accepted.

## Amendment note to ADR-031

ADR-031 §Context states "TradingView signs the alert body and we verify the
signature," and its title/framing use "HMAC". That wording is **imprecise**:
TradingView embeds a static secret in a static template; it does not sign or
compute anything. A dated amendment block has been added to the top of
`docs/adr/031-webhook-hmac.md` pointing to this ADR. ADR-031's *substance*
(server-side generation, Fernet-at-rest, reveal-once, destructive rotation,
log scrubbing) all stand unchanged and are reused verbatim by M04 — only the
"signs the body / HMAC verify" characterization of the *verification* step is
corrected here.

## See also

- ADR-031 — Webhook secret: generation, encryption, reveal-once, rotation
- ADR-041 — Alpaca replaces IBKR as the M04 execution broker
- `project-plan/04-webhook-ingest-and-ibkr.md` §6.3 (endpoint flow), §11
  (security), §16 (risk register)
- `docs/runbooks/webhook-debug.md` — tracing an ingested alert end-to-end
- `docs/runbooks/mfa-kek-rotation.md` — KEK rotation also re-wraps webhook secrets
