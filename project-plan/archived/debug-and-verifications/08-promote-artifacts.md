# 08 — Promote spike artifacts (Task A.3)

**Goal.** Move the spike artifacts from "throwaway-or-promote" to production-ready. Delete vestigial files, rename the runbook, document the production topology.

## Tasks

### 8.1 Delete vestigial spike files

ADR-040 gotcha #4 calls these out as "authored for the from-scratch image and aren't used by the gnzsnz base."

```bash
rm -f docker/ib-gateway/entrypoint.sh
rm -f docker/ib-gateway/ibc-config.ini
```

If these files exist after this command, the previous `rm -f` worked. If they didn't exist to begin with, ADR-040's note about them is outdated — that's fine, no action needed.

### 8.2 Rename the runbook for production usage

The current runbook `docs/runbooks/spike-ibkr-gateway.md` documents how to run the smoke test. Production needs a different runbook: how to operate, re-auth, and debug the IB Gateway sidecar.

```bash
# Rename
git mv docs/runbooks/spike-ibkr-gateway.md docs/runbooks/ib-gateway-reauth.md
```

Rewrite the renamed file with these sections (use the Edit/Write tool — read the existing file first to preserve what's still relevant):

- **Title:** "Runbook — IB Gateway sidecar (operations + re-auth)"
- **Status:** Production-ready (M04). Was spike runbook; promoted 2026-05-15 per ADR-040.
- **When to use this runbook.** When IB Gateway shows disconnected status, when re-auth is needed after IBKR-side changes, when a paper account needs to be set up for a new operator/developer.
- **Operating the sidecar.** Start/stop/status commands. The full env-var contract from ADR-040 Decision (Production env-var contract). Healthcheck verification.
- **Failure-mode triage table.** Keep the existing table from the spike runbook (4 rows mapped to exit codes 1–5). Update to mention the gnzsnz-config-render gotcha (gotcha #7) explicitly: "If smoke STEP 1 fails with TCP-Connected-then-API-TimeoutError despite a recent build, run `./scripts/verify_ibgw_config.sh`."
- **Re-auth procedure.** When IBKR's paper account silently disables API access (typically after 5+ days idle), the fix is one web login at <https://www.interactivebrokers.com/sso/Login>. Document the steps.
- **Bumping the gnzsnz tag.** Reference `docker/ib-gateway/Dockerfile` comments. Steps: pick newer tag, rebuild, run smoke STEP 1–3 against it pre-RTH, then RTH-verify STEP 4 + 5, then update Dockerfile + this runbook with the new pin.
- **CI integration.** Reference `scripts/verify_ibgw_config.sh` — it must exit 0 before any code that talks to the broker adapter is allowed to run in CI.

Delete from the file:
- "What this proves" / "spike" framing
- The four-assumption table (it belongs only in ADR-040 now)
- Any "Run it on Railway (the actual platform test)" section — production deploys are documented in `docs/runbooks/prod-bootstrap.md`.

### 8.3 Promote the smoke script note (don't delete, just refile)

`scripts/spike_ibkr_smoke.py` is still useful as a manual health check. Don't delete it. Update its docstring header to remove "SPIKE" framing — call it a "manual IBKR connectivity smoke test, used by `docs/runbooks/ib-gateway-reauth.md`".

```bash
# Read the file's current header
sed -n '1,40p' scripts/spike_ibkr_smoke.py
# Then edit the docstring to drop SPIKE-only framing, keep the technical content.
```

### 8.4 Update README in `docker/ib-gateway/`

`docker/ib-gateway/README.md` was already updated earlier in this loop (drops SPIKE framing, documents pin policy + env contract + port mapping). Re-read it to confirm it reflects today's state — specifically, it should mention the IBC template patch / config render override approach that fixes gnzsnz 10.45.1e. If not, add a section.

```bash
cat docker/ib-gateway/README.md
# Look for: env contract section, port mapping section, gnzsnz quirk callout.
# If the gnzsnz quirk callout is missing, add it referencing ADR-040 gotcha #7.
```

## Verify

```bash
# Vestigial files gone
ls docker/ib-gateway/entrypoint.sh docker/ib-gateway/ibc-config.ini 2>&1 | grep "No such file"
# Expected: both files reported as missing

# Runbook renamed
ls docs/runbooks/ib-gateway-reauth.md
ls docs/runbooks/spike-ibkr-gateway.md 2>&1 | grep "No such file"
# Expected: first exists, second is missing

# Smoke script docstring no longer says "SPIKE" at the top
head -3 scripts/spike_ibkr_smoke.py | grep -i "spike" && echo "still mentions SPIKE — update" || echo "OK"

# README has the gnzsnz quirk note
grep -E "gnzsnz|10\.45\.1e|AcceptIncoming" docker/ib-gateway/README.md
# Expected: at least one match
```

## FALLBACK

If any verify fails:

- Re-run the corresponding rm/mv/edit command.
- If the runbook rewrite feels half-baked, save what you have and add a TODO at the top: `<!-- TODO: complete production-ready rewrite -->`. Note in memory: "ib-gateway-reauth runbook needs a follow-up pass; current state is a partial promotion from the spike runbook."

## NEXT

Read `09-finalize-phase-a.md`.
