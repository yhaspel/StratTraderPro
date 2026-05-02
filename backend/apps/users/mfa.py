"""
MFA primitives — TOTP, backup codes, secret-at-rest, mfa_token (M02).

Public surface (used by views/services):
    encrypt_secret / decrypt_secret  — Fernet wrap/unwrap with FERNET_KEK
    generate_totp_secret             — base32 string, 32 chars
    build_provisioning_uri           — otpauth:// URI for QR
    render_qr_png_b64                — PNG-of-QR encoded as base64 string
    verify_totp                      — pyotp verify with ±MFA_TOTP_VALID_WINDOW
    generate_backup_codes            — (raw_codes[], BackupCode rows[])
    consume_backup_code              — atomic single-use mark
    issue_mfa_token                  — short-lived signed JWT (purpose=mfa)
    decode_mfa_token                 — return user_id or raise InvalidToken
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import secrets as _secrets
from typing import Optional

import pyotp
import qrcode
from cryptography.fernet import Fernet, InvalidToken as FernetInvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import Token

from .models import BackupCode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fernet (secret-at-rest)
# ---------------------------------------------------------------------------
def _fernet() -> Fernet:
    """Build a Fernet from settings.FERNET_KEK.

    Accepts either a raw url-safe-base64-encoded 32-byte key (preferred,
    `cryptography.fernet.Fernet.generate_key()`) OR a hex/raw 32-byte
    SHA-256 digest (legacy convenience for dev). We force-encode strings.
    """
    kek = settings.FERNET_KEK
    if isinstance(kek, str):
        kek = kek.encode("ascii")
    return Fernet(kek)


def encrypt_secret(secret_b32: str) -> bytes:
    """Wrap a TOTP base32 secret for storage."""
    return _fernet().encrypt(secret_b32.encode("ascii"))


def decrypt_secret(blob: bytes) -> str:
    """Unwrap. Raises ``InvalidToken`` on KEK mismatch — caller should map
    this to a hard MFA failure (do not silently accept).
    """
    try:
        return _fernet().decrypt(bytes(blob)).decode("ascii")
    except FernetInvalidToken as exc:  # pragma: no cover — operational error
        raise InvalidToken("MFA secret could not be decrypted (KEK mismatch?)") from exc


# ---------------------------------------------------------------------------
# TOTP
# ---------------------------------------------------------------------------
def generate_totp_secret() -> str:
    """Random base32 secret. 32 chars = 160 bits, the RFC 6238 recommended size."""
    return pyotp.random_base32(length=32)


def build_provisioning_uri(secret_b32: str, *, account_name: str) -> str:
    """``otpauth://totp/<issuer>:<account>?secret=...&issuer=<issuer>``."""
    return pyotp.TOTP(secret_b32, interval=30, digits=6).provisioning_uri(
        name=account_name,
        issuer_name=settings.MFA_TOTP_ISSUER,
    )


def render_qr_png_b64(uri: str) -> str:
    """Return base64-encoded PNG of the QR for ``uri``."""
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def verify_totp(secret_b32: str, code: str) -> bool:
    """Constant-window TOTP check. Tolerates ±MFA_TOTP_VALID_WINDOW steps.

    Strips whitespace and rejects anything that is not exactly 6 digits.
    """
    if code is None:
        return False
    code = str(code).strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret_b32, interval=30, digits=6).verify(
        code, valid_window=settings.MFA_TOTP_VALID_WINDOW
    )


# ---------------------------------------------------------------------------
# Backup codes
# ---------------------------------------------------------------------------
_BACKUP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusables


def _format_backup_code(raw: str) -> str:
    """Group as ``XXXX-XXXX`` for display."""
    return f"{raw[:4]}-{raw[4:]}"


def _normalize_backup_code(value: str) -> str:
    """Strip dashes/spaces, uppercase. Lets the user type it however."""
    return (value or "").replace("-", "").replace(" ", "").strip().upper()


def _hash_backup_code(raw: str, salt: str) -> str:
    """SHA-256(salt || raw) → hex. Per-row salt prevents cross-user rainbow lookups."""
    return hashlib.sha256((salt + raw).encode("ascii")).hexdigest()


@transaction.atomic
def generate_backup_codes(user, *, count: Optional[int] = None) -> list[str]:
    """
    Wipe + recreate this user's backup codes. Returns the **plaintext** codes
    (formatted as ``XXXX-XXXX``); only the hashes are stored. Caller MUST
    surface the plaintext to the user exactly once.
    """
    n = count or settings.MFA_BACKUP_CODE_COUNT
    BackupCode.objects.filter(user=user).delete()
    codes_plain: list[str] = []
    for _ in range(n):
        raw = "".join(_secrets.choice(_BACKUP_ALPHABET) for _ in range(8))
        salt = _secrets.token_hex(8)
        BackupCode.objects.create(
            user=user, code_hash=_hash_backup_code(raw, salt), salt=salt
        )
        codes_plain.append(_format_backup_code(raw))
    return codes_plain


def consume_backup_code(user, code: str) -> bool:
    """Constant-time-ish single-use consumption. Returns True iff a matching
    un-used code is found and just got marked used."""
    raw = _normalize_backup_code(code)
    if not raw or len(raw) != 8:
        return False
    # We have to walk all un-used rows because each has a different salt.
    # 10 rows max, so the constant-factor cost is negligible.
    for bc in BackupCode.objects.filter(user=user, used_at__isnull=True):
        if _hash_backup_code(raw, bc.salt) == bc.code_hash:
            bc.used_at = timezone.now()
            bc.save(update_fields=["used_at"])
            return True
    return False


# ---------------------------------------------------------------------------
# MFA token (short-lived JWT issued at login for MFA-enrolled users)
# ---------------------------------------------------------------------------
class _MFAToken(Token):
    """5-minute JWT bearing ``purpose=mfa``. Only accepted by /auth/mfa/verify/."""

    token_type = "mfa"
    lifetime = None  # filled in __init__

    def __init__(self, token=None, verify=True):
        # ``settings.MFA_TOKEN_TTL_MINUTES`` may be patched in tests, so we
        # read it lazily on each instantiation rather than at class-define
        # time.
        from datetime import timedelta as _td
        self.lifetime = _td(minutes=settings.MFA_TOKEN_TTL_MINUTES)
        super().__init__(token=token, verify=verify)


def issue_mfa_token(user) -> str:
    tok = _MFAToken()
    tok["user_id"] = str(user.id)
    tok["purpose"] = "mfa"
    return str(tok)


def decode_mfa_token(raw: str) -> str:
    """Return the user_id encoded in ``raw``. Raises ``InvalidToken`` on
    malformed token, expired token, or wrong ``purpose``.
    """
    try:
        tok = _MFAToken(token=raw)
    except TokenError as exc:
        raise InvalidToken(str(exc) or "MFA token invalid or expired.") from exc
    if tok.get("purpose") != "mfa":
        raise InvalidToken("Token is not an MFA challenge token.")
    user_id = tok.get("user_id")
    if not user_id:
        raise InvalidToken("MFA token missing user_id claim.")
    return str(user_id)


__all__ = [
    "encrypt_secret",
    "decrypt_secret",
    "generate_totp_secret",
    "build_provisioning_uri",
    "render_qr_png_b64",
    "verify_totp",
    "generate_backup_codes",
    "consume_backup_code",
    "issue_mfa_token",
    "decode_mfa_token",
]
