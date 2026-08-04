"""Alpaca ``APIError`` → adapter-neutral ``BrokerError`` mapping (M04 §6.2).

Nothing above the adapter sees an ``alpaca.common.exceptions.APIError``.
"""
from __future__ import annotations

from ..errors import BrokerError, BrokerErrorCode

# HTTP statuses the caller may safely retry with backoff.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Alpaca API key ID prefixes: paper keys start with "PK". Live trading keys
# start with "AK"; broker-API keys with "BK".
#
# M04 hard-rejected the live prefix outright (AC-04-6), because the adapter was
# paper-only by construction. M13 makes the endpoint mode-dependent, so the
# check becomes mode-AWARE rather than being dropped — and it now runs in BOTH
# directions (M13 F-4):
#
#   live-shaped key on a PAPER account → BROKER_LIVE_KEYS_FORBIDDEN
#       (unchanged; this is the guard that stops a mistaken paste reaching a
#        real account, and it is the single most valuable line here)
#   paper-shaped key on a LIVE account → BROKER_PAPER_KEYS_ON_LIVE
#       (new; stops an account labelled LIVE from silently trading paper)
#
# The prefixes are a heuristic, not a security boundary — Alpaca itself is the
# authority, and it will reject a mismatched key with 401/403. This check exists
# to fail *early and legibly*, before any key leaves the process.
LIVE_KEY_PREFIXES = ("AK", "BK")
PAPER_KEY_PREFIXES = ("PK",)


def looks_like_live_key(api_key_id: str) -> bool:
    return bool(api_key_id) and api_key_id.upper().startswith(LIVE_KEY_PREFIXES)


def looks_like_paper_key(api_key_id: str) -> bool:
    return bool(api_key_id) and api_key_id.upper().startswith(PAPER_KEY_PREFIXES)


def _status_of(exc) -> int | None:
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int) and 100 <= val <= 599:
            return val
    return None


def map_api_error(exc: Exception) -> BrokerError:
    """Translate any adapter-level exception into a ``BrokerError``."""
    if isinstance(exc, BrokerError):
        return exc
    status = _status_of(exc)
    msg = str(exc)[:200] or exc.__class__.__name__
    if status in (401, 403):
        return BrokerError(BrokerErrorCode.AUTH_FAILED, "Broker authentication failed.", status=status)
    if status == 429:
        return BrokerError(
            BrokerErrorCode.RATE_LIMITED, "Broker rate limit exceeded.", retryable=True, status=status
        )
    if status is not None and 500 <= status < 600:
        return BrokerError(
            BrokerErrorCode.UNAVAILABLE, "Broker temporarily unavailable.", retryable=True, status=status
        )
    if status in (400, 422):
        return BrokerError(BrokerErrorCode.ORDER_REJECTED, "Broker rejected the order.", status=status)
    return BrokerError(BrokerErrorCode.UNKNOWN, msg, status=status)
