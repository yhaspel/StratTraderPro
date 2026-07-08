"""FRED client (M06 §6.3) — credit spreads / macro series over plain httpx.

Free API; key is a deferred external (fixture-mocked in CI).
"""
from __future__ import annotations

from django.conf import settings


class FREDError(Exception):
    pass


class FREDClient:
    def __init__(self, *, api_key=None, http=None, base_url="https://api.stlouisfed.org/fred"):
        self.api_key = api_key if api_key is not None else getattr(settings, "FRED_API_KEY", "")
        self._http = http
        self._owned_http = None  # one reused client per instance (FIX-M10)
        self.base = base_url.rstrip("/")

    def _client(self):
        if self._http is not None:
            return self._http
        if self._owned_http is None:
            import httpx

            self._owned_http = httpx.Client(timeout=15.0)
        return self._owned_http

    def close(self) -> None:
        if self._owned_http is not None:
            self._owned_http.close()
            self._owned_http = None

    def series(self, series_id: str, **kw) -> list[dict]:
        import httpx

        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            **kw,
        }
        # One retry on a transport error; re-raise as FREDError from None so the
        # keyed request URL never surfaces (Sentry request-context leak) — FIX-M12.
        last_exc = None
        for _attempt in range(2):
            try:
                resp = self._client().get(f"{self.base}/series/observations", params=params)
            except httpx.RequestError as exc:
                last_exc = FREDError(f"transport: {type(exc).__name__}")
                continue
            if resp.status_code >= 400:
                raise FREDError(f"HTTP {resp.status_code}")
            data = resp.json()
            out = []
            for o in data.get("observations", []):
                val = o.get("value")
                if val in (None, ".", ""):
                    continue
                out.append({"ts": o["date"], "value": float(val)})
            return out
        raise last_exc from None
