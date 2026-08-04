"""Broker call audit recording (M04 §6.2 / AC-04-12).

Leaf module (imports models only) so adapters can record without importing the
service factory. NEVER receives or stores request/response bodies or keys —
callers pass only the endpoint name, status, latency and a mapped error code.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def record_broker_call(
    *,
    account_id=None,
    user_id=None,
    broker: str = "ALPACA",
    endpoint: str,
    method: str = "GET",
    status_code: int | None = None,
    latency_ms: int | None = None,
    ok: bool = True,
    error_code: str = "",
) -> None:
    from django.db import transaction

    from .models import BrokerCallAudit

    try:
        # Savepoint so a failed audit insert (e.g. stale FK) rolls back only
        # itself and never poisons the caller's surrounding transaction.
        with transaction.atomic():
            BrokerCallAudit.objects.create(
                broker_account_id=account_id,
                user_id=user_id,
                broker=broker,
                endpoint=endpoint[:64],
                method=method[:8],
                status_code=status_code,
                latency_ms=latency_ms,
                ok=ok,
                error_code=(error_code or "")[:48],
            )
    except Exception:  # pragma: no cover — auditing must never break the call
        logger.warning("broker.call_audit.failed", extra={"endpoint": endpoint})
