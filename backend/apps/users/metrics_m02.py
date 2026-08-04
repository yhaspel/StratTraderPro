"""M02 — MFA Prometheus counters (plan §12).

These extend the M01 Auth Health dashboard. Series naming follows the
``mfa_*_total`` convention used by other auth-flow metrics.
"""
from __future__ import annotations

from prometheus_client import Counter

# Successful enrollment (TOTP confirmed).
MFA_ENROLLMENTS_TOTAL = Counter(
    "auth_mfa_enrollments_total",
    "MFA devices that completed verification.",
)

# /auth/mfa/verify/ outcome.
MFA_VERIFICATIONS_TOTAL = Counter(
    "auth_mfa_verifications_total",
    "MFA challenge verifications by outcome.",
    labelnames=("result",),
)
MFAVerifyResult = type("MFAVerifyResult", (), {"OK": "ok", "FAIL": "fail"})

# Backup codes consumed (a separate signal so dashboards can flag spikes).
MFA_BACKUP_USED_TOTAL = Counter(
    "auth_mfa_backup_used_total",
    "Backup codes consumed at /auth/mfa/verify/.",
)

# Total challenge failures (TOTP wrong, backup wrong, on any phase).
# Drives the "MFA challenge failure rate > 20% over 10 min" alert.
MFA_CHALLENGE_FAILURES_TOTAL = Counter(
    "auth_mfa_challenge_failures_total",
    "MFA challenge failures across enroll/verify/disable.",
)

__all__ = [
    "MFA_ENROLLMENTS_TOTAL",
    "MFA_VERIFICATIONS_TOTAL",
    "MFAVerifyResult",
    "MFA_BACKUP_USED_TOTAL",
    "MFA_CHALLENGE_FAILURES_TOTAL",
]
