# Runbook: User Account Locked Out

**Last reviewed:** 2026-07-12

## Symptoms

- User reports they cannot log in.
- API returns `423 Locked` with error code `ACCOUNT_LOCKED`.
- User may have received an "account locked" email.

## Cause

10 or more failed login attempts within a 15-minute window for the same email address. This is an automatic security measure to prevent brute-force attacks.

## Auto-recovery

The lockout expires automatically after 15 minutes (configurable via `AUTH_LOCKOUT_DURATION_MINUTES`). The user can also self-recover by using the **password reset** flow — resetting the password clears the failed-attempt counter.

## Manual resolution

If the user cannot wait and cannot use password reset:

```bash
# Connect to the backend shell
docker compose exec backend python manage.py shell

# Clear failed attempts for the user
from apps.users.models import FailedLoginAttempt
FailedLoginAttempt.objects.filter(email="user@example.com").delete()
```

## Tuning

Settings in `config/settings/base.py` (overridable via env vars):

| Setting | Default | Env var |
|---|---|---|
| Failure threshold | 10 | `AUTH_LOCKOUT_THRESHOLD` |
| Sliding window | 15 min | `AUTH_LOCKOUT_WINDOW_MINUTES` |
| Lockout duration | 15 min | `AUTH_LOCKOUT_DURATION_MINUTES` |

## Monitoring

- Check `AuthEvent` table for `account_locked` events: `AuthEvent.objects.filter(event_type='account_locked', email='user@example.com')`
- Grafana: the Auth Health dashboard was retired by ADR-109. The `auth_*` series
  are still exported and queryable — in Explore, run
  `sum by (result) (increase(auth_login_total[24h]))`; a lockout episode shows as a
  burst of non-`ok` results.
- If a single email is being locked repeatedly from many IPs, this may indicate a targeted attack — consider notifying the user and suggesting MFA (M02).

## Escalation

If lockouts are happening at scale (many users simultaneously), this may indicate a credential-stuffing attack. Escalate to investigate IP patterns and consider enabling per-IP rate limiting at the load balancer level.
