"""GDPR personal-data export + anonymize-in-place (M11 §7.7).

Two guarantees this module must uphold (both AC-gating):

1. **Redaction.** The export ZIP must contain **no** broker API keys and **no**
   MFA secrets. We use *defence in depth*: an explicit allowlist of what is
   exported, PLUS a field-name denylist that redacts anything that looks like a
   secret even if a future field is added to an exported model. Never rely on the
   allowlist alone — the redaction test asserts the denylist bites.

2. **Anonymize keeps the row.** Account delete NEVER hard-``delete()``s the User
   (its PK anchors ``AuditLog.user``/``actor`` FKs, and the append-only trigger
   forbids deleting audit rows). We scrub PII on the live row in place.
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any

from django.utils import timezone

# Field-name substrings that must never appear in an export, regardless of which
# model they live on. Shared with the audit scrubber (P1-9) so there is one
# source of truth for what "looks sensitive".
from apps.audit.scrub import SENSITIVE_FIELD_PARTS

REDACTED = "[REDACTED]"


def _is_sensitive(field_name: str) -> bool:
    low = field_name.lower()
    return any(part in low for part in SENSITIVE_FIELD_PARTS)


def _jsonify(value: Any) -> Any:
    """Coerce a model field value to something json.dumps can serialize."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (dict, list)):
        return value
    return str(value)  # UUID, datetime, Decimal, IP, bytes-repr, FK id, ...


def serialize_instance(instance) -> dict:
    """One model row → a JSON-safe dict, redacting sensitive fields by name."""
    out: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        name = field.attname  # FK -> "<name>_id"
        if _is_sensitive(name) or _is_sensitive(field.name):
            out[field.name] = REDACTED
            continue
        out[field.name] = _jsonify(getattr(instance, field.attname, None))
    return out


def _serialize_qs(queryset) -> list[dict]:
    return [serialize_instance(obj) for obj in queryset.iterator()]


def _export_sections(user) -> dict[str, Any]:
    """Return {filename: json-serializable} for the user's personal data.

    Explicit allowlist — the source of truth for WHAT is exported. The denylist in
    ``serialize_instance`` is the backstop for HOW each row is redacted.
    """
    from apps.backtest.models import BacktestRun
    from apps.brokers.models import BrokerAccount, TradingHalt
    from apps.orders.models import Fill, Order, Position, ReconEvent
    from apps.risk.models import RiskEvent, SizingDecision
    from apps.strategies.models import Strategy, WebhookConfig
    from apps.webhooks.models import AlertMessage

    from .models import TermsAcceptance, UserProfile

    account = {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "is_verified": user.is_verified,
        "is_active": user.is_active,
        "created_at": _jsonify(user.created_at),
        "updated_at": _jsonify(user.updated_at),
        "pending_delete_at": _jsonify(user.pending_delete_at),
        "mfa_enabled": user.mfa_enabled,
    }

    profile = None
    try:
        profile = serialize_instance(UserProfile.objects.get(user=user))
    except UserProfile.DoesNotExist:
        profile = None

    sections = {
        "account.json": account,
        "profile.json": profile,
        "terms_acceptances.json": _serialize_qs(TermsAcceptance.objects.filter(user=user)),
        "strategies.json": _serialize_qs(Strategy.objects.filter(owner=user)),
        "webhook_configs.json": _serialize_qs(WebhookConfig.objects.filter(user=user)),
        "broker_accounts.json": _serialize_qs(BrokerAccount.objects.filter(user=user)),
        "trading_halts.json": _serialize_qs(TradingHalt.objects.filter(user=user)),
        "orders.json": _serialize_qs(Order.objects.filter(user=user)),
        "fills.json": _serialize_qs(Fill.objects.filter(order__user=user)),
        "positions.json": _serialize_qs(Position.objects.filter(user=user)),
        "recon_events.json": _serialize_qs(ReconEvent.objects.filter(user=user)),
        "alerts.json": _serialize_qs(AlertMessage.objects.filter(user=user)),
        "sizing_decisions.json": _serialize_qs(SizingDecision.objects.filter(user=user)),
        "risk_events.json": _serialize_qs(RiskEvent.objects.filter(user=user)),
        "backtests.json": _serialize_qs(BacktestRun.objects.filter(user=user)),
        "audit_log.json": _audit_rows(user),
    }
    return sections


def _audit_rows(user) -> list[dict]:
    """The user's own rows from the append-only audit log (AC-11-8)."""
    from apps.audit.models import AuditLog

    return _serialize_qs(AuditLog.objects.filter(user_id=user.id).order_by("id"))


_README = (
    "StratTraderPro — personal data export\n"
    "=====================================\n\n"
    "This archive contains the personal data StratTraderPro holds for your account,\n"
    "one JSON file per data category. For your security, broker API keys and MFA\n"
    "secrets are REDACTED (they are encrypted at rest and are never exported).\n\n"
    "Generated: {generated}\n"
    "Account:   {email} ({uid})\n\n"
    "Files:\n"
    "  account.json           Your account identity + status\n"
    "  profile.json           Preferences (timezone, language, notifications)\n"
    "  terms_acceptances.json Your Terms/Privacy acceptance history\n"
    "  strategies.json        Strategies you own\n"
    "  webhook_configs.json   Webhook configs (secret redacted)\n"
    "  broker_accounts.json   Connected brokers (credentials redacted)\n"
    "  orders.json / fills.json / positions.json / recon_events.json   Trading records\n"
    "  alerts.json            Inbound webhook alerts\n"
    "  sizing_decisions.json / risk_events.json / trading_halts.json   Risk records\n"
    "  backtests.json         Backtest runs\n"
    "  audit_log.json         Your entries in the tamper-evident audit log\n"
)


def build_export_zip(user) -> bytes:
    """Build the personal-data export ZIP for ``user`` and return its bytes.

    Streams into an in-memory buffer via ``zipfile``. Sections are small JSON
    documents; the largest realistic set (orders/fills/audit) stays well within
    memory for a single user.
    """
    sections = _export_sections(user)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "README.txt",
            _README.format(generated=timezone.now().isoformat(), email=user.email, uid=user.id),
        )
        for filename, payload in sections.items():
            zf.writestr(filename, json.dumps(payload, indent=2, sort_keys=True, default=str))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Anonymize-in-place (30-day soft delete expiry) — §7.7 / frozen decision §4.3
# ---------------------------------------------------------------------------
def anonymize_user(user) -> None:
    """Scrub PII on the live User row **in place**, keeping its PK.

    The User row is deliberately NOT deleted: its id anchors ``AuditLog.user`` /
    ``AuditLog.actor`` FKs, and the append-only trigger forbids deleting audit
    rows. Related credential/secret rows ARE deleted (they are useless once the
    account is dead and must not linger). An ``account.anonymized`` audit event
    is emitted so the chain records the erasure.
    """
    from apps.audit.services import emit

    from .models import BackupCode, MFADevice, UserProfile

    # 1) Drop credential/secret material FIRST, before scrubbing the row / clearing
    #    pending_delete_at. If a delete FAILS (e.g. a future PROTECT FK on
    #    BrokerAccount), we must NOT swallow it and report a false "anonymized" —
    #    that would leave `api_*_enc` ciphertext in the DB forever while claiming
    #    success (the exact silent-success failure this milestone exists to kill).
    #    Letting it propagate means the nightly job logs the failure and the row
    #    keeps `pending_delete_at`, so it retries next run.
    MFADevice.objects.filter(user=user).delete()
    BackupCode.objects.filter(user=user).delete()
    try:
        from apps.brokers.models import BrokerAccount
    except Exception:  # noqa: BLE001 — brokers app absent in a minimal config only
        BrokerAccount = None
    if BrokerAccount is not None:
        # No bare except here on purpose — a delete failure must be loud.
        BrokerAccount.objects.filter(user=user).delete()

    # 2) Scrub PII on the live row + clear the pending flag (only now that the
    #    credential material is provably gone).
    anon_email = f"deleted-{uuid.uuid4().hex}@anonymized.invalid"
    user.email = anon_email
    user.display_name = "deleted user"
    user.is_active = False
    user.is_verified = False
    user.set_unusable_password()
    user.pending_delete_at = None
    user.save(update_fields=[
        "email", "display_name", "is_active", "is_verified", "password", "pending_delete_at",
    ])

    # Scrub profile free-text but keep the row (FK from other tables may exist).
    UserProfile.objects.filter(user=user).update(
        default_broker_id=None, terms_version_accepted=""
    )

    emit(
        "account.anonymized",
        user_id=user.id,
        actor_id=user.id,
        entity_type="user",
        entity_id=str(user.id),
        metadata={"reason": "soft_delete_expiry"},
    )
