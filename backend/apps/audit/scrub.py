"""Sensitive-key scrubbing (M10 §6.1 — relocated from config/settings/base.py).

Two consumers:

1. ``_scrub_sensitive(_, __, event_dict)`` — the original python-json-logger /
   structlog-style processor kept verbatim (``apps/users/tests.py`` imports and
   tests it) so the logging behaviour is unchanged; it operates on the base
   ``SENSITIVE_KEYS`` set.

2. ``scrub(value)`` — the audit-log data scrubber for ``data_before`` /
   ``data_after`` diffs. It walks nested dicts/lists and redacts any key in
   ``AUDIT_SENSITIVE_KEYS`` = ``SENSITIVE_KEYS`` ∪ ``{key, code, mfa_code}`` (admin
   mutations post ``mfa_code`` in bodies that can land in diffs). Audit rows must
   never store a secret (§11) — this is the guard.
"""
from __future__ import annotations

REDACTED = "***REDACTED***"

# The base set (was config/settings/base.py:618). Log scrubbing uses exactly this.
SENSITIVE_KEYS = {"authorization", "sig", "secret", "password", "token", "api_key", "dsn"}

# Audit rows additionally redact MFA/secret material posted in admin mutation bodies.
AUDIT_SENSITIVE_KEYS = SENSITIVE_KEYS | {"key", "code", "mfa_code"}


def _scrub_sensitive(_, __, event_dict):
    """Remove sensitive keys from log output (unchanged logging processor)."""
    for key in list(event_dict.keys()):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
    return event_dict


def scrub(value, _keys=AUDIT_SENSITIVE_KEYS):
    """Deep-redact sensitive keys in an audit ``data_before``/``data_after`` value.

    Returns a new structure (does not mutate the caller's dict). Non-container
    values pass through unchanged.
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _keys:
                out[k] = REDACTED
            else:
                out[k] = scrub(v, _keys)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub(v, _keys) for v in value]
    return value
