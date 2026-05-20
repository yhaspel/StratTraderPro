# 07 — Update ADR-040 with the final findings

**Goal.** Bring `docs/adr/040-ibkr-gateway-sidecar.md` to a coherent **Accepted** state, with every assumption verified, every gotcha captured, and no `TO BE FILLED IN` placeholders or duplicate headers.

## Current state of ADR-040 (issues to fix)

Read the file first: `docs/adr/040-ibkr-gateway-sidecar.md`. Known issues at handoff:

1. Status line reads `Spike in progress (Day 1 of M04)` — must flip to `Accepted`.
2. Findings section: A2 step 4 (real fill) and A3 (reconnect) marked deferred to the 2026-05-11 RTH rerun, which didn't happen. Replace with the actual SpikeResult block captured in `06-rth-rerun.md`.
3. Decision section ends with a "TO BE FILLED IN" placeholder block listing three pivot options — that block is from an earlier draft. The actual Decision ("Promote with changes") is already partially written above it; consolidate into a single coherent Decision.
4. There is a **duplicate `## Consequences` header** — one block has real content (`Positive:` / `Negative:`), the other is a `TO BE FILLED IN` placeholder. Delete the placeholder, keep the populated one.
5. Findings note #4 calls vestigial spike files `docker/ib-gateway/entrypoint.sh` and `docker/ib-gateway/ibc-config.ini` "leave in place until reconnect+RTH run completes; clean up when the spike flips to Accepted." → cleanup happens in `08-promote-artifacts.md`; ensure that note is updated.
6. ADR doesn't mention the gnzsnz-config-render gotcha discovered today (gotcha #7 to add — see below).

## Steps

```bash
# 1. Read the file fully so the rewrite is informed
cat docs/adr/040-ibkr-gateway-sidecar.md

# 2. Apply edits (use the Edit tool or sed):
```

### Edit 1: flip Status

```
**Status:** Spike in progress (Day 1 of M04)
```
→
```
**Status:** Accepted (2026-05-15 — see Findings)
```

### Edit 2: A2 step 4 + A3 in Findings

Replace the existing "A2 partial — fill (Step 4): N/A this run" and "A3 (reconnect): ⏳ deferred" bullets with concrete results from the RTH rerun. Format the captured SpikeResult block verbatim, then write a one-line interpretation per bullet.

If the RTH rerun produced a clean STEP 4 + STEP 5 pass, both bullets become ✅ with the SpikeResult numbers cited inline.

If something didn't pass cleanly (e.g., reconnect required clientId rotation), document the exact constraint and reference where in the production code it must be addressed (e.g., "M04 §6.2 broker adapter must rotate clientIds per reconnect — see Findings A3").

### Edit 3: add gotcha #7

After the existing gotcha #6 ("EXISTING_SESSION_DETECTED_ACTION is unset by default"), insert:

```markdown
7. **gnzsnz/ib-gateway:10.45.1e omits `AcceptIncomingConnectionAction` and `AllowBlindTrading` from its IBC config template.** The image's render of `/home/ibgateway/ibc/config.ini` is missing both options entirely. Without `AcceptIncomingConnectionAction=accept`, every new API client connection triggers a hidden per-client "Trusted Computer" dialog that IBC can't auto-dismiss — manifesting as TCP-connects-then-API-handshake-times-out at the `ib_insync` layer. The compose env var `TWS_ACCEPT_INCOMING=accept` does **not** render this option in this image version (appears to map to an unrelated `AcceptBidAskLastSizeDisplayUpdateNotification` line). Discovered 2026-05-15 after multiple TimeoutError loops; fixed by [whichever approach was used — append-after-render shim OR template patch, document the specific approach] in `docker/ib-gateway/`. CI gate: `scripts/verify_ibgw_config.sh` asserts the three required overrides are present in the live config. Bumping the gnzsnz tag in the future requires re-running this script post-build.
```

### Edit 4: remove the duplicate `## Consequences` header

Delete the second `## Consequences` block (the one with the `TO BE FILLED IN` placeholder). Keep the populated one (Positive/Negative sub-bullets).

### Edit 5: clean up the Decision section

Remove the trailing `> **TO BE FILLED IN** based on Findings...` blockquote that lists three pivot options. The actual decision is "Promote with changes" — already documented above. Just remove the leftover placeholder.

### Edit 6: update Findings note #4 about vestigial files

Change `Leave in place until the spike's reconnect+RTH run completes; clean up when the spike flips to Accepted.` to `Removed in M04 production cleanup (see ADR-040 Status: Accepted 2026-05-15 and 08-promote-artifacts.md).`

## Verify

```bash
# Pattern checks — none of these should match
grep -nE "Spike in progress|TO BE FILLED IN" docs/adr/040-ibkr-gateway-sidecar.md
# Expected output: (empty)

# The duplicate Consequences header check
grep -c "^## Consequences" docs/adr/040-ibkr-gateway-sidecar.md
# Expected output: 1

# Status line check
grep "^\*\*Status:\*\*" docs/adr/040-ibkr-gateway-sidecar.md
# Expected output: **Status:** Accepted (2026-05-15 — see Findings)
```

If all three checks pass, ADR-040 is in its final accepted state.

## FALLBACK

If a section feels incoherent after edits (e.g., the Findings flow doesn't read well end-to-end), do a top-to-bottom prose read and rewrite. The ADR should tell the future reader a complete story: what was being decided, how it was tested, what was found, what was decided, what trade-offs were accepted.

## NEXT

Read `08-promote-artifacts.md`.
