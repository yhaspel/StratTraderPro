"""Development settings — local runserver + docker-compose."""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "backend"]  # nosec B104

# Local SQLite fallback (docker-compose overrides via DATABASE_URL)
DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3"),
}

CORS_ALLOWED_ORIGINS = [
    "http://localhost:4444",
    "http://localhost:4555",
]
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:4444",
    "http://localhost:4555",
]

# Console email backend in dev — Resend not used locally
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Use console-friendly logging in dev
LOGGING["handlers"]["console"]["formatter"] = "console"

# Disable Sentry in dev unless explicitly set
if not SENTRY_DSN:
    SENTRY_DSN = ""

# Simpler cache for dev
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
