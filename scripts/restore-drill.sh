#!/usr/bin/env bash
# M11 §7.6 / AC-11-7 — backup restore drill.
#
# pg_dump the SHARED app DB (READ-ONLY), restore it into a FRESH throwaway
# scratch Postgres, run verification queries (row counts on key tables) and
# re-verify the append-only audit-chain head against the restored copy. The
# shared Postgres is NEVER modified. The scratch container is removed on exit.
#
# Safe to run against the shared dev stack: pg_dump takes no locks that block
# writers and we only ever WRITE to the throwaway scratch instance.
#
#   scripts/restore-drill.sh
#
# Env overrides: PG_CONTAINER, BACKEND_CONTAINER, NET, DB, DB_USER, DB_PW,
#                SCRATCH_NAME, SCRATCH_PORT, PG_IMAGE
set -euo pipefail

DB="${DB:-strattraderpro}"
DB_USER="${DB_USER:-stp_user}"
DB_PW="${DB_PW:-stp_local_pw}"
NET="${NET:-strattraderpro_default}"
SCRATCH_NAME="${SCRATCH_NAME:-stp-restore-scratch}"
SCRATCH_PORT="${SCRATCH_PORT:-55432}"
PG_IMAGE="${PG_IMAGE:-postgres:16-alpine}"

# Auto-detect the shared containers by compose naming.
PG_CONTAINER="${PG_CONTAINER:-$(docker ps --format '{{.Names}}' | grep -E 'strattraderpro[-_]postgres[-_]1' | head -1)}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-$(docker ps --format '{{.Names}}' | grep -E 'strattraderpro[-_]backend[-_]1' | head -1)}"

WORKDIR="$(mktemp -d)"
DUMP="${WORKDIR}/shared_dump.sql"

log()  { printf '\033[1;34m[drill]\033[0m %s\n' "$*"; }
pass() { printf '\033[1;32m[PASS]\033[0m  %s\n' "$*"; }
fail() { printf '\033[1;31m[FAIL]\033[0m  %s\n' "$*"; }

cleanup() {
  log "cleanup: removing scratch container + temp files"
  docker rm -f "${SCRATCH_NAME}" >/dev/null 2>&1 || true
  rm -rf "${WORKDIR}" || true
}
trap cleanup EXIT

[ -n "${PG_CONTAINER}" ]      || { fail "shared postgres container not found"; exit 1; }
[ -n "${BACKEND_CONTAINER}" ] || { fail "shared backend container not found"; exit 1; }
log "shared postgres:  ${PG_CONTAINER}"
log "shared backend:   ${BACKEND_CONTAINER}"
log "scratch:          ${SCRATCH_NAME} (host :${SCRATCH_PORT})"

# --- 1. pg_dump the SHARED db (read-only) -----------------------------------
log "1/5 pg_dump ${DB} (read-only, --no-owner --no-privileges) ..."
docker exec -e PGPASSWORD="${DB_PW}" "${PG_CONTAINER}" \
  pg_dump -U "${DB_USER}" -d "${DB}" --no-owner --no-privileges > "${DUMP}"
DUMP_BYTES=$(wc -c < "${DUMP}" | tr -d ' ')
log "    dump size: ${DUMP_BYTES} bytes"
[ "${DUMP_BYTES}" -gt 0 ] || { fail "empty dump"; exit 1; }

# --- 2. boot a fresh scratch Postgres ---------------------------------------
log "2/5 starting scratch Postgres (${PG_IMAGE}) on network ${NET} ..."
docker rm -f "${SCRATCH_NAME}" >/dev/null 2>&1 || true
docker run -d --name "${SCRATCH_NAME}" --network "${NET}" \
  -p "${SCRATCH_PORT}:5432" \
  -e POSTGRES_DB="${DB}" -e POSTGRES_USER="${DB_USER}" -e POSTGRES_PASSWORD="${DB_PW}" \
  "${PG_IMAGE}" >/dev/null

log "    waiting for scratch to accept connections ..."
for i in $(seq 1 30); do
  if docker exec -e PGPASSWORD="${DB_PW}" "${SCRATCH_NAME}" \
       pg_isready -U "${DB_USER}" -d "${DB}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
  [ "$i" -eq 30 ] && { fail "scratch never became ready"; exit 1; }
done
pass "scratch is up"

# --- 3. restore into scratch ------------------------------------------------
log "3/5 restoring dump into scratch ..."
# Triggers/constraints are recreated AFTER the data COPY by pg_dump, so the
# append-only audit trigger does not fire during load. Tolerate benign notices;
# the row-count assertions below are the real success gate.
RESTORE_ERR="${WORKDIR}/restore.err"
docker exec -i -e PGPASSWORD="${DB_PW}" "${SCRATCH_NAME}" \
  psql -U "${DB_USER}" -d "${DB}" -v ON_ERROR_STOP=0 -q < "${DUMP}" \
  2> "${RESTORE_ERR}" 1>/dev/null || true
ERR_COUNT=$(grep -c '^ERROR' "${RESTORE_ERR}" 2>/dev/null || true); ERR_COUNT=${ERR_COUNT:-0}
if [ "${ERR_COUNT}" -gt 0 ]; then
  log "    restore emitted ${ERR_COUNT} ERROR line(s) (showing first 5):"
  grep '^ERROR' "${RESTORE_ERR}" | head -5 | sed 's/^/      /'
fi

# --- 4. verification queries: row counts must match -------------------------
log "4/5 verifying row counts (shared vs restored) ..."
TABLES=(users_user audit_log orders_order orders_fill orders_position brokers_account)
count() { # $1=container $2=table
  docker exec -e PGPASSWORD="${DB_PW}" "$1" \
    psql -U "${DB_USER}" -d "${DB}" -tAc "SELECT count(*) FROM $2" 2>/dev/null | tr -d ' ' || echo "ERR"
}
MISMATCH=0
printf '    %-26s %10s %10s\n' "table" "shared" "restored"
for t in "${TABLES[@]}"; do
  s=$(count "${PG_CONTAINER}" "$t"); r=$(count "${SCRATCH_NAME}" "$t")
  mark="ok"
  if [ "$s" != "$r" ]; then mark="MISMATCH"; MISMATCH=$((MISMATCH+1)); fi
  printf '    %-26s %10s %10s  %s\n' "$t" "$s" "$r" "$mark"
done
if [ "${MISMATCH}" -eq 0 ]; then pass "all key tables reproduced exactly"; else fail "${MISMATCH} table(s) mismatched"; fi

# --- 5. re-verify the audit hash-chain on the RESTORED copy ------------------
log "5/5 re-verifying audit chain against the restored DB ..."
VERIFY_JSON=$(docker exec \
  -e DATABASE_URL="postgres://${DB_USER}:${DB_PW}@${SCRATCH_NAME}:5432/${DB}" \
  "${BACKEND_CONTAINER}" \
  python manage.py shell -c \
  "from apps.audit.verifier import verify_chain; import json; print('VERIFY_RESULT='+json.dumps(verify_chain()))" \
  2>/dev/null | grep '^VERIFY_RESULT=' | sed 's/^VERIFY_RESULT=//')
echo "    verify_chain -> ${VERIFY_JSON}"
CHAIN_OK=$(printf '%s' "${VERIFY_JSON}" | grep -o '"ok": *true' || true)

echo
echo "======================= RESTORE DRILL RESULT ======================="
[ "${MISMATCH}" -eq 0 ]   && pass "row counts reproduced" || fail "row counts mismatched"
[ -n "${CHAIN_OK}" ]      && pass "audit chain re-verified OK on restored copy" \
                          || fail "audit chain verify did not return ok:true"
echo "===================================================================="

if [ "${MISMATCH}" -eq 0 ] && [ -n "${CHAIN_OK}" ]; then
  echo "DRILL: PASS"; exit 0
else
  echo "DRILL: FAIL"; exit 1
fi
