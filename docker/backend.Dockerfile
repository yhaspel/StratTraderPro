# ---------- Stage 1: Build wheels ----------
FROM python:3.12-slim AS builder

WORKDIR /build
COPY backend/requirements/ requirements/
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements/prod.txt

# ---------- Stage 2: Runtime ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prom-multiproc

# prometheus_client multiprocess mode (see backend/gunicorn.conf.py): each
# worker mmaps its counter state into this directory; the /metrics handler
# aggregates across all files. Must exist before the first worker boots.
RUN mkdir -p /tmp/prom-multiproc

# WeasyPrint (M09 PDF tearsheets) native deps — Pango/HarfBuzz/fontconfig + a
# font (DejaVu). No Cairo needed for WeasyPrint >= 53. Kept in sync with the
# apt list in .github/workflows/ci.yml (CI runs pytest on the runner, not here).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pre-built wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application code
COPY backend/ .

# Collect static files
RUN python manage.py collectstatic --noinput 2>/dev/null || true

# Railway injects PORT at runtime; 8777 stays as the local docker-compose default
ENV PORT=8777
EXPOSE 8777

# On boot: run migrations (idempotent, safe to repeat) then launch gunicorn.
# Using `sh -c` so ${PORT} expands at container start, not build time.
#
# WSGI hotfix (2026-05-20): switched from `config.asgi:application` +
# UvicornWorker back to `config.wsgi:application` with gthread workers.
# Reason: sentry-sdk 1.x DjangoIntegration installs SentryASGIMixin around
# the ASGI app; when allauth's *sync* AccountMiddleware reaches
# `_should_check_dangling_login` and calls `response.headers.get(...)`,
# `response` is the unawaited coroutine from SentryASGIMixin.__call__, so
# every request raises `AttributeError: 'coroutine' object has no attribute
# 'headers'` and gunicorn returns 500. The pre-existing /metrics
# `before_send` Sentry filter only suppressed the *event*, not the 500.
# Swapping to WSGI sidesteps the SentryASGIMixin entirely.
#
# Trade-off: no Channels/WebSocket support until M04 needs it. When ready,
# upgrade `sentry-sdk` to >=2.x (which has async-aware DjangoIntegration)
# and restore ASGI:
#   --worker-class uvicorn.workers.UvicornWorker config.asgi:application
# Tracked in plan §10.6.5.a (the long-term /metrics mount fix also resolves
# the underlying allauth/ASGI interaction).
#
# `gthread` worker class gives 3 workers × 4 threads = ~12 concurrent
# requests with the existing memory footprint, comparable to UvicornWorker's
# previous concurrency profile.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --config /app/gunicorn.conf.py --bind 0.0.0.0:${PORT} --workers 3 --worker-class gthread --threads 4 --timeout 120 --access-logfile - --error-logfile -"]
