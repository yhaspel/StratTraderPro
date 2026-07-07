"""Thin TradeStation API v3 client (M05 §7).

No official Python SDK — a small ``httpx`` client with transparent OAuth2 token
refresh on 401. Behind ``BROKER_TRADESTATION_ENABLED``; live-verified once API
access is granted. All HTTP is injectable so tests run with recorded fixtures /
mocks and never hit the network.
"""
from __future__ import annotations

import logging

from django.conf import settings

from ..errors import BrokerError, BrokerErrorCode

logger = logging.getLogger(__name__)


class TSAuthError(BrokerError):
    def __init__(self, message="TradeStation re-authentication required."):
        super().__init__("BROKER_REAUTH_REQUIRED", message, retryable=False, status=401)


def _http():
    import httpx

    return httpx.Client(timeout=10.0)


def exchange_code_for_tokens(code: str, code_verifier: str, *, http=None) -> dict:
    """authorization_code → token set. Returns the raw token dict."""
    http = http or _http()
    base = settings.TRADESTATION_OAUTH_BASE.rstrip("/")
    resp = http.post(
        f"{base}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.TRADESTATION_CLIENT_ID,
            "client_secret": settings.TRADESTATION_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.TRADESTATION_REDIRECT_URI,
            "code_verifier": code_verifier,
        },
    )
    if resp.status_code >= 400:
        raise BrokerError(BrokerErrorCode.AUTH_FAILED, "TradeStation code exchange failed.", status=resp.status_code)
    return resp.json()


class TSClient:
    def __init__(self, *, access_token, refresh_token, on_refresh=None, http=None):
        self._access = access_token
        self._refresh = refresh_token
        self._on_refresh = on_refresh
        self._http = http or _http()
        self._base = settings.TRADESTATION_API_BASE.rstrip("/")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access}", "Content-Type": "application/json"}

    def refresh(self) -> None:
        from ..metrics import OAUTH_REFRESH_TOTAL

        base = settings.TRADESTATION_OAUTH_BASE.rstrip("/")
        resp = self._http.post(
            f"{base}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.TRADESTATION_CLIENT_ID,
                "client_secret": settings.TRADESTATION_CLIENT_SECRET,
                "refresh_token": self._refresh,
            },
        )
        if resp.status_code >= 400:
            OAUTH_REFRESH_TOTAL.labels(broker="tradestation", result="fail").inc()
            raise TSAuthError()
        data = resp.json()
        self._access = data["access_token"]
        self._refresh = data.get("refresh_token", self._refresh)
        OAUTH_REFRESH_TOTAL.labels(broker="tradestation", result="ok").inc()
        if self._on_refresh:
            self._on_refresh(self._access, self._refresh, data.get("expires_in"))

    def _request(self, method: str, path: str, *, json=None, _retry=True):
        resp = self._http.request(
            method, f"{self._base}{path}", headers=self._headers(), json=json
        )
        if resp.status_code == 401 and _retry:
            self.refresh()
            return self._request(method, path, json=json, _retry=False)
        if resp.status_code == 429:
            raise BrokerError(
                BrokerErrorCode.RATE_LIMITED, "TradeStation rate limit.", retryable=True, status=429
            )
        if resp.status_code >= 500:
            raise BrokerError(
                BrokerErrorCode.UNAVAILABLE,
                "TradeStation unavailable.",
                retryable=True,
                status=resp.status_code,
            )
        if resp.status_code >= 400:
            raise BrokerError(
                BrokerErrorCode.ORDER_REJECTED,
                "TradeStation rejected the request.",
                status=resp.status_code,
            )
        return resp.json() if resp.content else {}

    # -- endpoints ----------------------------------------------------------
    def get_accounts(self) -> list[dict]:
        data = self._request("GET", "/brokerage/accounts")
        return data.get("Accounts", data) if isinstance(data, dict) else data

    def get_positions(self, account_number: str) -> list[dict]:
        data = self._request("GET", f"/brokerage/accounts/{account_number}/positions")
        return data.get("Positions", []) if isinstance(data, dict) else data

    def get_orders(self, account_number: str) -> list[dict]:
        data = self._request("GET", f"/brokerage/accounts/{account_number}/orders")
        return data.get("Orders", []) if isinstance(data, dict) else data

    def place_order(self, payload: dict) -> dict:
        data = self._request("POST", "/orderexecution/orders", json=payload)
        orders = data.get("Orders") if isinstance(data, dict) else None
        return (orders or [data])[0] if orders is not None else data

    def get_order(self, account_number: str, order_id: str) -> dict:
        return self._request("GET", f"/brokerage/accounts/{account_number}/orders/{order_id}")

    def cancel_order(self, order_id: str) -> None:
        self._request("DELETE", f"/orderexecution/orders/{order_id}")
