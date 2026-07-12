#!/usr/bin/env bash
# Shared helpers + SAFETY GUARD for the M11 §7.5 chaos drills.
#
# Every drill sources this file. It refuses to touch the SHARED dev stack
# (compose project `strattraderpro`) unless you explicitly override, because the
# drills are destructive (kill/pause/restart services). Run them on a DEDICATED
# throwaway stack instead — see scripts/chaos/README.md.
#
# Target selection:
#   PROJECT   compose project name of the DEDICATED stack (default: stp-chaos)
#   COMPOSE   compose file (default: docker-compose.yml at repo root)
# Prerequisites for most drills (documented per script):
#   - the dedicated stack is up:  docker compose -p "$PROJECT" up -d
#   - a Redis (not LocMem) cache backend so heartbeat/idempotency are shared
#     across processes (set CACHES to django-redis or run prod-shaped settings)
#   - fixtures seeded:  docker compose -p "$PROJECT" exec -T backend \
#         python /app/loadtest/seed.py --count 20 --with-broker
#   - the FakeBrokerAdapter seam ON (STP_LOADTEST_FAKE_BROKER=1 + PYTHONPATH),
#     so orders submit deterministically without touching real Alpaca.
set -euo pipefail

PROJECT="${PROJECT:-stp-chaos}"
COMPOSE="${COMPOSE:-docker-compose.yml}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

c()   { docker compose -p "${PROJECT}" -f "${REPO_ROOT}/${COMPOSE}" "$@"; }
log()  { printf '\033[1;34m[chaos]\033[0m %s\n' "$*"; }
step() { printf '\033[1;36m[step]\033[0m  %s\n' "$*"; }
pass() { printf '\033[1;32m[PASS]\033[0m  %s\n' "$*"; }
fail() { printf '\033[1;31m[FAIL]\033[0m  %s\n' "$*"; FAILED=1; }
assert() { printf '\033[1;33m[ASSERT]\033[0m %s\n' "$*"; }

guard_not_shared() {
  if [ "${PROJECT}" = "strattraderpro" ] && [ "${FORCE_SHARED:-0}" != "1" ]; then
    echo "REFUSING to run a destructive chaos drill against the SHARED stack" >&2
    echo "(PROJECT=strattraderpro). Use a dedicated project, e.g.:" >&2
    echo "    PROJECT=stp-chaos docker compose -p stp-chaos up -d" >&2
    echo "    PROJECT=stp-chaos scripts/chaos/$(basename "${0}")" >&2
    exit 2
  fi
}

# psql helper against the dedicated stack's postgres service.
q() { c exec -T postgres psql -U stp_user -d strattraderpro -tAc "$1" | tr -d ' '; }

FAILED=0
guard_not_shared
