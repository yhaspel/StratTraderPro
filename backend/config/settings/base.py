"""
Base settings for StratTraderPro.
Shared across dev, prod, and test environments.
"""
import os
import subprocess
from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

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
# Resolution order:
#   1. `git rev-parse` — works in local dev where the repo is mounted.
#   2. `GIT_SHA` env var — explicit override (e.g., baked into a CI image).
#   3. `RAILWAY_GIT_COMMIT_SHA` — auto-injected by Railway on every deploy;
#      trimmed to the short form. This is what makes /healthz on Railway
#      report the real commit instead of "unknown".
#   4. Literal "unknown".
try:
    GIT_SHA = (
        subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
        .decode("ascii")
        .strip()
    )
except Exception:
    GIT_SHA = (
        env("GIT_SHA", default="")
        or env("RAILWAY_GIT_COMMIT_SHA", default="")[:7]
        or "unknown"
    )

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
    "django.contrib.sites",  # M2.5 — required by django-allauth
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
    # M2.5 — django-allauth for Google OAuth (we hijack only the OAuth bits;
    # see apps/users/social_adapters.py for the bridge to our custom JWT pipeline).
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
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
    "apps.dashboard",  # M04 — Channels dashboard consumer
    "apps.backtest",
    "apps.marketdata",
    "apps.audit",
    "apps.admin_portal",
]

# M04 — Django Channels. ``daphne`` MUST precede django.contrib.staticfiles so
# its ASGI runserver takes over in dev; ``channels`` provides the consumer /
# routing / layer machinery. Prod HTTP is still served by gunicorn/WSGI
# (docker/backend.Dockerfile); websockets are served by a dedicated ASGI
# process (docker-compose `ws` service running `daphne config.asgi`).
INSTALLED_APPS = ["daphne"] + DJANGO_APPS + ["channels"] + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    # M10 §6.6 — mint/propagate a request_id (ULID) as early as possible.
    "config.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # M2.5 — required by django-allauth >= 0.61
    "allauth.account.middleware.AccountMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

# M2.5 — django-allauth requires the sites framework
SITE_ID = 1

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

# M2.5 — allauth needs its auth backend installed alongside Django's default
# (which our existing email/password login uses).
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

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
def _wrap_db_engines_for_prometheus(databases):
    """Swap stock Django DB engines for ``django_prometheus`` wrapper
    subclasses so ``/metrics`` emits ``django_db_query_duration_seconds``
    and ``django_db_new_connections_total``. The wrappers are transparent
    drop-in subclasses — same DSN handling, same query behavior. Without
    this, the System Health dashboard's Django DB row stays empty
    (`django_prometheus`'s middleware-side counters work without the
    wrapper, but the DB-side histogram + connection counter do not).
    """
    mapping = {
        "django.db.backends.postgresql": "django_prometheus.db.backends.postgresql",
        "django.db.backends.sqlite3": "django_prometheus.db.backends.sqlite3",
        "django.db.backends.mysql": "django_prometheus.db.backends.mysql",
    }
    for conf in databases.values():
        conf["ENGINE"] = mapping.get(conf["ENGINE"], conf["ENGINE"])
    return databases


DATABASES = _wrap_db_engines_for_prometheus({
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3"),
})
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
    # M10 — impersonation-aware authentication. The read-only write-block for
    # impersonation tokens MUST live at the auth layer: every mutating view
    # overrides permission_classes, which would drop a global permission (§6.2).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.users.authentication.ImpersonationAwareJWTAuthentication",
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
# Auth (M2.5) — Google OAuth via django-allauth
# ---------------------------------------------------------------------------
# We use django-allauth ONLY for the OAuth state machine (Google authorize
# round-trip + SocialAccount bookkeeping). Email verification, password reset,
# session login, and signup forms remain handled by our M01 custom code.
# Bridge logic lives in apps/users/social_adapters.py — it auto-links by
# verified email and bridges the post-callback User into our JWT pipeline.

GOOGLE_OAUTH_ENABLED = env.bool("GOOGLE_OAUTH_ENABLED", default=True)
GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID", default="")
GOOGLE_OAUTH_CLIENT_SECRET = env("GOOGLE_OAUTH_CLIENT_SECRET", default="")

# Exchange-code TTL — frontend POSTs the code to /auth/oauth/exchange/ within
# this window to swap it for a token pair (or MFA challenge).
OAUTH_EXCHANGE_TTL_MINUTES = env.int("OAUTH_EXCHANGE_TTL_MINUTES", default=5)

# allauth account config — neutered to avoid colliding with our M01 flows.
# We mix old-style (AUTHENTICATION_METHOD/USERNAME_REQUIRED) and new-style
# (LOGIN_METHODS/SIGNUP_FIELDS) settings because allauth 0.61 still validates
# both during boot.
ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_VERIFICATION = "none"   # we send our own verification email
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_ADAPTER = "apps.users.social_adapters.AccountAdapter"

# allauth socialaccount config
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True            # auto-link by verified email
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_STORE_TOKENS = False                   # we don't need Google's access token; only ID claims
SOCIALACCOUNT_ADAPTER = "apps.users.social_adapters.SocialAdapter"

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "key": "",
        },
        "SCOPE": ["email", "profile", "openid"],
        "AUTH_PARAMS": {"access_type": "online", "prompt": "select_account"},
        # Trust Google's email_verified claim — that's the whole point of OAuth.
        "VERIFIED_EMAIL": True,
    },
}

# After allauth completes the OAuth dance, redirect to our custom callback view
# which issues the exchange code and 302s to the frontend.
LOGIN_REDIRECT_URL = "/api/v1/auth/oauth/google/post-callback/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"

# ---------------------------------------------------------------------------
# Strategies (M03)
# ---------------------------------------------------------------------------
# Master feature flag — when False, /api/v1/strategies/* return 503.
# Useful for rollback without redeploy. See plan §15.
STRATEGIES_V1_ENABLED = env.bool("STRATEGIES_V1_ENABLED", default=True)

# Public base URL for the per-user/per-strategy webhook receiver. The
# endpoint itself goes live in M04; here we only display the URL to the
# user. Keep the trailing-slash semantics consistent with how TradingView
# constructs alert webhook URLs.
STRATEGY_WEBHOOK_BASE_URL = env(
    "STRATEGY_WEBHOOK_BASE_URL",
    default="https://api.strattraderpro.com/hooks/v1",
)

# ---------------------------------------------------------------------------
# Webhook ingest + Broker execution (M04)
# ---------------------------------------------------------------------------
# Master rollback flags (plan §15): flip either OFF without a redeploy.
#   WEBHOOK_V1_ENABLED=false  → the public webhook returns 503.
#   BROKER_ALPACA_ENABLED=false → Alpaca hidden from the picker; connect /
#                                 place_order return 503; streams exit cleanly.
WEBHOOK_V1_ENABLED = env.bool("WEBHOOK_V1_ENABLED", default=True)
BROKER_ALPACA_ENABLED = env.bool("BROKER_ALPACA_ENABLED", default=True)

# Hard paper-only default in M04. Live keys are rejected by validation and the
# Alpaca adapter hard-codes the paper endpoint, so this flag alone cannot turn
# on live trading in M04 — it is the master gate later milestones read.
ENABLE_LIVE_TRADING = env.bool("ENABLE_LIVE_TRADING", default=False)

# Webhook hardening (§6.3 / §11). Rate limit is applied BEFORE the body is read.
WEBHOOK_RATE_LIMIT_PER_MIN = env.int("WEBHOOK_RATE_LIMIT_PER_MIN", default=60)
WEBHOOK_MAX_BODY_BYTES = env.int("WEBHOOK_MAX_BODY_BYTES", default=16 * 1024)
WEBHOOK_IDEMPOTENCY_TTL_SECONDS = env.int("WEBHOOK_IDEMPOTENCY_TTL_SECONDS", default=86400)
# Optional TradingView source-IP allowlist — empty = disabled (default).
WEBHOOK_IP_ALLOWLIST = env.list("WEBHOOK_IP_ALLOWLIST", default=[])

# Fill transport. When True, publish_fill applies fills inline/synchronously
# (no Redis Stream, no consumer group) so the whole webhook→fill→position→WS
# path runs under SQLite + eager Celery in tests. Prod/staging keep this False
# and use the real Redis Stream `fills:user:{id}` + the FillIngestor consumer.
FILLS_INLINE = env.bool("FILLS_INLINE", default=False)

# Streams service heartbeat freshness (seconds) before a broker flips DEGRADED.
BROKER_STREAM_HEARTBEAT_TTL = env.int("BROKER_STREAM_HEARTBEAT_TTL", default=45)

# Optional platform-level Alpaca paper keys — LOCAL SMOKE ONLY. Production
# users always bring their own keys via the UI (stored encrypted per-user).
# Read by the `alpaca_smoke` management command; empty by default.
ALPACA_PAPER_KEY_ID = env("ALPACA_PAPER_KEY_ID", default="")
ALPACA_PAPER_SECRET_KEY = env("ALPACA_PAPER_SECRET_KEY", default="")

# ---------------------------------------------------------------------------
# Order lifecycle + second broker (M05)
# ---------------------------------------------------------------------------
# TradeStation is approval-gated (API access + no official Python SDK). The
# adapter + OAuth2/PKCE code path ship behind this flag, OFF by default; the
# live OAuth flow + real sim fills are verified later once access is granted.
BROKER_TRADESTATION_ENABLED = env.bool("BROKER_TRADESTATION_ENABLED", default=False)
TRADESTATION_CLIENT_ID = env("TRADESTATION_CLIENT_ID", default="")
TRADESTATION_CLIENT_SECRET = env("TRADESTATION_CLIENT_SECRET", default="")
TRADESTATION_REDIRECT_URI = env(
    "TRADESTATION_REDIRECT_URI",
    default="http://localhost:8777/api/v1/brokers/tradestation/oauth/callback/",
)
# Sim (paper) base URL in M05; the live URL is never used until the M12 gate.
TRADESTATION_API_BASE = env("TRADESTATION_API_BASE", default="https://sim-api.tradestation.com/v3")
TRADESTATION_OAUTH_BASE = env("TRADESTATION_OAUTH_BASE", default="https://signin.tradestation.com")
# OAuth `state` single-use TTL (Redis-backed).
TRADESTATION_OAUTH_STATE_TTL = env.int("TRADESTATION_OAUTH_STATE_TTL", default=600)

# Live trading requires BOTH this global flag AND per-user opt-in + a signed
# versioned disclaimer. False until the M12 gate (AC-05-8 enforcement).
LIVE_TRADING_DISCLAIMER_VERSION = env("LIVE_TRADING_DISCLAIMER_VERSION", default="v1")

# ---------------------------------------------------------------------------
# Market data + regime classifier (M06)
# ---------------------------------------------------------------------------
ENABLE_REGIME_UI = env.bool("ENABLE_REGIME_UI", default=True)
# FMP (equities/sector/treasury) + FRED (credit spreads). Keys are deferred
# externals — empty by default; all live calls are fixture-mocked in CI.
FMP_API_KEY = env("FMP_API_KEY", default="")
FMP_BASE_URL = env("FMP_BASE_URL", default="https://financialmodelingprep.com/stable")
FMP_RATE_LIMIT_PER_MIN = env.int("FMP_RATE_LIMIT_PER_MIN", default=750)
FRED_API_KEY = env("FRED_API_KEY", default="")
# Rule-classifier weight overrides (feature → signed weight); empty = defaults.
REGIME_RULE_WEIGHTS: dict = {}
# HMM retrain seed (deterministic training in CI).
REGIME_HMM_SEED = env.int("REGIME_HMM_SEED", default=42)

# ---------------------------------------------------------------------------
# Sentiment pipeline (M07)
# ---------------------------------------------------------------------------
SENTIMENT_ENABLED = env.bool("SENTIMENT_ENABLED", default=True)
# Tier-2 LLM (Llama) is behind its own flag — off drops to FinBERT-only
# (AC-07-10). Default OFF; enabled only on the dedicated llm-worker service.
LLM_WORKER_ENABLED = env.bool("LLM_WORKER_ENABLED", default=False)
# Real FinBERT (transformers[torch]) is off by default; the base image ships
# the FakeFinBert. The sentiment worker image sets FINBERT_ENABLED=true.
FINBERT_ENABLED = env.bool("FINBERT_ENABLED", default=False)
# When True (default), scorers are the deterministic canned fakes — no model
# weights required. The worker image sets this False to use the real models.
SENTIMENT_FAKE_SCORERS = env.bool("SENTIMENT_FAKE_SCORERS", default=True)
SENTIMENT_SPACY_NER = env.bool("SENTIMENT_SPACY_NER", default=False)
SENTIMENT_ALIAS_TAGGING = env.bool("SENTIMENT_ALIAS_TAGGING", default=True)
# GGUF path on the mounted volume (llm-worker image). Deferred external.
LLAMA_GGUF_PATH = env("LLAMA_GGUF_PATH", default="/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf")

# ---------------------------------------------------------------------------
# Risk engine + kill switches (M08)
# ---------------------------------------------------------------------------
# When off, process_alert uses the alert-provided qty directly (M04 behavior).
SIZING_V1_ENABLED = env.bool("SIZING_V1_ENABLED", default=True)
# When off, only the plain per-strategy on/off toggle is honored (plan §15).
KILL_SWITCHES_ENABLED = env.bool("KILL_SWITCHES_ENABLED", default=True)
# NOTE: sizing never falls back to a constant equity — a failed broker read
# fails CLOSED with a SIZING_NO_EQUITY reject (FIX-H2). No RISK_DEFAULT_EQUITY.

# ---------------------------------------------------------------------------
# Walk-forward backtester (M09)
# ---------------------------------------------------------------------------
# Master rollback flag (plan §15): when False the UI nav is hidden and all
# /api/v1/backtest/* endpoints return 503 BACKTEST_DISABLED. The nightly
# eviction beat still runs (default queue) so retention keeps working — it
# doubles as orphan cleanup while the feature is disabled.
BACKTEST_ENABLED = env.bool("BACKTEST_ENABLED", default=True)

# ---------------------------------------------------------------------------
# Admin portal + audit (M10)
# ---------------------------------------------------------------------------
# Env-only master gate (immutable flag): off → all /api/v1/admin/* return 503
# ADMIN_PORTAL_DISABLED and the frontend hides /admin. Audit emission is never
# gated by this (writes continue). Rollback without redeploy (§15).
ADMIN_PORTAL_ENABLED = env.bool("ADMIN_PORTAL_ENABLED", default=True)
# Operator address the nightly integrity verifier pages on a failure (AC-10-2).
AUDIT_ALERT_EMAIL = env("AUDIT_ALERT_EMAIL", default="")
# Read-only impersonation token/session TTL (AC-10-7).
IMPERSONATION_TTL_MINUTES = env.int("IMPERSONATION_TTL_MINUTES", default=15)

# Feature-flag registry (M10 §6.4). Each entry's ``default`` is the env-parsed
# settings value above (the fail-open target). Immutable flags (``mutable=False``)
# are env-only forever — the admin API rejects a flip with FLAG_IMMUTABLE.
# Dangerous flags require a typed name-confirm in the UI (server still MFA-gates).
def _flag(default, description, *, mutable=True, dangerous=False):
    return {"default": bool(default), "description": description, "mutable": mutable, "dangerous": dangerous}


FEATURE_FLAGS_REGISTRY = {
    "MFA_ENABLED": _flag(MFA_ENABLED, "MFA challenge + enrollment endpoints.", mutable=False),
    "GOOGLE_OAUTH_ENABLED": _flag(GOOGLE_OAUTH_ENABLED, "Google OAuth sign-in."),
    "STRATEGIES_V1_ENABLED": _flag(STRATEGIES_V1_ENABLED, "Strategy CRUD + upload API."),
    "WEBHOOK_V1_ENABLED": _flag(WEBHOOK_V1_ENABLED, "Public webhook ingest."),
    "BROKER_ALPACA_ENABLED": _flag(BROKER_ALPACA_ENABLED, "Alpaca broker adapter."),
    "BROKER_TRADESTATION_ENABLED": _flag(BROKER_TRADESTATION_ENABLED, "TradeStation broker adapter."),
    "ENABLE_LIVE_TRADING": _flag(ENABLE_LIVE_TRADING, "Master live-trading gate.", dangerous=True),
    "FILLS_INLINE": _flag(FILLS_INLINE, "Apply fills inline (no Redis stream).", mutable=False),
    "ENABLE_REGIME_UI": _flag(ENABLE_REGIME_UI, "Regime dashboard UI."),
    "SENTIMENT_ENABLED": _flag(SENTIMENT_ENABLED, "Sentiment pipeline + API."),
    "LLM_WORKER_ENABLED": _flag(LLM_WORKER_ENABLED, "Tier-2 LLM (Llama) scorer."),
    "FINBERT_ENABLED": _flag(FINBERT_ENABLED, "Real FinBERT scorer."),
    "SENTIMENT_FAKE_SCORERS": _flag(SENTIMENT_FAKE_SCORERS, "Use canned fake scorers.", dangerous=True),
    "SENTIMENT_SPACY_NER": _flag(SENTIMENT_SPACY_NER, "spaCy NER entity tagging."),
    "SENTIMENT_ALIAS_TAGGING": _flag(SENTIMENT_ALIAS_TAGGING, "Alias-based ticker tagging."),
    "SIZING_V1_ENABLED": _flag(SIZING_V1_ENABLED, "Risk-based position sizing.", dangerous=True),
    "KILL_SWITCHES_ENABLED": _flag(KILL_SWITCHES_ENABLED, "Kill-switch engine.", mutable=False),
    "BACKTEST_ENABLED": _flag(BACKTEST_ENABLED, "Walk-forward backtester."),
    "ADMIN_PORTAL_ENABLED": _flag(ADMIN_PORTAL_ENABLED, "Admin portal API.", mutable=False),
}

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
    # Keep the default enum hook and append the M04 webhook-path injector
    # (the webhook is a plain Django view outside DRF — see apps.webhooks.schema).
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "apps.webhooks.schema.add_webhook_path",
    ],
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
# Backstop so a task blocked on a black-holed broker HTTP call can't wedge a
# worker forever (FIX-H7). Soft raises SoftTimeLimitExceeded for cleanup; hard
# kills the worker process. Keep soft < hard.
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=30)
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=45)
# Prometheus scrape port for long-lived task processes (streams/worker/beat),
# which don't sit behind gunicorn's /metrics. 0 = disabled (FIX-C1).
TASK_METRICS_PORT = env.int("TASK_METRICS_PORT", default=0)

# M09 — dedicated `backtest` queue. **Explicit per-task route only** (first
# task-route in the repo): a `apps.backtest.tasks.*` glob would drag the nightly
# eviction task onto the backtest queue and silently break retention whenever
# the backtest worker is absent. `run_backtest` → backtest queue; everything
# else (incl. evict_expired_artifacts) stays on the default `celery` queue.
CELERY_TASK_ROUTES = {
    "apps.backtest.tasks.run_backtest": {"queue": "backtest"},
}

# Beat schedule. `fill_ingestor` drains the Redis fill streams (no-op under
# FILLS_INLINE, so inert in tests). run_broker_streams is deployed as its own
# always-on service, not a beat task.
CELERY_BEAT_SCHEDULE = {
    "fill-ingestor": {
        "task": "apps.orders.tasks.fill_ingestor",
        "schedule": env.float("FILL_INGESTOR_INTERVAL_SECONDS", default=5.0),
    },
    # M05 — reconcile positions against broker truth every 5 minutes.
    "reconcile-positions": {
        "task": "apps.orders.tasks.reconcile_positions_task",
        "schedule": env.float("RECONCILE_INTERVAL_SECONDS", default=300.0),
    },
    # M06 — nightly HMM retrain (~03:00 ET) + authoritative daily feature vector.
    "regime-retrain-hmm": {
        "task": "apps.regime.tasks.retrain_hmm",
        "schedule": crontab(hour=7, minute=0),
    },
    "regime-compute-features-daily": {
        "task": "apps.regime.tasks.compute_features_daily",
        "schedule": crontab(hour=22, minute=30),
    },
    # M07 — news ingest (15 min) → score pending → aggregate.
    "sentiment-ingest-news": {
        "task": "apps.sentiment.tasks.ingest_news",
        "schedule": env.float("SENTIMENT_INGEST_INTERVAL_SECONDS", default=900.0),
    },
    "sentiment-score-pending": {
        "task": "apps.sentiment.tasks.score_pending_articles",
        "schedule": env.float("SENTIMENT_SCORE_INTERVAL_SECONDS", default=120.0),
    },
    "sentiment-aggregate": {
        "task": "apps.sentiment.tasks.aggregate_sentiment",
        "schedule": env.float("SENTIMENT_AGG_INTERVAL_SECONDS", default=300.0),
    },
    # M08 — daily-loss circuit-breaker watcher (every 30s during market hours).
    "risk-daily-loss-watcher": {
        "task": "apps.risk.tasks.daily_loss_watcher",
        "schedule": env.float("DAILY_LOSS_INTERVAL_SECONDS", default=30.0),
    },
    # M09 — nightly (03:30 UTC) eviction of expired backtest artifacts. Runs on
    # the DEFAULT `celery` queue (not `backtest`) so retention keeps working when
    # the backtest worker is scaled to zero / not yet provisioned (§6.8).
    "backtest-evict-artifacts": {
        "task": "apps.backtest.tasks.evict_expired_artifacts",
        "schedule": crontab(hour=3, minute=30),
    },
    # M10 — nightly (08:00 UTC ≈ 04:00 ET) audit-chain integrity verification.
    # Default `celery` queue (M09 rule: no glob routes).
    "audit-verify-integrity": {
        "task": "apps.audit.tasks.verify_audit_integrity",
        "schedule": crontab(hour=8, minute=0),
    },
    # M10 — refresh celery_queue_depth{queue} gauge every 30s (default queue).
    "admin-queue-depths": {
        "task": "apps.admin_portal.tasks.update_queue_depths",
        "schedule": env.float("QUEUE_DEPTH_INTERVAL_SECONDS", default=30.0),
    },
}

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/1"),
        # Fail FAST on an unreachable/hung Redis instead of blocking the worker
        # until its 120s timeout. Without these, a Redis that accepts the TCP
        # connection but never responds hangs `/readyz`, `flags.is_enabled()`
        # (whose except only catches errors, not a blocking socket), webhook
        # idempotency, and rate limiting. With a short timeout the socket raises,
        # callers fall back gracefully (flags fail open to the env default).
        "OPTIONS": {
            "socket_connect_timeout": env.float("REDIS_SOCKET_CONNECT_TIMEOUT", default=2.0),
            "socket_timeout": env.float("REDIS_SOCKET_TIMEOUT", default=2.0),
        },
    }
}

# ---------------------------------------------------------------------------
# Channels (M04 — realtime dashboard)
# ---------------------------------------------------------------------------
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [env("REDIS_URL", default="redis://localhost:6379/0")]},
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
# Logging
# ---------------------------------------------------------------------------
# NOTE (M10 §6.1): the sensitive-key scrubber (SENSITIVE_KEYS + _scrub_sensitive)
# was relocated to apps/audit/scrub.py so the audit service and the log config
# share one key set (ADR-100). Import here only if a logging processor needs it.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    # M10 §6.6 — inject request_id + task_id into every record.
    "filters": {
        "request_context": {"()": "config.request_context.RequestContextFilter"},
    },
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(request_id)s %(task_id)s %(message)s",
        },
        "console": {
            "format": "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
            "filters": ["request_context"],
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

# ---------------------------------------------------------------------------
# Metrics exposition basic auth (M10 §6.5a). Unset → open (dev/test); prod warns.
# ---------------------------------------------------------------------------
METRICS_BASIC_AUTH_USERNAME = env("METRICS_BASIC_AUTH_USERNAME", default="")
METRICS_BASIC_AUTH_PASSWORD = env("METRICS_BASIC_AUTH_PASSWORD", default="")
