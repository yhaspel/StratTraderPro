"""TradeStationPaperAdapter (M05 §6.1) — sim/paper only.

Satisfies the same ``BrokerAdapter`` protocol as Alpaca. Constructed per
``BrokerAccount``; decrypts OAuth tokens internally and persists refreshed
tokens back to the row. Behind ``BROKER_TRADESTATION_ENABLED``; the live OAuth
handshake + real sim fills are verified once API access is granted.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from ..audit import record_broker_call
from ..base import (
    Account,
    BrokerConnState,
    BrokerHealth,
    ConnectionInfo,
    OrderAck,
    OrderRequest,
    OrderStatus,
    PositionDTO,
    Side,
)
from ..errors import BrokerError
from . import mapping
from .client import TSClient

logger = logging.getLogger(__name__)


class TradeStationPaperAdapter:
    name = "tradestation"
    supported_asset_classes = ["STOCK", "ETF", "OPTION", "FUTURE"]

    def __init__(self, account, *, client: TSClient | None = None):
        self.account = account
        self.account_number = account.account_number
        self._client = client

    @property
    def client(self) -> TSClient:
        if self._client is None:
            from ..services import decrypt_key

            self._client = TSClient(
                access_token=decrypt_key(self.account.ts_access_token_enc),
                refresh_token=decrypt_key(self.account.ts_refresh_token_enc),
                on_refresh=self._persist_tokens,
            )
        return self._client

    def _persist_tokens(self, access, refresh, expires_in):
        from datetime import timedelta

        from ..services import encrypt_key

        self.account.ts_access_token_enc = encrypt_key(access)
        self.account.ts_refresh_token_enc = encrypt_key(refresh)
        if expires_in:
            self.account.ts_expires_at = timezone.now() + timedelta(seconds=int(expires_in))
        self.account.save(
            update_fields=["ts_access_token_enc", "ts_refresh_token_enc", "ts_expires_at", "updated_at"]
        )

    def _audit(self, endpoint, ok, error_code=""):
        record_broker_call(
            account_id=self.account.id, user_id=self.account.user_id, broker="TRADESTATION",
            endpoint=endpoint, ok=ok, error_code=error_code,
        )

    def connect(self) -> ConnectionInfo:
        acct = self.get_account()
        return ConnectionInfo(
            account_number=acct.account_number, buying_power=acct.buying_power, is_paper=True
        )

    def disconnect(self) -> None:
        self._client = None

    def get_account(self) -> Account:
        try:
            accounts = self.client.get_accounts()
            self._audit("get_accounts", True)
        except BrokerError as exc:
            self._audit("get_accounts", False, exc.code)
            raise
        match = next(
            (a for a in accounts if str(a.get("AccountID")) == self.account_number),
            accounts[0] if accounts else {},
        )
        return mapping.from_ts_account(match)

    def list_positions(self) -> list[PositionDTO]:
        rows = self.client.get_positions(self.account_number)
        return [mapping.from_ts_position(r) for r in rows]

    def list_open_orders(self) -> list[OrderAck]:
        rows = self.client.get_orders(self.account_number)
        acks = [mapping.from_ts_order(r) for r in rows]
        return [a for a in acks if a.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL)]

    def place_order(self, req: OrderRequest, client_order_id: str) -> OrderAck:
        payload = mapping.to_ts_order_payload(req, client_order_id, self.account_number)
        try:
            resp = self.client.place_order(payload)
            self._audit("place_order", True)
        except BrokerError as exc:
            self._audit("place_order", False, exc.code)
            raise
        return mapping.from_ts_order(resp)

    def cancel_order(self, broker_order_id: str) -> None:
        self.client.cancel_order(broker_order_id)

    def get_order_status(self, broker_order_id: str) -> str | None:
        try:
            d = self.client.get_order(self.account_number, broker_order_id)
        except BrokerError:
            return None
        return mapping.from_ts_order(d).status.value

    def flatten_all(self, reason: str) -> list[OrderAck]:
        """TS has no one-call flatten; place an opposing market order per open
        position."""
        acks: list[OrderAck] = []
        for pos in self.list_positions():
            if pos.qty == 0:
                continue
            side = Side.SELL if pos.qty > 0 else Side.BUY
            req = OrderRequest(symbol=pos.symbol, side=side, qty=abs(pos.qty))
            try:
                acks.append(self.place_order(req, client_order_id=f"tsflat-{pos.symbol}"))
            except BrokerError:  # pragma: no cover — best-effort flatten
                logger.warning("ts.flatten.partial", extra={"symbol": pos.symbol})
        return acks

    def health(self) -> BrokerHealth:
        try:
            self.get_account()
            return BrokerHealth(state=BrokerConnState.CONNECTED, detail="ok")
        except BrokerError as exc:
            return BrokerHealth(state=BrokerConnState.DOWN, detail=exc.code)
