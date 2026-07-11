"""WSGI config for StratTraderPro (the gunicorn prod entry — docker/backend.Dockerfile)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

# M10 §6.6 — OTel init at the prod WSGI entry (asgi-only wiring would leave the
# scraped web tier untraced). No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set.
#
# ORDER IS LOAD-BEARING: DjangoInstrumentor activates by inserting its middleware
# into settings.MIDDLEWARE, but Django's WSGIHandler freezes the middleware chain
# in its constructor (load_middleware()). Initializing OTel *after*
# get_wsgi_application() mutates a list nothing reads again, so the web tier emits
# zero request spans (exporter healthy, Tempo empty). Init must precede it.
from config.otel import init_otel, log_otel_status  # noqa: E402

init_otel()

_django_app = get_wsgi_application()

# BUG-006 — now that django.setup() has applied settings.LOGGING, emit the
# "is tracing actually on?" confirmation. Logging it inside init_otel() would be
# too early: the root logger has no handlers yet and the INFO record is discarded.
log_otel_status()

# M10 §6.5a — /metrics served OUTSIDE Django's urlconf, in this same gunicorn
# process so the prometheus multiprocess mmap files are readable + the scrape
# bypasses the middleware chain (removes the Sentry before_send mitigation).
from config.metrics_endpoint import wrap_wsgi  # noqa: E402

application = wrap_wsgi(_django_app)
