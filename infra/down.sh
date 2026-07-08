#!/usr/bin/env bash
#
# down.sh — stop the StratTraderPro local stack. Containers and networks are
# removed; named data volumes (postgres/redis) are PRESERVED.
#
# To also wipe the database, use infra/restart-and-full-db-refresh.sh.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Stopping StratTraderPro local stack (data volumes kept)..."
# `down` targets every container in the compose project regardless of profile.
docker compose down --remove-orphans "$@"

echo "OK: stack down. Postgres/redis data preserved."
