#!/usr/bin/env bash
#
# up.sh — start the StratTraderPro local stack (detached), including the ngrok
# tunnel. First run auto-builds any missing images.
#
# Stack: postgres, redis, backend(:8777), worker, beat, streams, ws(:8788),
#        frontend(:4444), ngrok(web UI :4040, tunnels -> backend:8777)
#
set -euo pipefail

# Run from the project root (this script lives in infra/) so docker compose
# finds docker-compose.yml no matter where it's invoked from.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Starting StratTraderPro local stack (detached)..."
docker compose --profile tunnel up -d "$@"

echo
echo "OK: stack up. Endpoints:"
echo "    backend    -> http://localhost:8777"
echo "    ws (daphne)-> ws://localhost:8788/ws/dashboard/"
echo "    frontend   -> http://localhost:4444"
echo "    ngrok UI   -> http://localhost:4040   (public webhook tunnel -> backend:8777)"
echo "    postgres   -> localhost:5433    redis -> localhost:6380"
echo
echo "    logs:  docker compose logs -f        stop:  infra/down.sh"
