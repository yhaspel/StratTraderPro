# Runbook: Password Reset Abuse

## Symptoms

- A user reports receiving many password reset emails they didn't request.
- Monitoring shows a spike in `password_reset_requested` auth events for a single email.
- Rate-limit 429s on the password reset endpoint.

## Cause

An attacker is repeatedly requesting password resets for a target email, either to:
1. Annoy the user (email flooding).
2. Phish the user by training them to click reset links (then sending a fake one).
3. Probe whether the email exists (mitigated — our endpoint always returns 200).

## Immediate actions

1. **Verify rate limiting is active.** The endpoint is limited to 3 requests/minute per email. Confirm with:
   ```bash
   docker compose exec backend python manage.py shell -c "
   from apps.users.models import AuthEvent
   count = AuthEvent.objects.filter(
       event_type='password_reset_requested',
       email='target@example.com'
   ).count()
   print(f'Total reset requests: {count}')
   "
   ```

2. **Check IP patterns.** If requests come from a single IP or small range:
   ```bash
   docker compose exec backend python manage.py shell -c "
   from apps.users.models import AuthEvent
   ips = AuthEvent.objects.filter(
       event_type='password_reset_requested',
       email='target@example.com'
   ).values_list('ip', flat=True).distinct()
   print(list(ips))
   "
   ```
   Consider blocking the IP at the load balancer / CDN level.

3. **Reassure the user.** The reset tokens are single-use and expire in 1 hour. As long as the user doesn't click a link they didn't initiate, their account is safe.

## Prevention

- Rate limit is already in place (3/min/email).
- The endpoint does not reveal whether the email exists (always returns 200).
- Password reset tokens are cryptographically random (32 bytes, URL-safe), stored hashed, and single-use.
- Consider adding a CAPTCHA to the reset form if abuse persists (future enhancement).

## Monitoring

- Grafana: Auth Health dashboard → password reset rate panel.
- Alert if reset requests exceed 10/hour for a single email.
