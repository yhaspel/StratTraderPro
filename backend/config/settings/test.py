"""Test settings — fast, isolated, no external deps where possible."""
from .base import *  # noqa: F401, F403

DEBUG = False
SECRET_KEY = "test-secret-key-not-for-production"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Disable password validators for speed in tests
AUTH_PASSWORD_VALIDATORS = []

# Faster password hashing
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# In-memory cache
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Disable Celery during tests (tasks execute synchronously)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Disable Sentry in tests
SENTRY_DSN = ""

# In-memory email outbox during tests
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Loosen rate limits for unit tests; specific tests opt-in by overriding.
RATELIMIT_ENABLE = False
