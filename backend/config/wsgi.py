"""WSGI config for StratTraderPro (the gunicorn prod entry — docker/backend.Dockerfile)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

_django_app = get_wsgi_application()

# M10 §6.6 — OTel init at the prod WSGI entry (asgi-only wiring would leave the
# scraped web tier untraced). No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set.
from config.otel import init_otel  # noqa: E402

init_otel()

# M10 §6.5a — /metrics served OUTSIDE Django's urlconf, in this same gunicorn
# process so the prometheus multiprocess mmap files are readable + the scrape
# bypasses the middleware chain (removes the Sentry before_send mitigation).
from config.metrics_endpoint import wrap_wsgi  # noqa: E402

application = wrap_wsgi(_django_app)
