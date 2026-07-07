"""M03 — strategies service layer.

Pure-ish helpers used by the views, the management command, and tests.
Anything that must NOT appear in a logger call (secrets, raw template bytes
near rotation) lives here behind a short, audited interface.
"""
from __future__ import annotations

import hashlib
import logging
import secrets as _secrets
import uuid
from dataclasses import dataclass
from typing import Optional

from cryptography.fernet import InvalidToken as FernetInvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.users.mfa import _fernet  # reuse the same KEK as MFA secrets

from .models import Strategy, StrategyFile, WebhookConfig
from .validators import REQUIRED_WEBHOOK_KEYS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Webhook URL builder
# ---------------------------------------------------------------------------
def build_webhook_url(*, user_id: uuid.UUID | str, strategy_id: uuid.UUID | str) -> str:
    """``https://api.../hooks/v1/<user_uuid>/<strategy_uuid>/`` — endpoint live in M04."""
    base = settings.STRATEGY_WEBHOOK_BASE_URL.rstrip("/")
    return f"{base}/{user_id}/{strategy_id}/"


# ---------------------------------------------------------------------------
# Secret encryption — same Fernet KEK as MFA, separate function for clarity.
# ---------------------------------------------------------------------------
def encrypt_secret(raw: str) -> bytes:
    return _fernet().encrypt(raw.encode("ascii"))


def decrypt_secret(blob: bytes) -> str:
    try:
        return _fernet().decrypt(bytes(blob)).decode("ascii")
    except FernetInvalidToken as exc:  # pragma: no cover — operational
        raise RuntimeError(
            "Webhook secret could not be decrypted (KEK mismatch?)"
        ) from exc


def generate_secret() -> str:
    """48 random urlsafe bytes — plenty for HMAC."""
    return _secrets.token_urlsafe(48)


# ---------------------------------------------------------------------------
# Default webhook schema + template (used at config creation time)
# ---------------------------------------------------------------------------
def default_payload_template(strategy_slug: str) -> dict:
    """Reasonable starter payload that satisfies the stock JSON schema."""
    return {
        "strategy": strategy_slug,
        "action": "buy",
        "symbol": "AAPL",
        "qty": 1,
        "order_type": "MKT",
        "sig": "PASTE_YOUR_SECRET_HERE",
        "idempotency_key": "tv-{{strategy.order.id}}-{{time}}",
    }


def default_json_schema() -> dict:
    """Sensible starting JSON Schema. Users can edit; M04 still enforces the
    minimum required keys at the ingest endpoint regardless."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": list(REQUIRED_WEBHOOK_KEYS),
        "properties": {
            "strategy": {"type": "string"},
            "action": {"type": "string", "enum": ["buy", "sell", "exit"]},
            "symbol": {"type": "string"},
            "qty": {"type": "number"},
            # Extended order types + asset classes land in M05; STP_LMT + the
            # option/future descriptors flow through additionalProperties.
            "order_type": {"type": "string", "enum": ["MKT", "LMT", "STP", "STP_LMT"]},
            "asset_class": {"type": "string", "enum": ["STOCK", "ETF", "OPTION", "FUTURE"]},
            "sig": {"type": "string"},
            "idempotency_key": {"type": "string"},
        },
        "additionalProperties": True,
    }


# ---------------------------------------------------------------------------
# WebhookConfig CRUD + rotate
# ---------------------------------------------------------------------------
@dataclass
class RotationResult:
    config: WebhookConfig
    new_secret: str
    url: str


@transaction.atomic
def get_or_create_webhook_config(*, user, strategy: Strategy) -> tuple[WebhookConfig, bool, Optional[str]]:
    """First-time access creates a fresh config (with secret) AND returns the
    plaintext secret so the view can do reveal-once. Subsequent calls return
    ``(config, False, None)``."""
    try:
        cfg = WebhookConfig.objects.get(user=user, strategy=strategy)
        return cfg, False, None
    except WebhookConfig.DoesNotExist:
        raw = generate_secret()
        cfg = WebhookConfig.objects.create(
            user=user,
            strategy=strategy,
            secret_encrypted=encrypt_secret(raw),
            json_schema=default_json_schema(),
            payload_template=default_payload_template(strategy.slug),
            version=1,
        )
        return cfg, True, raw


@transaction.atomic
def rotate_secret(*, config: WebhookConfig) -> RotationResult:
    """Generate a fresh secret, increment version, return plaintext for one
    reveal-only response. Old secret is overwritten in place — rotation is
    intentionally destructive (AC-03-7)."""
    raw = generate_secret()
    config.secret_encrypted = encrypt_secret(raw)
    config.version += 1
    config.rotated_at = timezone.now()
    config.save(update_fields=["secret_encrypted", "version", "rotated_at", "updated_at"])
    return RotationResult(
        config=config,
        new_secret=raw,
        url=build_webhook_url(user_id=config.user_id, strategy_id=config.strategy_id),
    )


# ---------------------------------------------------------------------------
# load_strategies helpers — directory walk
# ---------------------------------------------------------------------------
@dataclass
class SeedSummary:
    seeded: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = None  # populated lazily

    def add_error(self, msg: str):
        if self.errors is None:
            self.errors = []
        self.errors.append(msg)


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


@transaction.atomic
def upsert_system_strategy(
    *,
    slug: str,
    name: str,
    description_short: str,
    pine_filename: str,
    pine_bytes: bytes,
    desc_filename: str,
    desc_bytes: bytes,
    webhook_filename: str,
    webhook_bytes: bytes,
) -> tuple[Strategy, bool]:
    """Idempotent create-or-update for a system strategy.

    Idempotency: if the existing row's three files all match by SHA-256, this
    is a no-op (returns ``(strategy, False)``). Otherwise files are replaced.
    """
    strategy, created = Strategy.objects.get_or_create(
        owner=None, slug=slug,
        defaults={
            "name": name,
            "description_short": description_short[:256],
            "is_system": True,
            "is_enabled": True,
        },
    )
    if not created:
        # Refresh display fields if changed.
        dirty: list[str] = []
        if strategy.name != name:
            strategy.name = name
            dirty.append("name")
        if strategy.description_short != description_short[:256]:
            strategy.description_short = description_short[:256]
            dirty.append("description_short")
        if dirty:
            strategy.save(update_fields=[*dirty, "updated_at"])

    expected = {
        StrategyFile.Kind.PINE: (pine_filename, pine_bytes),
        StrategyFile.Kind.DESC: (desc_filename, desc_bytes),
        StrategyFile.Kind.WEBHOOK_TEMPLATE: (webhook_filename, webhook_bytes),
    }

    changed = False
    for kind, (fname, blob) in expected.items():
        digest = sha256_bytes(blob)
        existing = strategy.files.filter(kind=kind).first()
        if existing and existing.sha256 == digest and existing.filename == fname:
            continue  # idempotent
        if existing:
            existing.delete()
        StrategyFile.objects.create(
            strategy=strategy,
            kind=kind,
            filename=fname[:128],
            sha256=digest,
            content=bytes(blob),
            size_bytes=len(blob),
        )
        changed = True

    return strategy, (created or changed)


__all__ = [
    "build_webhook_url",
    "encrypt_secret",
    "decrypt_secret",
    "generate_secret",
    "default_payload_template",
    "default_json_schema",
    "RotationResult",
    "get_or_create_webhook_config",
    "rotate_secret",
    "SeedSummary",
    "sha256_bytes",
    "upsert_system_strategy",
]
