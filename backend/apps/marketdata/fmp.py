"""FinancialModelingPrep client (M06 §6.1).

Token-bucket rate limiting, jittered retry on 429/5xx (tenacity), a simple
circuit breaker, and a response cache with cache-fallback so a rate-limit/outage
never surfaces a 5xx on the dashboard (AC-06-9). HTTP is injectable for tests —
no live FMP calls in CI (an API key is a deferred external).
"""
from __future__ import annotations

import hashlib
import logging
import time

from django.conf import settings
from django.core.cache import cache
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from .metrics import MARKETDATA_RATELIMIT_WAITS, MARKETDATA_REQUESTS

logger = logging.getLogger(__name__)

_CB_FAILS_KEY = "fmp:cb:fails"
_CB_OPEN_KEY = "fmp:cb:open"


class FMPError(Exception):
    pass


class FMPRateLimited(FMPError):
    pass


class FMPCircuitOpen(FMPError):
    pass


class FMPClient:
    def __init__(self, *, api_key=None, base_url=None, http=None,
                 per_minute=None, cb_threshold=5, cb_cooldown=60):
        self.api_key = api_key if api_key is not None else getattr(settings, "FMP_API_KEY", "")
        self.base = (base_url or getattr(settings, "FMP_BASE_URL", "https://financialmodelingprep.com/stable")).rstrip("/")
        self._http = http
        self.per_minute = per_minute or getattr(settings, "FMP_RATE_LIMIT_PER_MIN", 750)
        self.cb_threshold = cb_threshold
        self.cb_cooldown = cb_cooldown

    # -- rate limit (token bucket, fixed window) ---------------------------
    def _throttle(self) -> None:
        bucket = int(time.time() // 60)
        key = f"fmp:rl:{bucket}"
        try:
            cache.add(key, 0, timeout=90)
            n = cache.incr(key)
        except ValueError:  # pragma: no cover
            cache.set(key, 1, timeout=90)
            n = 1
        if n > self.per_minute:
            MARKETDATA_RATELIMIT_WAITS.inc()
            raise FMPRateLimited("client-side per-minute cap reached")

    # -- circuit breaker ----------------------------------------------------
    def _check_circuit(self) -> None:
        if cache.get(_CB_OPEN_KEY):
            raise FMPCircuitOpen("circuit open")

    def _record_failure(self) -> None:
        try:
            cache.add(_CB_FAILS_KEY, 0, timeout=self.cb_cooldown)
            fails = cache.incr(_CB_FAILS_KEY)
        except ValueError:  # pragma: no cover
            cache.set(_CB_FAILS_KEY, 1, timeout=self.cb_cooldown)
            fails = 1
        if fails >= self.cb_threshold:
            cache.set(_CB_OPEN_KEY, True, timeout=self.cb_cooldown)

    def _record_success(self) -> None:
        cache.delete(_CB_FAILS_KEY)

    # -- request ------------------------------------------------------------
    def _raw_get(self, path: str, params: dict):
        import httpx

        client = self._http or httpx.Client(timeout=15.0)
        q = {**params, "apikey": self.api_key}
        resp = client.get(f"{self.base}{path}", params=q)
        if resp.status_code == 429:
            raise FMPRateLimited("429")
        if resp.status_code >= 500:
            raise FMPError(f"{resp.status_code}")
        if resp.status_code >= 400:
            raise FMPError(f"HTTP {resp.status_code}")
        return resp.json()

    @retry(
        retry=retry_if_exception_type((FMPRateLimited, FMPError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.1, max=2.0),
        reraise=True,
    )
    def _get_with_retry(self, path, params):
        return self._raw_get(path, params)

    def get(self, path: str, params: dict, *, cache_ttl: int = 30, cache_key: str | None = None):
        """Rate-limited + retried GET with a cache-fallback. On rate-limit /
        circuit-open / exhausted retries, return the last cached response if we
        have one (never raise into a dashboard 5xx)."""
        if cache_key is None:
            digest = hashlib.sha256(f"{path}:{sorted(params.items())}".encode()).hexdigest()[:32]
            cache_key = f"fmp:resp:{digest}"
        ck = cache_key
        try:
            self._check_circuit()
            self._throttle()
            data = self._get_with_retry(path, params)
            self._record_success()
            MARKETDATA_REQUESTS.labels(endpoint=path.strip("/").split("/")[0] or "root", result="ok").inc()
            cache.set(ck, data, timeout=max(cache_ttl, 30))
            return data
        except (FMPRateLimited, FMPCircuitOpen, FMPError):
            self._record_failure()
            MARKETDATA_REQUESTS.labels(
                endpoint=path.strip("/").split("/")[0] or "root", result="fail"
            ).inc()
            cached = cache.get(ck)
            if cached is not None:
                logger.warning("fmp.cache_fallback", extra={"path": path})
                return cached
            raise

    # -- endpoints ----------------------------------------------------------
    def daily_bars(self, symbol: str) -> list[dict]:
        data = self.get("/historical-price-eod/full", {"symbol": symbol}, cache_ttl=86400)
        return _normalize_bars(data)

    def intraday_bars(self, symbol: str, tf: str = "5min", **kw) -> list[dict]:
        data = self.get(f"/historical-chart/{tf}", {"symbol": symbol, **kw}, cache_ttl=30)
        return _normalize_bars(data)

    def quote(self, symbol: str) -> dict:
        data = self.get("/quote", {"symbol": symbol}, cache_ttl=15)
        return (data[0] if isinstance(data, list) and data else data) or {}

    def treasury_yield_curve(self, **kw) -> list[dict]:
        return self.get("/economics/treasury-yield-curve", kw, cache_ttl=3600) or []

    def sector_performance(self) -> list[dict]:
        return self.get("/historical-sector-performance", {}, cache_ttl=3600) or []


def _normalize_bars(data) -> list[dict]:
    rows = data.get("historical", data) if isinstance(data, dict) else data
    out = []
    for r in rows or []:
        ts = r.get("date") or r.get("datetime") or r.get("timestamp")
        if ts is None:
            continue
        out.append({
            "ts": ts, "open": r.get("open"), "high": r.get("high"),
            "low": r.get("low"), "close": r.get("close"), "volume": r.get("volume", 0),
        })
    return out
