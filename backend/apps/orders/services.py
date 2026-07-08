"""Orders service layer (M04) — fill ingestion, position math, WS fan-out.

``ingest_fill_event`` is the single choke point every fill flows through
(whether delivered inline in tests or via the Redis Stream in prod). It is
idempotent on ``broker_exec_id`` — a reconnect REST catch-up that re-delivers
a seen execution creates no duplicate ``Fill`` and no double-counted position
(AC-04-11).
"""
from __future__ import annotations

import logging
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.brokers.base import FillEvent
from apps.dashboard.events import (
    FILL_CREATED,
    ORDER_UPDATED,
    POSITION_UPDATED,
    push_to_user,
)

from .models import Fill, Order, Position

logger = logging.getLogger(__name__)


def _parse_ts(ts):
    if not ts:
        return timezone.now()
    parsed = parse_datetime(str(ts))
    if parsed is None:
        return timezone.now()
    if timezone.is_naive(parsed):
        # django.utils.timezone.utc was removed in Django 5 — use datetime's
        # (FIX-M1). The old ref raised AttributeError, dropping the fill.
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    return parsed


def order_to_wire(order: Order) -> dict:
    return {
        "id": str(order.id),
        "client_order_id": order.client_order_id,
        "broker_order_id": order.broker_order_id,
        "symbol": order.symbol,
        "side": order.side,
        "qty": str(order.qty),
        "filled_qty": str(order.filled_qty),
        "order_type": order.order_type,
        "limit_price": str(order.limit_price) if order.limit_price is not None else None,
        "status": order.status,
        "reason": order.reason,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


def position_to_wire(pos: Position) -> dict:
    pnl = pos.unrealized_pnl
    return {
        "symbol": pos.symbol,
        "qty": str(pos.qty),
        "avg_cost": str(pos.avg_cost),
        "market_price": str(pos.market_price) if pos.market_price is not None else None,
        "unrealized_pnl": str(pnl) if pnl is not None else None,
        "broker_account": str(pos.broker_account_id),
    }


def fill_to_wire(fill: Fill) -> dict:
    return {
        "id": fill.id,
        "order_id": str(fill.order_id),
        "symbol": fill.order.symbol,
        "qty": str(fill.qty),
        "price": str(fill.price),
        "ts": fill.ts.isoformat() if fill.ts else None,
        "broker_exec_id": fill.broker_exec_id,
    }


# ---------------------------------------------------------------------------
# Position math
# ---------------------------------------------------------------------------
# Buy-side set — options carry BUY_TO_OPEN / BUY_TO_CLOSE, which are NOT
# Order.Side.BUY; testing membership (not equality) stops those fills from
# decrementing the position (FIX-H5).
_BUY_SIDES = {Order.Side.BUY, Order.Side.BUY_TO_OPEN, Order.Side.BUY_TO_CLOSE}


def _apply_fill_to_position(order: Order, side: str, qty: Decimal, price: Decimal) -> Position:
    pos, _ = Position.objects.select_for_update().get_or_create(
        broker_account=order.broker_account,
        symbol=order.symbol,
        defaults={"user": order.user, "qty": Decimal("0"), "avg_cost": Decimal("0")},
    )
    signed = qty if side in _BUY_SIDES else -qty
    new_qty = pos.qty + signed
    if pos.qty == 0 or new_qty == 0:
        pos.avg_cost = price if new_qty != 0 else Decimal("0")
    elif (pos.qty > 0) == (signed > 0):
        # same direction — weighted average
        pos.avg_cost = ((pos.avg_cost * abs(pos.qty)) + (price * qty)) / abs(new_qty)
    elif (pos.qty > 0) != (new_qty > 0):
        # flipped through zero (long→short or short→long) — the residual's basis
        # is the flip fill price, not the old average (FIX-L1).
        pos.avg_cost = price
    # else: reducing same side → basis unchanged
    pos.qty = new_qty
    pos.market_price = price  # M04: mark = latest fill price
    pos.save()
    return pos


_ORDER_STATUS_FROM_EVENT = {
    "new": Order.Status.SUBMITTED,
    "canceled": Order.Status.CANCELLED,
    "rejected": Order.Status.REJECTED,
    "partial_fill": Order.Status.PARTIAL,
}


@transaction.atomic
def ingest_fill_event(fill: FillEvent, *, user_id) -> dict:
    """Apply one normalized broker event. Idempotent on ``broker_exec_id``."""
    from apps.brokers.metrics import FILLS_INGESTED_TOTAL, ORDER_STATE_TRANSITIONS_TOTAL

    order = (
        Order.objects.select_for_update()
        .filter(client_order_id=fill.client_order_id)
        .first()
    )
    if order is None and fill.broker_order_id:
        order = (
            Order.objects.select_for_update()
            .filter(broker_order_id=fill.broker_order_id)
            .first()
        )
    if order is None:
        logger.info("fill.no_order", extra={"coid": fill.client_order_id, "event": fill.event_type})
        return {"ignored": True}

    prev_status = order.status
    broker_label = (order.broker_account.broker if order.broker_account_id else "unknown").lower()

    if fill.broker_order_id and order.broker_order_id != fill.broker_order_id:
        order.broker_order_id = fill.broker_order_id

    position_changed = False
    fill_row = None
    if fill.event_type in ("fill", "partial_fill") and fill.qty > 0:
        # Dedup is scoped per broker account (FIX-M2): synthetic fallback exec
        # ids (f"{order_id}:{event}:{qty}") share one namespace across brokers,
        # so a global-unique broker_exec_id could swallow a second account's fill.
        fill_row, created = Fill.objects.get_or_create(
            broker_account=order.broker_account,
            broker_exec_id=fill.broker_exec_id,
            defaults={
                "order": order,
                "qty": fill.qty,
                "price": fill.price,
                "ts": _parse_ts(fill.ts),
            },
        )
        if created:
            _apply_fill_to_position(order, order.side, fill.qty, fill.price)
            order.filled_qty = (order.filled_qty or Decimal("0")) + fill.qty
            position_changed = True
            FILLS_INGESTED_TOTAL.labels(broker=broker_label).inc()  # FIX-C1
        else:
            fill_row = None  # already ingested — dedup, emit nothing

    # Resolve order status.
    if fill.event_type == "fill":
        # 'fill' is the terminal execution for the order.
        order.status = (
            Order.Status.FILLED
            if order.filled_qty >= order.qty
            else Order.Status.PARTIAL
        )
    else:
        mapped = _ORDER_STATUS_FROM_EVENT.get(fill.event_type)
        if mapped is not None and order.status not in (
            Order.Status.FILLED,
            Order.Status.CANCELLED,
            Order.Status.REJECTED,
        ):
            order.status = mapped
    order.save()

    if order.status != prev_status:  # FIX-C1 — order state transition
        ORDER_STATE_TRANSITIONS_TOTAL.labels(broker=broker_label, to=order.status).inc()

    push_to_user(user_id, ORDER_UPDATED, order_to_wire(order))
    if fill_row is not None:
        push_to_user(user_id, FILL_CREATED, fill_to_wire(fill_row))
    if position_changed:
        pos = Position.objects.filter(
            broker_account=order.broker_account, symbol=order.symbol
        ).first()
        if pos is not None:
            push_to_user(user_id, POSITION_UPDATED, position_to_wire(pos))
    return {
        "order_id": str(order.id),
        "status": order.status,
        "fill_created": fill_row is not None,
        "position_changed": position_changed,
    }


@transaction.atomic
def reconcile_positions(account, adapter) -> int:
    """Snap our Position rows for ``account`` to the broker's authoritative
    list (used after ``flatten_all`` and on stream reconnect). Returns the
    number of rows changed. Emits ``position.updated`` for each touched symbol."""
    broker_positions = {p.symbol: p for p in adapter.list_positions()}
    changed = 0
    seen = set()
    for symbol, bp in broker_positions.items():
        seen.add(symbol)
        pos, _ = Position.objects.select_for_update().get_or_create(
            broker_account=account,
            symbol=symbol,
            defaults={"user": account.user, "qty": Decimal("0"), "avg_cost": Decimal("0")},
        )
        if pos.qty != bp.qty or pos.avg_cost != bp.avg_cost:
            pos.qty = bp.qty
            pos.avg_cost = bp.avg_cost
            pos.market_price = bp.market_price
            pos.save()
            changed += 1
            push_to_user(account.user_id, POSITION_UPDATED, position_to_wire(pos))
    # Symbols we hold but the broker no longer reports → flat.
    for pos in Position.objects.select_for_update().filter(broker_account=account).exclude(symbol__in=seen):
        if pos.qty != 0:
            pos.qty = Decimal("0")
            pos.avg_cost = Decimal("0")
            pos.save()
            changed += 1
            push_to_user(account.user_id, POSITION_UPDATED, position_to_wire(pos))
    return changed
