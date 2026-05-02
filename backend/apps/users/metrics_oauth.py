"""M2.5 — OAuth Prometheus counters.

These extend the Auth Health dashboard with a "Google OAuth" panel row.
Series naming follows the auth_oauth_*_total convention.
"""
from __future__ import annotations

from prometheus_client import Counter

OAUTH_LOGIN_TOTAL = Counter(
    "auth_oauth_login_total",
    "OAuth callback outcomes after Google round-trip + adapter run.",
    labelnames=("result",),
)
OAuthLoginResult = type("OAuthLoginResult", (), {"OK": "ok", "FAIL": "fail"})

OAUTH_EXCHANGE_TOTAL = Counter(
    "auth_oauth_exchange_total",
    "OAuth exchange-code redemption outcomes.",
    labelnames=("result",),
)
OAuthExchangeResult = type(
    "OAuthExchangeResult",
    (),
    {"OK": "ok", "MFA_REQUIRED": "mfa_required", "INVALID": "invalid"},
)

__all__ = [
    "OAUTH_LOGIN_TOTAL",
    "OAuthLoginResult",
    "OAUTH_EXCHANGE_TOTAL",
    "OAuthExchangeResult",
]
