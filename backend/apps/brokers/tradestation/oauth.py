"""TradeStation OAuth2 authorization_code + PKCE (M05 §6.1/§11).

PKCE mitigates auth-code interception; the ``state`` param is single-use
(Redis-backed via the Django cache) to block replay. All flows are behind
``BROKER_TRADESTATION_ENABLED`` — live verification is deferred until API
access is granted.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache

_STATE_PREFIX = "ts:oauth:state:"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` (S256)."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def issue_state(user_id) -> str:
    """Mint a single-use state token bound to the user, stored in Redis."""
    state = secrets.token_urlsafe(24)
    ttl = getattr(settings, "TRADESTATION_OAUTH_STATE_TTL", 600)
    cache.set(f"{_STATE_PREFIX}{state}", {"user_id": str(user_id)}, timeout=ttl)
    return state


def consume_state(state: str):
    """Return the stored payload and delete it (single-use). None if unknown."""
    key = f"{_STATE_PREFIX}{state}"
    payload = cache.get(key)
    if payload is not None:
        cache.delete(key)
    return payload


def store_verifier(state: str, verifier: str) -> None:
    ttl = getattr(settings, "TRADESTATION_OAUTH_STATE_TTL", 600)
    cache.set(f"{_STATE_PREFIX}verifier:{state}", verifier, timeout=ttl)


def consume_verifier(state: str) -> str | None:
    key = f"{_STATE_PREFIX}verifier:{state}"
    v = cache.get(key)
    if v is not None:
        cache.delete(key)
    return v


def build_authorize_url(*, state: str, code_challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.TRADESTATION_CLIENT_ID,
        "redirect_uri": settings.TRADESTATION_REDIRECT_URI,
        "audience": "https://api.tradestation.com",
        "scope": "openid offline_access MarketData ReadAccount Trade",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    base = settings.TRADESTATION_OAUTH_BASE.rstrip("/")
    return f"{base}/authorize?{urlencode(params)}"
