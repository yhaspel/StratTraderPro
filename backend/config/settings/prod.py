"""Production settings — Railway deployment."""
import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F401, F403

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
DATABASES = {
    "default": env.db("DATABASE_URL"),
}

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
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        environment=env(
            "SENTRY_ENVIRONMENT",
            default=env("RAILWAY_ENVIRONMENT_NAME", default="production"),
        ),
    )
