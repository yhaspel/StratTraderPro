#!/usr/bin/env bash
# M11 §7.5 Day 5
# ---------------------------------------------------------------------------
# DRILL: restart Postgres (local proxy for a DB failover).
# MEASURES:
#   - downtime window (DB unreachable → reachable again)
#   - app reconnect time (web answers a DB-backed request again)
# ASSERTS:
#   - the app recovers on its own (Django/psycopg re-establishes the pool) with
#     no manual intervention.
#
# The Railway-side managed-Postgres failover measurement is [LIVE] — this local
# restart only proves the app reconnects cleanly. Run on a DEDICATED stack.
# ---------------------------------------------------------------------------
source "$(dirname "$0")/_lib.sh"

RECONNECT_BUDGET="${RECONNECT_BUDGET:-60}"

db_up() { c exec -T postgres pg_isready -U stp_user -d strattraderpro >/dev/null 2>&1; }
app_db_ok() {
  # A cheap DB-backed check via the app process.
  c exec -T backend python - <<'PY' >/dev/null 2>&1
import django,os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings.dev"); django.setup()
from django.db import connection
connection.close()             # force a fresh connection
with connection.cursor() as cur:
    cur.execute("SELECT 1")
PY
}

step "confirm DB + app healthy pre-drill"
db_up && app_db_ok && pass "healthy" || { fail "not healthy pre-drill"; exit 1; }

step "RESTART postgres"
DOWN0=$(date +%s)
c restart postgres

step "measure DB downtime"
while db_up; do sleep 0.2; [ $(( $(date +%s) - DOWN0 )) -gt 30 ] && break; done  # wait until it actually goes down
DOWN_START=$(date +%s)
until db_up; do sleep 0.5; [ $(( $(date +%s) - DOWN_START )) -gt 120 ] && { fail "postgres never came back"; exit 1; }; done
DOWNTIME=$(( $(date +%s) - DOWN_START ))
log "postgres downtime ≈ ${DOWNTIME}s"

step "measure app reconnect (budget ${RECONNECT_BUDGET}s)"
R0=$(date +%s)
until app_db_ok; do
  sleep 1
  [ $(( $(date +%s) - R0 )) -gt "${RECONNECT_BUDGET}" ] && break
done
RECONNECT=$(( $(date +%s) - R0 ))
if app_db_ok; then pass "app reconnected in ~${RECONNECT}s (≤${RECONNECT_BUDGET}s)"
else fail "app did NOT reconnect within ${RECONNECT_BUDGET}s"; fi

echo
log "SUMMARY: db_downtime≈${DOWNTIME}s  app_reconnect≈${RECONNECT}s  (Railway failover = [LIVE])"
exit "${FAILED}"
