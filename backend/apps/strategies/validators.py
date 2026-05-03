"""M03 — strategy upload + webhook payload validators.

The upload endpoint accepts ``multipart/form-data`` with three file parts and
must reject malformed input loudly and consistently. This module is pure
(no Django, no DB) so it can be exercised in isolation.

Public surface:
    validate_uploaded_bundle(file_dict)  -> ParsedBundle
    validate_json_schema(schema)         -> None | raises
    validate_payload_against_schema(payload, schema) -> None | raises
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

# ---------------------------------------------------------------------------
# Limits — surfaced as constants so tests + frontend can reference them.
# ---------------------------------------------------------------------------
PINE_MAX_BYTES = 64 * 1024
DESC_MAX_BYTES = 16 * 1024
WEBHOOK_MAX_BYTES = 16 * 1024

#: Stem regex per plan §6.2 — the upload form sends three files; the *first*
#: file's stem is authoritative and the others must match the
#: ``<stem>_Description.txt`` / ``<stem>_Webhook.json`` naming pattern.
STEM_REGEX = re.compile(r"^[A-Za-z0-9_\-]{3,64}$")

#: Required keys in the webhook JSON payload template at upload time.
REQUIRED_WEBHOOK_KEYS = ("strategy", "action", "symbol", "qty", "order_type")

#: Substrings that are obvious red flags for stored-XSS in any of the three
#: files — the pine and description are displayed as text in the UI and
#: anything matching here is rejected up-front (defense in depth — Angular
#: also escapes by default).
XSS_SIGNATURES = (b"<script", b"javascript:", b"onerror=", b"onload=")

# ---------------------------------------------------------------------------
# Errors — raised by validators, caught by the view and mapped to envelope codes.
# ---------------------------------------------------------------------------
class StrategyValidationError(Exception):
    """Raised by validators; ``code`` maps to a response envelope error.code."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass
class ParsedBundle:
    stem: str
    pine_filename: str
    pine_bytes: bytes
    pine_sha256: str
    desc_filename: str
    desc_bytes: bytes
    desc_sha256: str
    webhook_filename: str
    webhook_bytes: bytes
    webhook_sha256: str
    webhook_template: dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _reject_path_traversal(filename: str) -> None:
    """Reject obviously dangerous filenames before we trust the stem."""
    if not filename:
        raise StrategyValidationError(
            "STRATEGY_FILE_MISMATCH", "Filename is empty.",
        )
    if "\x00" in filename:
        raise StrategyValidationError(
            "STRATEGY_FILE_MISMATCH", "Filename contains a null byte.",
        )
    if "/" in filename or "\\" in filename:
        raise StrategyValidationError(
            "STRATEGY_FILE_MISMATCH", "Filename contains a path separator.",
        )
    if filename.startswith("..") or "/.." in filename:
        raise StrategyValidationError(
            "STRATEGY_FILE_MISMATCH", "Filename contains '..'.",
        )


def _scan_for_xss(label: str, blob: bytes) -> None:
    lowered = blob.lower()
    for sig in XSS_SIGNATURES:
        if sig in lowered:
            raise StrategyValidationError(
                "STRATEGY_WEBHOOK_INVALID",
                f"Suspicious payload detected in {label}: contains {sig!r}.",
            )


# ---------------------------------------------------------------------------
# Bundle validation
# ---------------------------------------------------------------------------
def validate_uploaded_bundle(files: Mapping[str, tuple[str, bytes]]) -> ParsedBundle:
    """Validate a 3-file upload bundle.

    Args:
        files: mapping of form-field-name -> (original_filename, raw_bytes).
               Expected keys: ``pine``, ``description``, ``webhook``.
               (The view normalizes whatever the client sends into this shape.)

    Returns:
        ParsedBundle on success.

    Raises:
        StrategyValidationError on any failure.
    """
    for required in ("pine", "description", "webhook"):
        if required not in files:
            raise StrategyValidationError(
                "STRATEGY_FILE_MISMATCH",
                f"Missing required file part: {required!r}.",
            )

    pine_name, pine_bytes = files["pine"]
    desc_name, desc_bytes = files["description"]
    webhook_name, webhook_bytes = files["webhook"]

    for fn in (pine_name, desc_name, webhook_name):
        _reject_path_traversal(fn)

    # Derive stem from the .pine filename.
    if not pine_name.endswith(".pine"):
        raise StrategyValidationError(
            "STRATEGY_FILE_MISMATCH",
            f"Expected pine file to end in .pine, got {pine_name!r}.",
        )
    stem = pine_name[: -len(".pine")]
    if not STEM_REGEX.match(stem):
        raise StrategyValidationError(
            "STRATEGY_FILE_MISMATCH",
            "Strategy stem must be 3–64 chars, A–Z/a–z/0–9/_/-.",
        )

    expected_desc = f"{stem}_Description.txt"
    expected_webhook = f"{stem}_Webhook.json"
    if desc_name != expected_desc:
        raise StrategyValidationError(
            "STRATEGY_FILE_MISMATCH",
            f"Description filename must be {expected_desc!r} (got {desc_name!r}).",
        )
    if webhook_name != expected_webhook:
        raise StrategyValidationError(
            "STRATEGY_FILE_MISMATCH",
            f"Webhook filename must be {expected_webhook!r} (got {webhook_name!r}).",
        )

    # Size limits.
    if len(pine_bytes) > PINE_MAX_BYTES:
        raise StrategyValidationError(
            "STRATEGY_FILE_TOO_LARGE",
            f"Pine file exceeds {PINE_MAX_BYTES} bytes.",
        )
    if len(desc_bytes) > DESC_MAX_BYTES:
        raise StrategyValidationError(
            "STRATEGY_FILE_TOO_LARGE",
            f"Description exceeds {DESC_MAX_BYTES} bytes.",
        )
    if len(webhook_bytes) > WEBHOOK_MAX_BYTES:
        raise StrategyValidationError(
            "STRATEGY_FILE_TOO_LARGE",
            f"Webhook JSON exceeds {WEBHOOK_MAX_BYTES} bytes.",
        )

    # Pine sanity: must declare //@version=N within first 64 bytes.
    head = pine_bytes[:64].lower()
    if b"//@version=" not in head:
        raise StrategyValidationError(
            "STRATEGY_FILE_MISMATCH",
            "Pine file must declare //@version=N within first 64 bytes.",
        )

    # XSS scan.
    _scan_for_xss("pine", pine_bytes)
    _scan_for_xss("description", desc_bytes)
    _scan_for_xss("webhook", webhook_bytes)

    # Parse webhook JSON.
    try:
        webhook_template = json.loads(webhook_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise StrategyValidationError(
            "STRATEGY_WEBHOOK_INVALID",
            f"Webhook JSON is not UTF-8: {exc}.",
        ) from exc
    except json.JSONDecodeError as exc:
        raise StrategyValidationError(
            "STRATEGY_WEBHOOK_INVALID",
            f"Webhook JSON does not parse: {exc.msg} at line {exc.lineno}.",
        ) from exc

    if not isinstance(webhook_template, dict):
        raise StrategyValidationError(
            "STRATEGY_WEBHOOK_INVALID",
            "Webhook JSON top-level must be an object.",
        )

    missing = [k for k in REQUIRED_WEBHOOK_KEYS if k not in webhook_template]
    if missing:
        raise StrategyValidationError(
            "STRATEGY_WEBHOOK_INVALID",
            f"Webhook JSON missing required keys: {', '.join(missing)}.",
            details={"missing": missing},
        )

    return ParsedBundle(
        stem=stem,
        pine_filename=pine_name,
        pine_bytes=pine_bytes,
        pine_sha256=_sha256(pine_bytes),
        desc_filename=desc_name,
        desc_bytes=desc_bytes,
        desc_sha256=_sha256(desc_bytes),
        webhook_filename=webhook_name,
        webhook_bytes=webhook_bytes,
        webhook_sha256=_sha256(webhook_bytes),
        webhook_template=webhook_template,
    )


# ---------------------------------------------------------------------------
# JSON Schema validation (for the per-config schema editor)
# ---------------------------------------------------------------------------
def validate_json_schema(schema: Any) -> None:
    """Reject malformed JSON Schemas. Allows the empty dict (= no constraints)."""
    if not isinstance(schema, dict):
        raise StrategyValidationError(
            "WEBHOOK_SCHEMA_INVALID",
            "JSON Schema must be a JSON object.",
        )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise StrategyValidationError(
            "WEBHOOK_SCHEMA_INVALID",
            f"Invalid JSON Schema: {exc.message}",
        ) from exc


def validate_payload_against_schema(payload: Any, schema: Mapping) -> None:
    try:
        Draft202012Validator(dict(schema)).validate(payload)
    except JsonSchemaValidationError as exc:
        raise StrategyValidationError(
            "STRATEGY_WEBHOOK_INVALID",
            f"Payload does not match schema: {exc.message}",
        ) from exc


__all__ = [
    "PINE_MAX_BYTES",
    "DESC_MAX_BYTES",
    "WEBHOOK_MAX_BYTES",
    "STEM_REGEX",
    "REQUIRED_WEBHOOK_KEYS",
    "StrategyValidationError",
    "ParsedBundle",
    "validate_uploaded_bundle",
    "validate_json_schema",
    "validate_payload_against_schema",
]
