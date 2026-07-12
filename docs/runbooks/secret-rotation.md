# Runbook — Secret rotation (JWT signing key + DB password)

**Owner:** Yuval / platform on-call
**Last reviewed:** 2026-07-12 (M11 §7.12)
**Severity:** P2 planned; P0 on suspected leak
**Companion:** `docs/runbooks/mfa-kek-rotation.md` (Fernet KEK), `docs/adr/103-service-role-dispatch.md`
**Gated by:** AC-11-13 ([CI]-shaped rehearsal here; DB-password rotation is [LIVE])

Three long-lived secrets exist. KEK rotation has its own runbook (`mfa-kek-rotation.md`).
This one covers the **JWT signing key** and the **DB password**.

---

## 1. JWT signing key (`JWT_SIGNING_KEY`) — a DRAIN, not multi-kid

**Model (§0.7):** JWT is single-key **HS256** (SimpleJWT). There is **no `kid`** and no
multi-key verification. Rotating `JWT_SIGNING_KEY` therefore **invalidates every in-flight
access token immediately** — the server verifies only with the new key. This is a *drain*,
not a zero-downtime rotation. Building multi-`kid` is explicitly out of scope (plan §3).

### What breaks and for how long
- **Access tokens** (`ACCESS_TOKEN_LIFETIME` = **15 min**): every access token minted under
  the old key fails signature verification the instant the new key is live. Clients get a
  401, the refresh interceptor fires, and a **new access token is re-minted** from the still-
  valid refresh token.
- **Refresh tokens**: SimpleJWT refresh tokens are also HS256-signed, so they are invalidated
  too — BUT our custom `RefreshTokenFamily` re-issue path mints a fresh pair on the next
  refresh. Users whose refresh also fails must re-login (worst case: one re-login).

### Rehearsal (performed 2026-07-12, local) — measured
```
old access token vs NEW key : REJECTED (InvalidSignatureError)   <- in-flight tokens invalidated
new access token vs NEW key : ACCEPTED                            <- clean re-mint
```
Confirms: a token signed under key A is rejected under key B, and a token minted under key B
verifies cleanly. The observable drain window equals the 15-minute access-token TTL.

### Procedure ([LIVE] on Railway)
1. Schedule in a **low-traffic window** (the drain forces a re-mint for every active session).
2. Generate a new key: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
3. Set `JWT_SIGNING_KEY` on the backend service(s) — **staging first**. `web` + `ws` + worker
   all read `SIMPLE_JWT["SIGNING_KEY"]`, so set it everywhere the token is verified.
4. Redeploy. Watch `auth_refresh_total{result="ok"}` rise (clients re-minting) and
   `auth_login_total` for a bump (users whose refresh also drained).
5. Confirm no sustained 401 spike after ~15 min (the last old access tokens have expired).
6. Production after staging is clean.

### Rollback
Re-set the previous `JWT_SIGNING_KEY` and redeploy — tokens minted under the new key then
drain instead. Either direction is a ≤15-minute drain; never a data risk.

---

## 2. DB password (Railway Postgres) — [LIVE]

**[LIVE]/operator** — needs the Railway console + a measured downtime window.

1. Rotate the Postgres password in Railway (Postgres service → Variables / Connect).
2. Railway updates the injected `DATABASE_URL`; the app services must **redeploy** (or the
   connection pool re-reads the DSN) to pick up the new credential.
3. **Measure downtime**: from the moment the password changes to the first successful
   `/readyz` (`checks.db == "ok"`) after redeploy. Log it here after the run.
4. Rotate one environment at a time (staging → production). The pool fails closed on an
   unreachable DB (`socket_connect_timeout` = 2s), so a bad DSN surfaces fast rather than
   hanging.

**Measured downtime (fill in after the [LIVE] run):** _pending operator run._

---

## Cross-references
- Fernet KEK (secret-at-rest for MFA/webhook/broker): `docs/runbooks/mfa-kek-rotation.md`
  (M11 rehearsal + measured times appended there).
- The `SECRET_KEY` (Django) is not rotated here — it also drives the KEK default and JWT
  default, both overridden by real env in prod (`config/settings/prod.py` C2 fail-closed).
