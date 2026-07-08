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
import time

from .base import BrokerConnState, BrokerContext
from .metrics import BROKER_STREAM_DISCONNECTS_TOTAL, BROKER_WS_RECONNECTS_TOTAL
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
    resolved = 0
    getter = getattr(adapter, "get_order_status", None)
    for order in our_open:
        if order.broker_order_id and order.broker_order_id not in open_by_id:
            # No longer open at the broker. Resolve the REAL terminal status —
            # never assume FILLED, a closed order may be cancelled/rejected/
            # expired. Position truth is already snapped above; if we can't fetch
            # the status, leave the order and let the reconnected stream (or M05
            # reconciliation) resolve it rather than mislabel it.
            status = None
            if callable(getter):
                try:
                    status = getter(order.broker_order_id)
                except Exception:  # pragma: no cover — broker hiccup; leave as-is
                    status = None
            if status:
                Order.objects.filter(id=order.id).exclude(
                    status__in=[Order.Status.FILLED, Order.Status.CANCELLED, Order.Status.REJECTED]
                ).update(status=status)
                resolved += 1
    return {"strategy": "position_snap", "positions_changed": changed, "orders_resolved": resolved}


class StreamSupervisor:
    """Runs one stream thread per account with supervised restart. Instantiated
    by the ``run_broker_streams`` management command.

    FIX-H8:
      * Each stream thread owns its heartbeat (CONNECTED on a healthy run /
        received event, DEGRADED on disconnect). The supervisor loop NEVER
        blanket-stamps CONNECTED — that masked dead threads and marked
        thread-less accounts healthy.
      * The loop diffs ``load_active_accounts()`` against running threads to
        hot-add / hot-remove accounts (no restart needed) and prune dead threads.
      * Backoff resets only after a stream stayed up ``healthy_after`` seconds,
        so repeated immediate failures (auth/DNS) grow the delay instead of
        busy-looping catch-up at ~1/sec.
    """

    def __init__(
        self,
        *,
        heartbeat_interval: float = 15.0,
        healthy_after: float = 60.0,
        stream_factory=None,
        adapter_factory=None,
    ):
        self.heartbeat_interval = heartbeat_interval
        self.healthy_after = healthy_after
        self._threads: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._stop = threading.Event()
        self._stream_factory = stream_factory  # injectable for tests
        self._adapter_factory = adapter_factory

    def _context_for(self, account: BrokerAccount) -> BrokerContext:
        return BrokerContext(
            account_id=str(account.id),
            user_id=str(account.user_id),
            api_key_id=decrypt_key(account.api_key_id_enc),
            api_secret=decrypt_key(account.api_secret_enc),
            account_number=account.account_number,
        )

    def _build_adapter(self, account: BrokerAccount):
        if self._adapter_factory is not None:
            return self._adapter_factory(account)
        from .services import build_adapter

        return build_adapter(account)

    def _build_stream(self, account: BrokerAccount):
        if self._stream_factory is not None:
            return self._stream_factory(account)
        from apps.orders.fills import publish_fill  # pragma: no cover — live path

        from .alpaca.streams import AlpacaStream

        def on_event(user_id, event):  # pragma: no cover — live path
            # A received event proves the stream is alive → refresh CONNECTED.
            set_heartbeat(account.id, BrokerConnState.CONNECTED.value)
            publish_fill(user_id, event)

        return AlpacaStream(self._context_for(account), on_event=on_event)

    def _run_account(self, account: BrokerAccount, stop_event: threading.Event):
        attempt = 0
        while not stop_event.is_set():
            started = time.monotonic()
            if attempt > 0:
                BROKER_WS_RECONNECTS_TOTAL.labels(broker="alpaca").inc()
            try:
                # Catch up any fills missed while (re)connecting.
                catch_up_account(account, self._build_adapter(account))
                stream = self._build_stream(account)
                set_heartbeat(account.id, BrokerConnState.CONNECTED.value)
                stream.run()  # blocks until disconnect
            except Exception:  # noqa: BLE001 — supervised restart, never propagate
                BROKER_STREAM_DISCONNECTS_TOTAL.labels(broker="alpaca").inc()
                set_heartbeat(account.id, BrokerConnState.DEGRADED.value)
                logger.warning("broker.stream.error", extra={"account": str(account.id)})
            # Reset backoff only after a genuinely healthy run; otherwise grow it.
            if time.monotonic() - started >= self.healthy_after:
                attempt = 0
            else:
                attempt += 1
            if stop_event.is_set():
                break
            delay = backoff_delay(attempt)
            logger.warning(
                "broker.stream.reconnect",
                extra={"account": str(account.id), "attempt": attempt, "delay": delay},
            )
            stop_event.wait(delay)

    def _start_thread(self, account: BrokerAccount):
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_account, args=(account, stop_event), daemon=True
        )
        self._stops[str(account.id)] = stop_event
        self._threads[str(account.id)] = thread
        thread.start()

    def _reconcile_threads(self, accounts) -> None:
        """Start threads for newly-active accounts, signal-stop threads for
        removed accounts, and prune dead threads. Touches no heartbeat."""
        active = {str(a.id): a for a in accounts}
        for account_id in list(self._threads):
            thread = self._threads[account_id]
            if account_id not in active or not thread.is_alive():
                stop_event = self._stops.pop(account_id, None)
                if stop_event is not None:
                    stop_event.set()
                del self._threads[account_id]
        for account_id, account in active.items():
            if account_id not in self._threads:
                self._start_thread(account)

    def start(self):
        self._reconcile_threads(load_active_accounts())

    def run_forever(self):  # pragma: no cover — top-level loop
        try:
            while not self._stop.is_set():
                self._reconcile_threads(load_active_accounts())
                self._stop.wait(self.heartbeat_interval)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self._stop.set()
        for stop_event in list(self._stops.values()):
            stop_event.set()
