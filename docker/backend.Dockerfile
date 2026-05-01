# ---------- Stage 1: Build wheels ----------
FROM python:3.12-slim AS builder

WORKDIR /build
COPY backend/requirements/ requirements/
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements/prod.txt

# ---------- Stage 2: Runtime ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

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
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.asgi:application --bind 0.0.0.0:${PORT} --workers 3 --worker-class uvicorn.workers.UvicornWorker --timeout 120 --access-logfile - --error-logfile -"]
