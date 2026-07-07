"""Alpaca ``APIError`` → adapter-neutral ``BrokerError`` mapping (M04 §6.2).

Nothing above the adapter sees an ``alpaca.common.exceptions.APIError``.
"""
from __future__ import annotations

from ..errors import BrokerError, BrokerErrorCode

# HTTP statuses the caller may safely retry with backoff.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Alpaca API key ID prefixes: paper keys start with "PK". Live trading keys
# start with "AK"; broker-API keys with "BK". We hard-reject the live prefix so
# a pasted live key can never reach the (paper-only) endpoint (AC-04-6).
LIVE_KEY_PREFIXES = ("AK", "BK")


def looks_like_live_key(api_key_id: str) -> bool:
    return bool(api_key_id) and api_key_id.upper().startswith(LIVE_KEY_PREFIXES)


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
