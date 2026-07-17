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
_DEAD_SUFFIX = ":dead"
_ATTEMPTS_SUFFIX = ":attempts:"
# After this many failed ingest attempts a message is dead-lettered rather than
# retried forever, so a persistently-failing entry can't wedge the consumer (P0-2).
_MAX_DELIVERIES = 5
_ATTEMPTS_TTL = 86_400  # 24h — a stuck message's attempt counter self-expires.


def _redis():
    import redis

    return redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)


def _stream_key(user_id) -> str:
    return f"{_STREAM_PREFIX}{user_id}"


def _dead_stream_key(user_id) -> str:
    return f"{_STREAM_PREFIX}{user_id}{_DEAD_SUFFIX}"


def _attempts_key(user_id, msg_id) -> str:
    return f"{_STREAM_PREFIX}{user_id}{_ATTEMPTS_SUFFIX}{msg_id}"


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


def _dead_letter(client, user_id, msg_id, data, *, reason: str) -> None:
    """Route an un-ingestable message to the per-user dead-letter stream and
    alert. Raises if the dead-letter transport itself fails, so the caller can
    leave the message pending rather than ack-and-lose it (P0-2)."""
    from apps.brokers.metrics import FILLS_DEADLETTERED_TOTAL

    client.xadd(
        _dead_stream_key(user_id),
        {"data": data.get("data", ""), "reason": reason, "src_id": str(msg_id)},
        maxlen=10_000,
        approximate=True,
    )
    FILLS_DEADLETTERED_TOTAL.labels(reason=reason).inc()
    logger.error(
        "fill.ingest.deadletter",
        extra={"user_id": str(user_id), "msg_id": str(msg_id), "reason": reason},
    )


def _process_message(client, user_id, stream_key, msg_id, data, ingest_fill_event) -> bool:
    """Apply one stream entry. Returns True if the entry was *settled* (ack'd —
    ingested, deduped, or dead-lettered), False if it was left PENDING for retry.

    The old code ack'd unconditionally after a bare ``except``, so a transient DB
    error (deadlock, connection blip) silently dropped the fill forever — turning
    at-least-once delivery into at-most-once. Now:
      * parse failure (bad JSON / schema / Decimal) is POISON → dead-letter + ack;
      * ingest failure is treated as TRANSIENT → leave PENDING for replay (dedup
        by ``broker_exec_id`` makes reprocessing safe), bounded to _MAX_DELIVERIES
        attempts before dead-lettering so a persistently-failing entry can't wedge.
    """
    # 1) Parse — a parse failure can never be transient; it's a poison payload.
    try:
        fill = wire_to_fill(json.loads(data["data"]))
    except Exception:
        logger.exception(
            "fill.ingest.poison", extra={"user_id": str(user_id), "msg_id": str(msg_id)}
        )
        try:
            _dead_letter(client, user_id, msg_id, data, reason="poison")
        except Exception:  # pragma: no cover — dead-letter transport down; retry later
            logger.exception("fill.deadletter.failed", extra={"msg_id": str(msg_id)})
            return False
        client.xack(stream_key, _CONSUMER_GROUP, msg_id)
        return True

    # 2) Apply — a failure here is (almost always) transient. Leave the entry
    #    PENDING so the "0" replay branch re-reads it; bound the retries.
    try:
        ingest_fill_event(fill, user_id=user_id)
    except Exception:
        attempts_key = _attempts_key(user_id, msg_id)
        try:
            attempts = client.incr(attempts_key)
            client.expire(attempts_key, _ATTEMPTS_TTL)
        except Exception:  # pragma: no cover — counter store down; treat as first try
            attempts = 1
        if attempts >= _MAX_DELIVERIES:
            logger.error(
                "fill.ingest.exhausted",
                extra={"user_id": str(user_id), "msg_id": str(msg_id), "attempts": attempts},
            )
            try:
                _dead_letter(client, user_id, msg_id, data, reason="max_retries")
            except Exception:  # pragma: no cover — dead-letter down; keep pending
                logger.exception("fill.deadletter.failed", extra={"msg_id": str(msg_id)})
                return False
            client.xack(stream_key, _CONSUMER_GROUP, msg_id)
            client.delete(attempts_key)
            return True
        logger.warning(
            "fill.ingest.transient",
            extra={"user_id": str(user_id), "msg_id": str(msg_id), "attempts": attempts},
        )
        return False  # leave PENDING — do NOT ack

    # 3) Success — ack and clear the attempt counter.
    client.xack(stream_key, _CONSUMER_GROUP, msg_id)
    client.delete(_attempts_key(user_id, msg_id))
    return True


def drain_stream(user_id, *, count: int = 100, consumer: str = "ingestor-1") -> int:
    """Read pending + new messages for one user stream, applying each fill.
    Returns the number of messages *settled* (ack'd). Transiently-failed messages
    stay pending and are retried on the next drain."""
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
                if _process_message(client, user_id, stream_key, msg_id, data, ingest_fill_event):
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
