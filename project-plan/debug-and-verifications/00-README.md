# M04 Phase A — Debug & Verification Playbook

**Purpose.** Drive the M04 Day-1 IBKR spike close-out to completion in a self-directed loop, without round-trip clarifications. An autonomous coding agent reads these files in order, executes each step, observes the output, and pivots based on the decision points encoded in each file.

**Target outcome.** ADR-040 flips to **Accepted**, with all four assumptions (A1–A4) verified end-to-end against a working IB Gateway sidecar. Specifically:

- Smoke test STEP 1–3 (connect, account read, place order) pass against `localhost:4002`.
- Smoke test STEP 4 (real fill capture) passes during US RTH (16:30–23:00 Israel time, Mon–Fri).
- Smoke test STEP 5 (reconnect on same clientId) passes.
- ADR-040 Findings + Decision + Consequences sections are coherent and complete (currently has duplicate Consequences header and two `TO BE FILLED IN` markers).
- A regression-proof IBC config fix is in the Dockerfile, with a CI/runbook check that asserts it stays applied.

**Current state at handoff.** Day-1 spike was started 2026-05-09; today's rerun (2026-05-15) revealed that `gnzsnz/ib-gateway:10.45.1e`'s IBC config template is missing `AcceptIncomingConnectionAction=accept` and related options, causing every API client connection to time out at the protocol handshake. A Dockerfile patch was attempted that appends the missing options to `/home/ibgateway/ibc/config.ini.tmpl`, plus a verify script at `scripts/verify_ibgw_config.sh`. The verify script reports the live `config.ini` still lacks the three required overrides after rebuild + recreate — root cause not yet pinned. Container may currently be in a "Gateway finished" state from a prior `pkill` test; recovery is the first step.

**File order.** Files are numbered. Execute in order, top to bottom. Each file has a `NEXT` section at the bottom that tells the agent which file to read next based on the outcome.

```
00-README.md                  ← you are here
01-recover-container.md       ← bring gateway back from dead state if needed
02-diagnose-config-render.md  ← find why the Dockerfile patch didn't take effect
03-apply-config-fix.md        ← apply the correct fix based on the diagnosis
04-verify-smoke-connect.md    ← smoke STEP 1–3 must pass (pre-RTH safe)
05-edge-cases.md              ← fallbacks: rate limit, hidden modal, off-screen dialog
06-rth-rerun.md               ← RTH-window verification for STEP 4 + 5
07-update-adr-040.md          ← fold findings into ADR-040, flip Status=Accepted
08-promote-artifacts.md       ← A.3 — clean up vestigial spike files, rename runbook
09-finalize-phase-a.md        ← A.4 + A.5 + A.6 — env contract, tracker, verification
```

**Operating rules for the agent.**

1. **Stay in iteration loops within a file** — if a step fails, the file's `FALLBACK` section tells you what to try next. Only advance to the next file when this file's success criteria are met.
2. **Commit findings to memory** as you learn them. New gnzsnz gotchas, new IBC option semantics, dead-end paths all belong in memory so a future session doesn't repeat the loop.
3. **Don't introduce new approaches not in these files** without first updating the corresponding file. The file is the contract; if it's wrong, fix it, then proceed.
4. **Time-of-day matters.** STEP 4 (fill capture) requires US RTH (16:30–23:00 Israel time, Mon–Fri). Pre-RTH runs will exit code 4 with `fill_count=0`; that's not a failure, it just means the RTH rerun (file `06-rth-rerun.md`) hasn't happened yet.
5. **Rate-limit awareness.** Today's debugging has already burned ~50 failed `ib_insync.connect` attempts against the paper account. IBKR sometimes throttles paper accounts after rapid failed handshakes; if all configured fixes are in place and connects still fail, treat as suspected rate-limit (see `05-edge-cases.md`) — cooldown is typically 1–4 hours.
6. **Don't touch production code (`backend/`, `frontend/`) in this loop.** Phase A is strictly about the spike artifacts (`docker/ib-gateway/`, `scripts/spike_ibkr_smoke.py`, `docker-compose.yml`, `docs/adr/040-ibkr-gateway-sidecar.md`, `docs/runbooks/`, `project-plan/plan-progress-tracker.md`).
7. **Update the existing task list** (TodoWrite) as you transition between files. The current task IDs and their status are listed in `09-finalize-phase-a.md`.

**Success criteria — overall.**

- [ ] `./scripts/verify_ibgw_config.sh` exits 0 (live `config.ini` has all three required overrides).
- [ ] `python scripts/spike_ibkr_smoke.py --host localhost --port 4002 --client-id <N>` exits 0 during US RTH (all five steps pass).
- [ ] ADR-040 Status flipped to `Accepted`, both Consequences sections coherent, no `TO BE FILLED IN` placeholders remaining.
- [ ] Spike runbook renamed `docs/runbooks/ib-gateway-reauth.md` and rewritten for production topology.
- [ ] Vestigial spike files removed (`docker/ib-gateway/entrypoint.sh`, `docker/ib-gateway/ibc-config.ini`).
- [ ] `project-plan/plan-progress-tracker.md` Phase 04 section reflects current state (no longer just "⏳ Pending").
- [ ] Memory updated with the gnzsnz-config-render gotcha and any other learnings.
- [ ] No regressions: `git status` shows only Phase-A-related files modified.

**NEXT.** Read `01-recover-container.md`.
