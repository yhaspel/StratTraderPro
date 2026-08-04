"""Canonical hash-chain implementation (ADR-100) — the single source of truth.

``self_hash = SHA-256(prev_hash_ascii_bytes ‖ canonical_payload)``, genesis
``prev_hash`` = 64 zeros. Canonicalization: JSON with sorted keys and
``separators=(",", ":")`` over a fixed field set, ``id`` excluded (unknown before
insert). The verifier walks rows in ``id`` order and recomputes this.

IMPORTANT: the migration ``audit.0003`` inlines a **frozen copy** of these
functions — migrations must never import app code that can drift. Any change here
that alters the digest of an existing row MUST fail the golden-vector test
(``tests/test_hashing.py``) loudly; that is the guard against silent
canonicalization drift (§16).
"""
from __future__ import annotations

import hashlib
import json
from datetime import timezone as _tz

from django.core.serializers.json import DjangoJSONEncoder

GENESIS_PREV_HASH = "0" * 64

# The exact field set + order is irrelevant to the digest (keys are sorted) but
# the presence/absence of each key is not — keep this list frozen.
_FIELDS = (
    "occurred_at",
    "user_id",
    "actor_id",
    "event_type",
    "entity_type",
    "entity_id",
    "data_before",
    "data_after",
    "ip",
    "ua",
)


def iso_timestamp(dt) -> str:
    """ISO-8601 UTC with microseconds, e.g. ``2026-07-09T12:34:56.123456+00:00``.

    Always includes microseconds (``timespec="microseconds"``) so a whole-second
    timestamp hashes the same on write and on verify.
    """
    if isinstance(dt, str):
        return dt
    return dt.astimezone(_tz.utc).isoformat(timespec="microseconds")


def normalize_json(value):
    """Round-trip ``value`` through ``DjangoJSONEncoder`` so what we hash equals
    what JSONField stores (Decimal→str, datetime/UUID→str, …). Without this, a
    row hashed with a raw ``Decimal`` would fail verification after the DB read
    returns the coerced string.
    """
    if value is None:
        return None
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def canonical_payload(
    *,
    occurred_at,
    user_id,
    actor_id,
    event_type,
    entity_type="",
    entity_id="",
    data_before=None,
    data_after=None,
    ip=None,
    ua="",
) -> bytes:
    """Deterministic canonical bytes for one row (``id`` excluded)."""
    payload = {
        "occurred_at": iso_timestamp(occurred_at),
        "user_id": str(user_id) if user_id is not None else None,
        "actor_id": str(actor_id) if actor_id is not None else None,
        "event_type": event_type,
        "entity_type": entity_type or "",
        "entity_id": entity_id or "",
        "data_before": data_before,
        "data_after": data_after,
        "ip": ip if ip else None,
        "ua": ua or "",
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_self_hash(prev_hash: str, payload: bytes) -> str:
    """SHA-256 over the previous hash (ASCII hex) followed by the payload bytes."""
    return hashlib.sha256(prev_hash.encode("ascii") + payload).hexdigest()


def hash_row(prev_hash: str, **fields) -> str:
    """Convenience: canonicalize + chain in one call."""
    return compute_self_hash(prev_hash, canonical_payload(**fields))
