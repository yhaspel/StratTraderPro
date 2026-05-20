# 04 — Verify the smoke test connects (STEPS 1–3)

**Goal.** Confirm the config fix actually fixes the bug — `ib_insync` now connects, reads the account, and places an order without a TimeoutError.

This file is the validation gate that proves the diagnosis in `02-diagnose-config-render.md` and the fix in `03-apply-config-fix.md` are correct.

## Context

Pre-fix symptom: smoke STEP 1 (`connect`) failed with `API connection failed: TimeoutError()` after 10s, looping for 180s. ~50 such failed attempts have happened today across multiple clientIds.

Post-fix expectation: STEP 1 completes in under 1 second. STEP 2 (`accountSummary`) returns dozens of rows. STEP 3 (`placeOrder`) returns an ack with `status=PreSubmitted` or `Filled`.

STEP 4 (fill capture) will exit code 4 if it's before US RTH (16:30 IST). That's expected and **does not mean the fix is broken**.

## Steps

```bash
# 1. Confirm the verify gate still passes (config didn't drift)
./scripts/verify_ibgw_config.sh

# 2. Use a clientId that has not been used in any prior failed attempt today.
#    Today's burned clientIds: 7, 23, 31. Use something high.
CLIENT_ID=91

# 3. Run the smoke
python scripts/spike_ibkr_smoke.py --host localhost --port 4002 --client-id $CLIENT_ID 2>&1 | tee /tmp/smoke-$(date +%Y%m%d-%H%M%S).log

# 4. Inspect exit code
echo "Smoke exit code: $?"
```

## Verify

Examine the smoke log. Three possible outcomes:

### Outcome A — STEP 1–3 pass, STEP 4 times out (fill_count=0)

```
STEP 1: connect to localhost:4002 clientId=91
connected in <1s
STEP 2: read account summary
account summary: NN rows
STEP 3: place 1-share AAPL MKT (paper)
order ack: status=PreSubmitted brokerOrderId=NN
STEP 4: wait for fill (60s timeout — outside RTH this will time out)
STEP 4 NO-FILL: order accepted but no fill in 60s.
```

Exit code 4. **This is the success state for pre-RTH.** The connect + place path is proven. STEP 4 + STEP 5 are deferred to `06-rth-rerun.md`.

Note in memory: `Saturday 2026-05-09's spike STEP-3 caveat (IBKR error 10349 + TIF=DAY auto-resubmit) needs to land in the M04 production adapter. STEP 3 today's behavior either confirms or refines that requirement.`

Proceed.

### Outcome B — All five steps pass

`fill_count=1`, `reconnect_ok=True`, exit code 0.

You're running during US RTH. Excellent — `06-rth-rerun.md` is effectively pre-completed; just note that the rerun result was captured here. Skip 06 and proceed to `07-update-adr-040.md`.

### Outcome C — STEP 1 still fails with TimeoutError

The config fix didn't fix the underlying bug. Possible reasons:

1. **Verify script reports OK but the live config genuinely doesn't have effective overrides.** Re-inspect with: `docker compose exec ib-gateway grep -E "AcceptIncoming|AllowBlind|OverrideTws" /home/ibgateway/ibc/config.ini`. If lines are present but ineffective, IBC didn't reload them — recreate the container.
2. **IBKR-side rate limit.** Today's ~50 failed connects may have triggered a paper-account API cooldown. See `05-edge-cases.md` § rate-limit.
3. **Hidden modal off-screen.** Despite the config fix, there could be a queued dialog blocking the API thread. See `05-edge-cases.md` § hidden-modal.

Proceed to `05-edge-cases.md` carrying which sub-cause you suspect.

## Verify (acceptance)

For this file's contract: smoke STEPS 1–3 pass. If you got Outcome A, this file is complete and pre-RTH gate is closed. If Outcome B, this file plus 06 are both complete. If Outcome C, this file is **not** complete — debug via 05 and return.

## FALLBACK

If Outcome C and 05 doesn't resolve it either, document the persistent symptom in memory with full evidence (smoke log + container logs + config dump) and re-read 02 with fresh eyes. The diagnosis may have been wrong; a deeper rethink is warranted before further code changes.

## NEXT

- Outcome A → `06-rth-rerun.md` (do this during US RTH, then continue to 07).
- Outcome B → `07-update-adr-040.md`.
- Outcome C → `05-edge-cases.md`.
