#!/usr/bin/env bash
#
# up.sh — start the StratTraderPro local stack (detached), including the ngrok
# tunnel. Always passes --build so image layers are rebuilt from the layer cache
# (~instant when nothing changed; only re-runs pip when requirements/ or the
# Dockerfile changed). This self-heals stale per-service images: Compose tags a
# separate image per service off the shared backend.Dockerfile, so a plain
# `up -d` reuses old images and silently leaves beat/worker/streams/ws missing
# any newly-added dependency (e.g. vectorbt).
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
docker compose --profile tunnel up -d --build "$@"

echo
echo "OK: stack up. Endpoints:"
echo "    backend    -> http://localhost:8777"
echo "    ws (daphne)-> ws://localhost:8788/ws/dashboard/"
echo "    frontend   -> http://localhost:4444"
echo "    ngrok UI   -> http://localhost:4040   (public webhook tunnel -> backend:8777)"
echo "    postgres   -> localhost:5434    redis -> localhost:6380"
echo
echo "    logs:  docker compose logs -f        stop:  infra/down.sh"
