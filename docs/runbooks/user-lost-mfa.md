# Runbook — user lost their MFA device (and can't use a backup code)

**Severity:** P3 (user-blocking, not platform-impacting)
**Audience:** you, running your own instance
**Last reviewed:** 2026-09-20 (skew diagnostics)

## When this runbook applies

The user contacts support claiming they cannot sign in. They've already:

1. Tried entering a TOTP code from their authenticator app — phone is
   lost, broken, or wiped.
2. Tried the **"Use a backup code instead"** option on the MFA
   challenge screen — they cannot find their backup codes.

If either of those still works, this runbook is **not** the right
answer; tell them to use the backup-code flow and then regenerate codes
under Settings → Security → Backup codes.

## First: is the device actually lost, or are codes just being rejected?

Since 2026-09-20 a TOTP miss is no longer a single opaque `MFA_CODE_INVALID`.
Before disabling anything, read the last few `auth.mfa_challenge_fail` audit
rows for the user (admin portal → Audit, or `AuditLog.objects.filter(
event_type="auth.mfa_challenge_fail", user=u).order_by("-occurred_at")[:10]`)
and look at `data_after.reason`:

| `reason`      | `offset_steps` | Meaning | What to do |
|---------------|----------------|---------|------------|
| `clock_skew`  | e.g. `-4`      | The code is a real code from the **right secret**, generated for a time 4×30 s behind the server. The authenticator's clock is off. | User: Google Authenticator → ⋮ → Settings → *Time correction for codes* → Sync now (iOS/Android: enable automatic date & time). No reset needed. |
| `no_match`    | absent         | The code matches nowhere within ±5 min: it comes from a **different secret** — a stale entry left in the authenticator after a re-enrol, or a second account with the same label. | Have the user delete every "StratTraderPro" entry, then Settings → Security → Disable (or use a backup code to sign in) and re-enrol. If it still fails via one sign-in method but not the other (password vs Google), check for two `User` rows. |

The user also sees the distinction: `MFA_CODE_CLOCK_SKEW` carries the sync
instructions in its message; `MFA_CODE_INVALID` is the generic miss.

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
- Aggregate: there is **no** MFA-reset metric — the codebase exports none, and the
  Auth Health dashboard this used to point at (retired by ADR-109) never carried
  such a panel. Count these tickets by hand, or add a counter, if you want the
  monthly trend. If it spikes, revisit user education.
