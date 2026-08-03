# Runbook — user lost their MFA device (and can't use a backup code)

**Severity:** P3 (user-blocking, not platform-impacting)
**Audience:** you, running your own instance
**Last reviewed:** 2026-05-01 (M02)

## When this runbook applies

The user contacts support claiming they cannot sign in. They've already:

1. Tried entering a TOTP code from their authenticator app — phone is
   lost, broken, or wiped.
2. Tried the **"Use a backup code instead"** option on the MFA
   challenge screen — they cannot find their backup codes.

If either of those still works, this runbook is **not** the right
answer; tell them to use the backup-code flow and then regenerate codes
under Settings → Security → Backup codes.

## Goal

Disable MFA on the user's account so they can sign in with password
alone, log an audit trail, and notify them by email so a *real*
attacker can't quietly use this flow.

## Step-by-step

### 1. Verify identity OUT OF BAND

Do not skip this. The whole reason MFA exists is to stop someone with
just a password.

- Confirm the user's full name + display_name + registered email match
  what's in `users_user`.
- Confirm at least **two** of: last broker connected (M04+), last
  strategy name (M03+), approximate signup date, or a recent login IP
  from `users_auth_event`.
- For high-value accounts (>$10k notional or live broker connected),
  require a 1:1 video call where the user shows government-issued ID
  matching the account name.

If anything feels off, **stop**. Forward to a senior engineer.

### 2. Disable MFA via Django admin

```
/admin/users/mfadevice/ → select the user's device → Action: "Force-disable MFA (audited; emails the user)"
```

The bulk action:

- Deletes the `MFADevice` row.
- Wipes all `BackupCode` rows for the user.
- Emails the user that MFA was disabled.
- Writes an `AuthEvent(event_type="mfa_disabled", metadata={"actor": "admin", "admin_user": "<your email>"})`.

### 3. Tell the user what to do next

Email or message them to:

1. Sign in immediately with their password.
2. Go to Settings → Security and re-enroll MFA on their new device.
3. Save the fresh batch of 10 backup codes — somewhere durable this
   time (password manager, printed, sealed envelope).

### 4. Confirm in the audit log

Open `/admin/users/authevent/?event_type=mfa_disabled` and confirm
your action is logged with the right actor email and timestamp.

## What if the user's email is compromised?

Then they can't actually receive our "MFA was disabled" notification,
and the attacker may have already requested a password reset and
disabled MFA via this very runbook. Indicators:

- Mismatched recent IPs in `users_auth_event` (the user has only
  ever signed in from Cleveland but the last 5 logins are from Lagos).
- A `password_reset_confirmed` event followed within 10 minutes by a
  call to support.

If you suspect this:

1. **Lock the account** by setting `is_active=False` in the admin.
2. Page the SRE on-call.
3. Do not disable MFA. Open an incident ticket.

## After-action

- If you disabled MFA more than once for the same user in 30 days, file
  a follow-up ticket — they need help making the codes more durable.
- Aggregate: how many lost-MFA tickets we get per month is tracked from the
  tickets themselves — the Auth Health dashboard that used to carry it was
  retired by ADR-109. If it spikes, revisit user education.
