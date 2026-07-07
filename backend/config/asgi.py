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

# Initialize Django's app registry BEFORE importing consumers/routing so model
# imports inside them resolve.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.dashboard.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Auth is JWT-in-query-string + MFA enforcement inside the consumer
        # (plan §6.6), so no channels auth middleware is layered here.
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
