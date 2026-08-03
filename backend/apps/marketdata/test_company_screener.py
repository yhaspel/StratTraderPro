"""``FMPClient.company_screener`` contract test (M16 §10.1, ADR-063).

The recorded fixture is the **tripwire** the ADR-061 §4 vendor-change gate asks
for: if FMP renames or drops a screened field, this fails in CI rather than
silently returning half-populated rows to a user. Extra fields are tolerated
(vendors add columns); missing ones are not.
"""
from __future__ import annotations

import json
import pathlib

from django.core.cache import cache
from django.test import TestCase

from apps.marketdata.fmp import FMPClient, FMPError, FMPRateLimited

FIXTURE = pathlib.Path(__file__).parent.parent / "screener" / "fixtures" / "company_screener.json"
ROWS = json.loads(FIXTURE.read_text())

# The documented response contract (§6.2). Recorded as
# *documented-contract-to-verify* — the vendor's param table is JS-rendered, so
# AC-16-12 mandates a live re-validation once a real key is present.
DOCUMENTED_FIELDS = {
    "symbol", "companyName", "marketCap", "sector", "industry", "beta", "price",
    "lastAnnualDividend", "volume", "exchange", "exchangeShortName", "country",
    "isEtf", "isActivelyTrading",
}


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self._responses.pop(0) if self._responses else _Resp(200, [])


class CompanyScreenerContractTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_fixture_carries_every_documented_field(self):
        for row in ROWS:
            missing = DOCUMENTED_FIELDS - set(row)
            self.assertFalse(missing, f"fixture row {row.get('symbol')} missing {missing}")

    def test_returns_rows_and_hits_the_documented_path(self):
        http = _FakeHttp([_Resp(200, ROWS)])
        client = FMPClient(api_key="k", http=http)
        rows = client.company_screener({"marketCapMoreThan": 2_000_000_000, "limit": 3})
        self.assertEqual(len(rows), 3)
        url, params = http.calls[0]
        self.assertTrue(url.endswith("/company-screener"))
        self.assertEqual(params["marketCapMoreThan"], 2_000_000_000)
        self.assertEqual(params["limit"], 3)

    def test_params_are_passed_through_untouched_plus_the_key(self):
        http = _FakeHttp([_Resp(200, [])])
        client = FMPClient(api_key="secret-key", http=http)
        sent = {"sector": "Technology", "isActivelyTrading": True, "isEtf": False}
        client.company_screener(dict(sent))
        _, params = http.calls[0]
        for key, value in sent.items():
            self.assertEqual(params[key], value)
        self.assertEqual(params["apikey"], "secret-key")

    def test_extra_vendor_fields_are_tolerated(self):
        enriched = [{**ROWS[0], "someNewColumn": 42}]
        http = _FakeHttp([_Resp(200, enriched)])
        rows = FMPClient(api_key="k", http=http).company_screener({})
        self.assertEqual(rows[0]["someNewColumn"], 42)
        self.assertEqual(rows[0]["symbol"], "NVDA")

    def test_empty_or_null_body_becomes_an_empty_list(self):
        http = _FakeHttp([_Resp(200, None)])
        self.assertEqual(FMPClient(api_key="k", http=http).company_screener({}), [])

    def test_rides_the_shared_resilience_stack_retry_then_success(self):
        http = _FakeHttp([_Resp(429, {}), _Resp(429, {}), _Resp(200, ROWS)])
        rows = FMPClient(api_key="k", http=http).company_screener({})
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(http.calls), 3)

    def test_rate_limit_with_a_cold_cache_raises(self):
        http = _FakeHttp([_Resp(429, {}), _Resp(429, {}), _Resp(429, {})])
        with self.assertRaises(FMPRateLimited):
            FMPClient(api_key="k", http=http).company_screener({"a": 1})

    def test_tier_blocked_key_surfaces_as_a_plain_fmp_error(self):
        """A 4xx (endpoint not in the plan's tier) must NOT be retried and must
        land as ``FMPError`` -> run FAILED FMP_UNAVAILABLE (§7)."""
        http = _FakeHttp([_Resp(403, {})])
        with self.assertRaises(FMPError):
            FMPClient(api_key="k", http=http).company_screener({"b": 2})
        self.assertEqual(len(http.calls), 1)  # no retry on 4xx

    def test_cache_fallback_serves_the_last_good_payload(self):
        """AC-06-9 semantics come for free from the shared stack."""
        params = {"sector": "Technology"}
        ok_http = _FakeHttp([_Resp(200, ROWS)])
        FMPClient(api_key="k", http=ok_http).company_screener(dict(params))
        dead = _FakeHttp([_Resp(500, {}), _Resp(500, {}), _Resp(500, {})])
        rows = FMPClient(api_key="k", http=dead).company_screener(dict(params))
        self.assertEqual(len(rows), 3)

    def test_endpoint_label_for_the_metrics_series(self):
        """§6.8 relies on marketdata_requests_total{endpoint="company-screener"}."""
        from apps.marketdata.metrics import MARKETDATA_REQUESTS

        before = MARKETDATA_REQUESTS.labels(endpoint="company-screener", result="ok")._value.get()
        FMPClient(api_key="k", http=_FakeHttp([_Resp(200, ROWS)])).company_screener({"z": 1})
        after = MARKETDATA_REQUESTS.labels(endpoint="company-screener", result="ok")._value.get()
        self.assertEqual(after, before + 1)
