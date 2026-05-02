# ADR-020: TOTP for MFA — no SMS, no email codes

**Status:** Accepted
**Date:** 2026-05-01
**Milestone:** M02 MFA & User Profile

## Context

M02 ships multi-factor authentication. The platform's threat model is
account takeover by credential-stuffing or phishing of broker-connected
accounts; once compromised, an attacker can drain a brokerage. We need a
second factor that is both phishing-resistant and easy enough that we
won't see users disable it.

The broad options:

| Option | Phishable? | Cost | UX |
|---|---|---|---|
| TOTP (authenticator app) | Code-only phishable, but immune to SIM swap | $0 | Familiar |
| SMS one-time code | Yes — SIM swap, smishing | $0.005/msg | Familiar |
| Email one-time code | Yes — if mail is compromised | $0 | Familiar |
| WebAuthn / passkeys | No — origin-bound | $0 | Newer, mixed support |

## Decision

**We ship TOTP-only for M02.** WebAuthn / passkeys are tracked as a
post-MVP follow-up (see `project-plan/`).

Implementation specifics:

- `pyotp.TOTP` with `interval=30, digits=6`, `valid_window=1` (±30s
  drift tolerance).
- Secrets are 160-bit base32, generated via `pyotp.random_base32(32)`.
- Secrets at rest are wrapped with `cryptography.fernet` keyed by
  `settings.FERNET_KEK`; the KEK lives only in Railway env. See
  `docs/runbooks/mfa-kek-rotation.md`.
- 10 single-use backup codes per user, sha256+per-row-salt hashed.
- `mfa_token` (5-min purpose-scoped JWT) bridges the password step and
  the TOTP step at login.
- Brute-force defended by `5/min/mfa_token` rate limit on
  `/auth/mfa/verify/`.

## Alternatives explicitly rejected

- **SMS:** Vulnerable to SIM swap and SS7 interception. NIST 800-63B has
  deprecated SMS as an authenticator since 2017. For a system that gates
  brokerage access, the residual risk is too high.
- **Email:** If the user's email is compromised — which is exactly the
  scenario MFA is supposed to protect against during password reset —
  email codes give zero defense.
- **Push-based 2FA (Duo, Twilio Verify):** Would solve phishing better
  but adds third-party dependency, recurring cost, and onboarding
  friction. Reconsider at scale.
- **WebAuthn / passkeys:** Strongest option but adoption is uneven and
  recovery flow is harder to support today. We keep the door open: the
  `MFADevice` model can grow a `kind` column in the future.

## Consequences

- A user who loses both phone and backup codes must use the support
  recovery flow (see `docs/runbooks/user-lost-mfa.md`).
- Brand-new users on devices without an authenticator app must install
  one — we surface help links in the setup wizard.
- The key-encryption key (FERNET_KEK) is now a critical secret. If
  leaked, an attacker who also gets a DB dump can compute every TOTP
  code. Rotation procedure is documented.
- We do not block any legitimate authenticator app — Google
  Authenticator, Authy, 1Password, Bitwarden, and Microsoft
  Authenticator all interop via the standard `otpauth://` URI.

## References

- RFC 6238 — TOTP
- NIST SP 800-63B §5.1.4 — out-of-band authenticators
- OWASP ASVS v4 §2.8 — TOTP requirements
