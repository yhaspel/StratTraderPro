"""ASGI config for StratTraderPro.

Prod HTTP is served by gunicorn/WSGI (``config.wsgi``); this ASGI entrypoint
carries the M04 Channels websocket protocol (``/ws/dashboard/``) and is run by
a dedicated ASGI process (docker-compose ``ws`` service: ``daphne config.asgi``).
The ``http`` branch is kept wired so a single ASGI server can also serve HTTP
in dev / local runserver.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

# M10 §6.6 — OTel init on the ASGI (dev/daphne) entry too.
#
# ORDER IS LOAD-BEARING (mirrors config/wsgi.py): DjangoInstrumentor activates by
# inserting its middleware into settings.MIDDLEWARE, and Django freezes the
# middleware chain when the handler is constructed. Init must precede
# get_asgi_application() or the HTTP branch emits zero request spans.
from config.otel import init_otel, log_otel_status  # noqa: E402

init_otel()

# Initialize Django's app registry BEFORE importing consumers/routing so model
# imports inside them resolve.
django_asgi_app = get_asgi_application()

# BUG-006 — settings.LOGGING is applied now, so the confirmation actually lands.
log_otel_status()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.dashboard.routing import websocket_urlpatterns  # noqa: E402

# M10 §6.5a — mirror the /metrics exposition for dev runserver/daphne parity.
from config.metrics_endpoint import wrap_asgi_http  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": wrap_asgi_http(django_asgi_app),
        # Auth is JWT-in-query-string + MFA enforcement inside the consumer
        # (plan §6.6), so no channels auth middleware is layered here.
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
