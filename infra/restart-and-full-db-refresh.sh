#!/usr/bin/env bash
#
# restart-and-full-db-refresh.sh — DESTRUCTIVE. Drops and recreates the local
# database, then restarts the stack. On startup the backend runs
# `migrate --noinput`, so you come back up on a clean, fully-migrated but EMPTY
# database. Only the Postgres data is wiped; the frontend node_modules cache and
# built images are kept.
#
# Skip the confirmation prompt with `-y` / `--yes` or `FORCE=1`.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DB_NAME="strattraderpro"
DB_USER="stp_user"

# --- confirmation guard ---------------------------------------------------
FORCE="${FORCE:-0}"
case "${1:-}" in -y|--yes) FORCE=1 ;; esac
if [ "$FORCE" != "1" ]; then
  echo "WARNING: this DROPS and recreates the local '$DB_NAME' database — all local data is lost."
  read -r -p "         Continue? [y/N] " ans
  case "$ans" in
    [yY] | [yY][eE][sS]) ;;
    *) echo "Aborted."; exit 1 ;;
  esac
fi

echo "==> [1/4] Stopping app containers (frees DB connections)..."
docker compose down --remove-orphans

echo "==> [2/4] Starting postgres only and waiting for it to accept connections..."
docker compose up -d postgres
until docker compose exec -T postgres pg_isready -U "$DB_USER" -d postgres >/dev/null 2>&1; do
  sleep 1
done

echo "==> [3/4] Dropping & recreating '$DB_NAME'..."
docker compose exec -T postgres psql -U "$DB_USER" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME' AND pid <> pg_backend_pid();" >/dev/null
docker compose exec -T postgres psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;"
docker compose exec -T postgres psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

echo "==> [4/4] Bringing up the full stack (backend auto-migrates the fresh DB)..."
docker compose --profile tunnel up -d --build

echo
echo "OK: fresh database + stack up.  backend->8777  frontend->4444  ngrok->4040"
echo "    seed strategies:  docker compose exec backend python manage.py load_strategies --dir <path>"
echo "    create admin:     docker compose exec backend python manage.py createsuperuser"
