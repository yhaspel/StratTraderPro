#!/usr/bin/env python
"""M11 §7.4 / AC-11-4 — 50-user simultaneous L1 halt+flatten, measured server-side.

Why server-side rather than only via Locust HTTP: the REST path
(`POST /api/v1/risk/killswitches/` scope=USER) requires an MFA step-up code per
user and the flatten runs on-commit inside the web request, so an HTTP driver
measures request latency PLUS auth. This runner measures the pure kill-switch
action — ``killswitch.trigger_halt(level=L1, flatten=True)`` — across N users
fired at once, which is exactly the AC-08-8 / AC-11-4 budget (each single-user
flatten ≤5s p99; all N submitted within 10s; fleet p99 ≤8s).

It patches ``build_adapter`` to FakeBrokerAdapter IN THIS PROCESS (no app edit)
and seeds one open position per fake account so each flatten submits a real
closing order. The dominant p99 factor under contention is the serialized
append-only audit-chain insert (each halt emits RISK_HALT_ENGAGED) — precisely
what this scenario is meant to stress.

Run against a stack's DB (inside the backend container is simplest):

    docker exec strattraderpro-backend-1 \
      env STP_LOADTEST_FAKE_SEED_POSITION=1 \
      python /app/loadtest/flatten_50.py --users 50

WARNING: this engages a real L1 halt on each seeded user and writes audit rows;
run it against a DEDICATED stack, never the shared dev stack.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
# Make the seeded position the default for this runner unless explicitly disabled.
os.environ.setdefault("STP_LOADTEST_FAKE_SEED_POSITION", "1")

import django  # noqa: E402

django.setup()

from fake_broker_patch import patch_build_adapter  # noqa: E402

patch_build_adapter()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import close_old_connections  # noqa: E402

from apps.brokers.models import TradingHalt  # noqa: E402
from apps.risk import killswitch  # noqa: E402

User = get_user_model()


def _pctl(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def _flatten_one(user_id) -> tuple[float, int]:
    t0 = time.monotonic()
    # L1 = per-user global halt + flatten (flatten=True). trigger_halt schedules
    # flatten_user on_commit; call it directly so the timing is synchronous here.
    killswitch.trigger_halt(user_id=user_id, level=TradingHalt.Level.L1,
                            reason="LOADTEST_L1", flatten=False)
    result = killswitch.flatten_user(user_id, scope="USER")
    dt = time.monotonic() - t0
    close_old_connections()
    return dt, result.get("flattened", 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--prefix", default=os.environ.get("LT_PREFIX", "loadtest+"))
    args = ap.parse_args()

    users = list(
        User.objects.filter(email__startswith=args.prefix)
        .values_list("id", flat=True)[: args.users]
    )
    if len(users) < args.users:
        print(f"WARNING: only {len(users)} seeded users found (wanted {args.users}). "
              f"Run seed.py --count {args.users} first.", file=sys.stderr)
    if not users:
        return 2

    print(f"firing L1 halt+flatten for {len(users)} users simultaneously ...")
    wall0 = time.monotonic()
    latencies: list[float] = []
    flattened_total = 0
    with ThreadPoolExecutor(max_workers=len(users)) as pool:
        futures = [pool.submit(_flatten_one, uid) for uid in users]
        for fut in as_completed(futures):
            dt, flattened = fut.result()
            latencies.append(dt)
            flattened_total += flattened
    wall = time.monotonic() - wall0

    print("\n=== AC-11-4 — 50-user simultaneous L1 flatten ===")
    print(f"users:            {len(users)}")
    print(f"orders flattened: {flattened_total}")
    print(f"wall clock (all): {wall:.3f}s   (target: all submitted < 10s)")
    print(f"p50 flatten:      {statistics.median(latencies):.3f}s")
    print(f"p95 flatten:      {_pctl(latencies, 95):.3f}s")
    print(f"p99 flatten:      {_pctl(latencies, 99):.3f}s   (target ≤ 8s)")
    print(f"max flatten:      {max(latencies):.3f}s   (per-user AC-08-8 target ≤ 5s)")
    ok = wall < 10 and _pctl(latencies, 99) <= 8
    print(f"RESULT:           {'PASS' if ok else 'REVIEW'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
