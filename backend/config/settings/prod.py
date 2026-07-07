"""Production settings — Railway deployment."""
import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F401, F403
from .base import _wrap_db_engines_for_prometheus  # noqa: F401  star-import skips _names

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
# Railway terminates TLS at the edge — letting Django redirect HTTP→HTTPS
# again would create an infinite loop because the proxied request looks like HTTP.
# Keep this False on Railway; rely on the platform/CDN to enforce HTTPS.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = _wrap_db_engines_for_prometheus({
    "default": env.db("DATABASE_URL"),
})

# ---------------------------------------------------------------------------
# Logging — JSON format for structured log aggregation
# ---------------------------------------------------------------------------
LOGGING["handlers"]["console"]["formatter"] = "json"

# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------
# Derive Sentry environment from Railway's auto-injected
# RAILWAY_ENVIRONMENT_NAME (`staging` or `production`) so events from
# different envs group separately on the Sentry dashboard. Override via
# SENTRY_ENVIRONMENT if running outside Railway. Was previously hardcoded
# to "production" — a bug, since staging also runs under config.settings.prod.
def _sentry_before_send(event, hint):
    """Drop a known-noisy AttributeError that fires on every ``/metrics``
    scrape due to a 3-way interaction between django-allauth's
    ``AccountMiddleware``, Django ASGI mode, and ``sentry-sdk``'s ASGI
    auto-instrumentation.

    The chain that produces the error:

    1. ``gunicorn ... --worker-class uvicorn.workers.UvicornWorker``
       runs us as a fully ASGI app (see ``docker/backend.Dockerfile``).
    2. ``sentry_sdk.init(...)`` here installs ``DjangoIntegration``,
       which in ASGI mode wraps the app with ``SentryASGIMixin``.
    3. ``allauth.account.middleware.AccountMiddleware`` is a sync
       ``MiddlewareMixin`` that calls ``response.headers.get(...)`` in
       ``_should_check_dangling_login`` (allauth/account/middleware.py:40).
    4. On ``/metrics`` requests, the ``response`` object reaching that
       check is the unawaited coroutine ``SentryASGIMixin.__call__``
       rather than an ``HttpResponse``. ``coroutine.headers`` raises
       ``AttributeError: 'coroutine' object has no attribute 'headers'``.

    Functional impact: **none for users.** ``/metrics`` actually returns
    200 with the metric payload (grafana-agent successfully scrapes —
    confirmed via ``up{job="backend"}=1`` on the System Health dashboard).
    The exception fires in post-response middleware after the body is
    streamed. The cost is purely Sentry quota: at one Sentry event per
    scrape × 30s scrape interval × 2 envs = ~240 events/hr, the free
    tier's 5,000 events/month would be exhausted in ~21 hours.

    This filter drops *only* this specific exception when transaction is
    ``/metrics``. Real bugs anywhere else, including any other
    ``AttributeError`` on the same path, are still reported.

    Long-term fix (planned M10 §6.5): mount ``/metrics`` outside Django
    via ``prometheus_client.exposition.make_asgi_app()`` so the entire
    middleware chain (including allauth) is bypassed for scrapes. Track
    upstream fixes in ``django-allauth`` and ``sentry-sdk`` issues —
    once either side handles the async/sync handoff properly, this
    filter can be removed.
    """
    if "exc_info" in hint:
        exc_type, exc_value, _ = hint["exc_info"]
        if (
            exc_type is AttributeError
            and "'coroutine'" in str(exc_value)
            and "'headers'" in str(exc_value)
            and "/metrics" in (event.get("transaction") or "")
        ):
            return None
    return event


if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        # Never serialize stack-frame locals into events. Broker adapters
        # construct `TradingClient(api_key=..., secret_key=...)` with plaintext
        # keys as call args; with frame locals on, any exception escaping that
        # frame would ship the keys to Sentry (AC-04-12). Off = no creds leak.
        include_local_variables=False,
        environment=env(
            "SENTRY_ENVIRONMENT",
            default=env("RAILWAY_ENVIRONMENT_NAME", default="production"),
        ),
        before_send=_sentry_before_send,
    )
