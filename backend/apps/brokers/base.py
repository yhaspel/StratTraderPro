"""Broker-neutral contract (M04 §6.1).

The :class:`BrokerAdapter` protocol is the seam that made the IBKR→Alpaca
pivot cheap (ADR-041): everything above it speaks in the DTOs defined here,
never in a vendor SDK's types. ``FakeBrokerAdapter`` (tests) and
``AlpacaAdapter`` (paper) both satisfy it; TradeStation (M05) slots in later
without touching a single call site.

Design decisions carried from the plan:
- ``connect()`` takes **no** creds argument — an adapter is constructed per
  ``BrokerAccount`` and decrypts internally, so plaintext keys never travel
  through call sites.
- ``stream_fills()`` is **not** on the protocol — streaming is owned by the
  ``run_broker_streams`` service (§6.5), which writes normalized fills to a
  Redis Stream. Adapters stay synchronous and simple.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MKT = "MKT"
    LMT = "LMT"


class TimeInForce(str, Enum):
    DAY = "DAY"


class OrderStatus(str, Enum):
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class BrokerConnState(str, Enum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


# ---------------------------------------------------------------------------
# DTOs — plain dataclasses; adapters map their SDK types into these.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ConnectionInfo:
    account_number: str
    buying_power: Decimal
    currency: str = "USD"
    is_paper: bool = True


@dataclass(frozen=True)
class Account:
    account_number: str
    buying_power: Decimal
    cash: Decimal
    currency: str = "USD"
    status: str = "ACTIVE"
    is_paper: bool = True


@dataclass(frozen=True)
class PositionDTO:
    symbol: str
    qty: Decimal
    avg_cost: Decimal
    market_price: Decimal | None = None
    side: Side = Side.BUY


@dataclass(frozen=True)
class OrderRequest:
    """What the caller wants placed. ``client_order_id`` is passed separately
    to ``place_order`` so the idempotency anchor is explicit."""

    symbol: str
    side: Side
    qty: Decimal
    order_type: OrderType = OrderType.MKT
    limit_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    asset_class: str = "us_equity"


@dataclass(frozen=True)
class OrderAck:
    client_order_id: str
    broker_order_id: str
    status: OrderStatus
    symbol: str
    qty: Decimal
    filled_qty: Decimal = Decimal("0")
    submitted_at: str | None = None


@dataclass(frozen=True)
class FillEvent:
    """Normalized ``trade_updates`` event written to Redis by the streams
    service and consumed by ``FillIngestor`` (§6.4/§6.5). ``broker_exec_id``
    is the dedup anchor — unique per execution."""

    broker_exec_id: str
    client_order_id: str
    broker_order_id: str
    symbol: str
    side: Side
    event_type: str  # fill | partial_fill | canceled | rejected | new
    qty: Decimal = Decimal("0")
    price: Decimal = Decimal("0")
    ts: str | None = None
    filled_qty: Decimal = Decimal("0")


@dataclass(frozen=True)
class BrokerHealth:
    state: BrokerConnState
    detail: str = ""
    checked_at: str | None = None


@dataclass
class BrokerContext:
    """Everything an adapter needs, resolved from a ``BrokerAccount`` row.
    Keys are decrypted once by the factory (``brokers.services.build_adapter``)
    and never logged."""

    account_id: str
    user_id: str
    api_key_id: str = field(repr=False, default="")
    api_secret: str = field(repr=False, default="")
    account_number: str = ""

    def __repr__(self) -> str:  # pragma: no cover — redaction guard
        return f"BrokerContext(account_id={self.account_id!r}, user_id={self.user_id!r})"


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------
@runtime_checkable
class BrokerAdapter(Protocol):
    name: str
    supported_asset_classes: list[str]

    def connect(self) -> ConnectionInfo: ...
    def disconnect(self) -> None: ...
    def get_account(self) -> Account: ...
    def list_positions(self) -> list[PositionDTO]: ...
    def list_open_orders(self) -> list[OrderAck]: ...
    def place_order(self, req: OrderRequest, client_order_id: str) -> OrderAck: ...
    def cancel_order(self, broker_order_id: str) -> None: ...
    def flatten_all(self, reason: str) -> list[OrderAck]: ...
    def health(self) -> BrokerHealth: ...
