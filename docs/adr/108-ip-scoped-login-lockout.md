# ADR-108 — IP-scoped login lockout (per-IP primary, per-email secondary)

**Date:** 2026-07-18
**Status:** Accepted
**Milestone:** Review remediation (P2-4)
**Reference:** review plan `development-plans/2026-07-17-review-remediation-plan.md` §P2-4;
`backend/apps/users/services.py` (`is_locked`, `record_failed_login`),
`backend/apps/users/views.py` (`LoginView`), `backend/apps/users/test_auth.py`

## Context

Login lockout counted **failed attempts per email** within a window: N failures in
M minutes → the account returns `423 ACCOUNT_LOCKED` to *anyone* submitting that
email. That is a targeted-DoS primitive — a remote attacker who knows only a
victim's email address can submit N bad passwords from their own IP and lock the
victim out of their own account, from the victim's own (different) IP.

## Decision

Scope the lockout to the **requesting IP**:

- `record_failed_login` stores the resolved client IP with each failure (already did).
- `is_locked(email, ip)` counts failures for `(email, ip)` when an IP is supplied.
- `LoginView` resolves the requester IP and checks `is_locked(email, ip)`, so the
  423 lock applies only to the IP that actually produced the failures.

The **primary throttle stays the rate limit**: login is limited per-email (5/min)
*and* per-IP (20/min). The per-email rate cap bounds total attempts on any one
account to 5/min regardless of source, even distributed; the IP-scoped lockout is
the secondary control that stops a single-IP brute force without letting it lock
out third parties.

`is_locked(email)` with no IP keeps the legacy per-email semantics for callers
(and tests) that don't have a request IP.

## Consequences

- A remote attacker can no longer lock a victim out of the victim's own IP.
- A single-IP brute force on one account is still locked out at that IP.
- Tradeoff: a **distributed** attacker (many IPs, each below the lockout threshold)
  is not stopped by the lockout — but the **per-email 5/min rate limit** caps them
  to 5 attempts/minute on a given account regardless of IP count, so an online
  brute force remains infeasible. A CAPTCHA step-up on repeated per-email failures
  is a possible future hardening if that rate proves insufficient.
- The client-IP derivation still reads the left-most `X-Forwarded-For` entry (the
  pre-existing auth behaviour); tightening it to the trusted-proxy scheme used for
  webhooks (P2-1) is a separate follow-up and does not affect the DoS fix here.
