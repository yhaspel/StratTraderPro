"""System-health aggregation for /admin/health/ (M10 §6.2).

Each section is independently guarded so one failing subsystem degrades to a
null/error marker rather than 500-ing the whole page. Redis LLEN / broker
heartbeats / model ages are read live; the page renders native KPI cards and
links out to Grafana (frozen decision 8).
"""
from __future__ import annotations

import logging

from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — health must never 500
        logger.warning("admin.health.section_failed", extra={"section": getattr(fn, "__name__", "?")})
        return default


def _queue_depths():
    from .queues import all_queue_depths

    return all_queue_depths()


def _broker_streams():
    from apps.brokers.models import BrokerAccount
    from apps.brokers.services import get_stream_status

    counts: dict[str, int] = {}
    for acct in BrokerAccount.objects.filter(status=BrokerAccount.Status.CONNECTED):
        state = get_stream_status(acct)
        counts[state] = counts.get(state, 0) + 1
    return counts


def _hmm_age_seconds():
    from apps.regime.models import HMMModel

    m = HMMModel.objects.filter(active=True).order_by("-trained_at").first()
    if m is None:
        return None
    return int((timezone.now() - m.trained_at).total_seconds())


def _sentiment_backlog():
    from apps.sentiment.tasks import queue_backlog

    return queue_backlog()


def _db_ok():
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return True


def _redis_ok():
    from django.core.cache import cache

    cache.set("admin:health:ping", "1", 10)
    return cache.get("admin:health:ping") == "1"


def _verifier_state():
    from apps.audit.models import AuditVerifierState

    s = AuditVerifierState.load()
    return {
        "last_verified_id": s.last_verified_id,
        "run_at": s.run_at.isoformat() if s.run_at else None,
        "result": s.result or "never",
    }


def _active_halts():
    from apps.brokers.models import TradingHalt

    qs = TradingHalt.objects.filter(released_at__isnull=True)
    return {
        "total": qs.count(),
        "platform": qs.filter(level=TradingHalt.Level.L3).exists(),
    }


def _flags_overridden():
    from .models import FeatureFlag

    return FeatureFlag.objects.count()


def collect_health() -> dict:
    return {
        "queue_depths": _safe(_queue_depths, {}),
        "broker_streams": _safe(_broker_streams, {}),
        "hmm_model_age_seconds": _safe(_hmm_age_seconds),
        "sentiment_backlog": _safe(_sentiment_backlog, {}),
        "db_ok": bool(_safe(_db_ok, False)),
        "redis_ok": bool(_safe(_redis_ok, False)),
        "verifier": _safe(_verifier_state, {}),
        "active_halts": _safe(_active_halts, {}),
        "flags_overridden": _safe(_flags_overridden, 0),
        "generated_at": timezone.now().isoformat(),
    }
