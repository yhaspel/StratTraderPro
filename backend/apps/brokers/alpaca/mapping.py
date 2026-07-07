"""OrderRequest ↔ alpaca-py request models, and Alpaca DTO → our DTO mapping.

Reads are defensive (``getattr`` + ``Decimal(str(...))``) so the same code path
works against live SDK objects, recorded JSON fixtures, and simple test doubles.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from alpaca.trading.enums import OrderSide
from alpaca.trading.enums import TimeInForce as AlpacaTIF
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    StopLimitOrderRequest,
    StopOrderRequest,
)

from ..base import (
    Account,
    FillEvent,
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderType,
    PositionDTO,
    Side,
    TimeInForce,
)

# Open/close option sides collapse to plain BUY/SELL at Alpaca.
_SIDE_TO_ALPACA = {
    Side.BUY: OrderSide.BUY,
    Side.SELL: OrderSide.SELL,
}
_BUY_SIDES = {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}

_TIF_TO_ALPACA = {
    TimeInForce.DAY: AlpacaTIF.DAY,
    TimeInForce.GTC: AlpacaTIF.GTC,
    TimeInForce.IOC: AlpacaTIF.IOC,
}

# Alpaca order status strings → our OrderStatus.
_STATUS_MAP = {
    "new": OrderStatus.SUBMITTED,
    "accepted": OrderStatus.SUBMITTED,
    "accepted_for_bidding": OrderStatus.SUBMITTED,
    "pending_new": OrderStatus.PENDING_SUBMIT,
    "pending_cancel": OrderStatus.SUBMITTED,
    "pending_replace": OrderStatus.SUBMITTED,
    "held": OrderStatus.SUBMITTED,
    "partially_filled": OrderStatus.PARTIAL,
    "filled": OrderStatus.FILLED,
    "done_for_day": OrderStatus.SUBMITTED,
    "canceled": OrderStatus.CANCELLED,
    "cancelled": OrderStatus.CANCELLED,
    "expired": OrderStatus.CANCELLED,
    "replaced": OrderStatus.CANCELLED,
    "stopped": OrderStatus.SUBMITTED,
    "rejected": OrderStatus.REJECTED,
    "suspended": OrderStatus.SUBMITTED,
    "calculated": OrderStatus.SUBMITTED,
}

# trade_updates event → our normalized event_type.
_EVENT_MAP = {
    "new": "new",
    "fill": "fill",
    "partial_fill": "partial_fill",
    "canceled": "canceled",
    "cancelled": "canceled",
    "rejected": "rejected",
    "expired": "canceled",
    "done_for_day": "new",
    "replaced": "canceled",
    "accepted": "new",
    "pending_new": "new",
}


def _dec(value, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):  # pragma: no cover
        return Decimal(default)


def _enum_value(v) -> str:
    return str(getattr(v, "value", v) or "").lower()


# ---------------------------------------------------------------------------
# Request construction
# ---------------------------------------------------------------------------
def _alpaca_side(side) -> OrderSide:
    raw = getattr(side, "value", side)
    return OrderSide.BUY if str(raw) in _BUY_SIDES else OrderSide.SELL


def build_order_request(req: OrderRequest, client_order_id: str):
    """OrderRequest → alpaca-py request model. MKT/LMT/STP/STP_LMT + DAY/GTC/IOC
    (M05). Options are passed by OPRA/OCC symbol; futures are rejected upstream."""
    tif = _TIF_TO_ALPACA.get(req.time_in_force, AlpacaTIF.DAY)
    common = {
        "symbol": req.symbol,
        "qty": float(req.qty),
        "side": _alpaca_side(req.side),
        "time_in_force": tif,
        "client_order_id": client_order_id,
    }
    if req.order_type == OrderType.LMT:
        return LimitOrderRequest(limit_price=float(req.limit_price), **common)
    if req.order_type == OrderType.STP:
        return StopOrderRequest(stop_price=float(req.stop_price), **common)
    if req.order_type == OrderType.STP_LMT:
        return StopLimitOrderRequest(
            stop_price=float(req.stop_price), limit_price=float(req.limit_price), **common
        )
    return MarketOrderRequest(**common)


# ---------------------------------------------------------------------------
# Response mapping
# ---------------------------------------------------------------------------
def map_account(acct) -> Account:
    return Account(
        account_number=str(getattr(acct, "account_number", "") or ""),
        buying_power=_dec(getattr(acct, "buying_power", None)),
        cash=_dec(getattr(acct, "cash", None)),
        currency=str(getattr(acct, "currency", "USD") or "USD"),
        status=_enum_value(getattr(acct, "status", "ACTIVE")).upper() or "ACTIVE",
        is_paper=True,
    )


def map_position(pos) -> PositionDTO:
    qty = _dec(getattr(pos, "qty", None))
    side_raw = _enum_value(getattr(pos, "side", "long"))
    side = Side.SELL if side_raw == "short" or qty < 0 else Side.BUY
    return PositionDTO(
        symbol=str(getattr(pos, "symbol", "")),
        qty=qty,
        avg_cost=_dec(getattr(pos, "avg_entry_price", None)),
        market_price=_dec(getattr(pos, "current_price", None)) if getattr(pos, "current_price", None) else None,
        side=side,
    )


def map_order_ack(order) -> OrderAck:
    status_str = _enum_value(getattr(order, "status", "new"))
    submitted = getattr(order, "submitted_at", None) or getattr(order, "created_at", None)
    return OrderAck(
        client_order_id=str(getattr(order, "client_order_id", "") or ""),
        broker_order_id=str(getattr(order, "id", "") or ""),
        status=_STATUS_MAP.get(status_str, OrderStatus.SUBMITTED),
        symbol=str(getattr(order, "symbol", "")),
        qty=_dec(getattr(order, "qty", None)),
        filled_qty=_dec(getattr(order, "filled_qty", None)),
        submitted_at=str(submitted) if submitted else None,
    )


def map_trade_update(update) -> FillEvent:
    """Normalize a ``trade_updates`` payload (SDK ``TradeUpdate`` or dict) into
    a :class:`FillEvent`."""
    if isinstance(update, dict):
        event = update.get("event", "")
        order = update.get("order", {}) or {}
        get = lambda o, k: o.get(k) if isinstance(o, dict) else getattr(o, k, None)  # noqa: E731
        exec_id = update.get("execution_id")
        price = update.get("price")
        qty = update.get("qty")
        ts = update.get("timestamp")
    else:
        event = getattr(update, "event", "")
        order = getattr(update, "order", None)
        get = lambda o, k: getattr(o, k, None)  # noqa: E731
        exec_id = getattr(update, "execution_id", None)
        price = getattr(update, "price", None)
        qty = getattr(update, "qty", None)
        ts = getattr(update, "timestamp", None)

    event = _enum_value(event)
    side_raw = _enum_value(get(order, "side"))
    filled_qty = _dec(get(order, "filled_qty"))
    order_id = str(get(order, "id") or "")
    client_order_id = str(get(order, "client_order_id") or "")
    # Fallback exec id so dedup still works if the feed omits execution_id on
    # non-fill events (new/canceled/rejected).
    if not exec_id:
        exec_id = f"{order_id}:{event}:{filled_qty}"
    return FillEvent(
        broker_exec_id=str(exec_id),
        client_order_id=client_order_id,
        broker_order_id=order_id,
        symbol=str(get(order, "symbol") or ""),
        side=Side.SELL if side_raw == "sell" else Side.BUY,
        event_type=_EVENT_MAP.get(event, event or "new"),
        qty=_dec(qty),
        price=_dec(price),
        ts=str(ts) if ts else None,
        filled_qty=filled_qty,
    )
