"""Migrate ``users_auth_event`` into the chained ``audit_log`` (M10 §6.1 / §8).

Builds the hash chain from genesis over the historical AuthEvent rows in
``(occurred_at, id)`` order, mapping each to the ``auth.*`` taxonomy. Inserts the
original ``occurred_at`` (possible because ``AuditLog.occurred_at`` is
``default=timezone.now``, not ``auto_now_add``).

The hashing functions are a **FROZEN inline copy** of ``apps/audit/hashing.py`` —
migrations must never import app code that can drift. Asserts row-count parity and
that the stored head hash re-verifies. Depends on BOTH ``audit.0002`` (so the
enforcement triggers validate every insert on Postgres) and the latest ``users``
migration (so ``apps.get_model("users", "AuthEvent")`` resolves).
"""
from __future__ import annotations

import hashlib
import json
from datetime import timezone as _tz

from django.core.serializers.json import DjangoJSONEncoder
from django.db import migrations

# --- frozen hashing copy (do NOT import apps.audit.hashing) -----------------
_GENESIS = "0" * 64
_AUDIT_SENSITIVE_KEYS = {
    "authorization", "sig", "secret", "password", "token", "api_key", "dsn",
    "key", "code", "mfa_code",
}


def _iso(dt):
    if isinstance(dt, str):
        return dt
    return dt.astimezone(_tz.utc).isoformat(timespec="microseconds")


def _normalize(value):
    if value is None:
        return None
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _scrub(value):
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if isinstance(k, str) and k.lower() in _AUDIT_SENSITIVE_KEYS else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def _canonical(occurred_at, user_id, actor_id, event_type, entity_type, entity_id,
               data_before, data_after, ip, ua):
    payload = {
        "occurred_at": _iso(occurred_at),
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
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _self_hash(prev_hash, payload):
    return hashlib.sha256(prev_hash.encode("ascii") + payload).hexdigest()


# --- migration --------------------------------------------------------------
def forwards(apps, schema_editor):
    AuthEvent = apps.get_model("users", "AuthEvent")
    AuditLog = apps.get_model("audit", "AuditLog")

    source = list(AuthEvent.objects.all().order_by("occurred_at", "id"))
    prev_hash = _GENESIS
    created = 0
    final_hash = _GENESIS
    for ae in source:
        event_type = f"auth.{ae.event_type}"
        data_after = {"email": ae.email or ""}
        if ae.metadata:
            data_after.update(ae.metadata)
        data_after = _normalize(_scrub(data_after))
        ua = (ae.user_agent or "")[:512]
        payload = _canonical(
            ae.occurred_at, ae.user_id, None, event_type, "", "",
            None, data_after, ae.ip, ua,
        )
        self_hash = _self_hash(prev_hash, payload)
        AuditLog.objects.create(
            occurred_at=ae.occurred_at,
            user_id=ae.user_id,
            actor_id=None,
            event_type=event_type,
            entity_type="",
            entity_id="",
            data_before=None,
            data_after=data_after,
            ip=ae.ip,
            ua=ua,
            prev_hash=prev_hash,
            self_hash=self_hash,
        )
        prev_hash = self_hash
        final_hash = self_hash
        created += 1

    # Self-verify: row-count parity + stored head hash matches the built chain.
    source_count = len(source)
    if created != source_count:
        raise RuntimeError(
            f"audit migration parity failure: created {created} != {source_count} AuthEvent rows"
        )
    if created:
        head = AuditLog.objects.order_by("-id").first()
        if head.self_hash != final_hash:
            raise RuntimeError("audit migration head-hash mismatch after backfill")


def backwards(apps, schema_editor):
    # Irreversible in practice (the chain is rebuilt forward-only); reversing just
    # empties audit_log. On Postgres the append-only trigger blocks DELETE, so the
    # reverse is documented as backup-restore only (ADR-100 / §15).
    if schema_editor.connection.vendor == "postgresql":
        raise migrations.exceptions.IrreversibleError(
            "audit.0003 is forward-only on Postgres (append-only trigger blocks delete); "
            "roll back via DB backup restore."
        )
    AuditLog = apps.get_model("audit", "AuditLog")
    AuditLog.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0002_chain_triggers"),
        ("users", "0003_oauth_exchange_code"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
