# ADR-031 — Webhook HMAC: per-user secret, rotation, reveal-once

**Date:** 2026-05-03
**Status:** Accepted
**Milestone:** M03 — Strategies & Webhook Config

## Context

Each user/strategy pair gets a unique webhook URL plus an HMAC shared
secret. TradingView signs the alert body and we verify the signature
before queueing the order in M04. The secret needs to be:

- Generated server-side (so users can't reuse weak secrets).
- Stored encrypted at rest.
- Rotatable (because TradingView alert configs leak via screenshots,
  shoulder-surfing, browser extensions).
- Visible to the user **exactly once** so they can paste it into
  TradingView's alert template.

## Decision

### Generation
`secrets.token_urlsafe(48)` — 48 random bytes, encoded url-safe-base64.
~64 chars of entropy, well over the recommended HMAC-SHA256 floor.

### Encryption at rest
The same Fernet KEK (`settings.FERNET_KEK`) used for M02 MFA secrets
wraps the webhook secret. We deliberately reuse the KEK so KEK rotation
(documented in `docs/runbooks/mfa-kek-rotation.md`) covers both surfaces
in one operation.

`apps/strategies/services.encrypt_secret` and `decrypt_secret` are thin
wrappers over `apps.users.mfa._fernet` — kept as a separate module
function so future code review can find every plaintext-secret call site
with a grep for `decrypt_secret`.

### Rotation
`POST /api/v1/strategies/{id}/webhook-config/rotate/` is destructive:

- Generates a new secret.
- Increments `WebhookConfig.version`.
- Stamps `rotated_at = now()`.
- Returns the new plaintext secret in the response body **once**.

There is no history table — the old secret is gone immediately. This is
intentional: keeping rotated secrets around defeats the purpose of
rotation, and a misbehaving alert needs a hard-stop, not a fallback.

### Reveal-once UX
The plaintext secret is only present in API responses for:

1. The first `GET /webhook-config/` for a (user, strategy) pair (when
   the row is created on demand).
2. The response to `POST /webhook-config/rotate/`.

Subsequent `GET`s set `secret: null, reveal_once: false`. The frontend
store mirrors this: `clearRevealedSecret(strategyId)` is called when the
user closes the modal, so the secret can't be re-rendered later from
in-memory state alone.

The frontend modal also:
- Wraps the secret input in a high-contrast amber border with a
  "Copy this now — it will not be shown again" warning.
- Provides a one-click "Copy TradingView alert template" button that
  inlines the secret as the `sig` field — but only while the secret is
  still in memory; otherwise it leaves a `PASTE_YOUR_SECRET_HERE`
  placeholder.

### Logging discipline
Plaintext secrets must NEVER appear in logs. The
`SENSITIVE_KEYS` scrubber in `LOGGING` already drops `secret`, `sig`,
`token`, `password`, etc. The `views.WebhookConfigRotateView` log line
uses `extra={"version": ..., "strategy": ...}` — no secret field. A
unit test (`test_strategies.SecretLeakTests`) asserts the rotation-
endpoint log output never contains the freshly minted secret.

## Consequences

**Positive:**
- Same encryption story for MFA + webhooks → one KEK rotation runbook.
- Rotation is a proper invalidation, not a soft-rotation that an attacker
  can exploit by replaying the old secret.
- Reveal-once aligns with how every modern API key UX works (Stripe,
  GitHub, AWS) — users are increasingly used to the "copy now or rotate
  again" pattern.

**Negative:**
- If the user closes the rotation success modal without copying, they
  must rotate again (which breaks any existing TradingView alerts a
  second time). We mitigate with: clear amber framing, an explicit
  confirm dialog before rotating, and the auto-fill TV template button
  that does the copy on the user's behalf.
- No history table means we can't show "secret was last rotated by IP
  X.X.X.X" without joining against the audit log. Acceptable for MVP.

## Alternatives Considered

- **Per-strategy secret instead of per-user/per-strategy.** Easier to
  share but a leaked secret would compromise EVERY user of that
  strategy. Rejected.
- **Storing rotated secrets in a `previous_secrets` array for grace
  period.** Defeats the purpose of rotation; would need its own expiry
  worker. Rejected for MVP.
- **Returning the secret only at creation, never at rotation.** Bad UX —
  every rotation would force the user to also re-fetch via a separate
  reveal endpoint. Rejected.

## See Also

- ADR-030 — Strategy 3-file upload contract
- `apps/strategies/services.py` — `rotate_secret`, `encrypt_secret`
- `apps/strategies/views.py` — `WebhookConfigRotateView`
- `apps/strategies/test_strategies.py::WebhookConfigRotationTests`
- `docs/runbooks/mfa-kek-rotation.md` — KEK rotation also covers webhook secrets
