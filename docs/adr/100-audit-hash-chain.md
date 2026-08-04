# ADR-100 — App-computed hash chain + Postgres trigger enforcement for the audit log

**Date:** 2026-07-10
**Status:** Accepted
**Milestone:** M10 — Admin Portal, Audit Log & Observability
**Reference:** `project-plan/10-admin-audit-observability.md` §6.1, §6.11, §17; master §6.11, §17;
AC-10-1…AC-10-4; the `apps/audit` package; ADR-081 (the kill-switch events this chains);
runbooks `docs/runbooks/audit-integrity-failure.md`, `docs/runbooks/audit-integrity-verify-monthly.md`

## Context

M10 needs a tamper-evident audit log: an append-only record of security- and
money-relevant actions (auth, broker connect/mode, order submit, kill-switch
engage/release, admin actions, flag flips) that an operator — and, later, a
regulator — can trust was not silently edited after the fact. "Trust" here has a
specific meaning: any insertion, deletion, or in-place edit of a historical row
must be **detectable**, ideally **prevented at the database**, and the whole
record must be **re-verifiable from first principles** on a schedule.

Three questions had to be answered before writing the model:

1. **Where is the hash computed** — in the app, in a database trigger, or both?
2. **What actually stops an `UPDATE`/`DELETE`** — application discipline, or the
   database itself (including against the DB owner role Railway gives us)?
3. **Does everything go in the chain**, or are high-volume events kept out?

## Decision

### 1. The chain is app-computed; the database enforces it

Each `AuditLog` row (table `audit_log`) carries `prev_hash` and `self_hash`:

```
self_hash = sha256( prev_hash_ascii ‖ canonical_payload )
genesis prev_hash = "0" * 64   (64 ASCII zeros)
```

There is **one canonical hashing implementation** — `apps/audit/hashing.py`:

- `canonical_payload(**fields)` serializes a **fixed field set** as JSON with
  **sorted keys** and **compact separators** (`(",", ":")`, `ensure_ascii=False`).
  The field set, in order, is `occurred_at, user_id, actor_id, event_type,
  entity_type, entity_id, data_before, data_after, ip, ua`. The row's `id` is
  **excluded** — it isn't known until after `INSERT`, so it cannot be part of the
  pre-insert hash. `occurred_at` is normalized to ISO-8601 UTC with microseconds;
  `data_before`/`data_after` are round-tripped through `DjangoJSONEncoder` so what
  we hash is byte-identical to what `JSONField` reads back.
- `compute_self_hash(prev_hash, payload)` is `sha256(prev_hash.encode("ascii") +
  payload).hexdigest()`.

The write path is `apps/audit/services.emit()` — the **single** explicit call for
writing a chained row. Inside one `transaction.atomic()` it: takes a Postgres
advisory lock (below), reads the current chain head
(`AuditLog.objects.order_by("-id").values_list("self_hash").first()` — genesis if
empty), computes `self_hash`, and inserts. `emit()` **never raises into the
caller** (§11): audit failure must not break the business action. The
`except` wraps the atomic block from the outside — catching a trigger `RAISE`
*inside* the atomic block would poison the transaction with
`TransactionManagementError`; the outer `except` and the savepoint-nesting of the
inner `atomic()` mean a failed audit insert rolls back only its own savepoint and
increments `audit_events_dropped_total`, leaving the business transaction intact.

### 2. Postgres triggers are the integrity backstop — app discipline is not enough

Migration `audit.0002_chain_triggers` installs two triggers (and their functions),
**vendor-guarded** — the migration is a no-op on any non-Postgres backend:

- **`audit_log_block_mutation` (BEFORE UPDATE OR DELETE):** `RAISE EXCEPTION`
  unconditionally — `audit_log is append-only; update/delete is blocked for every
  role`. There is no `WHEN` clause and no role exemption. Even the table owner (on
  Railway, the single app role *is* effectively the owner) cannot `UPDATE` or
  `DELETE` a row while the trigger exists.
- **`audit_log_check_link` (BEFORE INSERT):** takes
  `pg_advisory_xact_lock(hashtext('audit_log'))`, validates `self_hash` matches
  `^[0-9a-f]{64}$`, reads the current head
  (`SELECT self_hash FROM audit_log ORDER BY id DESC LIMIT 1`), and enforces
  linkage: on an empty table the new `prev_hash` must equal the 64-zero genesis;
  otherwise `NEW.prev_hash` must equal the head's `self_hash`. A mismatch
  `RAISE`s. This means even a raw `INSERT` that bypasses `emit()` cannot forge a
  broken link — the DB rejects it.

### 3. The advisory lock serializes the chain head — in the app AND in the trigger

The chain has a single head; two concurrent writers reading the same head would
produce a fork. `pg_advisory_xact_lock(hashtext('audit_log'))` is taken **in both
places**: in `emit()` (`_advisory_lock()`) *and* at the top of the
`audit_log_check_link` trigger. Taking it in the app serializes the ORM read of
the head; taking it in the trigger serializes any writer (including a raw
`INSERT`) against the linkage check. Both use the same lock key, so they contend
on the same lock. It is a **transaction-scoped** lock — released at commit/rollback.

### 4. High-volume events are deliberately NOT chained (deviation from master §6.11)

Master §6.11 reads as "audit everything." We deviate, explicitly: **webhook-received
events and per-alert sizing decisions are excluded from the chain.** These are the
two highest-cardinality event streams in the system (one per inbound alert, one per
sizing computation), and chaining them would (a) serialize every webhook and every
sizing call through the single advisory lock, turning the audit chain into a
throughput bottleneck on the hot path, and (b) bloat the 7-year retention set with
operational telemetry rather than security-relevant actions.

They are not lost — they already live in their own first-class tables:
webhook ingest in `AlertMessage` (the M04 ingest audit row, `sig` stripped) and
sizing in `SizingDecision` (one row per sizing path, M08). Neither table is
hash-chained; both are queryable. The `AuditEventType` enum therefore has **no**
`webhook.*` or sizing family — the chain covers `auth.*`, `broker.*`, `order.*`,
`strategy.*`, `risk.*`, `admin.*`, `flag.*`, and `audit.*` only. `order.submitted`
*is* chained (one per placed order, far lower volume than one per inbound alert).

### 5. `AuthEvent` was migrated into the chain, then dropped

The M01 `AuthEvent` table was the pre-existing auth audit trail. Its `EventType`
enum (26 values: `login_ok`, `login_fail`, `refresh_reuse`, the MFA/OAuth events,
…) is **relocated verbatim** into `apps/audit/events.AuthEventType` so it survives
the table drop; the users app imports it as `EventType` and passes bare values
(`"login_ok"`) to `record_event()`, which prepends the `auth.` namespace before
calling `emit()`. Values are kept **byte-identical** to the historical column so
the migration maps cleanly.

The cutover is two migrations:

- **`audit.0003_migrate_auth_events`** (data migration) reads every `AuthEvent`
  ordered by `(occurred_at, id)`, rebuilds the hash chain from genesis (each row
  becomes an `auth.<event_type>` `AuditLog` row inserted with its **original**
  `occurred_at`), and **self-verifies**: it asserts the created count equals the
  source count and re-checks the final head hash, raising `RuntimeError` on any
  mismatch. It inlines **frozen copies** of the scrub/canonical/hash helpers so a
  later edit to `hashing.py` can never retroactively change what the migration
  computed. Its reverse is `IrreversibleError` on Postgres (the append-only trigger
  blocks the `DELETE`); recovery is a DB-backup restore.
- **`users.0004_drop_auth_event`** runs *after* `0003` and `DeleteModel`s
  `AuthEvent` — so the table is dropped only once every historical row is in the
  chain.

This is why `AuditLog.occurred_at` uses `default=timezone.now` and **not**
`auto_now_add`: the data migration must insert rows carrying historical timestamps.
`auto_now_add` would silently overwrite `occurred_at` on every insert, breaking the
hash of every migrated row.

### 6. The nightly verifier re-derives the whole chain from a cursor

`apps/audit/verifier.py` (`run_verifier()`) is scheduled by the beat task
`apps.audit.tasks.verify_audit_integrity` at **08:00 UTC (≈ 04:00 ET)**. It:

- Loads the singleton `AuditVerifierState` (`last_verified_id`,
  `last_verified_hash`) and **resumes from the cursor** — it does not re-hash the
  entire table every night, only rows past the last verified id, using the last
  verified hash as the starting `prev_hash`.
- Walks new rows in id order, recomputing each `self_hash` and asserting **both**
  linkage (`row.prev_hash == expected`) and hash (`recomputed == row.self_hash`).
- Asserts the **triggers still exist** (`triggers_present()` queries `pg_trigger`
  for both trigger names; returns `True` on SQLite).
- **On success:** advances the cursor, records `audit_verifier_duration_seconds`,
  increments `audit_integrity_check_total{result="ok"}`, and emits an
  `audit.verifier_completed` row.
- **On failure:** does **not** advance the cursor (it stays at the last good
  position), increments `audit_integrity_check_total{result="fail"}`, writes an
  `audit.integrity_failure` row (naming the suspect id + reason —
  `hash_mismatch` / `linkage_break` / trigger-missing), and **emails the operator**
  at `AUDIT_ALERT_EMAIL` (falling back to `DEFAULT_FROM_EMAIL`) with the suspect id
  range and a pointer to `docs/runbooks/audit-integrity-failure.md`.

The `AuditIntegrityFailure` alert (`increase(audit_integrity_check_total{result="fail"}[1h]) > 0`,
critical/page) fires off that metric — see `docs/runbooks/incident-triage.md`.

### 7. SQLite degrades to the same Python path, minus the lock and triggers

Tests and local dev run on SQLite. There, `_advisory_lock()` is a no-op
(vendor-guarded), the `0002` trigger migration is a no-op, and `triggers_present()`
returns `True`. The **same Python hashing + linkage code** runs on every backend,
so the chain is computed and verifiable identically; only the DB-level *enforcement*
(the mutation block and the trigger-side lock) is Postgres-only. The honest
consequence: on SQLite the append-only guarantee is app-discipline, not
DB-enforced. This is acceptable because SQLite is never a production backend — prod
is Postgres, where the triggers are the real backstop.

## Consequences

- **Tamper is prevented at the DB and detected on a schedule.** In-place edits and
  deletes are blocked by the trigger for every role; forged links are blocked at
  INSERT; anything that somehow slipped past is caught by the nightly verifier and
  pages the operator.
- **One hashing implementation, frozen at migration time.** `hashing.py` is the
  single source; the data migration froze its own copy so historical rows can never
  be invalidated by a future refactor.
- **The hot path stays fast.** Excluding webhook + sizing keeps the advisory lock
  off the two highest-volume streams; those events remain queryable in their own
  tables. Documented deviation from master §6.11.
- **Retention 7 years** (master §17). `audit_log` is a plain indexed table today;
  the **partition threshold** is **≥ 50M rows or ≥ 10 GB** — below that, range
  indexes on `occurred_at` are sufficient and monthly partitioning is deferred (it
  complicates the append-only triggers, which would have to be re-created per
  partition). Revisit when either threshold is crossed.

**Honest limits:**

- **The verifier is nightly, not real-time.** A tamper is detected within ~24 h,
  not instantly. The triggers make the tamper *hard* in the first place; the
  verifier is the catch-net, and its cadence is a cost/coverage trade.
- **A single advisory lock serializes all chained writes.** This is fine at MVP
  volume precisely *because* the two firehose streams are excluded. If a chained
  family ever becomes high-volume, revisit the exclusion set before the lock
  becomes a bottleneck.
- **SQLite is unenforced.** Only relevant to tests/dev, but stated plainly.

## Alternatives considered

1. **Trigger-computed hash (compute `self_hash` inside the INSERT trigger).**
   Rejected: plpgsql SHA-256 over the exact canonical JSON we hash in Python is
   fragile and duplicates the canonicalization logic in a second language, inviting
   drift. The app computes; the trigger *checks*. One source of truth for the hash.
2. **App-only enforcement (no triggers).** Rejected: the whole point is to survive
   a compromised or careless app process, or a raw `psql` session. Without the DB
   block, "append-only" is a convention, not a guarantee.
3. **Chain everything, including webhooks + sizing (literal master §6.11).**
   Rejected: turns the audit chain into a throughput bottleneck on the hot path and
   bloats 7-year retention with telemetry. Those events keep their own tables.
4. **Keep `AuthEvent` as a separate table.** Rejected: two parallel audit stores
   with different integrity guarantees is exactly the confusion M10 exists to
   remove. One chained log, one taxonomy.

## See also

- `backend/apps/audit/hashing.py` — the one canonical hashing implementation
- `backend/apps/audit/services.py` — `emit()`, the single chained-write path
- `backend/apps/audit/verifier.py` + `tasks.py` — nightly verifier + beat task
- `backend/apps/audit/migrations/0002_chain_triggers.py` — the trigger SQL
- `backend/apps/audit/migrations/0003_migrate_auth_events.py`,
  `backend/apps/users/migrations/0004_drop_auth_event.py` — the AuthEvent cutover
- `docs/runbooks/audit-integrity-failure.md` — what to do when the verifier fails
- `docs/runbooks/audit-integrity-verify-monthly.md` — the monthly spot-check drill
- ADR-101 (feature flags), ADR-102 (observability topology) — the other M10 ADRs
