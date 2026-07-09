"""Out-of-urlconf Prometheus /metrics exposition (M10 §6.5a, AC-10-12).

Served OUTSIDE Django's URL conf so scrapes bypass the whole middleware chain
(this removes the Sentry ``before_send`` mitigation). Wired into ``config/wsgi.py``
(the scraped gunicorn prod entry — same process, so the multiprocess mmap files
are readable) and mirrored in ``config/asgi.py`` for dev/daphne.

Multiprocess-aware: uses ``MultiProcessCollector`` when ``PROMETHEUS_MULTIPROC_DIR``
is set (gunicorn), else the per-process default registry. Basic auth is enforced
when ``METRICS_BASIC_AUTH_USERNAME``/``PASSWORD`` are set; unset → open (dev/test),
with prod logging a loud warning at startup (see ``settings/prod.py``).
"""
from __future__ import annotations

import base64
import hmac
import logging
import os

from django.conf import settings
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    generate_latest,
)
from prometheus_client import (
    REGISTRY as _DEFAULT_REGISTRY,
)
from prometheus_client import (
    multiprocess as _multiprocess,
)

logger = logging.getLogger(__name__)


def _registry():
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        reg = CollectorRegistry()
        _multiprocess.MultiProcessCollector(reg)
        return reg
    return _DEFAULT_REGISTRY


def _auth_ok(authorization: str) -> bool:
    user = getattr(settings, "METRICS_BASIC_AUTH_USERNAME", "") or ""
    pw = getattr(settings, "METRICS_BASIC_AUTH_PASSWORD", "") or ""
    if not user and not pw:
        return True  # open in dev/test
    if not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
    except Exception:  # noqa: BLE001
        return False
    u, _, p = decoded.partition(":")
    return hmac.compare_digest(u, user) and hmac.compare_digest(p, pw)


def _payload() -> bytes:
    return generate_latest(_registry())


# ---------------------------------------------------------------------------
# WSGI
# ---------------------------------------------------------------------------
def metrics_wsgi_app(environ, start_response):
    if not _auth_ok(environ.get("HTTP_AUTHORIZATION", "")):
        start_response(
            "401 Unauthorized",
            [("WWW-Authenticate", 'Basic realm="metrics"'), ("Content-Type", "text/plain")],
        )
        return [b"unauthorized"]
    data = _payload()
    start_response(
        "200 OK",
        [("Content-Type", CONTENT_TYPE_LATEST), ("Content-Length", str(len(data)))],
    )
    return [data]


def wrap_wsgi(django_app):
    """Dispatch ``/metrics`` to the exposition app, everything else to Django."""

    def app(environ, start_response):
        if environ.get("PATH_INFO") == "/metrics":
            return metrics_wsgi_app(environ, start_response)
        return django_app(environ, start_response)

    return app


# ---------------------------------------------------------------------------
# ASGI (dev / daphne parity)
# ---------------------------------------------------------------------------
async def metrics_asgi_app(scope, receive, send):
    headers = {k.lower(): v for k, v in scope.get("headers", [])}
    authorization = headers.get(b"authorization", b"").decode("latin-1")
    if not _auth_ok(authorization):
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"www-authenticate", b'Basic realm="metrics"'),
                                (b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"unauthorized"})
        return
    data = _payload()
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", CONTENT_TYPE_LATEST.encode("latin-1"))]})
    await send({"type": "http.response.body", "body": data})


def wrap_asgi_http(django_asgi_app):
    """Route ``/metrics`` to the ASGI exposition app, everything else to Django."""

    async def app(scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/metrics":
            await metrics_asgi_app(scope, receive, send)
            return
        await django_asgi_app(scope, receive, send)

    return app
