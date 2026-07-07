"""FakeBrokerAdapter (M04 §6.1) — deterministic test double.

Implements the full :class:`BrokerAdapter` protocol in memory. A ``script``
drives predetermined fills, partial fills, slippage and rejects; scripted
fills are written to the same fill transport (``apps.orders.fills.publish_fill``)
as the real adapter, so the ingest path is exercised identically whether the
broker is fake or Alpaca.

The adapter never talks to a network. It is the backbone of the AC-04-10
end-to-end test (webhook → order → fill → ``position.updated`` WS ≤ 5s) and of
every unit test that needs a scripted execution outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .base import (
    Account,
    BrokerConnState,
    BrokerContext,
    BrokerHealth,
    ConnectionInfo,
    FillEvent,
    OrderAck,
    OrderRequest,
    OrderStatus,
    PositionDTO,
    Side,
)
from .errors import BrokerError, BrokerErrorCode


@dataclass
class ScriptedFill:
    qty: Decimal
    price: Decimal


@dataclass
class ScriptStep:
    """What the Fake does for the next ``place_order`` call.

    ``reject`` short-circuits to a rejected order (emits a ``rejected`` event).
    Otherwise ``fills`` are emitted in order — one entry = full fill, several =
    partial fills. Empty ``fills`` with ``reject=False`` means "leave working"
    (a ``new`` event only, no fill) so cancel/timeout paths can be tested.
    """

    reject: bool = False
    reject_reason: str = "insufficient buying power"
    fills: list[ScriptedFill] = field(default_factory=list)
    leave_working: bool = False


class FakeBrokerAdapter:
    name = "fake"
    supported_asset_classes = ["us_equity"]

    def __init__(
        self,
        ctx: BrokerContext | None = None,
        *,
        script: list[ScriptStep] | None = None,
        account_number: str = "DUFAKE0001",
        buying_power: Decimal = Decimal("100000"),
        default_price: Decimal = Decimal("100.00"),
        publish=None,
    ) -> None:
        self.ctx = ctx or BrokerContext(account_id="fake", user_id="fake")
        self._script = list(script or [])
        self._account_number = account_number
        self._buying_power = Decimal(buying_power)
        self._default_price = Decimal(default_price)
        self._positions: dict[str, PositionDTO] = {}
        self._open_orders: list[OrderAck] = []
        self._emitted_fills: list[FillEvent] = []
        self._exec_seq = 0
        # Injectable sink for unit tests; defaults to the real transport.
        if publish is None:
            from apps.orders.fills import publish_fill as publish
        self._publish = publish

    # -- connection ---------------------------------------------------------
    def connect(self) -> ConnectionInfo:
        return ConnectionInfo(
            account_number=self._account_number,
            buying_power=self._buying_power,
            is_paper=True,
        )

    def disconnect(self) -> None:
        return None

    def get_account(self) -> Account:
        return Account(
            account_number=self._account_number,
            buying_power=self._buying_power,
            cash=self._buying_power,
            is_paper=True,
        )

    def list_positions(self) -> list[PositionDTO]:
        return [p for p in self._positions.values() if p.qty != 0]

    def list_open_orders(self) -> list[OrderAck]:
        return list(self._open_orders)

    # -- orders -------------------------------------------------------------
    def _next_exec_id(self, client_order_id: str) -> str:
        self._exec_seq += 1
        return f"fakeexec-{client_order_id}-{self._exec_seq}"

    def place_order(self, req: OrderRequest, client_order_id: str) -> OrderAck:
        step = self._script.pop(0) if self._script else None
        broker_order_id = f"fakeord-{client_order_id}"

        if step and step.reject:
            self._emit(
                FillEvent(
                    broker_exec_id=self._next_exec_id(client_order_id),
                    client_order_id=client_order_id,
                    broker_order_id=broker_order_id,
                    symbol=req.symbol,
                    side=req.side,
                    event_type="rejected",
                    qty=Decimal("0"),
                    price=Decimal("0"),
                )
            )
            return OrderAck(
                client_order_id=client_order_id,
                broker_order_id=broker_order_id,
                status=OrderStatus.REJECTED,
                symbol=req.symbol,
                qty=req.qty,
            )

        # Determine the fills to emit.
        if step and (step.fills or step.leave_working):
            fills = step.fills
        else:
            price = req.limit_price if req.limit_price is not None else self._default_price
            fills = [ScriptedFill(qty=req.qty, price=Decimal(price))]

        # Emit a `new` acknowledgement first (order state → SUBMITTED).
        self._emit(
            FillEvent(
                broker_exec_id=self._next_exec_id(client_order_id),
                client_order_id=client_order_id,
                broker_order_id=broker_order_id,
                symbol=req.symbol,
                side=req.side,
                event_type="new",
            )
        )

        filled = Decimal("0")
        for i, f in enumerate(fills):
            filled += f.qty
            is_last = i == len(fills) - 1 and filled >= req.qty
            self._emit(
                FillEvent(
                    broker_exec_id=self._next_exec_id(client_order_id),
                    client_order_id=client_order_id,
                    broker_order_id=broker_order_id,
                    symbol=req.symbol,
                    side=req.side,
                    event_type="fill" if is_last else "partial_fill",
                    qty=f.qty,
                    price=f.price,
                    filled_qty=filled,
                )
            )
            self._apply_position(req.symbol, req.side, f.qty, f.price)

        if filled < req.qty and not (step and step.leave_working):
            # Working remainder — keep as an open order.
            self._open_orders.append(
                OrderAck(
                    client_order_id=client_order_id,
                    broker_order_id=broker_order_id,
                    status=OrderStatus.PARTIAL,
                    symbol=req.symbol,
                    qty=req.qty,
                    filled_qty=filled,
                )
            )

        return OrderAck(
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            status=OrderStatus.SUBMITTED,
            symbol=req.symbol,
            qty=req.qty,
            filled_qty=Decimal("0"),
        )

    def cancel_order(self, broker_order_id: str) -> None:
        self._open_orders = [o for o in self._open_orders if o.broker_order_id != broker_order_id]

    def flatten_all(self, reason: str) -> list[OrderAck]:
        acks: list[OrderAck] = []
        for symbol, pos in list(self._positions.items()):
            if pos.qty == 0:
                continue
            coid = f"flatten-{symbol}"
            side = Side.SELL if pos.qty > 0 else Side.BUY
            self._emit(
                FillEvent(
                    broker_exec_id=self._next_exec_id(coid),
                    client_order_id=coid,
                    broker_order_id=f"fakeord-{coid}",
                    symbol=symbol,
                    side=side,
                    event_type="fill",
                    qty=abs(pos.qty),
                    price=pos.market_price or self._default_price,
                    filled_qty=abs(pos.qty),
                )
            )
            self._positions[symbol] = PositionDTO(
                symbol=symbol, qty=Decimal("0"), avg_cost=Decimal("0")
            )
            acks.append(
                OrderAck(
                    client_order_id=coid,
                    broker_order_id=f"fakeord-{coid}",
                    status=OrderStatus.FILLED,
                    symbol=symbol,
                    qty=abs(pos.qty),
                    filled_qty=abs(pos.qty),
                )
            )
        self._open_orders.clear()
        return acks

    def health(self) -> BrokerHealth:
        return BrokerHealth(state=BrokerConnState.CONNECTED, detail="fake adapter")

    def recent_fills(self, after=None) -> list[FillEvent]:
        """Replay every fill this adapter has emitted (exec ids preserved). The
        streams supervisor uses this for reconnect catch-up; dedup on
        ``broker_exec_id`` makes replay idempotent (AC-04-11)."""
        return [f for f in self._emitted_fills if f.event_type in ("fill", "partial_fill")]

    # -- internals ----------------------------------------------------------
    def _emit(self, event: FillEvent) -> None:
        self._emitted_fills.append(event)
        self._publish(self.ctx.user_id, event)

    def _apply_position(self, symbol: str, side: Side, qty: Decimal, price: Decimal) -> None:
        signed = qty if side == Side.BUY else -qty
        cur = self._positions.get(symbol)
        if cur is None or cur.qty == 0:
            self._positions[symbol] = PositionDTO(
                symbol=symbol, qty=signed, avg_cost=price, market_price=price, side=side
            )
            return
        new_qty = cur.qty + signed
        if new_qty == 0:
            avg = Decimal("0")
        elif (cur.qty > 0) == (signed > 0):
            # same direction — weighted average cost
            avg = ((cur.avg_cost * abs(cur.qty)) + (price * qty)) / abs(new_qty)
        else:
            avg = cur.avg_cost  # reducing — keep basis
        self._positions[symbol] = PositionDTO(
            symbol=symbol,
            qty=new_qty,
            avg_cost=avg,
            market_price=price,
            side=Side.BUY if new_qty >= 0 else Side.SELL,
        )


def raise_broker_error(code: str = BrokerErrorCode.UNAVAILABLE, message: str = "fake failure"):
    """Helper for tests that want ``place_order`` to raise."""
    raise BrokerError(code, message)
