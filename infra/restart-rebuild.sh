#!/usr/bin/env bash
#
# restart-rebuild.sh — rebuild images (using the layer cache) and recreate the
# app containers. Fast iteration after a code/dependency change. Postgres/redis
# data and volumes are kept; the DB is NOT wiped.
#
# For a from-scratch (no-cache) rebuild of every service including the celery
# workers, use infra/restart-all-docker-and-workers-and-rebuild.sh.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Rebuilding images (cached) + recreating containers (data kept)..."
docker compose build
docker compose --profile tunnel up -d --force-recreate "$@"

echo "OK: rebuilt and restarted.  backend->8777  frontend->4444  ngrok->4040"
