# 05 — Edge cases when STEP 1 still fails after the config fix

**Goal.** Resolve the residual `TimeoutError` if `04-verify-smoke-connect.md` produced Outcome C.

Three known edge cases, ordered by likelihood given today's history.

## § Hidden modal off-screen (most likely after config fix)

Even with `AcceptIncomingConnectionAction=accept` and `AllowBlindTrading=yes` in place, a different dialog (e.g., "Pending Tasks", "Password Expires", "Accept New Terms", "Reauthenticate") may have appeared and been auto-dismissed at boot but is still queued, or has reopened. The IBC log entry `Pending Tasks; event=Closed` (without a preceding `event=Opened`) is a tell — IBC noticed a dialog closing but didn't open it itself.

```bash
# List ALL X windows currently in the Xvfb display, including off-screen ones
docker compose exec ib-gateway sh -c '
  export DISPLAY=:1
  if ! command -v xdotool >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq xdotool >/dev/null 2>&1
  fi
  echo "=== All windows ==="
  xdotool search --onlyvisible "" 2>/dev/null | while read wid; do
    name=$(xdotool getwindowname $wid 2>/dev/null)
    geom=$(xdotool getwindowgeometry $wid 2>/dev/null | grep -oE "Geometry: [0-9]+x[0-9]+|Position: [0-9-]+,[0-9-]+")
    echo "wid=$wid name=\"$name\""
    echo "  $geom"
  done
'

# Take a screenshot of the full Xvfb display so off-screen dialogs are caught
docker compose exec --user root ib-gateway sh -c '
  command -v import >/dev/null 2>&1 || apt-get install -y -qq imagemagick >/dev/null 2>&1
  su ibgateway -c "DISPLAY=:1 import -window root /tmp/full-screen.png" 2>&1
  ls -la /tmp/full-screen.png
'
docker compose cp ib-gateway:/tmp/full-screen.png ./debug-fullscreen-$(date +%H%M%S).png
```

If `xdotool` lists windows beyond the main IBKR Gateway window (e.g., a window with `Pending Tasks`, `Warning`, `Reauthenticate`, or `Login` in its name):

```bash
# Dismiss the offending dialog by name
docker compose exec ib-gateway sh -c '
  export DISPLAY=:1
  WIN_NAME="Pending Tasks"   # or whatever you found
  WID=$(xdotool search --name "$WIN_NAME" 2>/dev/null | head -1)
  if [ -n "$WID" ]; then
    xdotool windowactivate $WID
    xdotool key Return     # try Enter first
    sleep 1
    xdotool key Escape     # then Escape if Enter didn't close it
    echo "Dismissed $WIN_NAME"
  fi
'

# Re-run the smoke
python scripts/spike_ibkr_smoke.py --host localhost --port 4002 --client-id 92
```

If a specific dialog was the cause, add it to IBC's auto-dismiss config by extending `docker/ib-gateway/overrides/append-overrides.sh` (or the .tmpl patch) with the appropriate IBC option. Reference: <https://github.com/IbcAlpha/IBC/blob/master/userguide.md> — search for `Accept...` and `Bypass...` options.

## § IBKR-side rate limit on the paper account

Symptom: STEP 1 still fails identically even after config is verified, no off-screen dialogs, and the same setup worked Saturday. Possible cause: paper-account API connect attempts have been throttled server-side after today's many failed handshakes.

**Cooldown is typically 1–4 hours.** If you suspect this:

```bash
# Confirm by trying a completely cold start: stop the container, wait 30 minutes, then retry.
docker compose --profile ibkr-spike down
echo "Started cooldown at $(date)" | tee /tmp/cooldown-start.log
# Wait at least 30 minutes (longer is safer).
# Then resume:
docker compose --profile ibkr-spike up -d ib-gateway
timeout 180 bash -c 'while ! docker compose logs --tail=200 ib-gateway 2>/dev/null | grep -q "Login has completed"; do sleep 3; done'
python scripts/spike_ibkr_smoke.py --host localhost --port 4002 --client-id 101
```

If cooldown clears it, document in memory: `IBKR paper account API rate-limits after ~50 failed connects; cooldown ~30 min observed`. Add to ADR-040 §16 risks.

If 4 hours of cooldown doesn't clear it, rate-limit isn't the cause.

## § The fix really didn't take effect

Re-verify from scratch:

```bash
docker compose exec ib-gateway grep -E "AcceptIncoming|AllowBlind|OverrideTws" /home/ibgateway/ibc/config.ini
docker compose exec ib-gateway ls -la /home/ibgateway/ibc/config.ini
docker compose exec ib-gateway sh -c 'stat -c "%y" /home/ibgateway/ibc/config.ini && stat -c "%y" /home/ibgateway/ibc/config.ini.tmpl'
```

If the live config.ini's mtime is *older* than container start, the live file was rendered before our background patcher ran. Force-recreate:

```bash
docker compose --profile ibkr-spike down
docker compose --profile ibkr-spike up -d --force-recreate ib-gateway
sleep 30  # allow the patcher to fire
./scripts/verify_ibgw_config.sh
```

If verify fails, return to `02-diagnose-config-render.md` — the diagnosis is wrong.

## Verify

The residual `TimeoutError` is gone. STEP 1 in the smoke test completes in <1s and the script proceeds to STEP 2.

## FALLBACK

If after exhausting all three sections, STEP 1 still TimeoutErrors:

1. Capture an exhaustive evidence bundle to `project-plan/debug-and-verifications/evidence-$(date +%Y%m%d-%H%M).tar.gz`:
   - Full `docker compose logs ib-gateway` (from container start)
   - Full `docker compose exec ib-gateway cat /home/ibgateway/ibc/config.ini`
   - Full `docker compose exec ib-gateway cat /home/ibgateway/Jts/jts.ini`
   - All `docker compose exec ib-gateway find /home/ibgateway/Jts -name '*.log' -exec cat {} \;`
   - The most recent smoke log
   - Screenshot of the Gateway window
2. Stop further changes. Update memory: `M04 Day-1 spike: gateway path blocked by [the specific persistent symptom]. Escalating: either fall back to extrange/ibkr-docker base image, OR pivot directly to M04A OAuth migration (which doesn't need a gateway at all).`
3. Stop progressing through files. Surface to the user: a strategic decision is needed.

## NEXT

If the residual was resolved here: return to `04-verify-smoke-connect.md` and re-run; you should now hit Outcome A or B.

If escalated to FALLBACK: pause and update the user.
