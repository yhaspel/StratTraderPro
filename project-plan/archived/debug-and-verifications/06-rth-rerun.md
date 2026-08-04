# 06 — RTH rerun: verify STEPS 4 and 5

**Goal.** Capture a real fill (STEP 4) and verify clientId reconnect (STEP 5) of the smoke test during US Regular Trading Hours. This closes the last two open assumptions in ADR-040.

## When to run

US RTH: 09:30–16:00 ET. In Israel time (Asia/Jerusalem, UTC+3 in summer): **16:30–23:00 IST, Mon–Fri**.

If the current time is outside this window, do not run. Instead, leave a note in memory with the next window's date+time, mark the task as "pending RTH", and stop progressing through these files until RTH opens.

```bash
# Quick check — is the current Israel-local time within RTH?
TZ=Asia/Jerusalem date '+%a %H:%M'
# If output is Mon-Fri and hour is between 16 and 23 (and 16:30+ for the start), proceed.
# Otherwise, halt this file. AC-04-7 cannot be verified outside this window.
```

## Steps

```bash
# 1. Reconfirm config + container health
./scripts/verify_ibgw_config.sh
docker compose ps ib-gateway

# 2. Use a fresh clientId
CLIENT_ID=201

# 3. Run the full smoke
python scripts/spike_ibkr_smoke.py --host localhost --port 4002 --client-id $CLIENT_ID 2>&1 | tee /tmp/smoke-rth-$(date +%Y%m%d-%H%M%S).log

# 4. Check exit code
echo "RTH smoke exit code: $?"
```

## Verify

Inspect the smoke log's `SPIKE RESULT` block. **Expected:**

```
============================================================
SPIKE RESULT — copy this into the ADR's Findings section
============================================================
  cold_start_seconds        = <small>
  connect_ok                = True
  account_summary_keys      = <NN>
  broker_order_id           = <NN>
  order_status_after_place  = Filled
  fill_count                = 1
  fill_price                = <NN.NN>
  reconnect_ok              = True
============================================================
ALL STEPS PASSED — assumptions 1-3 proven for this topology.
```

Exit code 0. All five assertions of ADR-040 are now empirically verified.

Save this block — it's the input to `07-update-adr-040.md`.

## FALLBACK

- **`fill_count=0` despite RTH.** The order was accepted but didn't fill in 60s. Possible reasons:
  - Symbol halted or low-volume at the moment. Re-run; if persistent, try a different liquid symbol by editing `scripts/spike_ibkr_smoke.py` (search for `Stock("AAPL"` and change).
  - Order is `PreSubmitted` but routing took >60s. Increase the fill deadline in the script from 60 to 120s and re-run.
- **`reconnect_ok=False`.** Gateway didn't release clientId on disconnect. Re-run with different `--client-id`; if that works, document the workaround in ADR-040 Findings: "broker adapter must rotate clientIds across reconnects". If even a fresh clientId fails, the Gateway crashed on disconnect — capture container logs and treat as a real A3 failure (rare but possible).
- **`order_status_after_place=Cancelled`.** IBKR rejected the order. Capture the exact rejection reason from container logs (`docker compose logs --tail=200 ib-gateway | grep -iE "reject|cancel|error"`) and document in ADR-040 as a constraint for the production adapter.

## NEXT

Read `07-update-adr-040.md`.
