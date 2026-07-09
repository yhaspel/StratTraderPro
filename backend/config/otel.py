"""OpenTelemetry initialization (M10 §6.6, frozen decision 7).

Instruments Django, Celery, redis, psycopg2, and httpx. The OTLP exporter is
wired ONLY when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set (empty default = no
export, keeping tests/dev clean). Called from ``config/wsgi.py`` (the prod
gunicorn entry), ``config/asgi.py`` (dev/daphne), and ``worker_process_init``.
Idempotent — safe to call from multiple entrypoints in one process.
"""
from __future__ import annotations

import hashlib
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_initialized = False


def user_id_hash(user_id) -> str:
    """First 16 hex of sha256(user id) — never a raw id in trace backends."""
    return hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:16]


def current_trace_id() -> str | None:
    """The active OTel span's 32-hex trace id, or None when tracing is off."""
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if ctx and ctx.is_valid:
            return format(ctx.trace_id, "032x")
    except Exception:  # noqa: BLE001,S110 — tracing optional
        pass
    return None


def tag_sentry_correlation() -> dict:
    """Tag the current Sentry scope with ``request_id`` + ``trace_id`` (§6.6).

    Returns the applied tags (for testing). Safe when Sentry is disabled.
    """
    from config.request_context import get_request_id

    tags = {}
    rid = get_request_id()
    if rid:
        tags["request_id"] = rid
    tid = current_trace_id()
    if tid:
        tags["trace_id"] = tid
    try:
        import sentry_sdk

        for k, v in tags.items():
            sentry_sdk.set_tag(k, v)
    except Exception:  # noqa: BLE001,S110 — Sentry optional
        pass
    return tags


def init_otel() -> bool:
    """Initialize tracing once per process. Returns True if it initialized now."""
    global _initialized
    if _initialized:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider(
            resource=Resource.create({"service.name": getattr(settings, "OTEL_SERVICE_NAME", "strattraderpro-backend")})
        )
        endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _instrument()
        _initialized = True
        logger.info("otel.initialized", extra={"otlp": bool(endpoint)})
        return True
    except Exception:  # noqa: BLE001 — tracing must never break boot
        logger.exception("otel.init_failed")
        return False


def _instrument() -> None:
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    DjangoInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    RedisInstrumentor().instrument()
    Psycopg2Instrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
