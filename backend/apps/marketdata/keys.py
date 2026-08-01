"""Instance data-provider API keys (FMP / FRED) — storage + resolution (ADR-062).

One set of keys per instance, editable by staff in Settings → Data Providers
and stored Fernet-wrapped with the shared platform KEK (same pattern as MFA /
webhook / broker secrets). ``FMP_API_KEY`` / ``FRED_API_KEY`` env vars remain a
fully supported fallback (local ``.env``, Railway) — a value stored through the
UI takes precedence over the env because it is the one an operator set most
deliberately, and because it reaches ALL Django services (web, worker, beat)
through the shared database with no per-service env duplication and no
redeploy.

Resolution order (``resolve_key``):
    1. ``DataProviderKey`` row (set via the UI)  →  decrypted value
    2. ``settings.FMP_API_KEY`` / ``settings.FRED_API_KEY`` (env)
    3. ``""``  (unconfigured — callers treat falsy as "not configured")

Plaintext keys live only inside this module and the vendor clients it feeds;
nothing above receives them (mirrors ``apps.brokers.services``).
"""
from __future__ import annotations

import logging

from cryptography.fernet import InvalidToken as FernetInvalidToken
from django.conf import settings
from django.db import DatabaseError

from apps.users.mfa import _fernet  # reuse the platform KEK (house precedent)

logger = logging.getLogger(__name__)

PROVIDER_FMP = "FMP"
PROVIDER_FRED = "FRED"
PROVIDERS = (PROVIDER_FMP, PROVIDER_FRED)

# Provider → the settings/env name that acts as the fallback source.
_ENV_SETTING = {PROVIDER_FMP: "FMP_API_KEY", PROVIDER_FRED: "FRED_API_KEY"}

# FRED base URL for key validation — same default as apps.marketdata.fred.
FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# Only show a last-4 hint for keys long enough that 4 chars reveal nothing
# useful (FMP + FRED keys are 32 hex/alnum chars).
_HINT_MIN_LEN = 12


class ProviderKeyInvalid(Exception):
    """The vendor rejected the key (401/403 → bad credentials)."""


class ProviderUnreachable(Exception):
    """The vendor could not be reached / answered 5xx during validation."""


# ---------------------------------------------------------------------------
# Credential encryption (shared platform KEK)
# ---------------------------------------------------------------------------
def encrypt_key(raw: str) -> bytes:
    return _fernet().encrypt(raw.encode("ascii"))


def decrypt_key(blob: bytes) -> str:
    if not blob:
        return ""
    try:
        return _fernet().decrypt(bytes(blob)).decode("ascii")
    except FernetInvalidToken as exc:  # pragma: no cover — operational
        raise RuntimeError("Data-provider key could not be decrypted (KEK mismatch?)") from exc


# ---------------------------------------------------------------------------
# Storage + resolution
# ---------------------------------------------------------------------------
def stored_key(provider: str) -> str:
    """The UI-stored key for ``provider``, or ``""``.

    Defensive on DB errors (fresh install mid-migrate, DB blip): a missing
    table must degrade to the env fallback, not crash a beat/worker boot.
    """
    from .models import DataProviderKey

    try:
        row = DataProviderKey.objects.filter(provider=provider).only("key_encrypted").first()
    except DatabaseError:  # pragma: no cover — operational
        logger.warning("marketdata.keys.db_unavailable", extra={"provider": provider})
        return ""
    if row is None:
        return ""
    return decrypt_key(row.key_encrypted)


def env_key(provider: str) -> str:
    return getattr(settings, _ENV_SETTING[provider], "") or ""


def resolve_key(provider: str) -> str:
    """UI-stored key → env var → ``""`` (see module docstring)."""
    return stored_key(provider) or env_key(provider)


def key_source(provider: str) -> str | None:
    """``"ui"`` | ``"env"`` | ``None`` — where the effective key comes from."""
    if stored_key(provider):
        return "ui"
    if env_key(provider):
        return "env"
    return None


def set_key(provider: str, raw: str, *, updated_by=None):
    """Encrypt + upsert the instance key for ``provider``. Returns the row."""
    from .models import DataProviderKey

    hint = raw[-4:] if len(raw) >= _HINT_MIN_LEN else ""
    row, _created = DataProviderKey.objects.update_or_create(
        provider=provider,
        defaults={
            "key_encrypted": encrypt_key(raw),
            "key_hint": hint,
            "updated_by": updated_by,
        },
    )
    return row


def clear_key(provider: str) -> bool:
    """Delete the UI-stored key. Returns True when a row was removed. The env
    fallback (if any) becomes the effective key again — this does NOT
    unconfigure a provider whose key also lives in the environment."""
    from .models import DataProviderKey

    deleted, _ = DataProviderKey.objects.filter(provider=provider).delete()
    return bool(deleted)


def key_status(provider: str, *, include_admin_detail: bool = False) -> dict:
    """Wire-format status for one provider (never includes key material)."""
    from .models import DataProviderKey

    source = key_source(provider)
    out: dict = {"provider": provider, "configured": source is not None, "source": source}
    if include_admin_detail:
        row = DataProviderKey.objects.filter(provider=provider).select_related("updated_by").first()
        out["hint"] = row.key_hint if row else ""
        out["updated_at"] = row.updated_at.isoformat() if row else None
        out["updated_by"] = row.updated_by.email if row and row.updated_by else None
    return out


# ---------------------------------------------------------------------------
# Pre-persistence key validation (mirrors the brokers AC-04-6 pattern: a bad
# key never creates a row). HTTP is injectable — no live vendor calls in CI.
# ---------------------------------------------------------------------------
def _probe(url: str, params: dict, http=None) -> int:
    """GET and return the status code. Transport errors raise
    ``ProviderUnreachable`` from ``None`` so the keyed URL never surfaces in a
    traceback/Sentry event (same leak-guard as the FMP/FRED clients)."""
    import httpx

    client = http or httpx.Client(timeout=10.0)
    try:
        try:
            resp = client.get(url, params=params)
        except httpx.RequestError as exc:
            raise ProviderUnreachable(f"transport: {type(exc).__name__}") from None
        return resp.status_code
    finally:
        if http is None:
            client.close()


def validate_provider_key(provider: str, raw: str, *, http=None) -> None:
    """Raise ``ProviderKeyInvalid`` / ``ProviderUnreachable`` unless the vendor
    accepts ``raw``. A 429 is accepted: rate-limiting implies the key
    authenticated, and rejecting it would make an exhausted-quota key
    impossible to save."""
    if provider == PROVIDER_FMP:
        base = getattr(settings, "FMP_BASE_URL", "https://financialmodelingprep.com/stable").rstrip("/")
        status = _probe(f"{base}/quote", {"symbol": "SPY", "apikey": raw}, http=http)
        if status in (401, 403):
            raise ProviderKeyInvalid("FMP rejected the key")
        if status >= 500:
            raise ProviderUnreachable(f"FMP HTTP {status}")
        if status >= 400 and status != 429:
            raise ProviderKeyInvalid(f"FMP HTTP {status}")
        return
    if provider == PROVIDER_FRED:
        status = _probe(
            f"{FRED_BASE_URL}/series/observations",
            {
                "series_id": "VIXCLS",
                "api_key": raw,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            },
            http=http,
        )
        # FRED answers 400 for a bad/unregistered api_key on an otherwise
        # valid request (fixed series_id above), and 429 when throttled.
        if status >= 500:
            raise ProviderUnreachable(f"FRED HTTP {status}")
        if status >= 400 and status != 429:
            raise ProviderKeyInvalid("FRED rejected the key")
        return
    raise ValueError(f"Unknown provider {provider!r}")
