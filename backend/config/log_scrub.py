"""Stdlib logging filter that redacts sensitive fields (M11 §7.1 V7).

M10 relocated the key set to ``apps.audit.scrub`` but flagged that the scrubber
was **never wired into the python-json-logger LOGGING config** — only the audit
*row* scrubber was active. This is the missing wire: a real ``logging.Filter``
attached to the console handler that redacts any record attribute whose name is a
sensitive key, so a secret passed via ``logger.info(..., extra={"api_key": x})``
can never reach the JSON log line. Same key set as the audit scrubber (ADR-100).
"""
from __future__ import annotations

import logging

from apps.audit.scrub import REDACTED, SENSITIVE_KEYS


class SensitiveDataFilter(logging.Filter):
    """Redact sensitive-named ``extra=`` fields from every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__.keys()):
            if key.lower() in SENSITIVE_KEYS:
                record.__dict__[key] = REDACTED
        return True
