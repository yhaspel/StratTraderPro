"""
Auth Prometheus counters (M01 plan §12).

These are scraped by django-prometheus' /metrics endpoint and shipped by the
Railway grafana-agent to Grafana Cloud, where the series are queryable in
Explore. The M01 Auth Health dashboard and its three alert rules that used to
read them were retired by ADR-109 (2026-08).

Result-label vocabulary is fixed — adding a new value is fine, but renaming
one will break the dashboard panels and alert expressions.
"""
from __future__ import annotations

from prometheus_client import Counter

# ---------------------------------------------------------------------------
# Login outcome
# ---------------------------------------------------------------------------
LOGIN_TOTAL = Counter(
    "auth_login_total",
    "Login attempts by terminal outcome.",
    labelnames=("result",),
)
# Allowed `result` values (kept as a constant so views can stay typo-safe).
LoginResult = type(
    "LoginResult",
    (),
    {
        "OK": "ok",
        "BAD_PASSWORD": "bad_password",
        "UNVERIFIED": "unverified",
        "LOCKED": "locked",
        "RATE_LIMITED": "rate_limited",
    },
)

# ---------------------------------------------------------------------------
# Refresh outcome
# ---------------------------------------------------------------------------
REFRESH_TOTAL = Counter(
    "auth_refresh_total",
    "Refresh-token rotation attempts by outcome.",
    labelnames=("result",),
)
RefreshResult = type(
    "RefreshResult",
    (),
    {
        "OK": "ok",
        "REUSE_DETECTED": "reuse_detected",
        "FAMILY_REVOKED": "family_revoked",
        "INVALID": "invalid",
    },
)

# ---------------------------------------------------------------------------
# Family revocations (no labels — every increment is a security signal)
# ---------------------------------------------------------------------------
FAMILY_REVOCATIONS_TOTAL = Counter(
    "auth_family_revocations_total",
    "Refresh-token families burned (reuse, logout, password reset, manual).",
)

# ---------------------------------------------------------------------------
# Password reset funnel
# ---------------------------------------------------------------------------
PASSWORD_RESET_TOTAL = Counter(
    "auth_password_reset_total",
    "Password reset funnel events.",
    labelnames=("step",),
)
PasswordResetStep = type(
    "PasswordResetStep",
    (),
    {
        "REQUESTED": "requested",   # POST /password/reset/  (link emailed)
        "CONFIRMED": "confirmed",   # POST /password/reset/confirm/  (new pw set)
    },
)


# ---------------------------------------------------------------------------
# Transactional email delivery
# ---------------------------------------------------------------------------
# services._send_templated() deliberately swallows provider errors so a Resend
# outage (or a 403 from an unverified sending domain) never 500s the endpoint
# the user is standing on. The cost of that choice is silence: a registration
# whose verification email was rejected still returns 201, and nothing anywhere
# says so. This counter is that missing signal — alert on
# rate(auth_email_send_total{result="error"}[15m]) > 0.
EMAIL_SEND_TOTAL = Counter(
    "auth_email_send_total",
    "Transactional email sends by template and outcome.",
    labelnames=("template", "result"),
)
EmailSendResult = type(
    "EmailSendResult",
    (),
    {
        "OK": "ok",        # provider accepted the message
        "ERROR": "error",  # provider rejected / network failed — nothing was sent
    },
)


__all__ = [
    "LOGIN_TOTAL",
    "LoginResult",
    "REFRESH_TOTAL",
    "RefreshResult",
    "FAMILY_REVOCATIONS_TOTAL",
    "PASSWORD_RESET_TOTAL",
    "PasswordResetStep",
    "EMAIL_SEND_TOTAL",
    "EmailSendResult",
]
