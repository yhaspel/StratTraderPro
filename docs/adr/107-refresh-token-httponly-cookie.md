# ADR-107 — Refresh token delivered as an HttpOnly cookie (not localStorage)

**Date:** 2026-07-17
**Status:** Accepted
**Milestone:** Review remediation (P1-4)
**Reference:** review plan `development-plans/2026-07-17-review-remediation-plan.md` §P1-4;
`backend/apps/users/cookies.py`, `backend/apps/users/views.py` (login/refresh/logout/verify-email/
password-reset-confirm), `backend/apps/users/views_m02.py` (MFA verify), `backend/apps/users/views_oauth.py`
(OAuth exchange), `backend/config/settings/base.py` (`REFRESH_COOKIE_*`), `backend/config/settings/prod.py`
(`REFRESH_COOKIE_SECURE`), `frontend/src/app/abstraction/stores/auth.store.ts`,
`frontend/src/app/abstraction/facades/auth.facade.ts`, `frontend/src/app/core/services/auth.api.ts`,
`frontend/src/app/core/interceptors/refresh.interceptor.ts`

## Context

The SPA persisted the long-lived (30-day) refresh token in `localStorage`. `localStorage`
is readable by any JavaScript on the origin, so a single XSS hands an attacker the
refresh token and thus indefinite access-token minting — persistent takeover of an
account that can place live trades. Access + MFA tokens were already in-memory-only;
only the refresh token regressed.

## Decision

Deliver the refresh token to browsers as a cookie:

- `HttpOnly` — unreadable from JavaScript, so XSS can no longer exfiltrate it.
- `Secure` — HTTPS only in prod (`REFRESH_COOKIE_SECURE=True`; off in dev/test over http).
- `SameSite=Strict` — **this is the CSRF control.** The cookie is never attached to a
  cross-site request (not even a top-level navigation), so a hostile origin cannot
  trigger a rotation with the victim's cookie. No separate CSRF token is required for
  this endpoint; a double-submit token remains a possible future hardening.
- `Path=/api/v1/auth/` — scoped to the auth endpoints (`/refresh/`, `/logout/`), not sent
  with ordinary API calls.

The refresh token is **stripped from every JSON response body** (login, MFA verify,
refresh, OAuth exchange, email verification, password-reset confirm) — the browser SPA
never sees the value, so even an XSS-triggered refresh cannot read it back.

`/auth/refresh/` and `/auth/logout/` read the token from the cookie; they also accept it
in the request body as a fallback for non-browser/API clients. Body-first precedence keeps
programmatic clients (and the existing test suite) working; the browser never sends a body,
so the fallback cannot reintroduce the exfiltration vector.

Frontend: the store no longer holds or persists a refresh token (and purges the legacy
`stp_refresh_token` key on construction). Bootstrap and the 401 refresh-interceptor attempt
a rotation unconditionally — they can't inspect the HttpOnly cookie, so the server decides
by returning a new pair (cookie present) or 401 (absent/expired). Auth API calls that set or
send the cookie use `withCredentials: true`.

## Consequences

- XSS can no longer steal the refresh token; the persistent-takeover path is closed.
- A cold page load always issues one silent `/auth/refresh/` (previously gated on a
  localStorage value we can no longer read) — negligible cost, already the bootstrap shape.
- The OpenAPI `TokenPairData` schema still documents a `refresh` field even though the body
  no longer carries it; the generated `schema.ts` and its contract test are left untouched to
  avoid churn in a file that does not regenerate cleanly in this environment. The frontend
  `AuthTokenPair.refresh` field is retained for that equivalence but is never read. Tightening
  the schema is deferred to a schema-regeneration pass.
