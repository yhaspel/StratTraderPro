"""Audit event taxonomy (M10 §6.1) — the single source of truth.

``AuthEventType`` is the M01 ``AuthEvent.EventType`` enum, relocated here so it
survives the ``AuthEvent`` table drop (frozen decision 1). The users app imports
it as ``EventType`` and passes bare values (``"login_ok"``) to
``record_event()``, which prepends the ``auth.`` namespace before calling
``emit()``. Keep the values byte-identical to the historical column so the data
migration maps cleanly.

``AuditEventType`` holds the non-auth namespaces. ``EVENT_TYPE_CHOICES`` is the
combined ``(value, label)`` list used for ``AuditLog.event_type`` choices.
"""
from __future__ import annotations

from django.db import models

# The ``auth.`` namespace prefix that ``record_event`` prepends.
AUTH_NAMESPACE = "auth."


class AuthEventType(models.TextChoices):
    """Relocated from ``apps.users.models.AuthEvent.EventType`` (26 values)."""

    REGISTER = "register"
    VERIFY_EMAIL = "verify_email"
    LOGIN_OK = "login_ok"
    LOGIN_FAIL = "login_fail"
    LOGOUT = "logout"
    REFRESH_OK = "refresh_ok"
    REFRESH_REUSE = "refresh_reuse"
    FAMILY_REVOKED = "family_revoked"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"  # noqa: S105
    PASSWORD_RESET_CONFIRMED = "password_reset_confirmed"  # noqa: S105
    ACCOUNT_LOCKED = "account_locked"
    RESEND_VERIFICATION = "resend_verification"
    MFA_ENROLLED = "mfa_enrolled"
    MFA_DISABLED = "mfa_disabled"
    MFA_CHALLENGE_OK = "mfa_challenge_ok"
    MFA_CHALLENGE_FAIL = "mfa_challenge_fail"
    BACKUP_CODE_USED = "backup_code_used"
    BACKUP_CODES_REGENERATED = "backup_codes_regenerated"
    PASSWORD_CHANGED = "password_changed"  # noqa: S105
    PROFILE_UPDATED = "profile_updated"
    SESSION_REVOKED = "session_revoked"
    OAUTH_LOGIN_OK = "oauth_login_ok"
    OAUTH_USER_CREATED = "oauth_user_created"
    OAUTH_LINKED = "oauth_linked"
    OAUTH_EXCHANGE_OK = "oauth_exchange_ok"
    OAUTH_EXCHANGE_FAIL = "oauth_exchange_fail"


class AuditEventType(models.TextChoices):
    """Non-auth namespaces written directly through ``emit()``."""

    # broker.*
    BROKER_CONNECT = "broker.connect", "Broker connected"
    BROKER_DISCONNECT = "broker.disconnect", "Broker disconnected"
    BROKER_MODE_CHANGE = "broker.mode_change", "Broker mode changed"
    # order.*
    ORDER_SUBMITTED = "order.submitted", "Order submitted"
    ORDER_FILL_INGESTED = "order.fill_ingested", "Fill ingested"
    # strategy.*
    STRATEGY_CREATED = "strategy.created", "Strategy created"
    STRATEGY_UPDATED = "strategy.updated", "Strategy updated"
    STRATEGY_DELETED = "strategy.deleted", "Strategy deleted"
    STRATEGY_SECRET_ROTATED = "strategy.secret_rotated", "Webhook secret rotated"
    # risk.*
    RISK_PROFILE_CHANGED = "risk.profile_changed", "Risk profile changed"
    RISK_HALT_ENGAGED = "risk.halt_engaged", "Kill switch engaged"
    RISK_HALT_RELEASED = "risk.halt_released", "Kill switch released"
    # admin.*
    ADMIN_USER_DISABLED = "admin.user_disabled", "User disabled"
    ADMIN_USER_ENABLED = "admin.user_enabled", "User enabled"
    ADMIN_IMPERSONATION_STARTED = "admin.impersonation_started", "Impersonation started"
    ADMIN_IMPERSONATION_STOPPED = "admin.impersonation_stopped", "Impersonation stopped"
    ADMIN_IMPERSONATED_READ = "admin.impersonated_read", "Impersonated read"
    ADMIN_PLATFORM_HALT_ENGAGED = "admin.platform_halt_engaged", "Platform halt engaged"
    ADMIN_PLATFORM_HALT_RELEASED = "admin.platform_halt_released", "Platform halt released"
    # flag.*
    FLAG_FLIPPED = "flag.flipped", "Feature flag flipped"
    # audit.*
    AUDIT_INTEGRITY_FAILURE = "audit.integrity_failure", "Audit integrity failure"
    AUDIT_VERIFIER_COMPLETED = "audit.verifier_completed", "Audit verifier completed"
    # security.* (C3 — step-up MFA brute-force throttle)
    MFA_STEPUP_THROTTLED = "security.mfa_stepup_throttled", "MFA step-up throttled"
    # account.* / terms.* (M11 §7.7/§7.8 — GDPR export/delete + terms acceptance)
    ACCOUNT_EXPORT_REQUESTED = "account.export_requested", "Data export requested"
    ACCOUNT_EXPORT_READY = "account.export_ready", "Data export ready"
    ACCOUNT_EXPORT_FAILED = "account.export_failed", "Data export failed"
    ACCOUNT_DELETE_REQUESTED = "account.delete_requested", "Account deletion requested"
    ACCOUNT_DELETE_CANCELLED = "account.delete_cancelled", "Account deletion cancelled"
    ACCOUNT_ANONYMIZED = "account.anonymized", "Account anonymized"
    TERMS_ACCEPTED = "terms.accepted", "Terms accepted"


def auth_event_type(value: str) -> str:
    """Namespaced audit event type for a bare auth event value."""
    return f"{AUTH_NAMESPACE}{value}"


# Full choices for the AuditLog.event_type field: every auth.* value + the rest.
_AUTH_CHOICES = [
    (auth_event_type(v), f"auth: {label}")
    for v, label in AuthEventType.choices
]
EVENT_TYPE_CHOICES = _AUTH_CHOICES + list(AuditEventType.choices)

# Convenience: the set of all valid event-type strings (used by tests).
ALL_EVENT_TYPES = {value for value, _ in EVENT_TYPE_CHOICES}

# The event-type "families" (namespace prefix) used for the audit_events_total
# metric label and the advisory admin-hours rule.
def event_family(event_type: str) -> str:
    return event_type.split(".", 1)[0] if "." in event_type else event_type
