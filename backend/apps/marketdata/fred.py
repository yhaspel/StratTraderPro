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
        self.base = base_url.rstrip("/")

    def series(self, series_id: str, **kw) -> list[dict]:
        import httpx

        client = self._http or httpx.Client(timeout=15.0)
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            **kw,
        }
        resp = client.get(f"{self.base}/series/observations", params=params)
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
