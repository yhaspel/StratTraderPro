"""Audit write path (M10 §6.1).

``emit()`` is the single explicit service call for writing a chained audit row.
It never raises into the caller: audit emission must never break the business
action (§11). The Postgres enforcement triggers (migration 0002) are the
integrity backstop, not app exceptions.

Exception ordering is exact: ``try:`` wraps ``with transaction.atomic():`` with
the ``except`` OUTSIDE the atomic block. Catching a trigger ``RAISE`` inside the
atomic block would throw ``TransactionManagementError``; when ``emit`` is called
inside a business transaction the inner ``atomic()`` nests as a savepoint so a
failed audit insert rolls back only the savepoint, leaving the business txn
valid.
"""
from __future__ import annotations

import logging

from django.db import connection, transaction

from .events import event_family
from .hashing import (
    GENESIS_PREV_HASH,
    canonical_payload,
    compute_self_hash,
    normalize_json,
)
from .metrics import AUDIT_EVENTS_DROPPED_TOTAL, AUDIT_EVENTS_TOTAL
from .scrub import scrub

logger = logging.getLogger(__name__)


def _client_ip(request) -> str | None:
    """First X-Forwarded-For hop, else REMOTE_ADDR (mirrors users.services)."""
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def _advisory_lock() -> None:
    """Serialize chain-head reads on Postgres. No-op on SQLite (tests/dev)."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('audit_log'))")


def emit(
    event_type,
    *,
    user=None,
    actor=None,
    user_id=None,
    actor_id=None,
    entity_type="",
    entity_id="",
    data_before=None,
    data_after=None,
    request=None,
    metadata=None,
    ip=None,
    ua="",
):
    """Write one chained ``AuditLog`` row. Returns the row, or ``None`` on failure
    (logged + ``audit_events_dropped_total``). Never raises.

    ``user``/``actor`` accept model instances; ``user_id``/``actor_id`` accept raw
    ids when the caller only has an id (avoids an extra query)."""
    from .models import AuditLog

    event_type = str(event_type)
    user_id = user_id if user_id is not None else getattr(user, "id", None)
    actor_id = actor_id if actor_id is not None else getattr(actor, "id", None)

    # Fold metadata into data_after (shallow) and scrub + normalize both diffs so
    # what we hash is byte-identical to what JSONField will store back.
    if metadata:
        data_after = {**(data_after or {}), **metadata}
    before = normalize_json(scrub(data_before)) if data_before is not None else None
    after = normalize_json(scrub(data_after)) if data_after is not None else None

    entity_type = (entity_type or "")[:64]
    entity_id = ("" if entity_id in (None, "") else str(entity_id))[:64]

    if request is not None:
        ip = ip or _client_ip(request)
        ua = ua or (request.META.get("HTTP_USER_AGENT") or "")
    ua = (ua or "")[:512]

    # Assign the timestamp ONCE and hash that exact value.
    from django.utils import timezone

    occurred_at = timezone.now()

    try:
        with transaction.atomic():
            # NOTE (P2-7): a NAMED advisory lock is required here, not a row-level
            # SELECT ... FOR UPDATE on the head. The chain head MOVES on every
            # insert, so a lock taken on the row that is the head *at read time*
            # is stale by the time the next writer commits — two concurrent
            # emits then chain from the same prev_hash and the DB linkage trigger
            # rejects the second (proven by the `-m pg` concurrency test). The
            # lock must span to commit for chain integrity; reducing that window
            # would require decoupling audit from the business transaction (a
            # semantic change, out of scope). Kept as-is deliberately.
            _advisory_lock()
            head = AuditLog.objects.order_by("-id").values_list("self_hash", flat=True).first()
            prev_hash = head or GENESIS_PREV_HASH
            payload = canonical_payload(
                occurred_at=occurred_at,
                user_id=user_id,
                actor_id=actor_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                data_before=before,
                data_after=after,
                ip=ip,
                ua=ua,
            )
            self_hash = compute_self_hash(prev_hash, payload)
            row = AuditLog.objects.create(
                occurred_at=occurred_at,
                user_id=user_id,
                actor_id=actor_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                data_before=before,
                data_after=after,
                ip=ip,
                ua=ua,
                prev_hash=prev_hash,
                self_hash=self_hash,
            )
    except Exception:  # noqa: BLE001 — audit must never break the business action
        logger.exception("audit.emit.failed", extra={"event_type": event_type})
        try:
            AUDIT_EVENTS_DROPPED_TOTAL.inc()
        except Exception:  # noqa: S110,BLE001 — pragma: no cover; metrics must not mask the drop
            pass
        return None

    try:
        AUDIT_EVENTS_TOTAL.labels(family=event_family(event_type)).inc()
    except Exception:  # noqa: S110,BLE001 — pragma: no cover
        pass
    return row
