"""M11 §7.4 load-test harness — three scenarios (AC-11-3, AC-11-4).

Run against a LOCAL docker-compose stack seeded by ``seed.py``. Pick a scenario
by naming its User class; parameterize with env vars.

    # 100 WS dashboards (AC-11-3)
    LT_FIXTURES=backend/loadtest/fixtures.json \
      locust -f backend/loadtest/locustfile.py WsDashboardUser \
      --headless -u 100 -r 20 -t 10m

    # 20 webhooks/sec (AC-11-3) — 20 users at ~1 rps each = 20 rps
    locust -f backend/loadtest/locustfile.py WebhookUser \
      --headless -u 20 -r 20 -t 10m

    # 50-user L1 flatten via REST (AC-11-4) — needs the FakeBrokerAdapter seam on
    # the target stack; the deterministic measurement is flatten_50.py instead.
    ENABLE_L1_FLATTEN=1 locust -f backend/loadtest/locustfile.py FlattenUser \
      --headless -u 50 -r 50 -t 1m

Env knobs:
  LT_FIXTURES   path to fixtures.json (default: ./fixtures.json next to this file)
  LT_HOST       override base http host (else fixtures.base_url)
  LT_WS_URL     override ws url        (else fixtures.ws_url)
  LT_WEBHOOK_WAIT  per-user seconds between webhook posts (default 1.0 → 1 rps/user)
  ENABLE_L1_FLATTEN=1  arm the destructive L1 flatten scenario (off by default)
"""
from __future__ import annotations

import itertools
import json
import os
import random
import threading
import time
import uuid
from pathlib import Path

import gevent
from locust import HttpUser, User, between, events, task

# --- fixtures ----------------------------------------------------------------
_DEFAULT_FIXTURES = Path(__file__).resolve().parent / "fixtures.json"
_FIXTURES_PATH = Path(os.environ.get("LT_FIXTURES", str(_DEFAULT_FIXTURES)))


def _load_fixtures() -> dict:
    if not _FIXTURES_PATH.exists():
        raise SystemExit(
            f"fixtures not found at {_FIXTURES_PATH}. Run seed.py first "
            f"(docker exec strattraderpro-backend-1 python /app/loadtest/seed.py)."
        )
    return json.loads(_FIXTURES_PATH.read_text())


_FIX = _load_fixtures()
_USERS = _FIX["users"]
_BASE_URL = os.environ.get("LT_HOST", _FIX.get("base_url", "http://localhost:8777"))
_WS_URL = os.environ.get("LT_WS_URL", _FIX.get("ws_url", "ws://localhost:8788"))

# Round-robin user assignment so each seeded user stays under its own
# WEBHOOK_RATE_LIMIT_PER_MIN (default 60/min) at 20 rps across the pool.
_user_cycle = itertools.cycle(_USERS)
_cycle_lock = threading.Lock()


def _next_user() -> dict:
    with _cycle_lock:
        return next(_user_cycle)


# Asset mix: 70% stocks, 20% ETFs, 10% options (M11 §7.4).
_STOCKS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]
_ETFS = ["SPY", "QQQ", "IWM", "DIA"]
_OPTION_UNDERLYINGS = ["AAPL", "SPY", "TSLA"]


def _pick_order() -> dict:
    r = random.random()
    if r < 0.70:
        return {"symbol": random.choice(_STOCKS), "asset_class": "STOCK"}
    if r < 0.90:
        return {"symbol": random.choice(_ETFS), "asset_class": "ETF"}
    return {
        "symbol": random.choice(_OPTION_UNDERLYINGS),
        "asset_class": "OPTION",
        "option_expiry": "2026-12-18",
        "option_strike": 200,
        "option_right": "CALL",
    }


# =============================================================================
# Scenario A — 100 WS dashboards (AC-11-3)
# =============================================================================
class WsDashboardUser(User):
    """Connect to /ws/dashboard/?token=<jwt>, await connection.ack, stay
    subscribed receiving events, and heartbeat. Reconnect rate is tracked as a
    named request so it shows up in the Locust stats table + CSV."""

    # WS users don't drive HTTP; keep them alive with a short spawn interval.
    wait_time = between(1, 2)

    def on_start(self):
        self._u = _next_user()
        self._stop = False
        self._greenlet = gevent.spawn(self._run)

    def on_stop(self):
        self._stop = True

    def _run(self):
        import websocket  # websocket-client (sync); gevent patches its socket

        url = f"{_WS_URL}/ws/dashboard/?token={self._u['access']}"
        reconnects = 0
        while not self._stop:
            t0 = time.time()
            try:
                ws = websocket.create_connection(url, timeout=10)
            except Exception as exc:  # noqa: BLE001
                self._fire("WS connect", t0, exc=exc)
                gevent.sleep(2)
                reconnects += 1
                self._fire_count("WS reconnect")
                continue
            # Expect connection.ack immediately.
            try:
                ws.settimeout(10)
                raw = ws.recv()
                msg = json.loads(raw) if raw else {}
                if msg.get("type") != "connection.ack":
                    self._fire("WS connect", t0, exc=RuntimeError(f"no ack: {msg}"))
                    ws.close()
                    gevent.sleep(2)
                    continue
                self._fire("WS connect", t0)
            except Exception as exc:  # noqa: BLE001
                self._fire("WS connect", t0, exc=exc)
                ws.close()
                gevent.sleep(2)
                continue

            # Subscribed loop: heartbeat + drain events until the socket drops.
            last_ping = time.time()
            while not self._stop:
                try:
                    if time.time() - last_ping > 20:
                        ws.send(json.dumps({"type": "ping"}))
                        last_ping = time.time()
                    ws.settimeout(2)
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if raw == "":
                        raise ConnectionError("server closed")
                    self._fire_count("WS event")
                except Exception:  # noqa: BLE001 — dropped → reconnect
                    reconnects += 1
                    self._fire_count("WS reconnect")
                    break
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
            if not self._stop:
                gevent.sleep(1)

    # -- stats helpers --------------------------------------------------------
    def _fire(self, name: str, t0: float, exc: Exception | None = None):
        events.request.fire(
            request_type="WS", name=name,
            response_time=(time.time() - t0) * 1000, response_length=0,
            exception=exc,
        )

    def _fire_count(self, name: str):
        events.request.fire(
            request_type="WS", name=name, response_time=0, response_length=0,
            exception=None,
        )


# =============================================================================
# Scenario B — 20 webhooks/sec (AC-11-3)
# =============================================================================
class WebhookUser(HttpUser):
    """POST /hooks/v1/{user}/{strategy}/ with a valid static ``sig`` + a UNIQUE
    idempotency_key per request; 70/20/10 stock/ETF/option mix. Locust records
    the ingest latency (view returns 200 after AlertMessage + process_alert
    dispatch). Ingest→submit p50/p95/p99 is the worker-side ORDER_SUBMIT_LATENCY
    histogram — scrape worker:9101/metrics during the run (see README)."""

    host = _BASE_URL

    def wait_time(self):
        return float(os.environ.get("LT_WEBHOOK_WAIT", "1.0"))

    def on_start(self):
        # Pin one seeded user per Locust user so its per-user rate limit is
        # predictable; the pool of 20+ users keeps aggregate at 20 rps.
        self._u = _next_user()

    @task
    def post_webhook(self):
        u = self._u
        order = _pick_order()
        body = {
            "strategy": "loadtest",
            "action": random.choice(["buy", "sell"]),
            "qty": 1,
            "order_type": "MKT",
            "sig": u["webhook_secret"],
            "idempotency_key": f"lt-{uuid.uuid4()}",
            **order,
        }
        path = f"/hooks/v1/{u['user_id']}/{u['strategy_id']}/"
        with self.client.post(
            path, json=body, name="POST /hooks/v1/{user}/{strategy}/",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 429:
                # Rate-limited: not a server error, but flag it so we can widen
                # the user pool if it dominates.
                resp.failure("429 rate-limited (widen user pool)")
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:200]}")


# =============================================================================
# Scenario C — 50-user simultaneous L1 flatten via REST (AC-11-4)
# =============================================================================
class FlattenUser(HttpUser):
    """Trigger the L1 halt+flatten through the real REST surface. DESTRUCTIVE
    (engages a real halt), off unless ENABLE_L1_FLATTEN=1. Requires the target
    stack to route to FakeBrokerAdapter (see fake_broker_patch.py) or it will hit
    real Alpaca. The deterministic, contention-focused measurement is
    flatten_50.py; this class exists so the flatten can also be exercised through
    the exact production HTTP + MFA-step-up path."""

    host = _BASE_URL
    wait_time = between(1, 1)
    fixed_count = 0  # set by --users; each user fires once

    def on_start(self):
        if os.environ.get("ENABLE_L1_FLATTEN") != "1":
            raise SystemExit(
                "FlattenUser is destructive; set ENABLE_L1_FLATTEN=1 to arm it "
                "and only on a dedicated stack."
            )
        self._u = _next_user()
        self._done = False

    @task
    def trigger_l1(self):
        if self._done:
            gevent.sleep(5)
            return
        self._done = True
        import pyotp

        u = self._u
        code = pyotp.TOTP(u["totp_secret"], interval=30, digits=6).now()
        headers = {"Authorization": f"Bearer {u['access']}"}
        body = {"scope": "USER", "active": True, "reason": "loadtest-L1", "mfa_code": code}
        with self.client.post(
            "/api/v1/risk/killswitches/", json=body, headers=headers,
            name="POST /api/v1/risk/killswitches/ (L1 flatten)", catch_response=True,
        ) as resp:
            if resp.status_code in (200, 201):
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:200]}")


# --- pretty end-of-run summary ----------------------------------------------
@events.quitting.add_listener
def _summary(environment, **_kw):
    st = environment.stats
    print("\n=== load-test summary ===")
    # Iterate EXISTING entries only — never call st.get(name, None), which would
    # insert a phantom (name, None) key and break locust's own shutdown sort.
    for (name, _method), entry in sorted(st.entries.items()):
        if entry.num_requests == 0:
            continue
        print(f"{name}: n={entry.num_requests} fail={entry.num_failures} "
              f"p50={entry.get_response_time_percentile(0.5)}ms "
              f"p95={entry.get_response_time_percentile(0.95)}ms "
              f"p99={entry.get_response_time_percentile(0.99)}ms")
    print(f"total requests={st.total.num_requests} failures={st.total.num_failures}")
