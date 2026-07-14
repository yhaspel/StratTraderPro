"""TradingStream wrapper used by run_broker_streams (M04 §6.5; mode-aware M13).

Wraps Alpaca's blocking ``TradingStream.run()`` asyncio loop. Each
``trade_updates`` event is normalized (``mapping.map_trade_update``) and handed
to an injected ``on_event`` callback — the supervisor forwards it to
``publish_fill``. The wrapper is DB-free; persistence happens downstream.

M13 — the stream endpoint MUST follow ``ctx.mode``, exactly like the adapter.
This used to be ``paper=True``, hard-coded, and leaving it that way while making
the *order* path mode-aware would have been the single most dangerous bug in the
milestone:

    a LIVE account would place REAL orders through the live REST endpoint, while
    its fill stream stayed subscribed to the PAPER endpoint.

Real fills would then never arrive. `ingest_fill_event` would never run, so
positions, realised P&L and equity would silently diverge from the broker's
actual state — and `daily_loss_watcher` and the kill switch would go on making
decisions about a portfolio that does not exist. Worse, it would conceal itself:
`broker_stream_heartbeat_age_seconds` would stay fresh (the paper socket is very
much alive), so `BrokerStreamSilent` would never fire. A dead fill pipeline that
reports itself healthy is this project's signature failure; it must not be
reintroduced on the one code path where the money is real.
"""
from __future__ import annotations

import logging

from ..base import BrokerContext, FillEvent
from ..errors import BrokerError, BrokerErrorCode
from ..live_gate import live_trading_permitted
from . import mapping

logger = logging.getLogger(__name__)


class AlpacaStream:
    def __init__(self, ctx: BrokerContext, *, on_event, stream=None):
        self.ctx = ctx
        self._on_event = on_event
        self._stream = stream

    def _build_stream(self):
        from alpaca.trading.stream import TradingStream

        # Re-assert the master gate here too. The supervisor starts a thread per
        # CONNECTED account; without this, a LIVE account connected while the flag
        # was on would keep streaming live trade-updates after the operator
        # revoked permission. Refusing here means the supervisor logs and drops it.
        if not self.ctx.is_paper and not live_trading_permitted():
            raise BrokerError(
                BrokerErrorCode.LIVE_TRADING_DISABLED,
                "Live trading is disabled; refusing to open a LIVE trade-updates stream.",
            )

        return TradingStream(
            self.ctx.api_key_id,
            self.ctx.api_secret,
            paper=self.ctx.is_paper,
        )

    async def _handler(self, data):
        try:
            event: FillEvent = mapping.map_trade_update(data)
            self._on_event(self.ctx.user_id, event)
        except Exception:  # pragma: no cover — a bad event must not kill the loop
            logger.exception("alpaca.stream.handler_error", extra={"account": self.ctx.account_id})

    def run(self):  # pragma: no cover — blocking network loop, exercised live
        if self._stream is None:
            self._stream = self._build_stream()
        self._stream.subscribe_trade_updates(self._handler)
        self._stream.run()

    def stop(self):  # pragma: no cover — live teardown
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:
                logger.debug("alpaca.stream.stop_error")
