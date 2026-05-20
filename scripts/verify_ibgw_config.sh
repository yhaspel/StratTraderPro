#!/usr/bin/env bash
# verify_ibgw_config.sh — assert the ib-gateway sidecar has the IBC overrides
# required for headless API access.
#
# Run after `docker compose --profile ibkr-spike up -d ib-gateway` and after
# IBC finishes login. Exits non-zero if any of the three required overrides
# is missing from the live /home/ibgateway/ibc/config.ini.
#
# Wired into:
#   - The smoke runbook as a pre-flight check.
#   - CI's ibkr-spike job (when we add it in M04 production).
#
# Background: gnzsnz/ib-gateway:10.45.1e ships an IBC config template that
# omits AcceptIncomingConnectionAction — without this, headless API clients
# hit a hidden "Trusted Computer" dialog and time out. ADR-040 has the full
# triage; docker/ib-gateway/Dockerfile patches the .tmpl at build time.

set -euo pipefail

REQUIRED=(
  "AcceptIncomingConnectionAction=accept"
  "AllowBlindTrading=yes"
  "OverrideTwsApiPort=4002"
)

CFG_PATH="/home/ibgateway/ibc/config.ini"
SERVICE="${IBGW_SERVICE:-ib-gateway}"
COMPOSE="docker compose --profile ibkr-spike"

if ! $COMPOSE ps "$SERVICE" 2>/dev/null | grep -q "Up\|running"; then
  echo "FAIL: $SERVICE is not running. Start with: $COMPOSE up -d $SERVICE" >&2
  exit 2
fi

LIVE_CFG=$($COMPOSE exec -T "$SERVICE" cat "$CFG_PATH" 2>/dev/null || true)
if [[ -z "$LIVE_CFG" ]]; then
  echo "FAIL: could not read $CFG_PATH from $SERVICE" >&2
  exit 3
fi

missing=()
for line in "${REQUIRED[@]}"; do
  if ! grep -qxF "$line" <<<"$LIVE_CFG"; then
    missing+=("$line")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "FAIL: $CFG_PATH is missing required IBC overrides:" >&2
  for m in "${missing[@]}"; do
    echo "  - $m" >&2
  done
  echo >&2
  echo "Fix: rebuild the image so docker/ib-gateway/Dockerfile's .tmpl patch applies:" >&2
  echo "  $COMPOSE build --no-cache $SERVICE && $COMPOSE up -d --force-recreate $SERVICE" >&2
  exit 1
fi

echo "OK: $CFG_PATH has all ${#REQUIRED[@]} required IBC overrides."
