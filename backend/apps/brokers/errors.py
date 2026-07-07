"""Broker error taxonomy (M04).

A single ``BrokerError`` carries a stable machine code (mapped to an i18n key
on the frontend — see plan §13) plus a ``retryable`` flag the streams/order
paths use to decide whether an exponential-jitter retry is safe.

Concrete adapters translate their SDK-specific exceptions into these codes in
their own ``errors.py`` (e.g. ``apps/brokers/alpaca/errors.py``). Nothing
above the adapter layer should ever see a vendor exception type.
"""
from __future__ import annotations


class BrokerErrorCode:
    """Stable string codes surfaced to the API and mapped to i18n keys."""

    AUTH_FAILED = "BROKER_AUTH_FAILED"
    LIVE_KEYS_FORBIDDEN = "BROKER_LIVE_KEYS_FORBIDDEN"
    RATE_LIMITED = "BROKER_RATE_LIMITED"
    UNSUPPORTED_ASSET = "ORDER_UNSUPPORTED_ASSET"
    UNSUPPORTED_ORDER_TYPE = "ORDER_UNSUPPORTED_TYPE"
    UNAVAILABLE = "BROKER_UNAVAILABLE"
    NOT_CONNECTED = "NO_BROKER_CONNECTED"
    DISABLED = "BROKER_DISABLED"
    ORDER_REJECTED = "BROKER_ORDER_REJECTED"
    UNKNOWN = "BROKER_UNKNOWN_ERROR"


class BrokerError(Exception):
    """Adapter-neutral broker failure.

    ``code``      — one of :class:`BrokerErrorCode`.
    ``message``   — human-readable, safe to log (never contains keys/bodies).
    ``retryable`` — True for transient failures (429/5xx) the caller may retry
                    with backoff. False for terminal failures (auth, live keys,
                    unsupported asset).
    ``status``    — optional upstream HTTP status for observability.
    """

    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        retryable: bool = False,
        status: int | None = None,
    ) -> None:
        self.code = code
        self.message = message or code
        self.retryable = retryable
        self.status = status
        super().__init__(f"{code}: {self.message}")

    def __repr__(self) -> str:  # pragma: no cover — debug aid; never leaks creds
        return f"BrokerError(code={self.code!r}, retryable={self.retryable})"


class BrokerAuthError(BrokerError):
    def __init__(self, message: str = "Broker authentication failed.", *, status=None):
        super().__init__(BrokerErrorCode.AUTH_FAILED, message, retryable=False, status=status)


class BrokerLiveKeysForbidden(BrokerError):
    def __init__(self, message: str = "Live broker keys are not permitted in paper mode."):
        super().__init__(BrokerErrorCode.LIVE_KEYS_FORBIDDEN, message, retryable=False)


class BrokerRateLimited(BrokerError):
    def __init__(self, message: str = "Broker rate limit exceeded.", *, status=429):
        super().__init__(BrokerErrorCode.RATE_LIMITED, message, retryable=True, status=status)


class UnsupportedAsset(BrokerError):
    def __init__(self, message: str = "Only US stocks and ETFs are supported."):
        super().__init__(BrokerErrorCode.UNSUPPORTED_ASSET, message, retryable=False)


class UnsupportedOrderType(BrokerError):
    def __init__(self, message: str = "Order type not supported in this milestone."):
        super().__init__(BrokerErrorCode.UNSUPPORTED_ORDER_TYPE, message, retryable=False)
