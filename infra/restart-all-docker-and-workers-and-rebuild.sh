#!/usr/bin/env bash
#
# restart-all-docker-and-workers-and-rebuild.sh — full teardown + clean
# (no-cache) rebuild of EVERY service, then bring the whole stack back up.
#
# Rebuilds the backend image from scratch (re-installs dependencies), which also
# refreshes the celery workers/beat/streams/ws since they share that image.
# Postgres/redis data volumes are PRESERVED (the DB is not wiped).
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> [1/3] Tearing down all containers (data volumes kept)..."
docker compose down --remove-orphans

echo "==> [2/3] Rebuilding every image from scratch (--no-cache)..."
docker compose build --no-cache

echo "==> [3/3] Bringing the full stack back up (recreate all)..."
docker compose --profile tunnel up -d --force-recreate

echo
echo "OK: everything rebuilt from scratch and restarted."
echo "    backend->8777  ws->8788  frontend->4444  ngrok->4040"
echo "    workers: worker, beat (redbeat), streams  ->  docker compose ps"
