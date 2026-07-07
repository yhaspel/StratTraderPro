"""TradeStation symbology + payload mapping (M05 §6.1/§6.2).

Canonical StratTraderPro DTOs ↔ TradeStation API v3 shapes. TS symbology is
documented here (options + futures) per the ADR. Live-verified once API access
is granted; all conversions are unit-tested against the documented formats.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ..base import (
    Account,
    FillEvent,
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderType,
    PositionDTO,
    Side,
)

# CME/futures month codes.
_FUT_MONTH = {
    "01": "F", "02": "G", "03": "H", "04": "J", "05": "K", "06": "M",
    "07": "N", "08": "Q", "09": "U", "10": "V", "11": "X", "12": "Z",
}

_TS_ORDER_TYPE = {
    OrderType.MKT: "Market",
    OrderType.LMT: "Limit",
    OrderType.STP: "StopMarket",
    OrderType.STP_LMT: "StopLimit",
}

_TS_STATUS = {
    "ACK": OrderStatus.SUBMITTED, "OPN": OrderStatus.SUBMITTED, "RECEIVED": OrderStatus.SUBMITTED,
    "FLL": OrderStatus.FILLED, "FILLED": OrderStatus.FILLED,
    "FPR": OrderStatus.PARTIAL, "PARTIALLYFILLED": OrderStatus.PARTIAL,
    "CAN": OrderStatus.CANCELLED, "CANCELED": OrderStatus.CANCELLED, "EXP": OrderStatus.CANCELLED,
    "REJ": OrderStatus.REJECTED, "REJECTED": OrderStatus.REJECTED, "TSC": OrderStatus.CANCELLED,
}

_TS_SIDE = {
    Side.BUY: "Buy", Side.SELL: "Sell",
}
_BUY_TO = {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}


def _dec(v, default="0") -> Decimal:
    if v is None:
        return Decimal(default)
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):  # pragma: no cover
        return Decimal(default)


def to_ts_symbol(req: OrderRequest) -> str:
    """Canonical symbol → TradeStation symbol.

    - STOCK/ETF: unchanged (``AAPL``, ``BRK.B``).
    - OPTION: OCC/OPRA ``AAPL240119C00150000`` → TS ``AAPL 240119C150`` (space,
      strike with the trailing 3 implied-decimal zeros trimmed).
    - FUTURE: root + ``YYYY-MM`` → ``ESZ26`` (root + month code + 2-digit year).
    """
    if req.asset_class == "FUTURE" and req.future is not None:
        root = req.future.root.upper().lstrip("@")
        parts = req.future.expiry.split("-")
        if len(parts) >= 2:
            month = _FUT_MONTH.get(parts[1].zfill(2), "")
            yy = parts[0][-2:]
            return f"{root}{month}{yy}"
        return f"@{root}"
    if req.asset_class == "OPTION" and len(req.symbol) >= 15 and req.symbol[-8:].isdigit():
        occ = req.symbol
        # OCC/OSI: ROOT + YYMMDD(6) + C/P(1) + STRIKE(8, thousandths). The root is
        # everything before the trailing 15 chars.
        underlying = occ[:-15].strip()
        rest = occ[-15:]
        yymmdd, right, strike_raw = rest[:6], rest[6], rest[7:]
        strike = int(strike_raw) / 1000
        strike_txt = f"{strike:g}"
        return f"{underlying} {yymmdd}{right}{strike_txt}"
    return req.symbol


def to_ts_order_payload(req: OrderRequest, client_order_id: str, account_number: str) -> dict:
    trade_action = "BUY" if str(getattr(req.side, "value", req.side)) in _BUY_TO else "SELL"
    payload = {
        "AccountID": account_number,
        "Symbol": to_ts_symbol(req),
        "Quantity": str(req.qty),
        "OrderType": _TS_ORDER_TYPE.get(req.order_type, "Market"),
        "TradeAction": trade_action,
        "TimeInForce": {"Duration": str(getattr(req.time_in_force, "value", req.time_in_force))},
        "ClientOrderID": client_order_id,
    }
    if req.limit_price is not None:
        payload["LimitPrice"] = str(req.limit_price)
    if req.stop_price is not None:
        payload["StopPrice"] = str(req.stop_price)
    return payload


def from_ts_account(d: dict) -> Account:
    bal = d.get("Balances", d) if isinstance(d, dict) else {}
    return Account(
        account_number=str(d.get("AccountID", "") or ""),
        buying_power=_dec((bal or {}).get("BuyingPower")),
        cash=_dec((bal or {}).get("CashBalance")),
        currency="USD",
        status=str(d.get("Status", "ACTIVE")),
        is_paper=True,
    )


def from_ts_position(d: dict) -> PositionDTO:
    qty = _dec(d.get("Quantity"))
    long_short = str(d.get("LongShort", "Long")).lower()
    if long_short == "short":
        qty = -abs(qty)
    return PositionDTO(
        symbol=str(d.get("Symbol", "")),
        qty=qty,
        avg_cost=_dec(d.get("AveragePrice")),
        market_price=_dec(d.get("Last")) if d.get("Last") else None,
        side=Side.SELL if qty < 0 else Side.BUY,
    )


def from_ts_order(d: dict) -> OrderAck:
    status = str(d.get("Status", d.get("StatusDescription", "OPN"))).upper()
    return OrderAck(
        client_order_id=str(d.get("ClientOrderID", "") or ""),
        broker_order_id=str(d.get("OrderID", "") or ""),
        status=_TS_STATUS.get(status, OrderStatus.SUBMITTED),
        symbol=str(d.get("Symbol", "")),
        qty=_dec(d.get("Quantity") or d.get("QuantityOrdered")),
        filled_qty=_dec(d.get("FilledQuantity")),
    )


def from_ts_order_event(d: dict) -> FillEvent:
    status = str(d.get("Status", "")).upper()
    our_status = _TS_STATUS.get(status, OrderStatus.SUBMITTED)
    event = {
        OrderStatus.FILLED: "fill",
        OrderStatus.PARTIAL: "partial_fill",
        OrderStatus.CANCELLED: "canceled",
        OrderStatus.REJECTED: "rejected",
    }.get(our_status, "new")
    order_id = str(d.get("OrderID", "") or "")
    filled = _dec(d.get("FilledQuantity"))
    exec_id = str(d.get("ExecutionID") or f"{order_id}:{status}:{filled}")
    return FillEvent(
        broker_exec_id=exec_id,
        client_order_id=str(d.get("ClientOrderID", "") or ""),
        broker_order_id=order_id,
        symbol=str(d.get("Symbol", "")),
        side=Side.BUY if str(d.get("TradeAction", "BUY")).upper() in _BUY_TO else Side.SELL,
        event_type=event,
        qty=_dec(d.get("ExecutionQuantity") or filled),
        price=_dec(d.get("ExecutionPrice") or d.get("FilledPrice")),
        filled_qty=filled,
    )
