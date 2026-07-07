"""Fill-streams supervisor (M04 §6.5).

Owns the always-on ``run_broker_streams`` service: one ``TradingStream`` thread
per connected paper account, a heartbeat the ``/status/`` endpoint reads, and
reconnect logic (supervised restart with backoff + REST catch-up). The pure
pieces (backoff, catch-up, account loading) are unit-tested; the blocking thread
loop is exercised live.
"""
from __future__ import annotations

import logging
import random
import threading

from .base import BrokerConnState, BrokerContext
from .metrics import BROKER_STREAM_DISCONNECTS_TOTAL
from .models import BrokerAccount
from .services import decrypt_key, set_heartbeat

logger = logging.getLogger(__name__)

_MAX_BACKOFF = 30.0


def backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter, capped at 30s."""
    base = min(2.0 ** max(0, attempt - 1), _MAX_BACKOFF)
    return round(base * (0.5 + random.random() * 0.5), 3)  # noqa: S311 — jitter


def load_active_accounts():
    return list(
        BrokerAccount.objects.filter(
            broker=BrokerAccount.Broker.ALPACA, mode=BrokerAccount.Mode.PAPER
        ).exclude(status=BrokerAccount.Status.ERROR)
    )


def catch_up_account(account: BrokerAccount, adapter) -> dict:
    """REST catch-up after a stream gap. Two strategies:

    * adapters exposing ``recent_fills`` (exec-level ids) → replay them; dedup on
      ``broker_exec_id`` makes this exact (no lost/duplicated fill — AC-04-11).
    * otherwise (Alpaca has no per-execution history endpoint) → snap positions
      to the broker's authoritative list and refresh open-order status. Position
      truth is preserved without synthesizing phantom fills; per-execution Fill
      backfill is deferred to M05's reconciliation loop.
    """
    from apps.orders.fills import publish_fill
    from apps.orders.models import Order
    from apps.orders.services import reconcile_positions

    replayed = 0
    if hasattr(adapter, "recent_fills"):
        for fe in adapter.recent_fills():
            publish_fill(account.user_id, fe)
            replayed += 1
        return {"strategy": "replay", "replayed": replayed}

    changed = reconcile_positions(account, adapter)
    # Refresh open-order status from the broker's authoritative view.
    open_by_id = {o.broker_order_id: o for o in adapter.list_open_orders() if o.broker_order_id}
    our_open = Order.objects.filter(
        broker_account=account,
        status__in=[Order.Status.SUBMITTED, Order.Status.PARTIAL, Order.Status.PENDING_SUBMIT],
    )
    for order in our_open:
        if order.broker_order_id and order.broker_order_id not in open_by_id:
            # No longer open at the broker — best-effort mark filled/closed.
            Order.objects.filter(id=order.id).exclude(
                status__in=[Order.Status.FILLED, Order.Status.CANCELLED, Order.Status.REJECTED]
            ).update(status=Order.Status.FILLED)
    return {"strategy": "position_snap", "positions_changed": changed}


class StreamSupervisor:
    """Runs one stream thread per account with supervised restart. Instantiated
    by the ``run_broker_streams`` management command."""

    def __init__(self, *, heartbeat_interval: float = 15.0):
        self.heartbeat_interval = heartbeat_interval
        self._threads: dict[str, threading.Thread] = {}
        self._stop = threading.Event()

    def _context_for(self, account: BrokerAccount) -> BrokerContext:
        return BrokerContext(
            account_id=str(account.id),
            user_id=str(account.user_id),
            api_key_id=decrypt_key(account.api_key_id_enc),
            api_secret=decrypt_key(account.api_secret_enc),
            account_number=account.account_number,
        )

    def _run_account(self, account: BrokerAccount):  # pragma: no cover — live loop
        from apps.orders.fills import publish_fill

        from .alpaca.streams import AlpacaStream
        from .services import build_adapter

        attempt = 0
        while not self._stop.is_set():
            try:
                # Catch up any fills missed while (re)connecting.
                catch_up_account(account, build_adapter(account))
                set_heartbeat(account.id, BrokerConnState.CONNECTED.value)
                stream = AlpacaStream(self._context_for(account), on_event=publish_fill)
                attempt = 0
                stream.run()  # blocks until disconnect
            except Exception:
                BROKER_STREAM_DISCONNECTS_TOTAL.labels(broker="alpaca").inc()
                set_heartbeat(account.id, BrokerConnState.DEGRADED.value)
                attempt += 1
                delay = backoff_delay(attempt)
                logger.warning(
                    "broker.stream.reconnect",
                    extra={"account": str(account.id), "attempt": attempt, "delay": delay},
                )
                self._stop.wait(delay)

    def start(self):  # pragma: no cover — spawns live threads
        for account in load_active_accounts():
            t = threading.Thread(target=self._run_account, args=(account,), daemon=True)
            t.start()
            self._threads[str(account.id)] = t

    def run_forever(self):  # pragma: no cover — top-level loop
        self.start()
        try:
            while not self._stop.is_set():
                for account in load_active_accounts():
                    set_heartbeat(account.id)
                self._stop.wait(self.heartbeat_interval)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):  # pragma: no cover
        self._stop.set()
