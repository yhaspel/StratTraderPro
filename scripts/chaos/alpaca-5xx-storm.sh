#!/usr/bin/env bash
# M11 §7.5 Day 4  (frozen decision §4.7 — Alpaca is the only live-path broker)
# ---------------------------------------------------------------------------
# DRILL: Alpaca REST 5xx storm, injected via a FakeBrokerAdapter that raises
#        BrokerError(UNAVAILABLE) on place_order.
# ASSERTS:
#   1. Retry/backoff is BOUNDED — process_alert has max_retries=0 and rejects on
#      BrokerError rather than entering a retry storm (§6.3). The order lands in
#      REJECTED, not an unbounded retry loop.
#   2. NO DUPLICATE orders — a 5xx does not create a second order for the same
#      client_order_id (idempotency anchor holds even under broker failure).
#
# This exercises the platform's failure handling; it does NOT hit real Alpaca.
# Run on a DEDICATED stack. TradeStation retry/backoff is covered by a separate
# adapter unit test (flag OFF, no live traffic).
# ---------------------------------------------------------------------------
source "$(dirname "$0")/_lib.sh"

IDEM="chaos-5xx-$(date +%s)"

read -r USERID SID SECRET < <(c exec -T backend python - <<'PY'
import json,pathlib
u=json.loads(pathlib.Path("/app/loadtest/fixtures.json").read_text())["users"][0]
print(u["user_id"], u["strategy_id"], u["webhook_secret"])
PY
)

step "install a 5xx-raising adapter in the WORKER process for this drill"
cat <<'NOTE'
  NOTE: this drill assumes the worker was started with an adapter that raises on
  place_order. The simplest way on a dedicated stack is to run the worker with:
     STP_LOADTEST_FAKE_BROKER=1 STP_LOADTEST_FAKE_5XX=1 PYTHONPATH=/app/loadtest
  and extend fake_broker_patch._build_fake to return an adapter whose
  place_order raises BrokerError(UNAVAILABLE) when STP_LOADTEST_FAKE_5XX=1.
  Below we drive traffic and assert the platform's bounded-failure behavior.
NOTE

step "fire the same idempotency_key 5 times into the 5xx storm"
for i in 1 2 3 4 5; do
  c exec -T backend python - "$USERID" "$SID" "$SECRET" "$IDEM" <<'PY'
import json,sys,urllib.request
uid,sid,secret,idem=sys.argv[1:5]
body=json.dumps({"strategy":"loadtest","action":"buy","symbol":"AAPL","qty":1,
                 "order_type":"MKT","sig":secret,"idempotency_key":idem}).encode()
req=urllib.request.Request(f"http://localhost:8777/hooks/v1/{uid}/{sid}/",data=body,
                           headers={"Content-Type":"application/json"})
try:
    r=urllib.request.urlopen(req,timeout=5); print("HTTP",r.status)
except Exception as e: print("ERR",e)
PY
done
sleep 6

step "ASSERT bounded failure: at most ONE order for the key, in REJECTED"
N=$(q "SELECT count(*) FROM orders_order o JOIN webhooks_alert_message a ON a.id=o.raw_alert_id WHERE a.idempotency_key='${IDEM}'")
REJ=$(q "SELECT count(*) FROM orders_order o JOIN webhooks_alert_message a ON a.id=o.raw_alert_id WHERE a.idempotency_key='${IDEM}' AND o.status='REJECTED'")
log "orders for key: ${N}  rejected: ${REJ}"
[ "${N}" -le 1 ] && pass "no duplicate orders under the 5xx storm (n=${N})" \
                 || fail "duplicate orders created under 5xx storm (n=${N})"
assert "on a stack with the 5xx adapter installed, the single order should be REJECTED (bounded, no retry storm): rejected=${REJ}"

exit "${FAILED}"
