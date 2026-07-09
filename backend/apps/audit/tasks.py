"""Audit Celery tasks (M10 §6.1). Nightly integrity verifier on the default
``celery`` queue (M09 rule: no glob routes; explicit per-task routes only)."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.audit.tasks.verify_audit_integrity")
def verify_audit_integrity():
    """Nightly hash-chain integrity verification (beat: 08:00 UTC ≈ 04:00 ET)."""
    from .verifier import run_verifier

    result = run_verifier()
    logger.info(
        "audit.verifier.run",
        extra={"ok": result["ok"], "checked": result["checked"], "trigger_ok": result["trigger_ok"]},
    )
    return {"ok": result["ok"], "checked": result["checked"]}
