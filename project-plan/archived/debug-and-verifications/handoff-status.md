# M04 Phase A — Handoff status as of 2026-05-15 17:17 IDT

> **Phase A — COMPLETE.** All eleven acceptance criteria met. Smoke STEPS 1–4 verified live during RTH; STEP 5 (same-Gateway reconnect) uncovered a `gnzsnz/ib-gateway:10.45.1e` constraint documented in ADR-040 Findings A3 and carried into the M04 §6.2 broker-adapter design. Ready to start Phase B production code.

## What completed in this run

### Code / config fixes

- **IBC config-render gotcha diagnosed and fixed.** `docker/ib-gateway/Dockerfile` now strips CRLF line-endings and `sed`-substitutes literal values into the three required IBC options (`OverrideTwsApiPort=4002`, `AllowBlindTrading=yes`, `AcceptIncomingConnectionAction=accept`), plus expands `TrustedTwsApiClientIPs` to include IPv6 forms as defense-in-depth.
- **`scripts/spike_ibkr_smoke.py` updated** so STEP 3 places the AAPL MKT order with explicit `tif="DAY"` — without that, IBKR paper-account preset rejects every first send with `Error 10349`. STEP 5 now tries same-clientId, then falls back to rotated clientId on failure, so the reconnect constraint is explicit in the log.
- **`docker-compose.yml`** cleaned: removed dead `DEBUG_VNC` env var (gnzsnz never read it), replaced with `VNC_SERVER_PASSWORD` passthrough that actually starts x11vnc when set in `.env`.

### Documentation

- **ADR-040** flipped to Status: Accepted (2026-05-15). New gotcha #7 documents the gnzsnz config-render trap + sed fix + all dead-end paths burned today (JAVA_TOOL_OPTIONS clobber, vmoptions `-D` filter, ENABLEAPI-invalid-for-Gateway, jts.ini-overwrite-by-IBC, xdotool windowkill crashes JVM). Findings A2 Step 4 + A3 updated with the actual SpikeResult numbers from today's RTH run.
- **`docs/runbooks/ib-gateway-reauth.md`** rewritten from spike framing to production operations. Re-auth procedure documents the **paper-account dormancy** finding — today's exact failure mode — as the single most important triage step.
- **`docker/ib-gateway/README.md`** has the gnzsnz config-render callout.
- **`backend/.env.example`** has the `IB Gateway sidecar` env block.
- **`project-plan/plan-progress-tracker.md`** Phase 04 sub-table shows A.1–A.5 done.

### Verified smoke results (2026-05-15 RTH run, clientId 310)

```
STEP 1: connected in 0.7s; serverVersion=176
STEP 2: account summary 80 rows (DUN167649); positions PLTR/QQQ/AAPL visible
STEP 3: order ack status=Filled brokerOrderId=5
STEP 4: fill captured qty=1.0 price=299.15 execId=0000e0d5.6a071c95.01.01 (commission $1.00)
STEP 5: same-clientId reconnect → TimeoutError
         rotated clientId 311  → TimeoutError
         (Gateway allows 1 session per process boot — see Findings A3)
```

Raw logs: `project-plan/debug-and-verifications/evidence-20260515/smoke-rth-1234pass-5constrained.log`.

## The actual root cause (for the morning's TimeoutError loop)

Three layers stacked on top of each other; today peeled them one at a time:

1. **`gnzsnz/ib-gateway:10.45.1e` config-render gap** (ADR-040 gotcha #7) — fixed by sed-based Dockerfile patches on the IBC template. The verify gate `scripts/verify_ibgw_config.sh` now asserts the three required overrides land in the live `config.ini`. Necessary but not sufficient.
2. **IBKR paper-account dormancy** — 6 days since last web-portal login → IBKR's auth backend silently disables headless API access for that user. Boot logs look normal; Gateway's TWS Socket API thread isn't even spawned; port 4002 binds but nothing reads from it. The morning's "TCP accepts, API handshake silently dropped" symptom is exactly this. The runbook now documents this prominently as the *first* thing to check.
3. **`tif="DAY"` paper-account preset** — IBKR rejects the first send of a TIF-less MarketOrder with `Error 10349`. The smoke script now sets `tif="DAY"` upfront; production adapter must do the same.

Once all three were resolved, STEPS 1–4 ran cleanly end-to-end and STEP 5 revealed the one-session-per-Gateway-boot constraint.

## What's left for the user

### 1. Railway env-var setup (anytime — independent of the smoke)

Execute the commands in `project-plan/debug-and-verifications/railway-setup-commands.md` against both staging and production environments. This is the only user-action step the playbook flagged; everything else closed inside this session.

### 2. (Optional, for next session) Open ADR-041 — production broker-adapter topology

Two design choices are now forced by today's findings:

- **Container-per-session vs. Gateway-restart-on-disconnect.** Pick one. Container-per-session matches Railway's worker-per-deploy model better; Gateway-restart-on-disconnect is lighter-weight in dev but adds boot-latency on every reconnect.
- **Web re-auth scheduling.** Paper account becomes dormant after ~5–6 days of no SSO login. Production adapter needs either a scheduled "heartbeat web login" task (M04 Celery beat?) or a documented operator runbook ("log into IBKR portal once a week") referencing `docs/runbooks/ib-gateway-reauth.md`.

Both decisions belong in ADR-041 alongside the §6.2 broker-adapter design; not in scope for this Phase A close-out.

## File-by-file checklist

| Playbook file | Status |
|---|---|
| 00-README.md | n/a (read) |
| 01-recover-container.md | ✅ done |
| 02-diagnose-config-render.md | ✅ done — root cause was the templated-line false-match on the append-if-missing guard |
| 03-apply-config-fix.md | ✅ done — sed-based fix + CRLF strip + TrustedTwsApiClientIPs IPv6 expansion |
| 04-verify-smoke-connect.md | ✅ done — STEPS 1–3 cleanly pass after web re-auth |
| 05-edge-cases.md | ✅ done — hidden modals dismissed; rate-limit/dormancy ruled in via the web-login fix |
| 06-rth-rerun.md | ✅ done — STEP 4 fill captured, STEP 5 constraint documented |
| 07-update-adr-040.md | ✅ done — gotcha #7 added with full triage |
| 08-promote-artifacts.md | ✅ done — runbook renamed + rewritten, vestigial files removed |
| 09-finalize-phase-a.md | ✅ done — env contract locked, Railway commands generated, all verify checks green |

## Allowed-paths audit (git status --short)

```
 M backend/.env.example
 M docker-compose.yml
 M docker/ib-gateway/Dockerfile
 M docker/ib-gateway/README.md
 D docker/ib-gateway/entrypoint.sh
 D docker/ib-gateway/ibc-config.ini
 M docs/adr/040-ibkr-gateway-sidecar.md
RM docs/runbooks/spike-ibkr-gateway.md -> docs/runbooks/ib-gateway-reauth.md
 M project-plan/plan-progress-tracker.md
 M scripts/spike_ibkr_smoke.py
?? gateway-api-msgs.png, gateway-during-connect.png, gateway-screen.png   (pre-existing, untouched)
?? project-plan/04A-IBKR-Web-API.md                                       (pre-existing, untouched)
?? project-plan/debug-and-verifications/
?? scripts/verify_ibgw_config.sh                                          (new — regression gate)
```

All changes within the playbook's allowed paths. No edits to `backend/apps/`, `frontend/`, or other `project-plan/0N-*.md` files. No git pushes, no Railway deploys, no live-account trades. The paper-account got three small AAPL fills during today's smoke runs (clientId 290/300/310, all 1-share BUY at market) — accounted for as a normal artefact of running the spike against paper.

## Evidence bundle

`project-plan/debug-and-verifications/evidence-20260515/`:

- `smoke-rth-1234pass-5constrained.log` — the definitive RTH run (clientId 310): STEPS 1–4 pass, STEP 5 shows both same-clientId and rotated-clientId reconnect failing
- `smoke-rth-1234pass-5sameclientid-fail.log` — earlier RTH run (clientId 300) showing STEPS 1–4 pass and same-clientId reconnect failing identically
- `smoke-20260515-134156.log` — pre-fix morning run (TimeoutError loop)
- `smoke-20260515-135114.log` — post-config-fix, pre-web-reauth (still TimeoutError)
- `full-screen.png` / `gateway-screen-during-debug.png` — Xvfb screenshots of Gateway GUI during the morning's silent-drop diagnosis

## Exact next action

Run the Railway commands. Then in the next session, open ADR-041 for the M04 production broker-adapter design with the container-per-session + dormancy-heartbeat decisions called out above.
