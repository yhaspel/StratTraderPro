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

# BUG-006 — `otel.initialized` was being swallowed.
#
# init_otel() must run BEFORE get_wsgi_application() (BUG-001), which means it also
# runs before django.setup() applies settings.LOGGING. At that point the root logger
# has no handlers and an INFO record is dropped on the floor (Python's lastResort
# handler only emits WARNING+). So the one line that told you whether tracing was
# actually on vanished — and its absence then *looked* like a regression.
#
# Fix: record the outcome here, and emit it from log_otel_status(), which the
# entrypoints call once logging is configured.
_otlp_enabled: bool | None = None  # None -> init never completed


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


def _traces_endpoint(endpoint: str) -> str:
    """Normalize an OTLP endpoint to the traces signal URL (idempotent)."""
    url = endpoint.rstrip("/")
    if url.endswith("/v1/traces"):
        return url
    return f"{url}/v1/traces"


def init_otel() -> bool:
    """Initialize tracing once per process. Returns True if it initialized now."""
    global _initialized, _otlp_enabled
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

            # The OTLP/HTTP exporter only appends the `/v1/traces` signal path when it
            # resolves the endpoint from the environment itself; an endpoint passed
            # explicitly is used verbatim (see OTLPSpanExporter.__init__:
            # `endpoint or environ.get(..., _append_trace_path(...))`). Passing the
            # OTLP *base* URL therefore POSTs to `/otlp` and every span 404s silently.
            # Normalize so both the base and the full signal URL work.
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=_traces_endpoint(endpoint)))
            )
        trace.set_tracer_provider(provider)
        _instrument()
        _initialized = True
        # Do NOT log here — settings.LOGGING is not applied yet (BUG-006). Stash the
        # outcome; log_otel_status() emits it once the entrypoint has set Django up.
        _otlp_enabled = bool(endpoint)
        return True
    except Exception:  # noqa: BLE001 — tracing must never break boot
        # ERROR *does* survive an unconfigured logging stack (lastResort emits
        # WARNING+), so a broken init is still visible even this early.
        logger.exception("otel.init_failed")
        return False


def log_otel_status() -> None:
    """Emit the boot-time tracing confirmation (BUG-006).

    Call from an entrypoint AFTER Django is set up, i.e. after
    ``get_wsgi_application()`` / ``get_asgi_application()``, so ``settings.LOGGING``
    is in effect and the record actually goes somewhere. No-op if init never
    completed (the failure was already logged by init_otel).
    """
    if _otlp_enabled is None:
        return
    logger.info("otel.initialized", extra={"otlp": _otlp_enabled})


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
