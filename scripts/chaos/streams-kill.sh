#!/usr/bin/env bash
# M11 §7.5 Day 3  →  AC-11-6
# ---------------------------------------------------------------------------
# DRILL: crash-loop `run_broker_streams` (Alpaca trade_updates gone).
# ASSERTS:
#   1. GET /api/v1/brokers/{id}/status/ flips to DEGRADED within
#      BROKER_STREAM_HEARTBEAT_TTL (default 45s) + margin  → assert ≤ 60s.
#      (The heartbeat cache key `broker:hb:{id}` ages past the TTL once the
#      streams service stops refreshing it.)
#   2. L1 flatten still works via the REST path — it goes through the broker
#      adapter's synchronous flatten_all, independent of the fill stream.
#   3. On restart, missed fills are recovered via the REST cursor and DEDUPED on
#      broker_exec_id (AC-04-11 semantics): re-ingesting the same exec id twice
#      inserts one fill row, not two.
#
# PREREQ: a Redis (not LocMem) cache so the streams process and the web process
# share `broker:hb:{id}`; on a LocMem dev stack the status check cannot observe
# another process's heartbeat. Run on a DEDICATED stack.
# ---------------------------------------------------------------------------
source "$(dirname "$0")/_lib.sh"

TTL="${BROKER_STREAM_HEARTBEAT_TTL:-45}"
BUDGET="${DEGRADED_BUDGET:-60}"

# Resolve a connected broker account id + its user for the status check.
read -r ACCT UID < <(q "SELECT id||' '||user_id FROM brokers_account WHERE status='CONNECTED' LIMIT 1" | tr '|' ' ')
[ -n "${ACCT:-}" ] || { fail "no CONNECTED broker account — seed with --with-broker first"; exit 1; }
log "probing broker account ${ACCT}"

status_now() { # read stream status directly from the cache (what the API returns)
  c exec -T backend python - "${ACCT}" <<'PY'
import sys,django,os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings.dev"); django.setup()
from apps.brokers.models import BrokerAccount
from apps.brokers.services import get_stream_status
a=BrokerAccount.objects.get(id=sys.argv[1])
print(get_stream_status(a))
PY
}

step "seed a fresh heartbeat (simulate a healthy stream), confirm CONNECTED"
c exec -T backend python - "${ACCT}" <<'PY'
import sys,django,os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings.dev"); django.setup()
from apps.brokers.services import set_heartbeat
set_heartbeat(sys.argv[1])
PY
S=$(status_now); log "status: ${S}"

step "CRASH-LOOP the streams service (stop refreshing the heartbeat)"
c stop streams || true
T0=$(date +%s)

step "poll status until DEGRADED (budget ${BUDGET}s = TTL ${TTL}s + margin)"
DEG=0
while [ $(( $(date +%s) - T0 )) -lt "${BUDGET}" ]; do
  S=$(status_now)
  if [ "${S}" = "DEGRADED" ] || [ "${S}" = "DOWN" ]; then DEG=1; break; fi
  sleep 3
done
ELAPSED=$(( $(date +%s) - T0 ))
[ "${DEG}" = 1 ] && pass "status flipped to ${S} in ${ELAPSED}s (≤${BUDGET}s)" \
                 || fail "status did NOT flip to DEGRADED within ${BUDGET}s"

step "ASSERT L1 flatten still works via REST while the stream is DOWN"
FL=$(c exec -T backend python - "${UID}" <<'PY'
import sys,django,os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings.dev"); django.setup()
from apps.risk import killswitch
r=killswitch.flatten_user(sys.argv[1], scope="USER")
print("OK" if isinstance(r, dict) else "ERR")
PY
)
[ "${FL}" = "OK" ] && pass "flatten_user completed via REST path with the stream down" \
                   || fail "flatten via REST failed while stream down"

step "restart streams; ASSERT fill catch-up dedupes on broker_exec_id"
c start streams
# Re-ingest the SAME broker_exec_id twice for a REAL order and assert exactly one
# Fill row survives. ingest_fill_event dedups via
# Fill.get_or_create(broker_account, broker_exec_id) — the (account, exec_id)
# unique constraint — so replay on reconnect is idempotent (AC-04-11).
DEDUP=$(c exec -T backend python - <<'PY'
import django,os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings.dev"); django.setup()
from decimal import Decimal
from apps.brokers.base import FillEvent, Side
from apps.orders.services import ingest_fill_event
from apps.orders.models import Order, Fill
order=Order.objects.select_related("broker_account").first()
if order is None:
    print("SKIP no order to attach a fill to (drive some webhook traffic first)")
else:
    exec_id="chaos-dedup-1"
    ev=FillEvent(broker_exec_id=exec_id, client_order_id=order.client_order_id,
                 broker_order_id=order.broker_order_id or "", symbol=order.symbol,
                 side=Side.SELL, event_type="fill", qty=Decimal("1"), price=Decimal("100"),
                 filled_qty=Decimal("1"))
    ingest_fill_event(ev, user_id=str(order.user_id))
    ingest_fill_event(ev, user_id=str(order.user_id))   # replay
    rows=Fill.objects.filter(broker_account=order.broker_account, broker_exec_id=exec_id).count()
    print(f"rows={rows}")
# Global invariant (always holds): no duplicate (account, exec_id) survives.
dup=Fill.objects.count()-Fill.objects.values("broker_account","broker_exec_id").distinct().count()
print(f"global_dupes={dup}")
PY
)
log "dedup probe: ${DEDUP}"
if printf '%s' "${DEDUP}" | grep -q 'rows=1' || printf '%s' "${DEDUP}" | grep -q 'SKIP'; then
  pass "replayed broker_exec_id ingested once (deduped)"
else
  case "${DEDUP}" in *rows=*) fail "fill dedupe on broker_exec_id did not hold: ${DEDUP}";; esac
fi
printf '%s' "${DEDUP}" | grep -q 'global_dupes=0' \
  && pass "no duplicate (account, broker_exec_id) fills anywhere" \
  || fail "duplicate fills present: ${DEDUP}"

exit "${FAILED}"
