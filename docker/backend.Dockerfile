# ---------- Stage 1: Build wheels ----------
FROM python:3.14-slim AS builder

WORKDIR /build
COPY backend/requirements/ requirements/
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements/prod.txt

# ---------- Stage 2: Runtime ----------
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prom-multiproc

# prometheus_client multiprocess mode (see backend/gunicorn.conf.py): each
# worker mmaps its counter state into this directory; the /metrics handler
# aggregates across all files. Must exist before the first worker boots.
RUN mkdir -p /tmp/prom-multiproc

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
# UvicornWorker requires an ASGI app (config.asgi); using config.wsgi here would
# raise `WSGIHandler.__call__() missing 1 required positional argument:
# 'start_response'` on every request. config.asgi.py exposes an ASGI app via
# django.core.asgi.get_asgi_application — that's what uvicorn expects.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.asgi:application --config /app/gunicorn.conf.py --bind 0.0.0.0:${PORT} --workers 3 --worker-class uvicorn.workers.UvicornWorker --timeout 120 --access-logfile - --error-logfile -"]
