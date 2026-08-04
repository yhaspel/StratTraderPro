# ADR-021: Google OAuth via django-allauth, with custom JWT bridge

**Status:** Accepted
**Date:** 2026-05-02
**Milestone:** M2.5 — Google OAuth

## Context

Users want a one-click sign-up/sign-in path via Google in addition to email
+ password. We need to integrate Google's OAuth 2.0 flow without breaking
the M01 custom auth pipeline (JWT family rotation, MFA gate, audit log).

Two libraries were considered:

- **django-allauth** — comprehensive social-auth framework, supports 60+
  providers, includes its own session login, email verification, password
  reset, account linking UI.
- **Authlib** — thin OAuth client; just handles the state machine
  (authorize URL, code exchange, userinfo fetch). No Django integration
  assumptions.

## Decision

**Use django-allauth, but only for the OAuth state machine.** All other
features (email verification, password reset, session login, JWT issuance,
MFA) remain in our M01/M02 custom code. allauth's adapters are wired to
suppress its session-login behavior; we hijack at the post-callback step
and bridge the resulting User through our `issue_token_pair` + MFA gate.

The user explicitly chose allauth in the M2.5 scoping question, with
awareness that we'd be using only ~10% of its surface area. Reasoning: the
project may add more providers (Apple, GitHub) in the future, and having
allauth already in place reduces friction to add them.

## Implementation specifics

### Flow (server-side authorization-code grant with state)

```
1. Frontend GET  /api/v1/auth/oauth/google/start/
   → backend builds authorize URL via allauth's GoogleProvider, returns JSON
2. Frontend window.location.replace(authorize_url)
3. Google → consent → 302 back to /api/v1/auth/oauth/google/callback/
4. allauth's stock oauth2_callback view:
     - Validates state
     - Exchanges code for ID token
     - Fetches userinfo
     - Runs SocialAdapter.pre_social_login (our auto-link logic)
     - Creates/links User + SocialAccount
     - Logs the user in via Django session
     - 302s to LOGIN_REDIRECT_URL = /api/v1/auth/oauth/google/post-callback/
5. OAuthPostCallbackView:
     - Tears down the Django session
     - Records AuthEvent (OAUTH_USER_CREATED, OAUTH_LINKED, OAUTH_LOGIN_OK)
     - Sends notification email if first-time signup or just-linked
     - Mints single-use OAuthExchangeCode (5-min TTL)
     - 302 to FRONTEND/oauth/callback?exchange=<code>
6. Frontend OAuthCallbackComponent POSTs the code to
   /api/v1/auth/oauth/exchange/
7. OAuthExchangeView:
     - Consumes the code (single-use)
     - If user.mfa_enabled → return {mfa_required, mfa_token}
     - Else → issue_token_pair, return {access, refresh, user}
```

### Account linking semantics (auto-link by verified email)

When a Google sign-in arrives for an email that already has a User:

- If Google's `email_verified=true` → SocialAdapter.pre_social_login calls
  `sociallogin.connect(request, existing_user)`. The new SocialAccount row
  attaches to the existing User. The user keeps their MFA, sessions,
  profile, and password.
- If `email_verified=false` → no link, allauth proceeds with normal
  signup flow (which our adapter rejects via is_open_for_signup=False on
  the AccountAdapter, blocking unverified-email signups outright).

This matches the spec answered in our scoping question (auto-link by
verified email, recommended). Notification email (`oauth_account_linked.html`)
fires so a real user notices an attacker linking Google to their account.

### MFA still required after Google sign-in

Same as password login — Google proves email control, MFA proves second
factor. The exchange endpoint checks `user.mfa_enabled` and returns
`{mfa_required, mfa_token}` if applicable. This was an explicit decision
in the scoping question (recommended for finance apps).

### Why the exchange-code pattern (vs JWT in URL fragment)

JWTs in URL fragments leak through:
- Referrer headers (when the user clicks any link on the post-redirect page)
- Server access logs
- Browser history
- Analytics scripts that capture URL

The exchange-code pattern keeps tokens off the wire entirely. The code is:
- Single-use (consumed in DB on first POST)
- Short-lived (5 minutes default, configurable via `OAUTH_EXCHANGE_TTL_MINUTES`)
- Cryptographically random (`secrets.token_urlsafe(32)`)
- Stored hashed in DB (`hashlib.sha256` — same pattern as M01 verification
  tokens)

If the redirect URL leaks, an attacker has at most 5 minutes to redeem
the code, and only if they intercept it before the legitimate user's
frontend does. The redeemed-or-expired check makes this self-limiting.

### Why allauth and not Authlib

I (the implementer) flagged mid-build that Authlib would be a cleaner fit
for our use case (~200 lines vs ~600 lines + adapter config). The user
chose to push through with allauth as originally planned. The stated
reason: optionality for future providers (Apple, GitHub, etc.) where
allauth's batteries pay off.

## Consequences

### Positive
- Adding additional OAuth providers (Apple, GitHub, etc.) later is a
  one-line settings change + a new SocialApp row. No new adapter code.
- allauth's well-tested state-token + PKCE handling — we don't have to
  audit our own implementation.
- SocialAccount + SocialToken tables provide a clean audit surface for
  "which Google identities are linked to which Users".

### Negative
- ~6 new database tables (sites + 4 socialaccount + 1 our exchange code).
- Heavier dependency (django-allauth is ~25k LOC, plus python3-openid +
  requests-oauthlib transitives).
- We have to actively suppress allauth's parallel auth features (email
  verification, password reset, signup form) so they don't collide with
  ours. Current approach: AccountAdapter.is_open_for_signup() returns False
  to block local signup; ACCOUNT_EMAIL_VERIFICATION="none" disables
  allauth's verification flow. Future allauth versions may add new
  features that need similar suppression.

### Neutral
- We use `SOCIALACCOUNT_PROVIDERS` settings for OAuth credentials rather
  than database `SocialApp` rows. Both work; settings-only is simpler for
  our single-Google-app use case. Adding a second app per provider would
  require switching to `SocialApp` rows.

## References

- Google OAuth 2.0 docs: https://developers.google.com/identity/protocols/oauth2/web-server
- django-allauth socialaccount docs: https://docs.allauth.org/en/latest/socialaccount/index.html
- OAuth 2.0 Security Best Current Practice (RFC 9700)
- ADR-010 (JWT rotation) — explains the JWT pipeline our exchange step bridges into
- ADR-020 (TOTP-over-SMS) — explains the MFA gate that Google sign-in still passes through
