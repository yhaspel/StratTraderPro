# 09 — Finalize Phase A (A.4 + A.5 + A.6)

**Goal.** Lock the production env-var contract, update the progress tracker so future sessions know Phase A is done, and run a final verification pass.

## 9.1 — Lock the production env-var contract (Task A.4)

`docker-compose.yml`'s `ib-gateway` service has the full env contract baked in (verified earlier in this debug loop). The remaining work is the Railway side + the example file.

### 9.1.a — `backend/.env.example` documents the contract

```bash
# Read the file first
cat backend/.env.example | head -40

# Add a block describing the ib-gateway env vars users need to set locally.
# If a block already exists referencing TWS_USERID/TWS_PASSWORD, just add a comment
# pointing at docker-compose.yml + ADR-040 for the full contract.
```

The block to add (Edit, don't overwrite):

```bash
# ─── IB Gateway sidecar (spike profile: docker compose --profile ibkr-spike up) ───
# Paper credentials for the IBKR account used by the sidecar.
# The full env contract for the sidecar lives in docker-compose.yml's ib-gateway
# service definition (TWS_ACCEPT_INCOMING, READ_ONLY_API, etc.). See ADR-040
# Decision section for what each variable does. The IBC config overrides for
# gnzsnz 10.45.1e are baked into docker/ib-gateway/Dockerfile, not env-driven.
TWS_USERID=
TWS_PASSWORD=
# Optional — set to 1 to expose the Gateway GUI via VNC on localhost:5900
DEBUG_VNC=0
# Optional — set if your locale isn't Asia/Jerusalem
# TIME_ZONE=Asia/Jerusalem
```

### 9.1.b — Railway service setup

Railway side has two services: `ib-gateway-staging` and `ib-gateway-production` (if they exist; if not, this is a one-time setup).

This is a **manual user step** — Claude Code can't set Railway env vars on the user's behalf. Generate the commands the user will need to run, save them to `project-plan/debug-and-verifications/railway-setup-commands.md`, and have the user execute them outside this loop.

```bash
cat > project-plan/debug-and-verifications/railway-setup-commands.md << 'EOF'
# Railway setup commands for the ib-gateway service

Run these against both staging and production environments. For each env,
the Railway service should be named `ib-gateway`.

```bash
# Switch to the right Railway environment first
railway environment <staging | production>

# Set all required env vars (replace <PAPER_USER> / <PAPER_PASS>)
railway variables \
  --service ib-gateway \
  --set "TWS_USERID=<PAPER_USER>" \
  --set "TWS_PASSWORD=<PAPER_PASS>" \
  --set "TRADING_MODE=paper" \
  --set "READ_ONLY_API=no" \
  --set "BYPASS_WARNING=yes" \
  --set "TWS_ACCEPT_INCOMING=accept" \
  --set "RELOGIN_AFTER_TWOFA_TIMEOUT=yes" \
  --set "EXISTING_SESSION_DETECTED_ACTION=primary" \
  --set "TIME_ZONE=Asia/Jerusalem"

# Verify
railway variables --service ib-gateway | grep -E "TWS_|TRADING_|READ_ONLY|BYPASS|EXISTING_SESSION|TIME_ZONE"

# Redeploy so the new env takes effect
railway up --service ib-gateway
```

Note: Railway environment variable management may differ if you're using
the Railway Web UI rather than CLI. Either way the variable names and
values are the same.
EOF
```

## 9.2 — Update the progress tracker (Task A.5)

Edit `project-plan/plan-progress-tracker.md`. Find the Phase 04 section (currently reads `**Status:** ⏳ Pending`) and update it.

```bash
grep -n "^## Phase 04" project-plan/plan-progress-tracker.md
# Get the line number, then use Edit to update the block below it.
```

Target end-state for the Phase 04 section:

```markdown
## Phase 04 — Webhook Ingest & IBKR

**Status:** 🚧 In Progress (Phase A — spike close-out complete; Phase B–F production code pending)
**Started:** 2026-05-09
**Completed:** —

> See `04-webhook-ingest-and-ibkr.md` for full spec.
> Debug loop for Day-1 spike close-out: `project-plan/debug-and-verifications/`.

### Phase A — Spike close-out (Day 1)

| # | Sub-task | Status | Notes |
|---|---|---|---|
| 04.A.1 | IB Gateway sidecar smoke test (STEPS 1-3, connect+place) | ✅ Done | Pre-RTH verify pass against gnzsnz/ib-gateway:10.45.1e (see ADR-040 Findings). |
| 04.A.2 | RTH rerun (STEPS 4+5, fill+reconnect) | ✅ Done | [or 📅 Scheduled for next RTH window if not run yet — fill in the date and reference 06-rth-rerun.md] |
| 04.A.3 | ADR-040 finalized (Accepted) | ✅ Done | gnzsnz config-render gotcha captured as gotcha #7. |
| 04.A.4 | Spike artifacts promoted | ✅ Done | Runbook renamed `ib-gateway-reauth.md`. Vestigial files removed. CI gate: `scripts/verify_ibgw_config.sh`. |
| 04.A.5 | Production env contract locked | ✅ Done | `docker-compose.yml` + `backend/.env.example` updated. Railway commands in `project-plan/debug-and-verifications/railway-setup-commands.md`. |

### Phase B–F — Production code (pending)

Following M04 plan §6.1–§6.8 + §10–§14. Not yet started.

---
```

## 9.3 — Final verification (Task A.6)

```bash
# 1. All spike artifacts are in their expected state
./scripts/verify_ibgw_config.sh
ls docker/ib-gateway/Dockerfile docker/ib-gateway/README.md
ls docs/runbooks/ib-gateway-reauth.md
ls scripts/spike_ibkr_smoke.py scripts/verify_ibgw_config.sh

# 2. ADR-040 is coherent
grep -nE "Spike in progress|TO BE FILLED IN" docs/adr/040-ibkr-gateway-sidecar.md
# Expected: empty
grep -c "^## Consequences" docs/adr/040-ibkr-gateway-sidecar.md
# Expected: 1

# 3. Vestigial files gone
ls docker/ib-gateway/entrypoint.sh docker/ib-gateway/ibc-config.ini 2>&1 | grep "No such file"

# 4. Progress tracker reflects Phase A done
grep -A 5 "^## Phase 04" project-plan/plan-progress-tracker.md
# Expected: Status shows "In Progress", not "Pending"

# 5. Tasks reflect completion. Use the TodoWrite/TaskUpdate tool to mark:
#    A.1, A.1a (already), A.1b — completed
#    A.2 (ADR update) — completed
#    A.3, A.3a (already) — completed
#    A.4 (Railway commands generated, user-action remaining) — completed (note: user-action pending)
#    A.5 — completed
#    A.6 — completed (this is THIS task)

# 6. Memory captures the gnzsnz gotcha for future sessions
#    Save a new memory of type 'reference' titled "gnzsnz/ib-gateway IBC config gotcha"
#    Body: gnzsnz/ib-gateway:10.45.1e omits AcceptIncomingConnectionAction from its
#    IBC render. Fix: docker/ib-gateway/Dockerfile patches the template / Entry shim.
#    Verify: scripts/verify_ibgw_config.sh.
#    Why this matters: future tag bumps must re-verify post-build.
#    How to apply: when bumping the gnzsnz tag, always run the verify script after
#    rebuild; if it fails, follow project-plan/debug-and-verifications/02-... +03-...
#    Add a pointer to MEMORY.md.

# 7. git status — only Phase-A-relevant files should be modified
git status --short
# Expected files (any subset, plus the project-plan/debug-and-verifications/ folder):
#   docker/ib-gateway/Dockerfile
#   docker/ib-gateway/README.md
#   docker/ib-gateway/overrides/append-overrides.sh           (if Path C.1 was used)
#   docker-compose.yml                                        (already edited earlier)
#   docs/adr/040-ibkr-gateway-sidecar.md
#   docs/runbooks/spike-ibkr-gateway.md → ib-gateway-reauth.md  (rename)
#   scripts/spike_ibkr_smoke.py                               (docstring update)
#   scripts/verify_ibgw_config.sh                             (new file)
#   project-plan/plan-progress-tracker.md
#   project-plan/debug-and-verifications/*.md                 (this whole folder)
#   backend/.env.example                                      (block added)
# Deleted: docker/ib-gateway/entrypoint.sh, docker/ib-gateway/ibc-config.ini

# 8. NOT modified (do NOT commit changes to these):
#   backend/apps/                  (Phase B's domain)
#   frontend/                      (Phase C's domain)
#   project-plan/04*.md            (Phase plan files — only progress tracker is for tracking)
git diff --stat backend/apps frontend project-plan/04-webhook-ingest-and-ibkr.md project-plan/04A-IBKR-Web-API.md
# Expected: empty
```

## Verify

All 8 checks above pass. If any fail, return to the corresponding earlier file and complete the missing step.

## FALLBACK

If after a full pass any check still fails, write the residual state to `project-plan/debug-and-verifications/handoff-status.md` so the user can review at next session:

```bash
cat > project-plan/debug-and-verifications/handoff-status.md << EOF
# M04 Phase A — Handoff status as of $(date -u +%FT%TZ)

## Completed

[list with file references]

## Not completed

[list with reason for blocker]

## Suggested next action

[concrete next command for the user]
EOF
```

## NEXT

Phase A is done. M04 Phase B begins with `project-plan/04-webhook-ingest-and-ibkr.md` §6.1 (BrokerAdapter Protocol + FakeBrokerAdapter). That's outside this debug loop.

End of playbook.
