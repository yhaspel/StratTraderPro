"""Nightly integrity verifier (M10 §6.1 / AC-10-2).

Resumes from a persisted cursor, recomputes each row's hash and linkage, and on
Postgres asserts the two enforcement triggers still exist (drop-detection). On
mismatch: increments ``audit_integrity_check_total{result="fail"}``, emails the
operator, and writes an ``audit.integrity_failure`` row with the suspect id
range. The cursor advances only on success.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings
from django.core.mail import send_mail
from django.db import connection
from django.utils import timezone

from .events import AuditEventType
from .hashing import GENESIS_PREV_HASH, canonical_payload, compute_self_hash
from .metrics import AUDIT_INTEGRITY_CHECK_TOTAL, AUDIT_VERIFIER_DURATION

logger = logging.getLogger(__name__)

TRIGGER_NAMES = ("audit_log_block_mutation", "audit_log_check_link")


def triggers_present() -> bool:
    """True if both enforcement triggers exist (Postgres only; True on SQLite)."""
    if connection.vendor != "postgresql":
        return True
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            WHERE c.relname = 'audit_log' AND t.tgname = ANY(%s) AND NOT t.tgisinternal
            """,
            [list(TRIGGER_NAMES)],
        )
        return cur.fetchone()[0] >= len(TRIGGER_NAMES)


def _row_self_hash(row, prev_hash: str) -> str:
    payload = canonical_payload(
        occurred_at=row.occurred_at,
        user_id=row.user_id,
        actor_id=row.actor_id,
        event_type=row.event_type,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        data_before=row.data_before,
        data_after=row.data_after,
        ip=row.ip,
        ua=row.ua,
    )
    return compute_self_hash(prev_hash, payload)


def verify_chain(*, start_id: int = 0, start_prev_hash: str = GENESIS_PREV_HASH) -> dict:
    """Walk forward from ``start_id`` recomputing hashes + linkage.

    Returns ``{ok, checked, last_id, last_hash, failed_id, reason}``.
    """
    from .models import AuditLog

    prev_hash = start_prev_hash or GENESIS_PREV_HASH
    last_id = start_id
    checked = 0
    qs = AuditLog.objects.filter(id__gt=start_id).order_by("id").iterator()
    for row in qs:
        # Linkage: this row must point at the running head.
        if row.prev_hash != prev_hash:
            return {
                "ok": False,
                "checked": checked,
                "last_id": last_id,
                "last_hash": prev_hash,
                "failed_id": row.id,
                "reason": "linkage_break",
            }
        expected = _row_self_hash(row, prev_hash)
        if expected != row.self_hash:
            return {
                "ok": False,
                "checked": checked,
                "last_id": last_id,
                "last_hash": prev_hash,
                "failed_id": row.id,
                "reason": "hash_mismatch",
            }
        prev_hash = row.self_hash
        last_id = row.id
        checked += 1
    return {
        "ok": True,
        "checked": checked,
        "last_id": last_id,
        "last_hash": prev_hash,
        "failed_id": None,
        "reason": "",
    }


def _notify_failure(result: dict, trigger_ok: bool) -> None:
    to = getattr(settings, "AUDIT_ALERT_EMAIL", "") or getattr(settings, "DEFAULT_FROM_EMAIL", "")
    if not to:
        return
    suspect = result.get("failed_id")
    body = (
        "Audit-log integrity check FAILED.\n\n"
        f"Reason: {result.get('reason') or ('trigger_missing' if not trigger_ok else 'unknown')}\n"
        f"Suspect row id: {suspect}\n"
        f"Last good id: {result.get('last_id')}\n"
        f"Enforcement triggers present: {trigger_ok}\n\n"
        "Freeze audit-consumer trust and investigate before any release "
        "(docs/runbooks/audit-integrity-failure.md)."
    )
    try:
        send_mail(
            subject="[StratTraderPro] AUDIT INTEGRITY FAILURE",
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", to),
            recipient_list=[to],
            fail_silently=True,
        )
    except Exception:  # pragma: no cover — email must not break the verifier
        logger.exception("audit.verifier.email_failed")


def run_verifier() -> dict:
    """Full verifier run: metrics, trigger-presence, cursor advance, audit rows."""
    from .models import AuditVerifierState
    from .services import emit

    started = time.monotonic()
    state = AuditVerifierState.load()
    trigger_ok = triggers_present()
    result = verify_chain(
        start_id=state.last_verified_id,
        start_prev_hash=state.last_verified_hash or GENESIS_PREV_HASH,
    )
    ok = result["ok"] and trigger_ok
    duration = time.monotonic() - started
    AUDIT_VERIFIER_DURATION.observe(duration)
    AUDIT_INTEGRITY_CHECK_TOTAL.labels(result="ok" if ok else "fail").inc()

    state.run_at = timezone.now()
    state.result = "ok" if ok else "fail"
    if ok:
        # Advance the cursor only on success.
        state.last_verified_id = result["last_id"]
        state.last_verified_hash = result["last_hash"]
        state.save(update_fields=["run_at", "result", "last_verified_id", "last_verified_hash"])
        emit(
            AuditEventType.AUDIT_VERIFIER_COMPLETED,
            entity_type="audit_verifier",
            data_after={"checked": result["checked"], "last_id": result["last_id"], "duration_s": round(duration, 3)},
        )
    else:
        state.save(update_fields=["run_at", "result"])
        _notify_failure(result, trigger_ok)
        emit(
            AuditEventType.AUDIT_INTEGRITY_FAILURE,
            entity_type="audit_log",
            entity_id=str(result.get("failed_id") or ""),
            data_after={
                "reason": result.get("reason") or ("trigger_missing" if not trigger_ok else "unknown"),
                "suspect_id": result.get("failed_id"),
                "last_good_id": result.get("last_id"),
                "triggers_present": trigger_ok,
            },
        )
    return {**result, "trigger_ok": trigger_ok, "duration_s": duration}
