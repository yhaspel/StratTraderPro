# Backup & restore (M11 §7.6 → AC-11-7)

Last reviewed: 2026-07-12

## Backup topology

| Layer | What | Retention | Owner |
|---|---|---|---|
| Railway daily automated backup | full managed-Postgres snapshot | 30 days | **[LIVE]** operator (Railway) |
| Weekly `pg_dump` → Cloudflare R2 | logical `pg_dump` offload | 90 days | **[LIVE]** operator (R2 bucket + creds — §7.9) |
| Restore drill | scripted verify-restore into a scratch Postgres | ephemeral | **[CI]** `scripts/restore-drill.sh` |

The Railway snapshot + the R2 offload require the real project/bucket and are
Section-B operator steps. The **drill below is buildable and was run.**

## The restore drill — `scripts/restore-drill.sh`

What it does (the shared Postgres is **never** modified — `pg_dump` only, and all
writes go to a throwaway scratch container removed on exit via `trap`):

1. `pg_dump` the shared app DB read-only (`--no-owner --no-privileges`).
2. Boot a fresh `stp-restore-scratch` Postgres (host `:55432`) on the stack network.
3. Restore the dump into scratch (triggers/constraints are recreated *after* the
   data COPY by `pg_dump`, so the append-only audit trigger does not fire during
   load).
4. **Verification queries:** row counts on `users_user`, `audit_log`,
   `orders_order`, `orders_fill`, `orders_position`, `brokers_account` must match
   the source exactly.
5. **Audit-chain re-verify:** run `apps.audit.verifier.verify_chain` against the
   restored copy (via the backend container's `manage.py shell` with
   `DATABASE_URL` pointed at scratch) and assert `ok: true`.

Run:

```bash
scripts/restore-drill.sh
```

## Captured run (2026-07-12, shared dev stack)

```
[drill] shared postgres:  strattraderpro-postgres-1
[drill] shared backend:   strattraderpro-backend-1
[drill] scratch:          stp-restore-scratch (host :55432)
[drill] 1/5 pg_dump strattraderpro (read-only, --no-owner --no-privileges) ...
[drill]     dump size: 243999 bytes
[drill] 2/5 starting scratch Postgres (postgres:16-alpine) on network strattraderpro_default ...
[PASS]  scratch is up
[drill] 3/5 restoring dump into scratch ...
[drill] 4/5 verifying row counts (shared vs restored) ...
    table                          shared   restored
    users_user                          3          3  ok
    audit_log                          16         16  ok
    orders_order                        0          0  ok
    orders_fill                         0          0  ok
    orders_position                     0          0  ok
    brokers_account                     0          0  ok
[PASS]  all key tables reproduced exactly
[drill] 5/5 re-verifying audit chain against the restored DB ...
    verify_chain -> {"ok": true, "checked": 16, "last_id": 16, "last_hash": "afd4eeea…d39b4", "failed_id": null, "reason": ""}

======================= RESTORE DRILL RESULT =======================
[PASS]  row counts reproduced
[PASS]  audit chain re-verified OK on restored copy
====================================================================
DRILL: PASS
[drill] cleanup: removing scratch container + temp files
```

**Result: PASS.** The restore reproduced last-known state exactly (all key tables)
and the append-only audit hash-chain re-verified `ok: true` over all 16 rows on
the restored copy. Scratch container removed on exit.

> Note: the drill runs against whatever data the source DB holds at drill time
> (here a near-fresh dev DB: 3 users, 16 audit rows, 0 orders). On a populated
> prod snapshot the same assertions apply at scale; the audit-chain re-verify is
> the meaningful integrity gate regardless of row count.

## Operator / [LIVE] steps

- **Railway PITR / daily snapshot:** enable in the Railway Postgres plugin;
  confirm the 30-day window and test a point-in-time restore into a staging DB.
- **Weekly `pg_dump` → R2:** a scheduled job dumps prod and uploads to the R2
  bucket (SSE on; 90-day lifecycle rule). Provision the bucket + credentials per
  `docs/ops/prod-bringup.md` §7.9; until then the offload is a no-op with a clear
  operator note.
- **Disaster restore:** `pg_restore`/`psql` the latest R2 dump (or Railway
  snapshot) into a fresh Postgres, run this drill's verification queries + the
  audit-chain re-verify before repointing the app.
