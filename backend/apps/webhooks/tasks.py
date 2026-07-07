"""Celery tasks for webhook alert processing (M04 §6.3)."""
from __future__ import annotations

import hashlib
import logging
import time
from decimal import Decimal, InvalidOperation

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


def _reject(order, alert, reason: str):
    from apps.dashboard.events import ORDER_UPDATED, push_to_user
    from apps.orders.models import Order
    from apps.orders.services import order_to_wire

    Order.objects.filter(id=order.id).update(status=Order.Status.REJECTED, reason=reason[:64])
    order.refresh_from_db()
    push_to_user(alert.user_id, ORDER_UPDATED, order_to_wire(order))
    alert.status = alert.Status.REJECTED
    alert.reject_reason = reason[:48]
    alert.processed_at = timezone.now()
    alert.save(update_fields=["status", "reject_reason", "processed_at"])
    return {"order_id": str(order.id), "rejected": reason}


@shared_task(bind=True, max_retries=0)
def process_alert(self, alert_id):
    """Hydrate an alert, size (verbatim qty in M04), place via the user's
    default broker, persist the order, and push realtime events."""
    from apps.brokers.base import (
        FutureContract,
        OptionContract,
        OrderRequest,
        OrderType,
        Side,
        TimeInForce,
    )
    from apps.brokers.errors import BrokerError
    from apps.brokers.models import BrokerAccount
    from apps.brokers.services import build_adapter
    from apps.dashboard.events import ORDER_CREATED, ORDER_UPDATED, push_to_user
    from apps.orders.models import Order
    from apps.orders.services import order_to_wire

    from .metrics import ORDER_SUBMIT_LATENCY
    from .models import AlertMessage

    try:
        alert = AlertMessage.objects.select_related("user", "strategy").get(id=alert_id)
    except AlertMessage.DoesNotExist:
        logger.warning("process_alert.missing", extra={"alert_id": str(alert_id)})
        return {"error": "alert_not_found"}
    if alert.status != AlertMessage.Status.RECEIVED:
        return {"skipped": "already_processed"}

    body = alert.body_json or {}
    account = (
        BrokerAccount.objects.filter(user=alert.user, is_default=True).first()
        or BrokerAccount.objects.filter(user=alert.user).order_by("created_at").first()
    )
    # Broker routing (AC-05-2): an alert may specify "broker" to override the
    # user's default. Falls back to default/oldest if the named broker isn't
    # connected.
    broker_pref = str(body.get("broker", "")).upper().strip()
    if broker_pref:
        override = (
            BrokerAccount.objects.filter(user=alert.user, broker=broker_pref)
            .order_by("-is_default", "created_at")
            .first()
        )
        if override is not None:
            account = override
    if account is None:
        alert.status = AlertMessage.Status.REJECTED
        alert.reject_reason = "NO_BROKER_CONNECTED"
        alert.processed_at = timezone.now()
        alert.save(update_fields=["status", "reject_reason", "processed_at"])
        return {"rejected": "NO_BROKER_CONNECTED"}

    # Belt-and-suspenders kill-switch re-check (the webhook may have raced a
    # halt toggle between accept and processing — §6.3 / M08 §6.3).
    from apps.risk.killswitch import is_blocked

    blocked = is_blocked(alert.user_id, alert.strategy_id)
    if blocked:
        alert.status = AlertMessage.Status.REJECTED
        alert.reject_reason = blocked
        alert.processed_at = timezone.now()
        alert.save(update_fields=["status", "reject_reason", "processed_at"])
        return {"rejected": blocked}

    # --- parse the alert into order intent -------------------------------
    action = str(body.get("action", "")).lower()
    symbol = str(body.get("symbol", "")).upper().strip()
    ot_raw = str(body.get("order_type", "MKT")).upper().strip()
    asset_raw = str(body.get("asset_class", "STOCK")).upper().strip() or "STOCK"
    tif_raw = str(body.get("tif", body.get("time_in_force", "DAY"))).upper().strip()
    side = {
        "buy": Side.BUY,
        "sell": Side.SELL,
        "exit": Side.SELL,
        "buy_to_open": Side.BUY,
        "sell_to_open": Side.SELL,
        "buy_to_close": Side.BUY,
        "sell_to_close": Side.SELL,
    }.get(action)
    # Our Order preserves the richer open/close side even though the broker
    # OrderRequest collapses to BUY/SELL (adapters map the semantics).
    order_side = {
        "buy": Order.Side.BUY,
        "sell": Order.Side.SELL,
        "exit": Order.Side.SELL,
        "buy_to_open": Order.Side.BUY_TO_OPEN,
        "sell_to_open": Order.Side.SELL_TO_OPEN,
        "buy_to_close": Order.Side.BUY_TO_CLOSE,
        "sell_to_close": Order.Side.SELL_TO_CLOSE,
    }.get(action, Order.Side.BUY)
    try:
        qty = Decimal(str(body.get("qty")))
    except (InvalidOperation, TypeError):
        qty = Decimal("0")

    # Derive the client_order_id from the idempotency key (when present) so
    # Alpaca's unique-client_order_id constraint is a real second guard for
    # AC-04-4: a duplicate idempotency_key maps to the SAME coid even if the
    # Redis SETNX was lost, so both our Order.get_or_create and the broker
    # reject the duplicate. Falls back to the alert id otherwise. 36 chars,
    # under Alpaca's client_order_id length limit.
    idem_key = str(body.get("idempotency_key", "")).strip()
    if idem_key:
        digest = hashlib.sha256(f"{alert.user_id}:{idem_key}".encode()).hexdigest()[:32]
        client_order_id = f"stp-{digest}"
    else:
        client_order_id = f"stp-{alert.id}"
    order, created = Order.objects.get_or_create(
        client_order_id=client_order_id,
        defaults={
            "user": alert.user,
            "strategy": alert.strategy,
            "broker_account": account,
            "raw_alert": alert,
            "symbol": symbol,
            "side": order_side,
            "qty": qty if qty > 0 else Decimal("0"),
            "order_type": Order.OrderType.MKT,
            "time_in_force": Order.TimeInForce.DAY,
            "status": Order.Status.PENDING_SUBMIT,
        },
    )
    if not created:
        return {"skipped": "duplicate_client_order_id", "order_id": str(order.id)}
    push_to_user(alert.user_id, ORDER_CREATED, order_to_wire(order))

    # --- pre-submit validation (uniform across adapters) -----------------
    if side is None:
        return _reject(order, alert, "INVALID_ACTION")
    if qty <= 0:
        return _reject(order, alert, "INVALID_QTY")
    if not symbol:
        return _reject(order, alert, "ORDER_UNSUPPORTED_ASSET")
    if asset_raw not in ("STOCK", "ETF", "OPTION", "FUTURE"):
        return _reject(order, alert, "ORDER_UNSUPPORTED_ASSET")
    # Crypto pairs (SYM/SYM) are out of scope for equities/options; only futures
    # may carry a non-equity symbol shape.
    if "/" in symbol and asset_raw != "FUTURE":
        return _reject(order, alert, "ORDER_UNSUPPORTED_ASSET")

    ot_map = {
        "MKT": OrderType.MKT,
        "LMT": OrderType.LMT,
        "STP": OrderType.STP,
        "STP_LMT": OrderType.STP_LMT,
    }
    otype = ot_map.get(ot_raw)
    if otype is None:
        return _reject(order, alert, "ORDER_UNSUPPORTED_TYPE")

    limit_price = stop_price = None
    if otype in (OrderType.LMT, OrderType.STP_LMT):
        try:
            limit_price = Decimal(str(body.get("limit_price", body.get("price"))))
        except (InvalidOperation, TypeError):
            return _reject(order, alert, "ORDER_INVALID_LIMIT")
    if otype in (OrderType.STP, OrderType.STP_LMT):
        try:
            stop_price = Decimal(str(body.get("stop_price")))
        except (InvalidOperation, TypeError):
            return _reject(order, alert, "ORDER_INVALID_STOP")

    tif = {"DAY": TimeInForce.DAY, "GTC": TimeInForce.GTC, "IOC": TimeInForce.IOC}.get(
        tif_raw, TimeInForce.DAY
    )

    option = future = None
    if asset_raw == "OPTION" and body.get("option_expiry") and body.get("option_strike"):
        try:
            option = OptionContract(
                expiry=str(body["option_expiry"]),
                strike=Decimal(str(body["option_strike"])),
                right=str(body.get("option_right", "CALL")).upper(),
            )
        except (InvalidOperation, TypeError):
            option = None
    if asset_raw == "FUTURE":
        future = FutureContract(
            root=str(body.get("future_root", symbol)).upper(),
            expiry=str(body.get("future_expiry", "")),
        )

    # Persist the resolved intent on the order row.
    Order.objects.filter(id=order.id).update(
        order_type=ot_raw,
        limit_price=limit_price,
        stop_price=stop_price,
        time_in_force=tif.value,
        asset_class=asset_raw,
        option_expiry=option.expiry if option else None,
        option_strike=option.strike if option else None,
        option_right=(option.right if option else ""),
        future_root=(future.root if future else ""),
        future_expiry=(future.expiry if future else ""),
        side=order_side,
    )

    def _build_req(q):
        return OrderRequest(
            symbol=symbol, side=side, qty=q, order_type=otype, limit_price=limit_price,
            stop_price=stop_price, time_in_force=tif, asset_class=asset_raw,
            option=option, future=future,
        )

    req = _build_req(qty)

    # --- build adapter ---------------------------------------------------
    try:
        adapter = build_adapter(account)
    except BrokerError as exc:
        return _reject(order, alert, exc.code)

    # --- sizing (M08 §6.2 — only when the user has a RiskProfile) ---------
    from apps.risk.integration import apply_sizing

    try:
        sizing = apply_sizing(
            alert=alert, order=order, account=account, adapter=adapter,
            requested_qty=qty, side=order_side, symbol=symbol, price_hint=limit_price,
        )
    except Exception:  # noqa: BLE001 — sizing must fail closed, never leave the order stuck at PENDING_SUBMIT
        logger.exception("process_alert.sizing_error", extra={"order": str(order.id)})
        return _reject(order, alert, "SIZING_ERROR")
    if sizing is not None:
        if not sizing.ok:
            return _reject(order, alert, sizing.reason)
        qty = sizing.qty
        Order.objects.filter(id=order.id).update(qty=qty)
        req = _build_req(qty)

    # --- place -----------------------------------------------------------
    try:
        t0 = time.monotonic()
        ack = adapter.place_order(req, client_order_id)
        ORDER_SUBMIT_LATENCY.labels(broker=str(account.broker).lower()).observe(time.monotonic() - t0)
    except BrokerError as exc:
        logger.info("process_alert.broker_error", extra={"code": exc.code, "order": str(order.id)})
        return _reject(order, alert, exc.code)
    except Exception:  # noqa: BLE001 — never re-raise into a retry storm (§6.3)
        logger.exception("process_alert.unexpected", extra={"order": str(order.id)})
        return _reject(order, alert, "BROKER_UNKNOWN_ERROR")

    # Record broker id; advance status only if inline fills haven't already
    # moved it past PENDING_SUBMIT (FILLS_INLINE path).
    if ack.broker_order_id:
        Order.objects.filter(id=order.id).update(broker_order_id=ack.broker_order_id)
    Order.objects.filter(id=order.id, status=Order.Status.PENDING_SUBMIT).update(
        status=Order.Status.SUBMITTED
    )
    order.refresh_from_db()
    push_to_user(alert.user_id, ORDER_UPDATED, order_to_wire(order))

    alert.status = AlertMessage.Status.ACCEPTED
    alert.processed_at = timezone.now()
    alert.save(update_fields=["status", "processed_at"])
    return {"order_id": str(order.id), "status": order.status, "broker_order_id": order.broker_order_id}
