"""M06 — market data: bar store idempotency, gap detection, FMP client."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.marketdata.fmp import (
    FMPCircuitOpen,
    FMPClient,
    FMPError,
    FMPRateLimited,
    FMPServerError,
)
from apps.marketdata.fred import FREDClient, FREDError
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

    def test_date_only_ts_stored_aware_and_idempotent(self):
        # FIX-M6-1: a date-only string parses to naive midnight — must be stored
        # tz-aware (UTC), and the (symbol,tf,ts) upsert stays idempotent.
        from django.utils import timezone as djtz

        row = [{"ts": "2026-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}]
        r1 = upsert_bars("SPY", "1d", row)
        self.assertEqual(r1["created"], 1)
        bar = Bar.objects.get(symbol="SPY", tf="1d")
        self.assertFalse(djtz.is_naive(bar.ts))
        self.assertEqual(bar.ts.hour, 0)  # midnight UTC
        r2 = upsert_bars("SPY", "1d", row)  # re-run
        self.assertEqual((r2["created"], r2["updated"]), (0, 1))

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

    def test_reuses_single_httpx_client(self):
        # FIX-M10: one client per instance, reused (no pool leak per call).
        client = FMPClient(api_key="k")  # no injected http
        with mock.patch("httpx.Client") as HC:
            HC.return_value = mock.Mock()
            first, second = client._client(), client._client()
        self.assertIs(first, second)
        HC.assert_called_once()

    def test_malformed_json_falls_back_to_cache(self):
        # FIX-M11: a 200 with a non-JSON body must route through resilience.
        client = FMPClient(api_key="k", http=_FakeHttp([_FakeResp(200, {"v": 1})]))
        self.assertEqual(client.get("/quote", {"symbol": "SPY"}), {"v": 1})  # caches

        class _BadJson:
            def get(self, url, params=None):
                return _BadJsonResp()

        client._http = _BadJson()
        self.assertEqual(client.get("/quote", {"symbol": "SPY"}), {"v": 1})  # cache-fallback

    def test_malformed_json_raises_without_cache(self):
        client = FMPClient(api_key="k", http=type("H", (), {
            "get": lambda self, url, params=None: _BadJsonResp()})())
        with self.assertRaises(FMPServerError):
            client.get("/quote", {"symbol": "NEVER_CACHED_M11"})


class _BadJsonResp:
    status_code = 200
    content = b"<html>error</html>"

    def json(self):
        raise ValueError("Expecting value: line 1 column 1")


class FREDClientTests(TestCase):
    def _http(self, payload):
        return type("H", (), {"get": lambda self, url, params=None: _FakeResp(200, payload)})()

    def test_series_parses_and_skips_missing(self):
        rows = FREDClient(api_key="k", http=self._http({"observations": [
            {"date": "2026-01-02", "value": "3.5"},
            {"date": "2026-01-03", "value": "."},
        ]})).series("BAMLH0A0HYM2")
        self.assertEqual(rows, [{"ts": "2026-01-02", "value": 3.5}])

    def test_transport_error_hides_api_key(self):
        # FIX-M12: a transport error must not surface the keyed request URL.
        import httpx

        class _Boom:
            def get(self, url, params=None):
                raise httpx.ConnectError("connection refused")

        with self.assertRaises(FREDError) as ctx:
            FREDClient(api_key="SUPERSECRETKEY", http=_Boom()).series("DGS10")
        self.assertNotIn("SUPERSECRETKEY", str(ctx.exception))

    def test_reuses_single_httpx_client(self):
        # FIX-M10: FRED reuses one client per instance too.
        client = FREDClient(api_key="k")
        with mock.patch("httpx.Client") as HC:
            HC.return_value = mock.Mock()
            self.assertIs(client._client(), client._client())
        HC.assert_called_once()
