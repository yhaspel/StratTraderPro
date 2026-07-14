"""AlpacaAdapter (M04 §6.2; mode switch M13).

Execution mode comes from the **BrokerAccount** (``ctx.mode``), never from a
global setting: ``TradingClient(paper=self.is_paper)``. ``ENABLE_LIVE_TRADING``
is permission to *create* a live account — it is not a mode, and flipping it
must never move an existing paper account onto the live endpoint (M13 F-3).

Key shape is validated against the declared mode in both directions (M13 F-4):
live-shaped keys (``AK``/``BK``) on a PAPER account are refused with
``BROKER_LIVE_KEYS_FORBIDDEN`` — the guard that stops a mistaken paste reaching
a real account — and paper-shaped keys (``PK``) on a LIVE account are refused
with ``BROKER_PAPER_KEYS_ON_LIVE``, so an account labelled LIVE can never
quietly execute against the paper endpoint.

Every broker call is wrapped for latency/audit and retried with jittered
backoff on 429/5xx.
"""
from __future__ import annotations

import logging
import random
import time

from requests.adapters import HTTPAdapter

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
from ..live_gate import live_trading_permitted
from . import mapping
from .errors import (
    RETRYABLE_STATUS,
    looks_like_live_key,
    looks_like_paper_key,
    map_api_error,
)

logger = logging.getLogger(__name__)

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"
_MAX_RETRIES = 3
# Bound every Alpaca HTTP call so a black-holed TCP connection can't wedge a
# Celery worker or the streams catch-up forever (FIX-H7). Mirrors the TS client.
ALPACA_HTTP_TIMEOUT = 10.0


class _TimeoutHTTPAdapter(HTTPAdapter):
    """Injects a default request timeout — ``requests`` has no session-level one."""

    def __init__(self, *args, timeout=ALPACA_HTTP_TIMEOUT, **kwargs):
        self._timeout = timeout
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self._timeout
        return super().send(request, **kwargs)


def _apply_timeout(client, timeout: float = ALPACA_HTTP_TIMEOUT):
    """Mount a timeout adapter on the alpaca-py client's ``requests`` session.
    No-op for clients that don't expose a mountable ``requests`` session (the
    Celery task time-limit is the backstop there)."""
    session = getattr(client, "_session", None)
    if session is not None and hasattr(session, "mount"):
        adapter = _TimeoutHTTPAdapter(timeout=timeout)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    return client
# Alpaca supports US equities/ETFs and options (by OCC symbol). No futures.
_SUPPORTED_ASSET_CLASSES = ("STOCK", "ETF", "OPTION", "us_equity")
_SUPPORTED_ORDER_TYPES = (OrderType.MKT, OrderType.LMT, OrderType.STP, OrderType.STP_LMT)


class AlpacaAdapter:
    name = "alpaca"
    supported_asset_classes = list(_SUPPORTED_ASSET_CLASSES)

    def __init__(self, ctx: BrokerContext, *, client=None, data_client=None):
        self.ctx = ctx
        self._client = client  # injectable for tests
        self._data_client = data_client  # market-data client for get_quote (FIX-H3)

    # -- mode ---------------------------------------------------------------
    @property
    def is_paper(self) -> bool:
        """The endpoint follows the ACCOUNT, not a global flag (M13 F-3).

        `settings.ENABLE_LIVE_TRADING` is permission to *create* a LIVE account.
        It is deliberately NOT consulted here: if it were, flipping that one env
        var would silently move every existing paper account onto the live
        endpoint — turning a permission into a mode, which is precisely the
        class of blast-radius mistake this design exists to prevent.
        """
        return self.ctx.is_paper

    # -- client -------------------------------------------------------------
    @property
    def client(self):
        if self._client is None:
            from alpaca.trading.client import TradingClient

            self._client = _apply_timeout(
                TradingClient(
                    api_key=self.ctx.api_key_id,
                    secret_key=self.ctx.api_secret,
                    paper=self.is_paper,
                )
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
        # M13 F-4 — key shape must agree with the account's declared mode, in
        # BOTH directions. Checked before any key leaves the process.
        if self.is_paper:
            if looks_like_live_key(self.ctx.api_key_id):
                raise BrokerError(
                    BrokerErrorCode.LIVE_KEYS_FORBIDDEN,
                    "These look like LIVE trading keys, but this account is PAPER. "
                    "Connect a new account in live mode instead — an account's mode "
                    "cannot be changed after it is created.",
                )
        else:
            # Belt and braces: the API layer already refuses to create a LIVE
            # account while the gate is off (M13 F-2). Re-assert it at the
            # adapter, because this is the last place before real money — and a
            # row created while the flag was on must not keep trading live after
            # the operator turns it back off.
            if not live_trading_permitted():
                raise BrokerError(
                    BrokerErrorCode.LIVE_TRADING_DISABLED,
                    "Live trading is disabled on this deployment.",
                )
            if looks_like_paper_key(self.ctx.api_key_id):
                raise BrokerError(
                    BrokerErrorCode.PAPER_KEYS_ON_LIVE,
                    "These look like PAPER keys, but this account is LIVE. A live "
                    "account trading on the paper endpoint would misreport every "
                    "order it places.",
                )

        acct = self.get_account()
        return ConnectionInfo(
            account_number=acct.account_number,
            buying_power=acct.buying_power,
            currency=acct.currency,
            is_paper=self.is_paper,
        )

    def disconnect(self) -> None:
        self._client = None

    def get_account(self) -> Account:
        raw = self._call("get_account", lambda: self.client.get_account())
        # M13 — the account row is the only thing that knows paper vs live;
        # Alpaca's payload carries no discriminator.
        return mapping.map_account(raw, is_paper=self.is_paper)

    def get_quote(self, symbol: str):
        """Latest trade price for sizing (FIX-H3). Best-effort — returns None on
        any failure so the caller falls back to the last daily bar / rejects,
        never fabricating a price. Bounded by the Celery task time limit."""
        try:
            if self._data_client is None:
                from alpaca.data.historical import StockHistoricalDataClient

                self._data_client = _apply_timeout(
                    StockHistoricalDataClient(self.ctx.api_key_id, self.ctx.api_secret)
                )
            from alpaca.data.requests import StockLatestTradeRequest

            resp = self._data_client.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=symbol)
            )
            trade = resp.get(symbol) if isinstance(resp, dict) else resp
            price = getattr(trade, "price", None)
            return mapping._dec(price) if price is not None else None
        except Exception:  # noqa: BLE001 — quote is best-effort; degrade to bar/reject
            logger.warning("alpaca.get_quote.failed", extra={"symbol": symbol})
            return None

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
