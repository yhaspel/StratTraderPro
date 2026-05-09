#!/usr/bin/env bash
# IB Gateway sidecar entrypoint — M04 Day-1 SPIKE
#
# Sequence:
#   1. Render IBC config.ini from template + env (creds, mode)
#   2. Boot Xvfb (IB Gateway is a Swing app, needs an X display)
#   3. Optionally boot x11vnc for debugging (DEBUG_VNC=1)
#   4. Detect installed IB Gateway major version (varies by build)
#   5. exec IBC's gatewaystart.sh — IBC handles login + keepalive
#
# On any failure: log loudly and exit non-zero so the orchestrator restarts.

set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*"; }
die() { printf '[entrypoint][FATAL] %s\n' "$*" >&2; exit 1; }

# --- Required env -----------------------------------------------------------
: "${TWS_USERID:?env TWS_USERID is required (paper account login)}"
: "${TWS_PASSWORD:?env TWS_PASSWORD is required (paper account password)}"
: "${TRADING_MODE:=paper}"

if [[ "${TRADING_MODE}" != "paper" ]]; then
    # M04 is paper-only by AC and by milestone scope. Refuse to boot in live
    # mode from this image — too easy to ship an env var mistake into prod.
    die "TRADING_MODE=${TRADING_MODE} not allowed in spike image (paper only)"
fi

# --- Render IBC config ------------------------------------------------------
# sed with a control-character delimiter (\x01) — unlikely to appear in any
# real password. We also sanity-check that the password doesn't contain it,
# because if it did the substitution would silently corrupt the config and
# IBC would fail to log in with no useful error. Spike-quality; M04 proper
# will template via Django settings instead of an env-rendered .ini file.
log "rendering IBC config.ini"
case "${TWS_PASSWORD}" in
    *$'\x01'*) die "TWS_PASSWORD contains a literal SOH (\\x01); cannot template safely" ;;
esac
DELIM=$'\x01'
sed \
    -e "s${DELIM}__TWS_USERID__${DELIM}${TWS_USERID}${DELIM}g" \
    -e "s${DELIM}__TWS_PASSWORD__${DELIM}${TWS_PASSWORD}${DELIM}g" \
    -e "s${DELIM}__TRADING_MODE__${DELIM}${TRADING_MODE}${DELIM}g" \
    "${IBC_PATH}/config.ini.template" > "${IBC_PATH}/config.ini"
chmod 600 "${IBC_PATH}/config.ini"

# --- Xvfb -------------------------------------------------------------------
log "starting Xvfb on ${DISPLAY}"
# Xvfb is left as a background child of this script. The container's PID 1
# is the IBC process (via `exec` below); when IBC exits, the container exits
# and Xvfb is reaped. We don't need to track XVFB_PID for cleanup.
Xvfb "${DISPLAY}" -screen 0 1024x768x16 -nolisten tcp &

# Wait for X to be ready (xdpyinfo succeeds once the display is listening)
for _ in {1..40}; do
    if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
        log "Xvfb is up"
        break
    fi
    sleep 0.25
done
xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1 \
    || die "Xvfb failed to come up within 10s"

# --- Optional VNC for debugging --------------------------------------------
if [[ "${DEBUG_VNC}" == "1" ]]; then
    log "starting x11vnc on :5900 (DEBUG_VNC=1, no password — do not expose to public net)"
    x11vnc -display "${DISPLAY}" -forever -shared -nopw -bg -quiet \
        -rfbport 5900 -listen 0.0.0.0
fi

# --- Detect IB Gateway version ---------------------------------------------
# Installer puts versioned dirs under ${TWS_PATH}/ibgateway/<version>/. The
# version string changes with every IBKR release (e.g. "1019", "1023"). Pick
# the highest one present.
TWS_MAJOR_VERSION="$(
    find "${TWS_PATH}/ibgateway" -mindepth 1 -maxdepth 1 -type d \
        2>/dev/null | sort -V | tail -1 | xargs -n1 basename
)"
[[ -n "${TWS_MAJOR_VERSION}" ]] \
    || die "no IB Gateway install found under ${TWS_PATH}/ibgateway"
log "detected IB Gateway version: ${TWS_MAJOR_VERSION}"

# --- IBC --------------------------------------------------------------------
# gatewaystart.sh wraps ibcstart.sh with sensible defaults for Gateway mode.
# We pass the version and config explicitly; everything else IBC infers.
log "starting IBC (mode=${TRADING_MODE}, port=${TWS_PORT})"
cd "${IBC_PATH}"

# IBC reads the rendered config.ini for creds; we don't pass them on the
# command line (would leak via /proc/<pid>/cmdline).
exec ./scripts/ibcstart.sh "${TWS_MAJOR_VERSION}" \
    --gateway \
    --mode="${TRADING_MODE}" \
    --tws-path="${TWS_PATH}" \
    --ibc-path="${IBC_PATH}" \
    --ibc-ini="${IBC_PATH}/config.ini"
