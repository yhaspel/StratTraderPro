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
# C2 — fail CLOSED on missing / insecure signing + encryption keys.
# base.py falls back to a PUBLIC dev default for SECRET_KEY (and derives the
# JWT signing key + Fernet KEK from it) so tests/runserver work unprovisioned.
# In prod that default forges JWTs and derives the KEK for every stored broker
# secret/TOTP — so re-read both with NO default (django-environ raises when
# unset) and reject the known insecure values. Fails the boot early.
# ---------------------------------------------------------------------------
import base64 as _b64  # noqa: E402
import hashlib as _hashlib  # noqa: E402

from django.core.exceptions import ImproperlyConfigured  # noqa: E402

_INSECURE_SECRET = "insecure-dev-key-change-in-prod"

SECRET_KEY = env("SECRET_KEY")  # no default → ImproperlyConfigured if unset
if SECRET_KEY == _INSECURE_SECRET:
    raise ImproperlyConfigured(
        "SECRET_KEY is the insecure dev default — set a real SECRET_KEY in prod."
    )

FERNET_KEK = env("FERNET_KEK")  # no default → ImproperlyConfigured if unset
_insecure_kek = _b64.urlsafe_b64encode(
    _hashlib.sha256(_INSECURE_SECRET.encode("utf-8")).digest()
).decode("ascii")
if FERNET_KEK == _insecure_kek:
    raise ImproperlyConfigured(
        "FERNET_KEK is the SHA-derived dev default — set a real FERNET_KEK in prod."
    )

# Defense in depth: the JWT signing key (base.py defaults it to SECRET_KEY) must
# not be unset or the insecure default either.
if SIMPLE_JWT.get("SIGNING_KEY") in ("", None, _INSECURE_SECRET):  # noqa: F405
    raise ImproperlyConfigured(
        "SIMPLE_JWT SIGNING_KEY is unset or the insecure default in prod."
    )

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
# Metrics exposition — warn loudly if basic auth is unconfigured in prod.
# ---------------------------------------------------------------------------
import logging as _logging  # noqa: E402

# M1 — /metrics fails CLOSED in prod: if basic-auth creds are unset the endpoint
# returns 401 (see config/metrics_endpoint._auth_ok) rather than exposing metrics
# openly. Still warn loudly so the operator knows to provision the creds.
METRICS_REQUIRE_AUTH = True
if not (METRICS_BASIC_AUTH_USERNAME and METRICS_BASIC_AUTH_PASSWORD):  # noqa: F405
    _logging.getLogger("config.metrics_endpoint").warning(
        "METRICS_BASIC_AUTH_USERNAME/PASSWORD unset — /metrics will 401 (fail "
        "closed) in production until both env vars are set (backend + grafana-agent)."
    )

# ---------------------------------------------------------------------------
# GDPR export storage (M11 §7.7) — Cloudflare R2 (S3-compatible). Only switch to
# the S3 backend when a bucket is configured; otherwise keep the filesystem
# default and mark storage NOT ready so the export task leaves jobs PENDING with
# an operator note (risk §17) instead of crashing on an unconfigured backend.
# ---------------------------------------------------------------------------
_exports_bucket = env("EXPORTS_BUCKET", default="")
if _exports_bucket:
    STORAGES["exports"] = {  # noqa: F405
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": _exports_bucket,
            "access_key": env("AWS_ACCESS_KEY_ID", default=""),
            "secret_key": env("AWS_SECRET_ACCESS_KEY", default=""),
            # R2 (or any S3-compatible) endpoint, e.g. https://<acct>.r2.cloudflarestorage.com
            "endpoint_url": env("AWS_S3_ENDPOINT_URL", default=""),
            "region_name": env("AWS_S3_REGION_NAME", default="auto"),
            # 24h presigned download URLs (frozen decision §4.2).
            "querystring_auth": True,
            "querystring_expire": EXPORT_SIGNED_URL_TTL_SECONDS,  # noqa: F405
            "default_acl": None,  # R2 is private-by-default; no ACLs
            "file_overwrite": True,
        },
    }
    EXPORTS_STORAGE_READY = True
else:
    EXPORTS_STORAGE_READY = False
    _logging_gdpr = __import__("logging").getLogger("apps.users.gdpr")
    _logging_gdpr.warning(
        "EXPORTS_BUCKET unset — GDPR exports stay PENDING until Cloudflare R2 is "
        "provisioned (set EXPORTS_BUCKET + AWS_* + AWS_S3_ENDPOINT_URL). See docs/ops/prod-bringup.md."
    )

# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------
# Derive Sentry environment from Railway's auto-injected RAILWAY_ENVIRONMENT_NAME
# (`staging` or `production`) so events from different envs group separately.
#
# M10 §6.5a — the `_sentry_before_send` /metrics filter is DELETED: under the WSGI
# revert (docker/backend.Dockerfile) the allauth/ASGI crash it filtered cannot
# occur, and /metrics no longer traverses Django middleware at all now that it is
# served out of the urlconf (config/metrics_endpoint.py).
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
        # M10 §6.5e — tag events with the deploy SHA for release health.
        release=GIT_SHA if GIT_SHA != "unknown" else None,  # noqa: F405
    )
