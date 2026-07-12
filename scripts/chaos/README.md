# Chaos drills (M11 §7.5)

Six destructive fault-injection drills. **They run on a DEDICATED throwaway
docker-compose stack, never the shared dev stack** (`_lib.sh` refuses
`PROJECT=strattraderpro` unless `FORCE_SHARED=1`). Each drill prints
`[ASSERT]`/`[PASS]`/`[FAIL]` and exits non-zero on failure.

| Script | Day | AC | What it breaks | Key assertion |
|---|---|---|---|---|
| `redis-kill.sh` | 1 | AC-11-5 | Redis (broker+cache) ~90s | Celery recovers ≤60s; idempotency holds; no orphans |
| `worker-kill.sh` | 2 | — | SIGKILL a worker mid-flatten | Idempotent retry — no duplicate orders |
| `streams-kill.sh` | 3 | AC-11-6 | crash-loop `run_broker_streams` | status→DEGRADED ≤60s; REST flatten still works; fills dedupe on `broker_exec_id` |
| `alpaca-5xx-storm.sh` | 4 | — | Alpaca REST 5xx (fake adapter) | Bounded retry; no duplicate orders |
| `db-restart.sh` | 5 | — | restart Postgres | App reconnects on its own; measure downtime |
| `role-removal.sh` | 6 | AC-11-14 | blank/bogus `SERVICE_ROLE` | Crashes loudly, non-zero exit, never serves HTTP (would have caught BUG-011) |

## Stand up a dedicated stack

```bash
export PROJECT=stp-chaos
# A separate project = separate network/volumes; publish nothing that clashes
# with the shared stack, or stop the shared stack first.
docker compose -p "$PROJECT" up -d --build

# Prereqs most drills assume:
#  - a Redis cache backend (NOT LocMem) so heartbeat/idempotency are shared
#    across the web/worker/streams processes. Run the stack with prod-shaped
#    settings or point CACHES at django-redis.
#  - fixtures + the FakeBrokerAdapter seam so orders submit deterministically:
docker compose -p "$PROJECT" exec -T backend \
  env STP_LOADTEST_FAKE_BROKER=1 PYTHONPATH=/app/loadtest \
  python /app/loadtest/seed.py --count 20 --with-broker
# (and set STP_LOADTEST_FAKE_BROKER=1 + PYTHONPATH=/app/loadtest on the
#  backend/worker/streams services so build_adapter -> FakeBrokerAdapter — see
#  backend/loadtest/README.md "FakeBrokerAdapter seam".)
```

## Run a drill

```bash
PROJECT=stp-chaos scripts/chaos/redis-kill.sh
PROJECT=stp-chaos scripts/chaos/role-removal.sh   # safe next to any stack (docker run only)
```

## Notes

- **`role-removal.sh` is non-destructive** — it only `docker run`s throwaway
  containers from the built image, so it can validate the SERVICE_ROLE guard
  even alongside the shared stack (still guarded; pass `FORCE_SHARED=1` to point
  it at the shared image on purpose).
- The other five drills stop/kill/restart services and MUST target a dedicated
  stack.
- Results are captured in `docs/ops/chaos-drill-logs.md`.
