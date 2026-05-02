"""
Base settings for StratTraderPro.
Shared across dev, prod, and test environments.
"""
import os
import subprocess
from datetime import timedelta
from pathlib import Path

import environ

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, ".env"), overwrite=False)

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key-change-in-prod")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

# ---------------------------------------------------------------------------
# Git version (used in /healthz)
# ---------------------------------------------------------------------------
try:
    GIT_SHA = (
        subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
        .decode("ascii")
        .strip()
    )
except Exception:
    GIT_SHA = env("GIT_SHA", default="unknown")

# ---------------------------------------------------------------------------
# Installed apps
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "django_prometheus",
    "anymail",
]

LOCAL_APPS = [
    "apps.users",
    "apps.strategies",
    "apps.webhooks",
    "apps.regime",
    "apps.sentiment",
    "apps.risk",
    "apps.brokers",
    "apps.orders",
    "apps.backtest",
    "apps.marketdata",
    "apps.audit",
    "apps.admin_portal",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

# ---------------------------------------------------------------------------
# URL / WSGI / ASGI
# ---------------------------------------------------------------------------
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "users.User"

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database (overridden per environment)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3"),
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.users.validators.LettersAndDigitsValidator"},
]

# Argon2id is the preferred hasher; legacy hashers retained so existing rows can
# upgrade transparently on next login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# ---------------------------------------------------------------------------
# REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    # M02 — uniform error envelope, MFA_REQUIRED mapping
    "EXCEPTION_HANDLER": "apps.users.exception_handler.custom_exception_handler",
}

# ---------------------------------------------------------------------------
# SimpleJWT
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    # Rotation/reuse handled by our custom RefreshTokenFamily logic, not by
    # simplejwt's blacklist app — but blacklist app is still installed for
    # belt-and-braces revocation of compromised tokens.
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default=SECRET_KEY),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "apps.users.serializers.AuthTokenObtainSerializer",
}

# ---------------------------------------------------------------------------
# Auth (M01) — lockout + token TTLs surfaced for ops adjustment
# ---------------------------------------------------------------------------
AUTH_LOCKOUT_THRESHOLD = env.int("AUTH_LOCKOUT_THRESHOLD", default=10)
AUTH_LOCKOUT_WINDOW_MINUTES = env.int("AUTH_LOCKOUT_WINDOW_MINUTES", default=15)
AUTH_LOCKOUT_DURATION_MINUTES = env.int("AUTH_LOCKOUT_DURATION_MINUTES", default=15)

# Frontend base URL — used to construct verification / reset links in emails.
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:4444")

# ---------------------------------------------------------------------------
# Auth (M02) — MFA
# ---------------------------------------------------------------------------
# Master feature flag: when False, /api/v1/auth/mfa/* return 503 and login
# never branches into the MFA-pending state. Useful for emergency rollback
# without redeploying. See plan-progress-tracker.md M02 §15.
MFA_ENABLED = env.bool("MFA_ENABLED", default=True)

# Fernet key-encryption key (KEK) for MFA secrets at rest. In dev/test we
# derive a deterministic KEK from SECRET_KEY so the test suite + a fresh
# `runserver` work without provisioning. In prod, FERNET_KEK MUST be a real
# 32-byte url-safe base64 key supplied via Railway env. Rotation procedure
# documented in docs/runbooks/mfa-kek-rotation.md.
import base64 as _b64
import hashlib as _hashlib

_default_kek = _b64.urlsafe_b64encode(_hashlib.sha256(SECRET_KEY.encode("utf-8")).digest()).decode("ascii")
FERNET_KEK = env("FERNET_KEK", default=_default_kek)

# MFA token (issued at login for enrolled users, exchanged at /auth/mfa/verify/)
MFA_TOKEN_TTL_MINUTES = env.int("MFA_TOKEN_TTL_MINUTES", default=5)
# TOTP step tolerance: ±1 step (= ±30s) per plan AC-02-11.
MFA_TOTP_VALID_WINDOW = env.int("MFA_TOTP_VALID_WINDOW", default=1)
MFA_TOTP_ISSUER = env("MFA_TOTP_ISSUER", default="StratTraderPro")
MFA_BACKUP_CODE_COUNT = env.int("MFA_BACKUP_CODE_COUNT", default=10)

# ---------------------------------------------------------------------------
# Email (Anymail / Resend; console backend in dev — see dev.py)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="anymail.backends.resend.EmailBackend")
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="StratTraderPro <no-reply@strattraderpro.com>",
)
ANYMAIL = {"RESEND_API_KEY": env("RESEND_API_KEY", default="")}

# ---------------------------------------------------------------------------
# drf-spectacular (OpenAPI)
# ---------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "StratTraderPro API",
    "DESCRIPTION": "Trading bot platform API — webhook-driven, regime-aware, multi-broker.",
    "VERSION": "0.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS: list[str] = []

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULER = "redbeat.RedBeatScheduler"
CELERY_REDBEAT_REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/1"),
    }
}

# ---------------------------------------------------------------------------
# i18n / L10n
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
LANGUAGES = [("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------------
# Logging (structlog with sensitive key scrubbing)
# ---------------------------------------------------------------------------
SENSITIVE_KEYS = {"authorization", "sig", "secret", "password", "token", "api_key", "dsn"}


def _scrub_sensitive(_, __, event_dict):
    """Remove sensitive keys from log output."""
    for key in list(event_dict.keys()):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
        "console": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# ---------------------------------------------------------------------------
# Sentry (configured per-environment)
# ---------------------------------------------------------------------------
SENTRY_DSN = env("SENTRY_DSN", default="")

# ---------------------------------------------------------------------------
# OpenTelemetry
# ---------------------------------------------------------------------------
OTEL_SERVICE_NAME = "strattraderpro-backend"
OTEL_EXPORTER_OTLP_ENDPOINT = env("OTEL_EXPORTER_OTLP_ENDPOINT", default="")
