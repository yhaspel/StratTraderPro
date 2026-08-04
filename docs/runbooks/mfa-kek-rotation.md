# Runbook — rotating the MFA key-encryption key (FERNET_KEK)

**Severity:** P2 (planned), P0 (suspected leak)
**Audience:** you, running your own instance
**Last reviewed:** 2026-05-01 (M02)

## What this protects

`FERNET_KEK` wraps every `MFADevice.secret_encrypted` row at rest. An
attacker with both a database dump *and* the KEK can compute every TOTP
code in the platform. The KEK lives only in the Railway environment —
never in code, never in CI, never in `.env.example`.

## Trigger conditions

- **Planned:** annually, end of Q1.
- **Emergency:** suspected leak — KEK appearing in a logs query, an
  exposed env var dump, or a revoked staff member with deploy access.

## Rotation procedure (envelope-encryption pattern)

This procedure rotates without ever decrypting all secrets at once.
We bring up KEK_v2 alongside KEK_v1, re-wrap each user's secret with
KEK_v2 lazily (on next MFA verify) or eagerly (one-shot management
command), then retire KEK_v1.

### Pre-flight

1. Make sure you have a recent successful database backup. The
   procedure is reversible, but a backup short-circuits any "should I
   panic?" moment.
2. Get the platform team's go-ahead. This is a sensitive operation; do
   not solo it.

### Step 1 — generate KEK_v2

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Save the new key to your password manager and to Railway's
**Environment** tab as `FERNET_KEK_V2`. Do not deploy yet.

### Step 2 — deploy with both keys live

In `config/settings/base.py`, swap the single-key Fernet for a
`MultiFernet`:

```python
from cryptography.fernet import Fernet, MultiFernet

_keys = [Fernet(env("FERNET_KEK_V2").encode()), Fernet(env("FERNET_KEK").encode())]
FERNET = MultiFernet(_keys)
```

The first key in the list is used for **encrypt**, all keys are tried
for **decrypt**. So new wraps use v2 immediately; old rows still
decrypt under v1.

Deploy to staging, run `pytest`, deploy to prod. Watch
`auth_mfa_verifications_total{result="fail"}` for any spike.

### Step 3 — eager re-wrap (recommended)

Run the management command (added in M02):

```
python manage.py rewrap_mfa_secrets
```

It iterates `MFADevice` rows, decrypts with `MultiFernet`, re-encrypts
with the primary key, saves. Idempotent.

### Step 4 — retire KEK_v1

After 7 days of normal traffic AND `rewrap_mfa_secrets` reports zero
remaining v1 rows, remove `FERNET_KEK` from Railway. Switch the
`settings/base.py` definition back to a single-key Fernet on
`FERNET_KEK_V2`. Rename the env var back to `FERNET_KEK` (a one-line
swap in Railway).

### Step 5 — audit

Open Sentry and Grafana for the rotation window. Confirm:

- No new `MFA secret could not be decrypted` errors.
- `mfa_verifications_total{result="ok"}` rate is unchanged.
- `users_auth_event` shows no spike in `mfa_challenge_fail`.

## Emergency rotation (suspected leak)

Same procedure but compress the timeline:

1. Generate KEK_v2 immediately, get it to Railway env via the platform
   admin (not a self-service operation).
2. Deploy MultiFernet config + push `rewrap_mfa_secrets` synchronously.
3. Once 100% of rows are v2, **revoke KEK_v1** by deleting it from
   Railway and rolling all running pods so no process holds it in
   memory.
4. File a security incident report. The incident is *not* "MFA was
   compromised" unless we also see a corresponding DB exfiltration
   event — without both, the wrap is still effectively secure.

## Rollback

If post-deploy errors spike: revert the `settings/base.py` change to
the single-key Fernet on the *original* `FERNET_KEK`. Existing v2-wrapped
rows will fail to decrypt — but that's only the tiny window of MFA
enrollments performed after Step 2 deployed and before rollback. Those
users will need to re-enroll. Comms template in
`docs/runbooks/mfa-rotation-rollback-comms.md` (TBD).

---

## M11 §7.12 — Rotation rehearsal (measured 2026-07-12)

The rotation was rehearsed locally to time the `MultiFernet` re-encryption pass. The M11 PR
**leaves the code at single-key `Fernet(settings.FERNET_KEK)`** — the `MultiFernet` swap is a
rotation-time-only edit (frozen decision §5), never committed to `settings`.

Rehearsal (5000 simulated stored secrets — MFA TOTP + webhook `sig` + broker keys across users):

```
secrets rotated       : 5000
seed (encrypt old)    : 45.6 ms
MultiFernet.rotate    : 84.8 ms   (17.0 us/secret)   <- decrypt-with-old, re-encrypt-with-new
verify new-key decrypt: 34.7 ms
all decrypt under new : True
```

**Extrapolation:** at ~17 µs/secret the re-encryption pass is dominated by the DB round-trips,
not the crypto — even 100k stored secrets re-encrypt in <2s of pure crypto. Batch the
`save(update_fields=[...])` writes; the wall-clock is I/O-bound.

**The rehearsal confirms the runbook's three-step swap works:** (1) introduce
`MultiFernet([Fernet(new), Fernet(old)])`, (2) `mf.rotate(ciphertext)` every stored secret and
save, (3) revert to single-key `Fernet(new)` and drop the old KEK from Railway. Every rotated
secret decrypts under the new single key. No committed `MultiFernet`.
