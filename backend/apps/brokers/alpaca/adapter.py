"""AlpacaAdapter (M04 §6.2) — paper trading only.

``TradingClient(paper=True)`` is hard-coded: the live endpoint is unreachable
by construction in M04. Live API keys (``AK``/``BK`` prefix) are rejected up
front with ``BROKER_LIVE_KEYS_FORBIDDEN`` so a mistaken paste can never reach a
real account. Every broker call is wrapped for latency/audit and retried with
jittered backoff on 429/5xx.
"""
from __future__ import annotations

import logging
import random
import time

from ..audit import record_broker_call
from ..base import (
    Account,
    BrokerConnState,
    BrokerContext,
    BrokerHealth,
    ConnectionInfo,
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderType,
    PositionDTO,
)
from ..errors import BrokerError, BrokerErrorCode
from . import mapping
from .errors import RETRYABLE_STATUS, looks_like_live_key, map_api_error

logger = logging.getLogger(__name__)

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
_MAX_RETRIES = 3
# Alpaca supports US equities/ETFs and options (by OCC symbol). No futures.
_SUPPORTED_ASSET_CLASSES = ("STOCK", "ETF", "OPTION", "us_equity")
_SUPPORTED_ORDER_TYPES = (OrderType.MKT, OrderType.LMT, OrderType.STP, OrderType.STP_LMT)


class AlpacaAdapter:
    name = "alpaca"
    supported_asset_classes = list(_SUPPORTED_ASSET_CLASSES)

    def __init__(self, ctx: BrokerContext, *, client=None):
        self.ctx = ctx
        self._client = client  # injectable for tests

    # -- client -------------------------------------------------------------
    @property
    def client(self):
        if self._client is None:
            from alpaca.trading.client import TradingClient

            self._client = TradingClient(
                api_key=self.ctx.api_key_id,
                secret_key=self.ctx.api_secret,
                paper=True,
            )
        return self._client

    # -- audited call wrapper ----------------------------------------------
    def _call(self, endpoint: str, fn, *, method: str = "GET", retry: bool = True):
        attempt = 0
        while True:
            attempt += 1
            t0 = time.monotonic()
            try:
                result = fn()
            except BrokerError:
                raise
            except Exception as exc:  # noqa: BLE001 — mapped to BrokerError below
                err = map_api_error(exc)
                latency = int((time.monotonic() - t0) * 1000)
                if retry and err.retryable and err.status in RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                    self._audit(endpoint, method, err.status, latency, ok=False, error_code=err.code)
                    time.sleep(_backoff(attempt))
                    continue
                self._audit(endpoint, method, err.status, latency, ok=False, error_code=err.code)
                raise err from exc
            latency = int((time.monotonic() - t0) * 1000)
            self._audit(endpoint, method, 200, latency, ok=True)
            return result

    def _audit(self, endpoint, method, status, latency, *, ok, error_code=""):
        record_broker_call(
            account_id=None if self.ctx.account_id in ("pending", "fake") else self.ctx.account_id,
            user_id=None if self.ctx.user_id in ("pending", "fake") else self.ctx.user_id,
            broker="ALPACA",
            endpoint=endpoint,
            method=method,
            status_code=status,
            latency_ms=latency,
            ok=ok,
            error_code=error_code,
        )

    # -- protocol -----------------------------------------------------------
    def connect(self) -> ConnectionInfo:
        if looks_like_live_key(self.ctx.api_key_id):
            raise BrokerError(
                BrokerErrorCode.LIVE_KEYS_FORBIDDEN,
                "These look like live trading keys; only Alpaca paper keys are allowed.",
            )
        acct = self.get_account()
        return ConnectionInfo(
            account_number=acct.account_number,
            buying_power=acct.buying_power,
            currency=acct.currency,
            is_paper=True,
        )

    def disconnect(self) -> None:
        self._client = None

    def get_account(self) -> Account:
        raw = self._call("get_account", lambda: self.client.get_account())
        return mapping.map_account(raw)

    def list_positions(self) -> list[PositionDTO]:
        raw = self._call("get_all_positions", lambda: self.client.get_all_positions())
        return [mapping.map_position(p) for p in (raw or [])]

    def list_open_orders(self) -> list[OrderAck]:
        def _fetch():
            from alpaca.trading.enums import QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest

            return self.client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))

        raw = self._call("get_orders", _fetch)
        return [mapping.map_order_ack(o) for o in (raw or [])]

    def place_order(self, req: OrderRequest, client_order_id: str) -> OrderAck:
        if req.asset_class not in _SUPPORTED_ASSET_CLASSES:
            raise BrokerError(
                BrokerErrorCode.UNSUPPORTED_ASSET,
                "Only US stocks and ETFs are supported in this milestone.",
            )
        if req.order_type not in _SUPPORTED_ORDER_TYPES:
            raise BrokerError(
                BrokerErrorCode.UNSUPPORTED_ORDER_TYPE,
                f"Order type {req.order_type} is not supported.",
            )
        order_data = mapping.build_order_request(req, client_order_id)

        # submit_order is NOT auto-retried: a timeout could mean the order DID
        # land. On failure we probe by client_order_id (idempotent) before
        # surfacing an error (plan §6.2 duplicate-guard).
        try:
            raw = self._call(
                "submit_order",
                lambda: self.client.submit_order(order_data=order_data),
                method="POST",
                retry=False,
            )
        except BrokerError as err:
            existing = self._lookup_by_client_id(client_order_id)
            if existing is not None:
                return mapping.map_order_ack(existing)
            raise err
        return mapping.map_order_ack(raw)

    def _lookup_by_client_id(self, client_order_id: str):
        try:
            return self._call(
                "get_order_by_client_id",
                lambda: self.client.get_order_by_client_id(client_order_id),
            )
        except BrokerError:
            return None

    def get_order_status(self, broker_order_id: str) -> str | None:
        """Fetch the broker's authoritative status for one order (used by the
        reconnect catch-up to resolve closed orders without assuming FILLED).
        Returns our ``Order.Status`` string, or None if unavailable."""
        try:
            raw = self._call(
                "get_order_by_id", lambda: self.client.get_order_by_id(broker_order_id)
            )
        except BrokerError:
            return None
        return mapping.map_order_ack(raw).status.value

    def cancel_order(self, broker_order_id: str) -> None:
        self._call(
            "cancel_order_by_id",
            lambda: self.client.cancel_order_by_id(broker_order_id),
            method="DELETE",
        )

    def flatten_all(self, reason: str) -> list[OrderAck]:
        raw = self._call(
            "close_all_positions",
            lambda: self.client.close_all_positions(cancel_orders=True),
            method="DELETE",
        )
        acks: list[OrderAck] = []
        for item in raw or []:
            body = getattr(item, "body", None)
            if body is not None:
                acks.append(mapping.map_order_ack(body))
            else:
                acks.append(
                    OrderAck(
                        client_order_id="",
                        broker_order_id=str(getattr(item, "order_id", "") or ""),
                        status=OrderStatus.SUBMITTED,
                        symbol=str(getattr(item, "symbol", "") or ""),
                        qty=mapping._dec(getattr(item, "qty", None)),
                    )
                )
        return acks

    def health(self) -> BrokerHealth:
        try:
            self.get_account()
            return BrokerHealth(state=BrokerConnState.CONNECTED, detail="ok")
        except BrokerError as exc:
            return BrokerHealth(state=BrokerConnState.DOWN, detail=exc.code)


def _backoff(attempt: int) -> float:
    """Exponential backoff with full jitter; capped for test-suite sanity."""
    base = min(2 ** (attempt - 1), 8)
    return base * (0.5 + random.random() * 0.5)  # noqa: S311 — jitter, not crypto
