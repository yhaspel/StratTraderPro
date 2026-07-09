# Runbook — Monthly audit-integrity verification spot-check

**Owner:** Yuval
**Cadence:** Monthly. Record the run date and the observed values each time.
Mirrors the `docs/runbooks/kill-switch-verify-monthly.md` precedent — a dated,
executable drill against a built-and-tested system.
**Status:** The nightly verifier (`apps.audit.tasks.verify_audit_integrity`, beat
08:00 UTC ≈ 04:00 ET), the hash chain, and the Postgres enforcement triggers are
built and unit-tested (M10, AC-10-1…AC-10-4). This drill confirms, by hand and once
a month, that the automated verifier is actually running and the DB-level
enforcement is actually in place — so a silently-disabled verifier or a
dropped trigger is caught by a human, not just assumed. **Companion docs:**
`docs/adr/100-audit-hash-chain.md` (the design this verifies — read §2/§6 first),
`docs/runbooks/audit-integrity-failure.md` (what to do if any check fails).

## Drill log

| Date run | By | Verifier ran ≤24h? | `result` | `last_verified_id` advanced? | Triggers present? | Manual `verify_chain` ok? | `integrity_check_total{ok/fail}` | Notes |
|---|---|---|---|---|---|---|---|---|
| _YYYY-MM-DD_ | | | | | | | | |

> Copy the row each month. Record pass/fail per column and the metric deltas.

## Prerequisites

- Admin access to a `manage.py shell` on the target environment (Railway service
  shell in prod).
- A Prometheus/Grafana view of `audit_integrity_check_total{result}` and
  `audit_verifier_duration_seconds`, or `curl` on the relevant `/metrics`.
- The operator inbox — so you can confirm no failure email is sitting unseen.

## Step 1 — Confirm the nightly verifier actually ran

The whole point of the automated path is that it runs unattended. Confirm it did:

```python
# manage.py shell
from apps.audit.models import AuditVerifierState
st = AuditVerifierState.load()
print("run_at            :", st.run_at)            # should be within the last ~24h
print("result            :", st.result)            # "ok"
print("last_verified_id  :", st.last_verified_id)  # non-zero, advancing month over month
print("last_verified_hash:", st.last_verified_hash[:12])
```

- `run_at` older than ~24 h ⇒ **the beat isn't firing** — check the `beat` service
  and the schedule. A verifier that never runs is a silent failure the same as a red
  one.
- `result == "fail"` ⇒ go straight to `audit-integrity-failure.md`.
- `last_verified_id` should be larger than last month's logged value (the chain is
  growing and being verified). If it's stuck across two months with new audit rows
  present, the cursor isn't advancing — investigate.

## Step 2 — Confirm the metrics moved

Snapshot `audit_integrity_check_total{result="ok"}` — it should have incremented
roughly once per night since last month (≈ +30). A flat counter means the task
isn't running even if `run_at` looks plausible (or the scrape is missing —
`worker-metrics-scrape.md`). `audit_integrity_check_total{result="fail"}` must be
**0** over the window.

## Step 3 — Confirm the DB-level enforcement is still in place (Postgres)

The triggers are what make the log append-only. Confirm both still exist:

```python
# manage.py shell
from apps.audit import verifier
print("triggers_present:", verifier.triggers_present())   # True on Postgres+SQLite
```

On prod, also eyeball them directly:

```sql
SELECT t.tgname FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'audit_log' AND NOT t.tgisinternal;
-- expect: audit_log_block_mutation, audit_log_check_link
```

A missing trigger is a finding even if the chain still verifies — the protection is
off. See `audit-integrity-failure.md` Appendix B (how/when trigger removal is gated).

Optional, once, to *feel* the enforcement: attempt an UPDATE in a throwaway
transaction and confirm it `RAISE`s (then `ROLLBACK`):

```sql
BEGIN;
UPDATE audit_log SET ua = 'tamper' WHERE id = (SELECT max(id) FROM audit_log);
-- expect: ERROR: audit_log is append-only; update/delete is blocked for every role
ROLLBACK;
```

## Step 4 — Run a manual full verification

Independently re-derive the chain (this is the same code the nightly task runs, but
you invoke it now and read the result):

```python
# manage.py shell
from apps.audit import verifier
print(verifier.verify_chain())
# expect: {'ok': True, 'checked': <n>, 'last_id': ..., 'last_hash': ..., 'failed_id': None, 'reason': ''}
```

`ok: True` with `failed_id: None` is the pass. Any `False` ⇒ note the `failed_id` +
`reason` and follow `audit-integrity-failure.md`.

## Pass criteria

- Nightly verifier ran within ~24 h, `result == "ok"`, `last_verified_id` advanced.
- `audit_integrity_check_total{result="ok"}` incremented over the month;
  `{result="fail"}` is 0.
- Both triggers present (and the UPDATE attempt raises, if you ran it).
- Manual `verify_chain()` returns `ok: True`.
- No unseen failure email in the operator inbox.

Log the row. Any failed criterion is a finding — most route to
`audit-integrity-failure.md`; a non-firing beat routes to the `beat` service.
