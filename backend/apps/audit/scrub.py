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

# Exact keys the audit scrubber redacts. The short/broad ones ("sig", "key",
# "code") are kept exact-only — as substrings they'd over-match "design",
# "monkey", "zip_code".
AUDIT_SENSITIVE_KEYS = SENSITIVE_KEYS | {"key", "code", "mfa_code"}

# P1-9 — shared substring denylist. A key is sensitive if it CONTAINS any of
# these, so variants like ``api_secret``, ``current_password``,
# ``secret_encrypted``, ``refresh_token`` are caught (exact match missed them).
# Shared with the GDPR export redactor (apps.users.gdpr) so there is one source
# of truth. Every entry is long enough not to over-match common field names.
SENSITIVE_FIELD_PARTS = (
    "secret",
    "password",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "_enc",
    "encrypted",
    "credential",
    "private_key",
    "current_jti",
    "code_hash",
    "salt",
    "dsn",
)


def _key_is_sensitive(key: str) -> bool:
    low = key.lower()
    return low in AUDIT_SENSITIVE_KEYS or any(part in low for part in SENSITIVE_FIELD_PARTS)


def _scrub_sensitive(_, __, event_dict):
    """Remove sensitive keys from log output (unchanged logging processor)."""
    for key in list(event_dict.keys()):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
    return event_dict


def scrub(value):
    """Deep-redact sensitive keys in an audit ``data_before``/``data_after`` value.

    A key is redacted if it exactly matches the audit key set OR contains a
    sensitive substring (P1-9), so ``api_secret`` / ``secret_encrypted`` /
    ``current_password`` never persist into the immutable log. Returns a new
    structure (does not mutate the caller's dict).
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and _key_is_sensitive(k):
                out[k] = REDACTED
            else:
                out[k] = scrub(v)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value
