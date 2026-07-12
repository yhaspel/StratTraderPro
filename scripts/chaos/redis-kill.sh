#!/usr/bin/env bash
# M11 §7.5 Day 1  →  AC-11-5
# ---------------------------------------------------------------------------
# DRILL: kill Redis for ~90s mid-traffic.
# ASSERTS:
#   1. Celery recovers within 60s of Redis returning (worker reconnects, the
#      default queue drains).
#   2. The idempotency guard holds across the outage — a REPEATED
#      idempotency_key produces exactly ONE order (at-most-once), never a
#      duplicate, via the Redis SETNX guard + Alpaca client_order_id.
#   3. No orphaned orders left stuck in PENDING_SUBMIT after the queue drains.
#
# Redis is BOTH the Celery broker and (on a prod-shaped stack) the cache backing
# idempotency; the outage exercises both. Run on a DEDICATED stack only.
# ---------------------------------------------------------------------------
source "$(dirname "$0")/_lib.sh"

DOWN_SECS="${DOWN_SECS:-90}"
RECOVER_BUDGET="${RECOVER_BUDGET:-60}"
IDEM="chaos-redis-$(date +%s)"   # one repeated key we fire multiple times

# Pick a seeded user for the repeated-key probe.
read -r UID SID SECRET < <(c exec -T backend python - <<'PY'
import json,pathlib
f=pathlib.Path("/app/loadtest/fixtures.json")
u=json.loads(f.read_text())["users"][0]
print(u["user_id"], u["strategy_id"], u["webhook_secret"])
PY
)
post_repeat() { # fire the SAME idempotency_key
  c exec -T backend python - "$UID" "$SID" "$SECRET" "$IDEM" <<'PY'
import json,sys,urllib.request
uid,sid,secret,idem=sys.argv[1:5]
body=json.dumps({"strategy":"loadtest","action":"buy","symbol":"AAPL","qty":1,
                 "order_type":"MKT","sig":secret,"idempotency_key":idem}).encode()
req=urllib.request.Request(f"http://localhost:8777/hooks/v1/{uid}/{sid}/",
                           data=body,headers={"Content-Type":"application/json"})
try:
    r=urllib.request.urlopen(req,timeout=5); print("HTTP",r.status)
except Exception as e: print("ERR",e)
PY
}

step "baseline order count"
BEFORE=$(q "SELECT count(*) FROM orders_order")
log "orders before: ${BEFORE}"

step "fire the repeated idempotency_key BEFORE the outage (creates 1 order)"
post_repeat

step "KILL redis for ${DOWN_SECS}s"
c kill redis || true
assert "during the outage the webhook path 5xx's on dispatch — that is expected; the guard is about NOT double-processing on recovery"
post_repeat || true       # same key again, mid-outage
sleep "${DOWN_SECS}"

step "restart redis"
c start redis
T0=$(date +%s)

step "wait ≤${RECOVER_BUDGET}s for Celery to reconnect + drain"
RECOVERED=0
while [ $(( $(date +%s) - T0 )) -lt "${RECOVER_BUDGET}" ]; do
  if c exec -T backend celery -A config.celery inspect ping -t 5 >/dev/null 2>&1; then
    RECOVERED=1; break
  fi
  sleep 3
done
ELAPSED=$(( $(date +%s) - T0 ))
[ "${RECOVERED}" = 1 ] && pass "Celery reconnected in ${ELAPSED}s (≤${RECOVER_BUDGET}s)" \
                       || fail "Celery did NOT reconnect within ${RECOVER_BUDGET}s"

step "fire the SAME idempotency_key AGAIN post-recovery"
post_repeat
sleep 5   # let the worker drain

step "ASSERT idempotency: exactly ONE order for this key across all 3 fires"
# client_order_id = stp-<sha256(user:idem)[:32]>; count orders for this user+symbol
# created during the drill window is a coarse proxy — assert the strict guard via
# the AlertMessage duplicate counter instead:
DUP=$(q "SELECT count(*) FROM orders_order o JOIN webhooks_alert_message a ON a.id=o.raw_alert_id WHERE a.idempotency_key='${IDEM}'")
[ "${DUP}" = "1" ] && pass "exactly 1 order for idempotency_key=${IDEM}" \
                   || fail "expected 1 order for the repeated key, got ${DUP} (duplicate!)"

step "ASSERT no orphaned PENDING_SUBMIT orders"
ORPH=$(q "SELECT count(*) FROM orders_order WHERE status='PENDING_SUBMIT'")
[ "${ORPH}" = "0" ] && pass "no orders stuck in PENDING_SUBMIT" \
                    || fail "${ORPH} order(s) orphaned in PENDING_SUBMIT"

exit "${FAILED}"
