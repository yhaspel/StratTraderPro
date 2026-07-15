# 01 — Recover the `ib-gateway` container

**Goal.** Ensure `ib-gateway` is running and IBC has finished login. This is the precondition for every subsequent file.

## Context

A prior debug step ran `pkill -TERM -f "ibcalpha.ibc.IbcGateway"` inside the container, which killed the Java Gateway. IBC tried to autorestart, failed (no autorestart token), and exited. Container logs ended with `IBC returned exit status 143` / `Gateway finished`. The container may be Exited or in a degraded state.

## Steps

```bash
# 1. Check container state
docker compose ps ib-gateway

# 2. Bring it back regardless of current state — idempotent
docker compose --profile ibkr-spike down
docker compose --profile ibkr-spike up -d ib-gateway

# 3. Wait for IBC to log in. Don't proceed until you see "Login has completed".
#    Cold start can take 60–120s on first build; subsequent boots ~30–60s.
timeout 180 bash -c '
  while ! docker compose logs --tail=200 ib-gateway 2>/dev/null | grep -q "Login has completed"; do
    sleep 3
  done
'

# 4. Sanity-check the listening port from the host
nc -zv localhost 4002
```

## Verify

- `docker compose ps ib-gateway` shows the service as `Up` / running.
- `docker compose logs --tail=80 ib-gateway` ends with IBC successfully reaching the API tab configuration (last lines should mention `Configuration tasks completed` or `Pending Tasks; event=Closed`).
- `nc -zv localhost 4002` prints `Connection succeeded`.

If all three pass, the container is recovered. Proceed.

## Fallback

If step 3 times out (180s elapsed and `Login has completed` never appears):

1. Check `docker compose logs --tail=200 ib-gateway` for an explicit error.
2. If credentials look wrong (`Login failed`), confirm `.env` has the right `TWS_USERID` / `TWS_PASSWORD` for the paper account. The compose substitution requires `.env` to live at the **repo root**, not inside `backend/`.
3. If the dialog `"Existing session detected"` is mentioned and there's no follow-up action, verify `EXISTING_SESSION_DETECTED_ACTION=primary` is set in `docker-compose.yml` for the `ib-gateway` service. If missing, add it, then `docker compose down && up -d`.
4. If `Login failed` with auth error, the paper account may need a one-time web login at <https://www.interactivebrokers.com/sso/Login> to clear an IBKR-side pending task. After web login, retry from step 1.

Note any new failure mode in memory before moving on.

## NEXT

Read `02-diagnose-config-render.md`.
