# ADR-010: JWT Refresh Token Family Rotation

**Status:** Accepted
**Date:** 2026-04-17
**Milestone:** M01 Auth Foundation

## Context

StratTraderPro uses JWT for stateless authentication. Refresh tokens are long-lived (30 days) and must be protected against theft and replay. The standard approach of simple token rotation (issue a new refresh on each use, blacklist the old one) does not detect stolen tokens until the legitimate user tries to refresh — by which time the attacker may have already used the token.

## Decision

We implement **refresh token family rotation with reuse detection**, as recommended by the OAuth 2.0 Security Best Current Practice (RFC 9700 §2.2.2):

1. **Family creation:** On login, a `RefreshTokenFamily` row is created with a `family_id` (UUID) and `current_jti` (the JTI of the active refresh token in this family).
2. **Rotation:** When a refresh token is used, we verify its JTI matches `current_jti`. If it matches, we issue a new refresh token (same family, new JTI) and update `current_jti`.
3. **Reuse detection:** If a refresh token's JTI does *not* match `current_jti` (i.e., an old token is being replayed), the entire family is revoked. All tokens in that lineage become invalid, forcing the user to re-authenticate.
4. **Logout:** Revokes the family.

The `family_id` is embedded as a custom claim in the refresh JWT.

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| Opaque refresh tokens in DB | Requires a DB hit on every API call if access tokens are short-lived. JWT access + opaque refresh is viable but adds complexity with two token formats. |
| Simple blacklist rotation (simplejwt default) | Does not detect reuse — a stolen token can be used indefinitely until the legitimate user refreshes. |
| Sliding session with no refresh | Poor UX — users are logged out after inactivity. |

## Consequences

- A stolen refresh token is detected the moment the legitimate client (or attacker) uses the *other* copy — whichever arrives second triggers family revocation.
- Adds one DB row per login session (`RefreshTokenFamily`) and one DB read per refresh call.
- Concurrent tabs sharing the same refresh token can cause false-positive reuse detection. Mitigated by: the frontend stores the refresh token in localStorage (shared across tabs), so only one copy exists per browser. If cookie-based storage is adopted later, `SameSite=Lax` + a single cookie ensures the same behavior.
- Race condition from rapid parallel refreshes is mitigated by the single `current_jti` field — only the first request succeeds; subsequent ones see a stale JTI and trigger revocation. A future improvement could add a Redis SETNX lock per family.
