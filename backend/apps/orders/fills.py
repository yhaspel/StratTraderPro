"""Fill transport (M04 §6.4/§6.5).

Producers (``run_broker_streams`` and ``FakeBrokerAdapter``) call
:func:`publish_fill`. When ``FILLS_INLINE`` is set (tests), fills apply
synchronously through :func:`apps.orders.services.ingest_fill_event` — no Redis
needed. Otherwise they are ``XADD``-ed to per-user Redis Streams
``fills:user:{id}`` and drained by the ``FillIngestor`` task (consumer group).
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.conf import settings

from apps.brokers.base import FillEvent, Side

logger = logging.getLogger(__name__)

_CONSUMER_GROUP = "fill_ingestors"
_STREAM_PREFIX = "fills:user:"


def _redis():
    import redis

    return redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)


def _stream_key(user_id) -> str:
    return f"{_STREAM_PREFIX}{user_id}"


def fill_to_wire(fill: FillEvent) -> dict:
    return {
        "broker_exec_id": fill.broker_exec_id,
        "client_order_id": fill.client_order_id,
        "broker_order_id": fill.broker_order_id,
        "symbol": fill.symbol,
        "side": fill.side.value if isinstance(fill.side, Side) else str(fill.side),
        "event_type": fill.event_type,
        "qty": str(fill.qty),
        "price": str(fill.price),
        "ts": fill.ts or "",
        "filled_qty": str(fill.filled_qty),
    }


def wire_to_fill(d: dict) -> FillEvent:
    return FillEvent(
        broker_exec_id=d.get("broker_exec_id", ""),
        client_order_id=d.get("client_order_id", ""),
        broker_order_id=d.get("broker_order_id", ""),
        symbol=d.get("symbol", ""),
        side=Side.SELL if str(d.get("side", "")).upper() == "SELL" else Side.BUY,
        event_type=d.get("event_type", "new"),
        qty=Decimal(d.get("qty", "0") or "0"),
        price=Decimal(d.get("price", "0") or "0"),
        ts=d.get("ts") or None,
        filled_qty=Decimal(d.get("filled_qty", "0") or "0"),
    )


def publish_fill(user_id, fill: FillEvent) -> None:
    if getattr(settings, "FILLS_INLINE", False):
        from .services import ingest_fill_event

        ingest_fill_event(fill, user_id=user_id)
        return
    try:
        client = _redis()
        client.xadd(
            _stream_key(user_id),
            {"data": json.dumps(fill_to_wire(fill))},
            maxlen=10_000,
            approximate=True,
        )
    except Exception:  # pragma: no cover — never lose the caller on transport error
        logger.exception("fill.publish.failed", extra={"user_id": str(user_id)})


# ---------------------------------------------------------------------------
# Consumer side (FillIngestor)
# ---------------------------------------------------------------------------
def _ensure_group(client, stream_key: str) -> None:
    try:
        client.xgroup_create(stream_key, _CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as exc:  # BUSYGROUP if it already exists
        if "BUSYGROUP" not in str(exc):  # pragma: no cover
            raise


def drain_stream(user_id, *, count: int = 100, consumer: str = "ingestor-1") -> int:
    """Read + ack pending messages for one user stream, applying each fill.
    Returns the number of messages processed."""
    from .services import ingest_fill_event

    client = _redis()
    stream_key = _stream_key(user_id)
    _ensure_group(client, stream_key)
    processed = 0
    # First replay this consumer's pending (unacked) entries, then new ones.
    for start_id in ("0", ">"):
        resp = client.xreadgroup(
            _CONSUMER_GROUP, consumer, {stream_key: start_id}, count=count, block=None
        )
        if not resp:
            continue
        for _stream, entries in resp:
            for msg_id, data in entries:
                try:
                    ingest_fill_event(wire_to_fill(json.loads(data["data"])), user_id=user_id)
                except Exception:  # pragma: no cover — poison message; ack to skip
                    logger.exception("fill.ingest.failed", extra={"msg_id": msg_id})
                client.xack(stream_key, _CONSUMER_GROUP, msg_id)
                processed += 1
    return processed


def sweep_all_streams(*, count: int = 100) -> int:
    """Drain every active ``fills:user:*`` stream once. Used by the FillIngestor
    beat task."""
    client = _redis()
    total = 0
    for key in client.scan_iter(match=f"{_STREAM_PREFIX}*", count=100):
        user_id = key[len(_STREAM_PREFIX):]
        total += drain_stream(user_id, count=count)
    return total
