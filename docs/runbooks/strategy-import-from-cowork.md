# Runbook — Importing strategies from the Trading Strategies project

**Last reviewed:** 2026-07-12

**Owner:** Yuval (creator of the Trading Strategies project)
**Used by:** ops + the deployment pipeline
**Command:** `python manage.py load_strategies <path>`

## What this is for

The Trading Strategies project is a separate Cowork project that holds
the canonical Pine scripts, descriptions, and (eventually) backtest
results for our system-curated catalogue. M03 introduces a Django
management command that walks that directory and seeds `Strategy`
+ `StrategyFile` rows with `is_system=True`, `owner=None`.

The same command is used both:
- Once at staging+prod cutover to bootstrap the catalogue.
- Whenever Yuval adds/edits strategies in the source-of-truth project,
  to push updates to the platform's database.

## Pre-flight

1. The source directory must be reachable from where you run
   `manage.py`. In local dev that's a path on your laptop; on Railway
   you'd need to mount or rsync the folder into the container — easier
   to run locally and let the deploy carry the resulting rows via DB
   migration if the catalogue is small (current case).
2. Each strategy lives in its own immediate sub-directory (e.g.
   `01-minervini-sepa-vcp/`, `02-ict-smart-money/`). The folder name
   becomes the `Strategy.slug`.
3. Each folder must contain at least:
   - One `*.pine` file.
   - One file with `description` in the name (`.txt` preferred) OR a
     `strategy.md` fallback.
4. A `*_Webhook.json` file is OPTIONAL. If absent, the command
   synthesizes a default webhook payload template from
   `apps.strategies.services.default_payload_template(slug)`.

## Running it

### Dry run first

```bash
cd backend
python manage.py load_strategies "/path/to/Trading Strategies/top-strategies" --dry-run
```

The dry-run prints one line per folder:

- `DRY  <slug>: pine=<file> desc=<file> webhook=<file> (NB/NB/NB)` —
  would seed/update.
- `SKIP <name> (no .pine + description)` — folder exists but isn't a
  strategy bundle.

The dry-run never writes to the DB. No row counts change.

### Real run

```bash
python manage.py load_strategies "/path/to/Trading Strategies/top-strategies"
```

Output:

- `NEW   <slug>` — new system row created.
- `UPD   <slug>` — existing row's files changed and were replaced.
- `NOOP  <slug>` — existing row's files match the current SHA-256s; no
  write.
- `SKIP  <name>` — not a strategy folder.
- `FAIL  <name>: <reason>` — folder looked like a strategy bundle but
  validation failed (e.g. webhook JSON didn't parse).

The summary line is grep-friendly:

```
load_strategies: seeded=N updated=M skipped=K errors=J
```

Exit code is 0 if `errors=0`, non-zero otherwise — CI can pin on this.

## Idempotency

Re-running the command with no source-folder changes is a no-op (every
strategy gets a `NOOP` line). Re-running after editing one pine script
results in `UPD <slug>` for that strategy and `NOOP` for the rest.

The idempotency check is per-file, by SHA-256. Filename and content
must both be unchanged for a `NOOP` — renaming a pine without changing
its content still triggers an `UPD`.

## Failure modes

- **`<root> is not a directory`** — typo in path or permissions. Verify
  you can `ls -la <path>` first.
- **`webhook file <name> is not valid UTF-8 JSON`** — the source
  webhook file is malformed. Either fix the JSON in the source project
  or delete the file (the command will synthesize a default).
- **A strategy gets `SKIP` instead of `NEW`** — there's no `*.pine` in
  that folder, OR no description file. Verify with `ls`.
- **Existing row's files don't change but we expected them to** — the
  SHA-256 matched. If you're updating a description file, double-check
  you saved the changes.

## After running on prod

- Confirm the row count: `SELECT count(*) FROM strategies_strategy
  WHERE is_system = true AND is_enabled = true;`
- Spot-check the file bytes:
  `SELECT length(content), kind FROM strategies_strategy_file WHERE
  strategy_id = '<uuid>';`
- Hit `GET /api/v1/strategies/` as an MFA-enrolled test user; confirm
  the system rows show with the System badge.

## Related

- `apps/strategies/management/commands/load_strategies.py`
- `apps/strategies/services.py` — `upsert_system_strategy`
- ADR-030 — strategy 3-file contract
- `project-plan/03-strategies-and-webhook-config.md` §6.4
