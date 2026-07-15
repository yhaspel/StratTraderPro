# Runbook — Audit-log integrity failure

**Last reviewed:** 2026-07-12

**Owner:** Yuval
**Status:** Executable. The nightly verifier
(`apps.audit.tasks.verify_audit_integrity`, beat 08:00 UTC ≈ 04:00 ET), the hash
chain, and the Postgres enforcement triggers are built and unit-tested (M10,
AC-10-1…AC-10-4). **Companion docs:** `docs/adr/100-audit-hash-chain.md` (the design
this verifies — read §1/§2/§6 first), `docs/runbooks/incident-triage.md` (this is
the `AuditIntegrityFailure` critical page), `docs/runbooks/audit-integrity-verify-monthly.md`
(the monthly spot-check), `project-plan/10-admin-audit-observability.md` §6.1, §6.11, §17.

## What a verifier failure means

At 08:00 UTC the verifier resumes from its cursor
(`AuditVerifierState.last_verified_id` / `last_verified_hash`), walks every new
`audit_log` row in id order, and re-derives each `self_hash` from
`sha256(prev_hash ‖ canonical_payload)`. It asserts **three** things:

1. **Linkage** — each row's `prev_hash` equals the previous row's `self_hash`.
2. **Hash** — each row's stored `self_hash` equals the recomputed value.
3. **Triggers present** — both `audit_log_block_mutation` and
   `audit_log_check_link` still exist on the table.

Any one failing → it increments `audit_integrity_check_total{result="fail"}`,
writes an `audit.integrity_failure` row (naming the suspect id + reason), and
**emails `AUDIT_ALERT_EMAIL`** (falling back to `DEFAULT_FROM_EMAIL`) with the
suspect id range and a link here. The `AuditIntegrityFailure` alert
(`increase(...{result="fail"}[1h]) > 0`, critical) pages you.

The reason string tells you which check failed:

- **`hash_mismatch`** — a row's stored `self_hash` no longer matches its content.
  Someone/something changed a column value *and* somehow got the row to persist
  (e.g. a row inserted by a path that bypassed `emit()`, or — on a backend without
  the triggers — an in-place edit).
- **`linkage_break`** — a row's `prev_hash` doesn't match the prior head. A row was
  inserted out of chain, or a row was deleted from the middle.
- **trigger missing** — one of the enforcement triggers is gone. The append-only
  guarantee is off; the chain may still verify, but it is no longer *protected*.

**On Postgres with the triggers intact, `hash_mismatch` and `linkage_break` should
be impossible** — the triggers reject the mutations that cause them. So a real
failure means one of: the triggers were removed (see the "trigger missing" reason,
or check §restricted-role below), the DB was restored from a bad backup, or the
data was manipulated at a level below the app (direct `psql` as a superuser after
disabling triggers). Treat every failure as a **potential security incident** until
proven otherwise.

## Step 1 — Freeze audit-consumer trust (do this first)

The moment you're paged, **stop treating the audit log as authoritative** for any
decision until you've confirmed the scope:

- Do not export or hand off the audit log as "verified" (compliance, a support
  escalation, an investigation) while it's red.
- Do not let any automated consumer act on it. There are none today that gate money
  on the chain, but the reconstruction-from-audit and the admin audit search / CSV
  export should carry a caveat until cleared.
- Note the exact suspect id range from the email — you'll investigate that window.

The chain **before** the suspect id is still trustworthy (it verified on prior
runs, and the cursor didn't advance past the last good row). The break is *at or
after* `suspect_id`; everything strictly before `last_good_id` is intact.

## Step 2 — Investigate the suspect id range

Read the suspect row and its neighbors directly (read is never blocked; only
UPDATE/DELETE):

```python
# manage.py shell   (prod: Railway service shell)
from apps.audit.models import AuditLog, AuditVerifierState
st = AuditVerifierState.load()
print(st.last_verified_id, st.last_verified_hash, st.result, st.run_at)

sid = <suspect_id_from_email>
rows = AuditLog.objects.filter(id__gte=sid-2, id__lte=sid+2).order_by("id")
for r in rows:
    print(r.id, r.event_type, r.occurred_at, r.prev_hash[:8], r.self_hash[:8])
```

Recompute the suspect row's hash by hand and compare:

```python
from apps.audit.hashing import canonical_payload, compute_self_hash
r = AuditLog.objects.get(id=sid)
payload = canonical_payload(
    occurred_at=r.occurred_at, user_id=r.user_id, actor_id=r.actor_id,
    event_type=r.event_type, entity_type=r.entity_type, entity_id=r.entity_id,
    data_before=r.data_before, data_after=r.data_after, ip=r.ip, ua=r.ua,
)
print("stored  :", r.self_hash)
print("recomputed:", compute_self_hash(r.prev_hash, payload))
```

- If they **differ** → the row's content was changed after it was written
  (`hash_mismatch`). Compare against Sentry/logs/DB backups to see what the row
  *should* have said and who could have changed it.
- If they **match** but `r.prev_hash != prior.self_hash` → the break is linkage: a
  row was inserted or deleted around it. Look for a gap or an out-of-order id.

Then check the triggers directly (this is what `triggers_present()` queries):

```sql
SELECT t.tgname FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'audit_log' AND NOT t.tgisinternal;
-- expect: audit_log_block_mutation, audit_log_check_link
```

If a trigger is missing, that alone explains the failure and is the first thing to
restore (§trigger removal below). Cross-reference `auth.login_ok` rows for staff
accounts around the incident window (see `incident-triage.md` — the new-IP
advisory) and any `flag.flipped` / `admin.*` rows you didn't authorize.

## Step 3 — Contain, then decide

- **Confirmed benign** (e.g. a known bad backup restore, a migration you ran that
  legitimately re-seeded rows): document it, then re-baseline (§re-baseline).
- **Confirmed or suspected tamper:** rotate the operator credentials, review admin
  sessions and `admin.impersonation_started` rows, restore the audit table from the
  last known-good backup if the content was altered, and write a full postmortem
  (`docs/postmortem-template.md`). Do not re-baseline over a tamper — restore first.

## Appendix A — Restricted-role provisioning (two-role posture)

The append-only triggers `RAISE` for **every** role including the table owner, so
day-to-day even the owning role cannot UPDATE/DELETE audit rows — good. But a
role that **owns** `audit_log` *can* `DROP TRIGGER` (an object's owner may drop
its triggers), which is the one way the protection can be turned off from inside
the app's own credentials.

The stronger posture — available on any self-hosted Postgres, where you control
role creation — is to run the application on a role that is **not the owner** of
`audit_log` and has had its mutate rights on that table revoked, while all DDL
(trigger create/drop, migrations) runs under a **separate owner/admin role** used
only for deploys.

Provision it like this, **run as the owner/admin role** (the role migrations run
as, which owns the tables):

```sql
-- 1. A runtime role for the app's normal connection. Owns nothing.
CREATE ROLE stp_app LOGIN PASSWORD '<generated>';
GRANT CONNECT ON DATABASE strattraderpro TO stp_app;
GRANT USAGE ON SCHEMA public TO stp_app;

-- 2. Normal DML across the whole application schema — WITHOUT this the app
--    cannot touch any non-audit table. This is the grant the app needs to run.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO stp_app;
GRANT USAGE,  SELECT                 ON ALL SEQUENCES IN SCHEMA public TO stp_app;

-- Make the above apply to tables/sequences created by FUTURE migrations too.
-- (ALTER DEFAULT PRIVILEGES must name the role that CREATES the objects — i.e.
--  the owner/admin role you are running this as.)
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO stp_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT                  ON SEQUENCES TO stp_app;

-- 3. Now claw back the dangerous rights on audit_log ONLY. The role keeps
--    INSERT + SELECT there; it is not the owner, so it also cannot DROP TRIGGER.
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_log FROM stp_app;
```

Point `DATABASE_URL` at `stp_app` for the runtime services (backend, worker,
beat, streams, ws); run migrations under the owner/admin role via a separate
`DATABASE_URL`/migration step.

If you instead run everything on a single owning role (the simplest deployment),
the append-only block still holds against ordinary writes, but a compromised app
credential could `DROP TRIGGER`. In that single-role mode the nightly verifier's
trigger-presence check is your catch-net. Prefer the two-role split above when you
can.

## Appendix B — How/when trigger removal is gated

Trigger removal is **never** a routine operation. It exists for exactly two reasons:

1. **A migration that legitimately alters the table structure** may need to drop and
   re-create the triggers within the same migration (the reverse of
   `audit.0002_chain_triggers` drops them, with a loud `WARNING` comment). Any such
   migration must re-install both triggers before it completes, and the *next*
   verifier run confirms `triggers_present()` — a migration that leaves them off
   will page you the following morning.
2. **A confirmed-benign re-baseline** (Appendix C) where you must delete/rewrite
   rows. This is the only sanctioned manual path, and it is gated on: (a) a written
   reason, (b) a fresh DB backup taken first, (c) doing it in a maintenance window,
   and (d) re-installing the triggers and re-running the verifier immediately after.

If you ever find the triggers dropped and **cannot** account for it via (1) or (2),
that is the tamper case — do not re-add them and move on; investigate first.

## Appendix C — Re-baseline (only after a confirmed-benign failure)

After you've proven the failure is benign (e.g. a legitimate restore), advance the
verifier past it so it stops paging. **Do not do this over an unexplained failure.**

1. Take a fresh backup.
2. Run the verifier interactively to get the exact last-good position:
   `python manage.py shell -c "from apps.audit import verifier; print(verifier.verify_chain())"`.
3. If the correct remediation was to re-write rows, that requires dropping the
   triggers (Appendix B gate 2), fixing the data so the chain is internally
   consistent again, re-installing the triggers, and confirming
   `verifier.triggers_present()` is `True`.
4. Re-run `verify_audit_integrity` and confirm
   `audit_integrity_check_total{result="ok"}` increments and the cursor advances.

Record the incident in the monthly drill log (`audit-integrity-verify-monthly.md`).
