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

# M11 §7.0 — the SERVICE_ROLE dispatcher (BUG-011). It lives OUTSIDE /app because
# every backend-image compose service bind-mounts ./backend:/app, which would mask
# anything under /app; and `COPY backend/ .` above does not carry the repo's
# docker/ dir, so it needs its own COPY. chmod defends against a non-exec commit.
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

# M11 operator follow-up — bake the commit SHA INTO the image.
#
# /healthz previously reported a stale SHA in production (said e5ecd75, was running
# dd93bcb). Every other source of the SHA is runtime state and can drift from the
# code actually in the container. A value written here cannot: it ships with the
# layer it describes. config/settings/base.py reads this file FIRST, above every
# env var (see _resolve_git_sha).
#
# Railway exposes RAILWAY_GIT_COMMIT_SHA to the builder; declaring the ARG lets it
# through. If it is absent (plain `docker build`, or a Railway change that stops
# providing it) the file is simply empty and the old env-var chain still applies —
# so this fails SOFT and can never make /healthz worse than it is today.
ARG RAILWAY_GIT_COMMIT_SHA=""
RUN printf '%s' "${RAILWAY_GIT_COMMIT_SHA}" > /app/.git_sha \
    && echo "baked git sha: [$(cat /app/.git_sha)]"

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
#
# M11 §7.0 — CMD (not ENTRYPOINT, so `docker run <image> <cmd>` still overrides
# it for debugging) is the SERVICE_ROLE dispatcher. The `web` role reproduces the
# exact gunicorn command above (pinned in docker/entrypoint.expected). Unset or
# unrecognised SERVICE_ROLE => exit 1, never a silent `web` fallback (BUG-011).
CMD ["/usr/local/bin/entrypoint.sh"]
