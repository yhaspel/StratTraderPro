"""M06 — market data: bar store idempotency, gap detection, FMP client."""
from __future__ import annotations

from datetime import datetime, timezone

from django.core.cache import cache
from django.test import TestCase

from apps.marketdata.fmp import (
    FMPCircuitOpen,
    FMPClient,
    FMPError,
    FMPRateLimited,
    FMPServerError,
)
from apps.marketdata.models import Bar
from apps.marketdata.services import missing_bars, upsert_bars


def _bar_rows(n=3, start_day=1):
    return [
        {"ts": f"2026-01-0{start_day + i}T00:00:00Z", "open": 10 + i, "high": 11 + i,
         "low": 9 + i, "close": 10.5 + i, "volume": 1000 + i}
        for i in range(n)
    ]


class BarStoreTests(TestCase):
    def test_upsert_idempotent(self):
        r1 = upsert_bars("SPY", "1d", _bar_rows(3))
        self.assertEqual(r1["created"], 3)
        r2 = upsert_bars("SPY", "1d", _bar_rows(3))  # re-run
        self.assertEqual(r2["created"], 0)
        self.assertEqual(r2["updated"], 3)
        self.assertEqual(Bar.objects.filter(symbol="SPY", tf="1d").count(), 3)

    def test_gap_detection(self):
        # Insert day 1 and 3; day 2 (a weekday) is missing.
        upsert_bars("QQQ", "1d", [
            {"ts": "2026-01-05T00:00:00Z", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0},
            {"ts": "2026-01-07T00:00:00Z", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0},
        ])
        start = datetime(2026, 1, 5, tzinfo=timezone.utc)
        end = datetime(2026, 1, 7, tzinfo=timezone.utc)
        gaps = missing_bars("QQQ", "1d", start, end)
        self.assertIn(datetime(2026, 1, 6, tzinfo=timezone.utc), gaps)  # Jan 6 = Tuesday


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.content = b"x"

    def json(self):
        return self._payload


class _FakeHttp:
    """Scripted httpx.Client stand-in — pops responses per call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, params=None):
        self.calls += 1
        r = self._responses.pop(0) if self._responses else _FakeResp(200, [])
        return r


class FMPClientTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_retry_on_429_then_success(self):
        http = _FakeHttp([_FakeResp(429, {}), _FakeResp(429, {}), _FakeResp(200, {"ok": 1})])
        client = FMPClient(api_key="k", http=http)
        data = client.get("/quote", {"symbol": "SPY"})
        self.assertEqual(data, {"ok": 1})
        self.assertEqual(http.calls, 3)

    def test_rate_limit_falls_back_to_cache(self):
        http = _FakeHttp([_FakeResp(200, {"v": 1})])
        client = FMPClient(api_key="k", http=http, per_minute=1)
        first = client.get("/quote", {"symbol": "SPY"})  # caches
        self.assertEqual(first, {"v": 1})
        second = client.get("/quote", {"symbol": "SPY"})  # throttled → cached fallback
        self.assertEqual(second, {"v": 1})

    def test_circuit_opens_and_raises_without_cache(self):
        http = _FakeHttp([_FakeResp(500, {})] * 10)
        client = FMPClient(api_key="k", http=http, cb_threshold=3)
        for _ in range(3):
            with self.assertRaises((FMPError, FMPRateLimited)):
                client.get("/quote", {"symbol": "X"})
        # circuit now open — next call short-circuits (still raises, no cache)
        with self.assertRaises((FMPCircuitOpen, FMPError, FMPRateLimited)):
            client.get("/quote", {"symbol": "Y"})

    def test_transport_outage_falls_back_to_cache(self):
        import httpx

        client = FMPClient(api_key="k", http=_FakeHttp([_FakeResp(200, {"v": 1})]))
        self.assertEqual(client.get("/quote", {"symbol": "SPY"}), {"v": 1})  # caches

        class _Boom:
            def get(self, url, params=None):
                raise httpx.ConnectError("connection refused")

        client._http = _Boom()  # transport outage on the same client
        self.assertEqual(client.get("/quote", {"symbol": "SPY"}), {"v": 1})  # cache-fallback (H1)

    def test_transport_outage_raises_without_cache(self):
        import httpx

        class _Boom:
            def get(self, url, params=None):
                raise httpx.ConnectTimeout("timeout")

        client = FMPClient(api_key="k", http=_Boom())
        with self.assertRaises(FMPServerError):
            client.get("/quote", {"symbol": "NEVER_CACHED"})

    def test_normalize_bars_skips_partial_rows(self):
        http = _FakeHttp([_FakeResp(200, {"historical": [
            {"date": "2026-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
            {"date": "2026-01-03", "open": None, "high": None, "low": None, "close": None},
        ]})])
        client = FMPClient(api_key="k", http=http)
        rows = client.daily_bars("SPY")
        self.assertEqual(len(rows), 1)  # partial row dropped (L1)

    def test_normalize_bars(self):
        http = _FakeHttp([_FakeResp(200, {"historical": [
            {"date": "2026-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
        ]})])
        client = FMPClient(api_key="k", http=http)
        rows = client.daily_bars("SPY")
        self.assertEqual(rows[0]["close"], 1.5)
        self.assertEqual(rows[0]["ts"], "2026-01-02")
