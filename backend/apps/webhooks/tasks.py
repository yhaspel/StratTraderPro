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
    from apps.brokers.base import OrderRequest, OrderType, Side, TimeInForce
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
    if account is None:
        alert.status = AlertMessage.Status.REJECTED
        alert.reject_reason = "NO_BROKER_CONNECTED"
        alert.processed_at = timezone.now()
        alert.save(update_fields=["status", "reject_reason", "processed_at"])
        return {"rejected": "NO_BROKER_CONNECTED"}

    # --- parse the alert into order intent -------------------------------
    action = str(body.get("action", "")).lower()
    symbol = str(body.get("symbol", "")).upper().strip()
    ot_raw = str(body.get("order_type", "MKT")).upper().strip()
    side = {"buy": Side.BUY, "sell": Side.SELL, "exit": Side.SELL}.get(action)
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
            "side": side or Order.Side.BUY,
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
    if not symbol or "/" in symbol:  # crypto pairs use SYM/SYM → out of scope
        return _reject(order, alert, "ORDER_UNSUPPORTED_ASSET")

    limit_price = None
    if ot_raw == "LMT":
        raw_price = body.get("limit_price", body.get("price"))
        try:
            limit_price = Decimal(str(raw_price))
        except (InvalidOperation, TypeError):
            return _reject(order, alert, "ORDER_INVALID_LIMIT")
        Order.objects.filter(id=order.id).update(
            order_type=Order.OrderType.LMT, limit_price=limit_price
        )
    elif ot_raw != "MKT":
        return _reject(order, alert, "ORDER_UNSUPPORTED_TYPE")

    req = OrderRequest(
        symbol=symbol,
        side=side,
        qty=qty,
        order_type=OrderType.LMT if ot_raw == "LMT" else OrderType.MKT,
        limit_price=limit_price,
        time_in_force=TimeInForce.DAY,
    )

    # --- place -----------------------------------------------------------
    try:
        adapter = build_adapter(account)
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
