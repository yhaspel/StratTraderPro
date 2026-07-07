"""Brokers service layer (M04).

Owns: credential encryption (shared platform KEK, same as MFA/webhook secrets),
the adapter factory, the halt gate, and the streams-heartbeat / status view.
Secrets live only inside this module and the adapters it builds; nothing above
receives plaintext keys.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from cryptography.fernet import InvalidToken as FernetInvalidToken
from django.conf import settings
from django.core.cache import cache

from apps.users.mfa import _fernet  # reuse the platform KEK

from .base import BrokerAdapter, BrokerConnState, BrokerContext
from .errors import BrokerError, BrokerErrorCode
from .models import BrokerAccount, TradingHalt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credential encryption
# ---------------------------------------------------------------------------
def encrypt_key(raw: str) -> bytes:
    return _fernet().encrypt(raw.encode("ascii"))


def decrypt_key(blob: bytes) -> str:
    # Empty for brokers that don't use an api-key pair (e.g. TradeStation, which
    # authenticates with OAuth tokens instead).
    if not blob:
        return ""
    try:
        return _fernet().decrypt(bytes(blob)).decode("ascii")
    except FernetInvalidToken as exc:  # pragma: no cover — operational
        raise RuntimeError("Broker key could not be decrypted (KEK mismatch?)") from exc


# ---------------------------------------------------------------------------
# Adapter factory
# ---------------------------------------------------------------------------
def build_adapter(account: BrokerAccount) -> BrokerAdapter:
    """Construct the concrete adapter for a ``BrokerAccount``, decrypting creds
    internally. Raises ``BrokerError(BROKER_DISABLED)`` when the broker's
    feature flag is off (plan §15)."""
    ctx = BrokerContext(
        account_id=str(account.id),
        user_id=str(account.user_id),
        api_key_id=decrypt_key(account.api_key_id_enc),
        api_secret=decrypt_key(account.api_secret_enc),
        account_number=account.account_number,
    )
    if account.broker == BrokerAccount.Broker.ALPACA:
        if not getattr(settings, "BROKER_ALPACA_ENABLED", True):
            raise BrokerError(BrokerErrorCode.DISABLED, "Alpaca is disabled by ops.")
        from .alpaca.adapter import AlpacaAdapter

        return AlpacaAdapter(ctx)
    if account.broker == BrokerAccount.Broker.TRADESTATION:
        if not getattr(settings, "BROKER_TRADESTATION_ENABLED", False):
            raise BrokerError(BrokerErrorCode.DISABLED, "TradeStation is disabled by ops.")
        from .tradestation.adapter import TradeStationPaperAdapter

        return TradeStationPaperAdapter(account)
    raise BrokerError(BrokerErrorCode.UNAVAILABLE, f"Unknown broker {account.broker!r}.")


def build_adapter_from_keys(*, api_key_id: str, api_secret: str, broker: str) -> BrokerAdapter:
    """Build a throwaway adapter from raw keys for a pre-persistence connection
    test (POST /brokers/). Used before we know the account number."""
    ctx = BrokerContext(account_id="pending", user_id="pending", api_key_id=api_key_id, api_secret=api_secret)
    if broker == BrokerAccount.Broker.ALPACA:
        if not getattr(settings, "BROKER_ALPACA_ENABLED", True):
            raise BrokerError(BrokerErrorCode.DISABLED, "Alpaca is disabled by ops.")
        from .alpaca.adapter import AlpacaAdapter

        return AlpacaAdapter(ctx)
    raise BrokerError(BrokerErrorCode.UNAVAILABLE, f"Unknown broker {broker!r}.")


# ---------------------------------------------------------------------------
# Halt gate (M04 minimal; M08 builds the full engine on TradingHalt)
# ---------------------------------------------------------------------------
def active_halt_reason(*, user_id, strategy_id) -> str | None:
    """Return ``USER_HALTED`` / ``STRATEGY_HALTED`` if an active halt blocks this
    (user, strategy), else None. User-level halt (strategy NULL) takes priority."""
    if TradingHalt.objects.filter(
        user_id=user_id, strategy__isnull=True, released_at__isnull=True
    ).exists():
        return "USER_HALTED"
    if strategy_id and TradingHalt.objects.filter(
        user_id=user_id, strategy_id=strategy_id, released_at__isnull=True
    ).exists():
        return "STRATEGY_HALTED"
    return None


# ---------------------------------------------------------------------------
# Streams heartbeat / status
# ---------------------------------------------------------------------------
def _heartbeat_key(account_id) -> str:
    return f"broker:hb:{account_id}"


def set_heartbeat(account_id, state: str = BrokerConnState.CONNECTED.value) -> None:
    """Called by run_broker_streams every ~15s. TTL is 3× the freshness window
    so a couple of missed beats still read DEGRADED (not DOWN)."""
    ttl = getattr(settings, "BROKER_STREAM_HEARTBEAT_TTL", 45) * 4
    cache.set(
        _heartbeat_key(account_id),
        {"state": state, "ts": datetime.now(timezone.utc).isoformat()},
        timeout=ttl,
    )


def get_stream_status(account: BrokerAccount) -> str:
    """Resolve CONNECTED / DEGRADED / DOWN from the heartbeat the streams
    service refreshes (§6.5). No heartbeat at all → DOWN."""
    hb = cache.get(_heartbeat_key(account.id))
    if not hb:
        return BrokerConnState.DOWN.value
    try:
        ts = datetime.fromisoformat(hb["ts"])
    except (KeyError, ValueError):  # pragma: no cover — defensive
        return BrokerConnState.DOWN.value
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    ttl = getattr(settings, "BROKER_STREAM_HEARTBEAT_TTL", 45)
    if age > ttl:
        return BrokerConnState.DEGRADED.value
    return hb.get("state", BrokerConnState.CONNECTED.value)


def notify_accounts_changed(account_id, action: str) -> None:
    """Publish a Redis pub/sub message so run_broker_streams can hot-add/remove
    a stream when a user connects/disconnects an account (§6.5). Best-effort."""
    try:
        import redis

        client = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        client.publish("brokers.accounts.changed", f"{action}:{account_id}")
    except Exception:  # pragma: no cover — pub/sub is a convenience, not required
        logger.debug("brokers.accounts.changed publish skipped")
